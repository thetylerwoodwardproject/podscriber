from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import GeneratedScript, Job
from app.routers._shared import latest_job, recent_episodes, sse_job_stream
from app.services.jobs import submit_script_generation
from app.templating import templates

router = APIRouter()


@router.get("/generator", response_class=HTMLResponse)
def generator_page(request: Request, db: Session = Depends(get_db)):
    scripts = list(db.execute(select(GeneratedScript).order_by(GeneratedScript.created_at.desc())).scalars())

    # Latest job status per script, for the "In progress" / "Error" list badges below.
    # Jobs are ordered newest-first, so the first hit per script_id via setdefault wins.
    latest_status: dict[int, str] = {}
    jobs = db.execute(
        select(Job).where(Job.job_type == "script_generate").order_by(Job.created_at.desc())
    ).scalars()
    for job in jobs:
        latest_status.setdefault(job.generated_script_id, job.status)

    return templates.TemplateResponse(
        request,
        "generator.html",
        {
            "active_nav": "generator",
            "recent_episodes": recent_episodes(db),
            "scripts": scripts,
            "latest_status": latest_status,
        },
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


@router.post("/generator/{script_id}/retry")
def retry_script_generation(script_id: int, db: Session = Depends(get_db)):
    script = db.get(GeneratedScript, script_id)
    if script is None:
        return RedirectResponse(url="/generator", status_code=303)

    job = Job(job_type="script_generate", status="pending", generated_script_id=script.id)
    db.add(job)
    db.commit()
    db.refresh(job)

    submit_script_generation(job.id)

    return RedirectResponse(url=f"/generator/{script_id}", status_code=303)


@router.post("/generator/{script_id}/delete")
def delete_script(script_id: int, db: Session = Depends(get_db)):
    script = db.get(GeneratedScript, script_id)
    if script is not None:
        db.execute(delete(Job).where(Job.generated_script_id == script_id))
        db.delete(script)
        db.commit()
    return RedirectResponse(url="/generator", status_code=303)


@router.get("/generator/{script_id}", response_class=HTMLResponse)
def generator_detail(script_id: int, request: Request, db: Session = Depends(get_db)):
    script = db.get(GeneratedScript, script_id)
    if script is None:
        return RedirectResponse(url="/generator", status_code=303)

    job = latest_job(db, "script_generate", generated_script_id=script_id)
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
    return sse_job_stream(
        query_fn=lambda db: latest_job(db, "script_generate", generated_script_id=script_id),
        payload_fn=lambda job: {"status": job.status, "error_message": job.error_message},
        not_found_payload={"status": "pending"},
    )
