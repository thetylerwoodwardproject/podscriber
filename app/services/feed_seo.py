"""Generates SEO-improved title/description suggestions for the podcast's RSS back
catalog, from each episode's existing feed title+description (no transcript — back-
catalog episodes were never uploaded to Podscriber, so there's no audio to work from).
"""

import hashlib
import logging
import traceback

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import config
from app.db import SessionLocal
from app.models import Episode, FeedEpisodeSuggestion, Job, now_utc
from app.services import settings_store
from app.services.episode_fetch import AudioDownloadError, download_audio
from app.services.feed_catalog import load_feed_episodes
from app.services.llm.factory import get_llm_provider
from app.services.pipeline import save_transcript
from app.services.transcription.factory import get_transcription_provider

logger = logging.getLogger("podscriber.feed_seo")


def episode_key(guid: str | None, title: str, pub_date) -> str:
    if guid and guid.strip():
        return guid.strip()
    return "fallback:" + hashlib.sha1(f"{title}|{pub_date}".encode()).hexdigest()


def generate_suggestion_for_episode(
    db: Session,
    provider,
    key: str,
    title: str,
    description: str,
    transcript_text: str | None = None,
) -> FeedEpisodeSuggestion:
    suggestion = provider.generate_seo_suggestion(title, description, transcript_text)
    row = db.execute(
        select(FeedEpisodeSuggestion).where(FeedEpisodeSuggestion.episode_key == key)
    ).scalar_one_or_none()
    if row is None:
        row = FeedEpisodeSuggestion(episode_key=key)
        db.add(row)
    row.original_title = title
    row.original_description = description
    row.suggested_title = suggestion.title
    row.suggested_description = suggestion.description
    row.suggested_keywords = suggestion.keywords
    row.used_transcript = transcript_text is not None
    row.generated_at = now_utc()
    db.commit()
    return row


def run_feed_seo_bulk(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.status = "running"
        db.commit()

        s = settings_store.get_all(db)
        feed = load_feed_episodes(db, s, force=False)
        episodes = feed.get("episodes", [])
        total = len(episodes)

        existing_keys = {
            key
            for (key,) in db.execute(select(FeedEpisodeSuggestion.episode_key))
        }
        provider = get_llm_provider(db)
        failures = 0

        for idx, ep in enumerate(episodes):
            key = episode_key(ep.get("guid"), ep["title"], ep["pub_date"])
            job.current_step = f"{idx + 1}/{total}: {ep['title'][:50]}"
            job.progress_pct = round((idx + 1) / total * 100) if total else 100
            db.commit()

            if key in existing_keys:
                continue  # already suggested — "Generate all" only fills gaps
            try:
                generate_suggestion_for_episode(db, provider, key, ep["title"], ep["description"])
            except Exception:
                logger.exception("feed_seo suggestion failed for episode_key=%s", key)
                db.rollback()
                failures += 1

        job.status = "done"
        job.progress_pct = 100
        job.error_message = f"{failures} of {total} episode(s) failed" if failures else None
        db.commit()
    except Exception:
        logger.exception("feed_seo bulk job %s failed", job_id)
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = "error"
            job.error_message = traceback.format_exc(limit=5)
            db.commit()
    finally:
        db.close()


def run_feed_episode_deep_suggest(job_id: int) -> None:
    """Downloads a back-catalog episode's audio, transcribes it, then generates a suggestion
    grounded in the real transcript instead of just the feed's title/description.

    Routed through jobs.py's _run_guarded, same as run_episode_processing — this job's
    episode_id always points at a synthetic (source="feed") Episode created for this purpose,
    so flipping its status to "error" on failure is harmless: that episode never appears in
    any episode-browsing UI (see the Episode.source filter in _shared.py/library.py).
    """
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        episode = db.get(Episode, job.episode_id)
        if episode is None:
            return
        row = db.execute(
            select(FeedEpisodeSuggestion).where(FeedEpisodeSuggestion.episode_id == episode.id)
        ).scalar_one_or_none()
        if row is None:
            return

        job.status = "running"
        db.commit()

        s = settings_store.get_all(db)
        feed = load_feed_episodes(db, s, force=False)
        match = next(
            (
                ep
                for ep in feed.get("episodes", [])
                if episode_key(ep.get("guid"), ep["title"], ep["pub_date"]) == row.episode_key
            ),
            None,
        )
        if match is None:
            raise RuntimeError("Episode no longer found in the cached feed.")

        if episode.transcript is None:
            if not match.get("enclosure_url"):
                raise RuntimeError("This episode's feed entry has no audio URL to download.")

            job.current_step = "downloading"
            job.progress_pct = 10
            db.commit()

            try:
                dest = download_audio(match["enclosure_url"], episode.id, config.max_upload_bytes)
            except AudioDownloadError as exc:
                raise RuntimeError(str(exc)) from exc
            episode.file_path = str(dest)
            episode.file_size_bytes = dest.stat().st_size
            episode.status = "processing"
            db.commit()

            job.current_step = "transcribing"
            job.progress_pct = 40
            db.commit()

            transcription_provider = get_transcription_provider(db)
            result = transcription_provider.transcribe(dest)
            transcript = save_transcript(db, episode, result, type(transcription_provider).__name__)
        else:
            transcript = episode.transcript

        job.current_step = "suggesting"
        job.progress_pct = 80
        db.commit()

        provider = get_llm_provider(db)
        generate_suggestion_for_episode(
            db, provider, row.episode_key, match["title"], match["description"], transcript.full_text
        )

        episode.status = "processed"
        job.status = "done"
        job.progress_pct = 100
        db.commit()
    finally:
        db.close()
