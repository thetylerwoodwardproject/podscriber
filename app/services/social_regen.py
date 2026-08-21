from app.db import SessionLocal
from app.models import Episode, Job
from app.services.llm.factory import get_llm_provider
from app.services.regen_job import run_regenerate


def _fetch_episode(db, job: Job) -> Episode | None:
    return db.get(Episode, job.episode_id) if job.episode_id else None


def run_social_regenerate(job_id: int, tone: str = "casual") -> None:
    db = SessionLocal()
    try:

        def apply_result(db, job: Job, episode: Episode) -> None:
            llm = get_llm_provider(db)
            transcript_text = episode.transcript.full_text if episode.transcript else ""
            description = episode.generated_content.description if episode.generated_content else ""
            social_groups = llm.generate_social_posts(transcript_text, description, tone=tone)
            if episode.generated_content:
                episode.generated_content.social_posts = [
                    {
                        "platform": g.platform,
                        "initial": g.initial,
                        "color": g.color,
                        "platform_key": g.platform_key,
                        "posts": g.posts,
                    }
                    for g in social_groups
                ]

        run_regenerate(
            db, job_id, fetch_parent=_fetch_episode, apply_result=apply_result, not_found_message="Episode not found."
        )
    finally:
        db.close()
