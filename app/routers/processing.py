import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models import Episode, Job
from app.routers._shared import recent_episodes
from app.services.pipeline import STEP_KEYS, STEP_LABELS
from app.templating import templates

router = APIRouter()


def _latest_job(db: Session, episode_id: int) -> Job | None:
    return db.execute(
        select(Job)
        .where(Job.episode_id == episode_id, Job.job_type == "episode_processing")
        .order_by(Job.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


@router.get("/episodes/{episode_id}/processing", response_class=HTMLResponse)
def processing_page(episode_id: int, request: Request, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    if episode.status == "processed":
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url=f"/episodes/{episode_id}")

    job = _latest_job(db, episode_id)
    active_keys = job.steps if job is not None and job.steps else STEP_KEYS
    steps = [{"key": k, "label": STEP_LABELS[k]} for k in STEP_KEYS if k in active_keys]
    return templates.TemplateResponse(
        request,
        "processing.html",
        {
            "active_nav": "upload",
            "recent_episodes": recent_episodes(db),
            "episode": episode,
            "steps": steps,
        },
    )


@router.get("/episodes/{episode_id}/status/stream")
def status_stream(episode_id: int):
    async def event_source():
        # An async generator, not a sync one: when the job's status is unchanged across
        # polls, the loop never hits a `yield`, so a sync generator would hold its one
        # worker-pool thread hostage in time.sleep() for the whole polling window in a
        # single blocking call — enough concurrently-stuck streams starve FastAPI's
        # thread pool for every other route. asyncio.sleep() yields to the event loop
        # instead of blocking a thread.
        last_payload = None
        for _ in range(1200):  # ~10 min ceiling, matches the other status streams
            # Open a fresh, short-lived session per poll instead of holding one for the
            # whole loop — a long-idle stream (job stuck pending behind a busy worker)
            # would otherwise pin a pooled connection for up to 10 minutes doing nothing,
            # which can starve the pool if several streams are open at once.
            db = SessionLocal()
            try:
                job = _latest_job(db, episode_id)
                if job is None:
                    payload = {"status": "pending", "current_step": "", "progress_pct": 0}
                else:
                    payload = {
                        "status": job.status,
                        "current_step": job.current_step,
                        "progress_pct": job.progress_pct,
                        "error_message": job.error_message,
                    }
            finally:
                db.close()
            if payload != last_payload:
                yield f"data: {json.dumps(payload)}\n\n"
                last_payload = payload
            if job is not None and job.status in ("done", "error"):
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_source(), media_type="text/event-stream")
