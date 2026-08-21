from app.db import SessionLocal
from app.models import Job, VideoClip
from app.services.llm.factory import get_llm_provider
from app.services.regen_job import run_regenerate


def _fetch_clip(db, job: Job) -> VideoClip | None:
    return db.get(VideoClip, job.video_clip_id) if job.video_clip_id else None


def run_clip_social_regenerate(job_id: int) -> None:
    db = SessionLocal()
    try:

        def apply_result(db, job: Job, clip: VideoClip) -> None:
            llm = get_llm_provider(db)
            soundbite = clip.soundbite
            result = llm.generate_clip_social(soundbite.quote, soundbite.episode.title or soundbite.episode.original_filename)
            clip.social_post = result.social_post
            if not clip.youtube_title:
                clip.youtube_title = result.youtube_title

        run_regenerate(
            db,
            job_id,
            fetch_parent=_fetch_clip,
            apply_result=apply_result,
            not_found_message="Soundbite or its video clip could not be found.",
        )
    finally:
        db.close()
