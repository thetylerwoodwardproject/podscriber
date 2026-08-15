import asyncio
import json
import re
from collections.abc import Callable

from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Episode, Job

_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_download_filename(name: str | None, fallback: str) -> str:
    """Turns user-entered text into a safe `<name>.mp4` download filename.

    Strips path separators and other characters that would confuse a Content-Disposition
    header or a filesystem, and falls back to `fallback` if nothing usable is left.
    """
    name = _UNSAFE_FILENAME_CHARS.sub("", (name or "").strip())
    name = re.sub(r"\s+", " ", name).strip(" .")
    if name.lower().endswith(".mp4"):
        name = name[:-4].strip(" .")
    name = name[:80].strip(" .")
    return f"{name}.mp4" if name else f"{fallback}.mp4"


def recent_episodes(db: Session, limit: int = 6) -> list[Episode]:
    return list(
        db.execute(
            select(Episode).where(Episode.source == "upload").order_by(Episode.created_at.desc()).limit(limit)
        ).scalars()
    )


def status_label(status: str) -> str:
    return {"processed": "Processed", "processing": "Processing", "draft": "Draft", "error": "Error"}.get(
        status, status.title()
    )


def format_duration(seconds: float | None) -> str:
    if not seconds:
        return "—"
    minutes = round(seconds / 60)
    return f"{minutes} min"


def ms_to_clock(ms: int) -> str:
    total_seconds = ms // 1000
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def latest_job(db: Session, job_type: str, **filters) -> Job | None:
    conditions = [Job.job_type == job_type] + [getattr(Job, key) == value for key, value in filters.items()]
    return db.execute(select(Job).where(*conditions).order_by(Job.created_at.desc()).limit(1)).scalar_one_or_none()


def sse_job_stream(
    query_fn: Callable[[Session], Job | None],
    payload_fn: Callable[[Job], dict],
    not_found_payload: dict,
    not_found_terminal: bool = False,
) -> StreamingResponse:
    """Polls `query_fn` for a Job's status and streams it as Server-Sent Events.

    Async, not sync: a sync generator using time.sleep() would hold its one worker-pool
    thread hostage for the whole polling window whenever the job's status is unchanged
    across polls, and enough concurrently-stuck streams starve FastAPI's thread pool for
    every other route. asyncio.sleep() yields to the event loop instead of blocking a thread.

    Opens a fresh, short-lived session per poll instead of holding one for the whole loop —
    a long-idle stream (job stuck pending behind a busy worker) would otherwise pin a pooled
    connection for up to the ~10 min ceiling, which can starve the pool if several streams are
    open at once.
    """

    async def event_source():
        last_payload = None
        for _ in range(1200):  # ~10 min ceiling
            db = SessionLocal()
            try:
                job = query_fn(db)
                payload = not_found_payload if job is None else payload_fn(job)
            finally:
                db.close()
            if payload != last_payload:
                yield f"data: {json.dumps(payload)}\n\n"
                last_payload = payload
            if job is not None and job.status in ("done", "error"):
                break
            if job is None and not_found_terminal:
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_source(), media_type="text/event-stream")
