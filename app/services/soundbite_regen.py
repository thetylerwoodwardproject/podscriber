from pathlib import Path

from app.db import SessionLocal
from app.models import Episode, Job
from app.services import pipeline
from app.services.llm.factory import get_llm_provider
from app.services.regen_job import run_regenerate


def _fetch_episode(db, job: Job) -> Episode | None:
    return db.get(Episode, job.episode_id) if job.episode_id else None


def run_soundbite_regenerate(job_id: int) -> None:
    db = SessionLocal()
    try:

        def apply_result(db, job: Job, episode: Episode) -> None:
            llm = get_llm_provider(db)
            transcript = episode.transcript
            transcript_text = transcript.full_text if transcript else ""
            segments = list(transcript.segments) if transcript else []
            old_soundbites = list(episode.soundbites)

            # Build the new set before deleting the old one, so an LLM/API failure here
            # leaves the episode's existing soundbites in place instead of losing them.
            pipeline.build_soundbites(db, episode, transcript_text, segments, llm)

            # Unlink each old soundbite/video-clip's own known files before deleting the
            # rows (cascade takes the VideoClip rows with them) — don't sweep whole
            # directories like reset_episode_for_retry() does, since images_dir() is
            # shared with the unrelated episode-level video feature.
            for sb in old_soundbites:
                if sb.clip_audio_path:
                    Path(sb.clip_audio_path).unlink(missing_ok=True)
                for clip in sb.video_clips:
                    if clip.exported_video_path:
                        Path(clip.exported_video_path).unlink(missing_ok=True)
                db.delete(sb)
            db.flush()

        run_regenerate(
            db, job_id, fetch_parent=_fetch_episode, apply_result=apply_result, not_found_message="Episode not found."
        )
    finally:
        db.close()
