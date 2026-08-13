from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import config
from app.db import get_db
from app.models import Episode, Job
from app.routers._shared import recent_episodes
from app.services import storage
from app.services.jobs import submit_episode_processing
from app.services.pipeline import STEP_KEYS, STEP_LABELS, reset_episode_for_retry
from app.templating import templates

router = APIRouter()


@router.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "upload.html",
        {"active_nav": "upload", "recent_episodes": recent_episodes(db), "step_labels": STEP_LABELS},
    )


@router.post("/episodes")
async def create_episode(file: UploadFile, db: Session = Depends(get_db)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in storage.ALLOWED_AUDIO_EXTENSIONS:
        return JSONResponse({"error": "Unsupported file type. Use MP3, WAV or M4A."}, status_code=400)

    safe_name = storage.safe_filename(file.filename or "episode")
    episode = Episode(
        title="",
        original_filename=file.filename or safe_name,
        file_path="",
        file_size_bytes=0,
        status="draft",
    )
    db.add(episode)
    db.commit()
    db.refresh(episode)

    dest = storage.episode_dir(episode.id) / f"original{ext}"
    size = 0
    max_bytes = config.max_upload_bytes
    too_large = False
    with open(dest, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                too_large = True
                break
            f.write(chunk)

    if too_large or size == 0:
        dest.unlink(missing_ok=True)
        db.delete(episode)
        db.commit()
        if too_large:
            return JSONResponse({"error": "File exceeds the 500MB limit."}, status_code=400)
        return JSONResponse({"error": "Uploaded file is empty."}, status_code=400)

    episode.file_path = str(dest)
    episode.file_size_bytes = size
    db.commit()

    return {"episode_id": episode.id, "filename": episode.original_filename, "size_bytes": size}


@router.post("/episodes/{episode_id}/process")
def start_processing(episode_id: int, db: Session = Depends(get_db), steps: list[str] | None = Form(None)):
    episode = db.get(Episode, episode_id)
    if episode is None:
        return RedirectResponse(url="/upload", status_code=303)

    if episode.status == "error":
        reset_episode_for_retry(db, episode)

    # Preserve pipeline order (STEP_KEYS) rather than trusting form submission order, since
    # _set_step()'s progress calc walks job.steps sequentially.
    chosen = set(steps or []) | {"transcribing"}
    selected = [k for k in STEP_KEYS if k in chosen]
    job = Job(episode_id=episode.id, job_type="episode_processing", status="pending", steps=selected)
    db.add(job)
    episode.status = "processing"
    db.commit()
    db.refresh(job)

    submit_episode_processing(job.id)

    return RedirectResponse(url=f"/episodes/{episode.id}/processing", status_code=303)
