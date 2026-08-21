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


def submit_job(job_id: int, run_fn, *args, executor: ThreadPoolExecutor | None = None, guarded: bool = True) -> None:
    """Hands a job off to a background executor.

    `guarded=True` (the default) routes through `_run_guarded`, which logs, records the
    error on the job, and flips the parent episode's status to "error" on failure — right
    for jobs that are themselves the episode's own processing. `guarded=False` skips the
    episode-status flip for jobs whose `run_fn` already does its own job-level error
    reporting and whose failure shouldn't mark an otherwise-fine episode as broken (manual
    regenerates, bulk SEO suggestions).
    """
    executor = executor or _executor
    if guarded:
        executor.submit(_run_guarded, job_id, run_fn, *args)
    else:
        executor.submit(run_fn, job_id, *args)


def submit_episode_processing(job_id: int) -> None:
    from app.services.pipeline import run_episode_processing

    submit_job(job_id, run_episode_processing, executor=_episode_executor)


def submit_feed_episode_deep_suggest(job_id: int) -> None:
    from app.services.feed_seo import run_feed_episode_deep_suggest

    # Runs local transcription like episode_processing, so it shares that executor's
    # single-worker discipline to avoid compounding CPU contention (see the comment above).
    submit_job(job_id, run_feed_episode_deep_suggest, executor=_episode_executor)


def submit_video_export(job_id: int) -> None:
    from app.services.video_export import run_video_export

    submit_job(job_id, run_video_export)


def submit_full_video_export(job_id: int) -> None:
    from app.services.video_export_full import run_full_video_export

    submit_job(job_id, run_full_video_export)


def submit_social_regenerate(job_id: int, tone: str) -> None:
    from app.services.social_regen import run_social_regenerate

    # guarded=False: a failed manual regenerate of an already-processed episode's social
    # posts shouldn't flip the whole episode to "error". run_social_regenerate handles its
    # own job-level error reporting.
    submit_job(job_id, run_social_regenerate, tone, guarded=False)


def submit_clip_social_regenerate(job_id: int) -> None:
    from app.services.clip_social_regen import run_clip_social_regenerate

    # guarded=False, same reasoning as submit_social_regenerate: a failed manual regenerate
    # of a soundbite's social copy shouldn't flip the whole episode to "error".
    submit_job(job_id, run_clip_social_regenerate, guarded=False)


def submit_clip_social_publish(
    job_id: int,
    platforms: list[str],
    mode: str,
    scheduled_at: str | None,
    video_source: dict | None,
    image_source: dict | None,
) -> None:
    from app.services.clip_social_publish import run_clip_social_publish

    # guarded=False, same reasoning as submit_social_regenerate: a failed publish attempt
    # shouldn't flip the whole episode to "error" — per-platform failures are recorded on
    # SocialPublish rows, and run_clip_social_publish handles its own job-level reporting.
    submit_job(job_id, run_clip_social_publish, platforms, mode, scheduled_at, video_source, image_source, guarded=False)


def submit_episode_social_publish(job_id: int, selections: list[dict], mode: str, scheduled_at: str | None) -> None:
    from app.services.episode_social_publish import run_episode_social_publish

    # guarded=False, same reasoning as submit_clip_social_publish.
    submit_job(job_id, run_episode_social_publish, selections, mode, scheduled_at, guarded=False)


def submit_script_generation(job_id: int) -> None:
    from app.services.script_generate import run_script_generation

    # A one-off LLM call, not CPU-bound like transcription, so it shares the 3-worker
    # executor rather than the dedicated single-worker episode executor.
    submit_job(job_id, run_script_generation)


def submit_feed_seo_bulk(job_id: int) -> None:
    from app.services.feed_seo import run_feed_seo_bulk

    # guarded=False, same reasoning as submit_social_regenerate: run_feed_seo_bulk has no
    # episode_id and owns its own job-level error reporting.
    submit_job(job_id, run_feed_seo_bulk, guarded=False)


def _run_guarded(job_id: int, fn, *args) -> None:
    try:
        fn(job_id, *args)
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
