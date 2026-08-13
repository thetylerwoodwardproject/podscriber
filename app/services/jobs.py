import logging
import traceback
from concurrent.futures import ThreadPoolExecutor

from app.db import SessionLocal
from app.models import Job

logger = logging.getLogger("podscriber.jobs")

_executor = ThreadPoolExecutor(max_workers=3)  # video_export, social_regenerate, feed_seo_bulk

# episode_processing runs a CPU-heavy transcription followed by several LLM calls; a dedicated
# single-worker executor makes multiple episode uploads queue and process one at a time instead
# of compounding CPU contention (see the Ollama Nice/CPUWeight note in CLAUDE.md).
_episode_executor = ThreadPoolExecutor(max_workers=1)


def submit_episode_processing(job_id: int) -> None:
    from app.services.pipeline import run_episode_processing

    _episode_executor.submit(_run_guarded, job_id, run_episode_processing)


def submit_feed_episode_deep_suggest(job_id: int) -> None:
    from app.services.feed_seo import run_feed_episode_deep_suggest

    # Runs local transcription like episode_processing, so it shares that executor's
    # single-worker discipline to avoid compounding CPU contention (see the comment above).
    _episode_executor.submit(_run_guarded, job_id, run_feed_episode_deep_suggest)


def submit_video_export(job_id: int) -> None:
    from app.services.video_export import run_video_export

    _executor.submit(_run_guarded, job_id, run_video_export)


def submit_social_regenerate(job_id: int, tone: str) -> None:
    from app.services.social_regen import run_social_regenerate

    # Not routed through _run_guarded: that helper also flips the parent episode's status
    # to "error" on failure, which is wrong here — regenerating social posts for an
    # already-processed episode shouldn't mark the whole episode as broken. run_social_regenerate
    # handles its own job-level error reporting.
    _executor.submit(run_social_regenerate, job_id, tone)


def submit_script_generation(job_id: int) -> None:
    from app.services.script_generate import run_script_generation

    # A one-off LLM call, not CPU-bound like transcription, so it shares the 3-worker
    # executor rather than the dedicated single-worker episode executor.
    _executor.submit(_run_guarded, job_id, run_script_generation)


def submit_feed_seo_bulk(job_id: int) -> None:
    from app.services.feed_seo import run_feed_seo_bulk

    # Not routed through _run_guarded, same reasoning as submit_social_regenerate:
    # run_feed_seo_bulk has no episode_id and owns its own job-level error reporting.
    _executor.submit(run_feed_seo_bulk, job_id)


def _run_guarded(job_id: int, fn) -> None:
    try:
        fn(job_id)
    except Exception:
        logger.exception("Job %s failed", job_id)
        db = SessionLocal()
        try:
            job = db.get(Job, job_id)
            if job is not None:
                job.status = "error"
                job.error_message = traceback.format_exc(limit=5)
                db.commit()
                if job.episode_id is not None:
                    from app.models import Episode

                    episode = db.get(Episode, job.episode_id)
                    if episode is not None:
                        episode.status = "error"
                        db.commit()
        finally:
            db.close()
