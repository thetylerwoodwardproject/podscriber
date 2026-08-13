import logging
import traceback

from app.db import SessionLocal
from app.models import Episode, Job
from app.services.llm.factory import get_llm_provider

logger = logging.getLogger("podscriber.jobs")


def run_social_regenerate(job_id: int, tone: str = "casual") -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.status = "running"
        db.commit()

        episode = db.get(Episode, job.episode_id) if job.episode_id else None
        if episode is None:
            job.status = "error"
            job.error_message = "Episode not found."
            db.commit()
            return

        llm = get_llm_provider(db)
        transcript_text = episode.transcript.full_text if episode.transcript else ""
        description = episode.generated_content.description if episode.generated_content else ""
        social_groups = llm.generate_social_posts(transcript_text, description, tone=tone)

        if episode.generated_content:
            episode.generated_content.social_posts = [
                {"platform": g.platform, "initial": g.initial, "color": g.color, "posts": g.posts}
                for g in social_groups
            ]
        job.status = "done"
        db.commit()
    except Exception:
        # Deliberately does not touch episode.status — unlike the full processing pipeline,
        # a failed regeneration of an already-processed episode's social posts shouldn't
        # flip the whole episode into an "error" state.
        logger.exception("Social regenerate job %s failed", job_id)
        job = db.get(Job, job_id)
        if job is not None:
            job.status = "error"
            job.error_message = traceback.format_exc(limit=5)
            db.commit()
    finally:
        db.close()
