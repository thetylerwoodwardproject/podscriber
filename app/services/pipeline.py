import shutil
from datetime import UTC
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Chapter, Episode, GeneratedContent, Job, Soundbite, Transcript, TranscriptSegment, VideoClip
from app.services import storage
from app.services.llm.factory import get_llm_provider
from app.services.soundbite_matching import match_quote_to_timestamps, quote_coverage
from app.services.transcription.base import TranscriptResult
from app.services.transcription.factory import get_transcription_provider

STEP_KEYS = ["transcribing", "titles", "description", "social", "soundbites", "chapters"]
STEP_LABELS = {
    "transcribing": "Transcribing audio",
    "titles": "Generating title ideas",
    "description": "Writing show notes",
    "social": "Drafting social posts",
    "soundbites": "Finding soundbites",
    "chapters": "Finding chapters",
}


def _set_step(job: Job, step: str, db) -> None:
    active_steps = job.steps or STEP_KEYS
    job.current_step = step
    job.progress_pct = round((active_steps.index(step) / len(active_steps)) * 100)
    db.commit()


def reset_episode_for_retry(db: Session, episode: Episode) -> None:
    """Discard a failed processing attempt's partial results so it can be re-run from scratch.

    Transcript/GeneratedContent have unique episode_id constraints, so leaving them in place would
    make a retry's inserts fail; soundbites/chapters would just duplicate. Clip/image/video files
    are keyed by soundbite/video-clip id, so a retry's fresh ids would orphan them on disk unless
    the whole directories are cleared too.
    """
    if episode.transcript is not None:
        db.delete(episode.transcript)
    if episode.generated_content is not None:
        db.delete(episode.generated_content)
    for soundbite in list(episode.soundbites):
        db.delete(soundbite)
    for chapter in list(episode.chapters):
        db.delete(chapter)
    db.flush()

    for dir_fn in (storage.clips_dir, storage.images_dir, storage.video_dir):
        shutil.rmtree(dir_fn(episode.id), ignore_errors=True)


def save_transcript(db: Session, episode: Episode, result: TranscriptResult, provider_name: str) -> Transcript:
    transcript = Transcript(
        episode_id=episode.id,
        full_text=result.full_text,
        language=result.language,
        provider=provider_name,
    )
    db.add(transcript)
    db.flush()
    for seg in result.segments:
        db.add(
            TranscriptSegment(
                transcript_id=transcript.id,
                index=seg.index,
                start_ms=seg.start_ms,
                end_ms=seg.end_ms,
                text=seg.text,
                words=[{"word": w.word, "start_ms": w.start_ms, "end_ms": w.end_ms} for w in seg.words] or None,
            )
        )
    episode.duration_seconds = result.duration_seconds
    db.commit()
    return transcript


def run_episode_processing(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        episode = db.get(Episode, job.episode_id)
        if episode is None:
            return

        job.status = "running"
        from datetime import datetime

        job.started_at = datetime.now(UTC)
        db.commit()

        steps = job.steps or STEP_KEYS

        # --- Step 1: transcription (always runs — every other step needs the transcript) ---
        _set_step(job, "transcribing", db)
        transcription_provider = get_transcription_provider(db)
        result = transcription_provider.transcribe(Path(episode.file_path))
        transcript = save_transcript(db, episode, result, type(transcription_provider).__name__)

        transcript_text = result.full_text
        segments = list(transcript.segments)
        llm = get_llm_provider(db)
        content = GeneratedContent(episode_id=episode.id, llm_provider=type(llm).__name__)
        db.add(content)
        db.flush()

        # --- Step 2: titles ---
        if "titles" in steps:
            _set_step(job, "titles", db)
            titles = llm.generate_titles(transcript_text)
            content.titles = [{"text": t.text, "score": t.score} for t in titles]
            best_idx = max(range(len(titles)), key=lambda i: titles[i].score) if titles else 0
            content.selected_title_index = best_idx
            episode.title = titles[best_idx].text if titles else episode.original_filename
            db.commit()

        # --- Step 3: description + keywords ---
        if "description" in steps:
            _set_step(job, "description", db)
            desc = llm.generate_description_and_keywords(transcript_text)
            content.description = desc.description
            content.keywords = desc.keywords
            db.commit()

        # --- Step 4: social posts ---
        if "social" in steps:
            _set_step(job, "social", db)
            social_groups = llm.generate_social_posts(transcript_text, content.description)
            content.social_posts = [
                {
                    "platform": g.platform,
                    "initial": g.initial,
                    "color": g.color,
                    "platform_key": g.platform_key,
                    "posts": g.posts,
                }
                for g in social_groups
            ]
            db.commit()

        # --- Step 5: soundbites ---
        new_soundbites: list[Soundbite] = []
        if "soundbites" in steps:
            _set_step(job, "soundbites", db)
            candidates = llm.select_soundbites(transcript_text)
            order_index = 0
            for cand in candidates:
                # A local model can occasionally leak reasoning/retry text into a schema-valid
                # "quote" field instead of an actual transcript excerpt. Requiring most of it to
                # match verbatim keeps that garbage from being saved and shown as a soundbite.
                if quote_coverage(segments, cand.quote) < 0.5:
                    continue
                start_ms, end_ms = match_quote_to_timestamps(segments, cand.quote)
                sb = Soundbite(
                    episode_id=episode.id,
                    quote=cand.quote,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    include=True,
                    order_index=order_index,
                )
                db.add(sb)
                new_soundbites.append(sb)
                order_index += 1
            db.commit()

        # --- Step 6: chapters ---
        if "chapters" in steps:
            _set_step(job, "chapters", db)
            chapter_candidates = llm.generate_chapters(transcript_text)
            chapter_rows = []
            for cand in chapter_candidates:
                start_ms, _end_ms = match_quote_to_timestamps(segments, cand.start_quote)
                chapter_rows.append((start_ms, cand.title))
            chapter_rows.sort(key=lambda pair: pair[0])
            if chapter_rows and chapter_rows[0][0] > 2000:
                chapter_rows[0] = (0, chapter_rows[0][1])  # Podcasting 2.0 convention: first chapter starts at 0
            for i, (start_ms, title) in enumerate(chapter_rows):
                db.add(Chapter(episode_id=episode.id, index=i, title=title, start_ms=start_ms))
            db.commit()

        # --- clip soundbite audio and pre-build its video clip now that timestamps are known ---
        from app.services.audio_clip import clip_soundbite_audio

        for sb in new_soundbites:
            try:
                clip_soundbite_audio(episode, sb)
            except Exception:
                pass  # a clipping failure shouldn't fail the whole pipeline; playback/download will just 404

            # Pre-create the VideoClip and its social copy so the soundbite's video editor
            # opens ready to adjust art/export, instead of requiring a manual "Create video"
            # + "Generate" click first.
            clip = VideoClip(soundbite_id=sb.id)
            db.add(clip)
            try:
                clip_social = llm.generate_clip_social(sb.quote, episode.title or episode.original_filename)
                clip.social_post = clip_social.social_post
                clip.youtube_title = clip_social.youtube_title
            except Exception:
                pass  # clip stays with empty social copy; can be regenerated from the editor
        db.commit()

        job.status = "done"
        job.progress_pct = 100
        job.finished_at = datetime.now(UTC)
        episode.status = "processed"
        db.commit()
    finally:
        db.close()
