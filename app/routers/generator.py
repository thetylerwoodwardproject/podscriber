import asyncio
import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models import GeneratedScript, Job
from app.routers._shared import recent_episodes
from app.services.jobs import submit_script_generation
from app.templating import templates

router = APIRouter()


def _latest_job(db: Session, script_id: int) -> Job | None:
    return db.execute(
        select(Job)
        .where(Job.generated_script_id == script_id, Job.job_type == "script_generate")
        .order_by(Job.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


@router.get("/generator", response_class=HTMLResponse)
def generator_page(request: Request, db: Session = Depends(get_db)):
    scripts = list(db.execute(select(GeneratedScript).order_by(GeneratedScript.created_at.desc())).scalars())
    return templates.TemplateResponse(
        request,
        "generator.html",
        {"active_nav": "generator", "recent_episodes": recent_episodes(db), "scripts": scripts},
    )


@router.post("/generator/generate")
def generate_script(
    topic: str = Form(...),
    research_text: str = Form(""),
    db: Session = Depends(get_db),
):
    script = GeneratedScript(topic=topic.strip(), research_text=research_text.strip())
    db.add(script)
    db.commit()
    db.refresh(script)

    job = Job(job_type="script_generate", status="pending", generated_script_id=script.id)
    db.add(job)
    db.commit()
    db.refresh(job)

    submit_script_generation(job.id)

    return RedirectResponse(url=f"/generator/{script.id}", status_code=303)


@router.get("/generator/{script_id}", response_class=HTMLResponse)
def generator_detail(script_id: int, request: Request, db: Session = Depends(get_db)):
    script = db.get(GeneratedScript, script_id)
    if script is None:
        return RedirectResponse(url="/generator", status_code=303)

    job = _latest_job(db, script_id)
    in_progress = bool(job and job.status in ("pending", "running"))
    return templates.TemplateResponse(
        request,
        "generator_detail.html",
        {
            "active_nav": "generator",
            "recent_episodes": recent_episodes(db),
            "script": script,
            "in_progress": in_progress,
            "error_message": job.error_message if job and job.status == "error" else None,
        },
    )


@router.get("/generator/{script_id}/status/stream")
def generator_status_stream(script_id: int):
    async def event_source():
        # Async, not sync — see processing.py's status_stream for why a sync generator
        # here would starve FastAPI's worker thread pool when the job status is idle.
        last_payload = None
        for _ in range(1200):  # ~10 min ceiling, matches the video-export/social-regen status streams
            # Open a fresh, short-lived session per poll instead of holding one for the
            # whole loop — see the matching comment in processing.py's status_stream.
            db = SessionLocal()
            try:
                job = _latest_job(db, script_id)
                if job is None:
                    payload = {"status": "pending"}
                else:
                    payload = {"status": job.status, "error_message": job.error_message}
            finally:
                db.close()
            if payload != last_payload:
                yield f"data: {json.dumps(payload)}\n\n"
                last_payload = payload
            if job is not None and job.status in ("done", "error"):
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_source(), media_type="text/event-stream")
