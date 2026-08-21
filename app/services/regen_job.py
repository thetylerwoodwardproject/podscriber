import logging
import traceback
from collections.abc import Callable

from app.models import Job

logger = logging.getLogger("podscriber.jobs")


def run_regenerate[T](
    db,
    job_id: int,
    fetch_parent: Callable[..., T | None],
    apply_result: Callable[..., None],
    not_found_message: str,
) -> None:
    """Shared job-status-transition body for "regenerate via LLM" jobs, given an
    already-open `db` session (session lifecycle stays with the caller, since each
    entity's `run_*` function needs its own module-level `SessionLocal` reference —
    e.g. for test monkeypatching).

    Fetches the job, marks it running, resolves a parent record via `fetch_parent(db,
    job)`, calls `apply_result(db, job, parent)` to do the LLM call and write the
    result, then marks the job done. Deliberately does not touch episode.status on
    failure — these are manual regenerates of already-processed content, so a failure
    shouldn't flip an otherwise-fine episode into an "error" state (see
    submit_job(guarded=False) callers).
    """
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.status = "running"
        db.commit()

        parent = fetch_parent(db, job)
        if parent is None:
            job.status = "error"
            job.error_message = not_found_message
            db.commit()
            return

        apply_result(db, job, parent)
        job.status = "done"
        db.commit()
    except Exception:
        logger.exception("Regenerate job %s failed", job_id)
        job = db.get(Job, job_id)
        if job is not None:
            job.status = "error"
            job.error_message = traceback.format_exc(limit=5)
            db.commit()
