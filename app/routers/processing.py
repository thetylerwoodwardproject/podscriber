from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Episode
from app.routers._shared import latest_job, recent_episodes, sse_job_stream
from app.services.pipeline import STEP_KEYS, STEP_LABELS
from app.templating import templates

router = APIRouter()


@router.get("/episodes/{episode_id}/processing", response_class=HTMLResponse)
def processing_page(episode_id: int, request: Request, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    if episode.status == "processed":
        return RedirectResponse(url=f"/episodes/{episode_id}")

    job = latest_job(db, "episode_processing", episode_id=episode_id)
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
    return sse_job_stream(
        query_fn=lambda db: latest_job(db, "episode_processing", episode_id=episode_id),
        payload_fn=lambda job: {
            "status": job.status,
            "current_step": job.current_step,
            "progress_pct": job.progress_pct,
            "error_message": job.error_message,
        },
        not_found_payload={"status": "pending", "current_step": "", "progress_pct": 0},
    )
