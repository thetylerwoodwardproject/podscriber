import json

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Episode, Job, Soundbite, VideoClip
from app.routers._shared import recent_episodes, sanitize_download_filename
from app.services import storage
from app.services.jobs import submit_video_export
from app.services.waveform import amplitude_envelope
from app.templating import templates

router = APIRouter()


def _get_or_create_clip(db: Session, soundbite: Soundbite) -> VideoClip:
    if soundbite.video_clip is None:
        clip = VideoClip(soundbite_id=soundbite.id, caption=soundbite.quote)
        db.add(clip)
        db.commit()
        db.refresh(soundbite)
    return soundbite.video_clip


@router.get("/episodes/{episode_id}/soundbites/{soundbite_id}/video", response_class=HTMLResponse)
def video_editor_page(episode_id: int, soundbite_id: int, request: Request, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    soundbite = db.get(Soundbite, soundbite_id)
    if episode is None or soundbite is None or soundbite.episode_id != episode_id:
        return RedirectResponse(url=f"/episodes/{episode_id}?tab=soundbites")

    clip = _get_or_create_clip(db, soundbite)

    envelope = []
    if soundbite.clip_audio_path:
        try:
            envelope = amplitude_envelope(soundbite.clip_audio_path, buckets=36)
        except Exception:
            envelope = [0.3] * 36
    else:
        envelope = [0.3] * 36

    swatches = ["#e2572c", "#0f8a6c", "#5b5bd6", "#c2410c", "#ffffff", "#c0ff00"]

    return templates.TemplateResponse(
        request,
        "video_clip.html",
        {
            "active_nav": "library",
            "recent_episodes": recent_episodes(db),
            "episode": episode,
            "soundbite": soundbite,
            "clip": clip,
            "envelope_json": json.dumps(envelope),
            "swatches": swatches,
        },
    )


@router.post("/episodes/{episode_id}/soundbites/{soundbite_id}/video/image")
async def upload_background_image(episode_id: int, soundbite_id: int, file: UploadFile, db: Session = Depends(get_db)):
    soundbite = db.get(Soundbite, soundbite_id)
    clip = _get_or_create_clip(db, soundbite)
    ext = (file.filename or "image.png").rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg", "webp"):
        ext = "png"
    dest = storage.images_dir(episode_id) / f"bg_{soundbite_id}.{ext}"
    with open(dest, "wb") as f:
        f.write(await file.read())
    clip.background_image_path = str(dest)
    db.commit()
    return {"url": f"/media/uploads/{episode_id}/images/{dest.name}"}


@router.post("/episodes/{episode_id}/soundbites/{soundbite_id}/video/logo")
async def upload_logo_image(episode_id: int, soundbite_id: int, file: UploadFile, db: Session = Depends(get_db)):
    soundbite = db.get(Soundbite, soundbite_id)
    clip = _get_or_create_clip(db, soundbite)
    ext = (file.filename or "logo.png").rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg", "webp"):
        ext = "png"
    dest = storage.images_dir(episode_id) / f"logo_{soundbite_id}.{ext}"
    with open(dest, "wb") as f:
        f.write(await file.read())
    clip.logo_image_path = str(dest)
    db.commit()
    return {"url": f"/media/uploads/{episode_id}/images/{dest.name}"}


@router.post("/episodes/{episode_id}/soundbites/{soundbite_id}/video/remove-image")
def remove_background_image(episode_id: int, soundbite_id: int, db: Session = Depends(get_db)):
    soundbite = db.get(Soundbite, soundbite_id)
    clip = _get_or_create_clip(db, soundbite)
    clip.background_image_path = None
    db.commit()
    return {"ok": True}


@router.post("/episodes/{episode_id}/soundbites/{soundbite_id}/video/remove-logo")
def remove_logo_image(episode_id: int, soundbite_id: int, db: Session = Depends(get_db)):
    soundbite = db.get(Soundbite, soundbite_id)
    clip = _get_or_create_clip(db, soundbite)
    clip.logo_image_path = None
    db.commit()
    return {"ok": True}


@router.post("/episodes/{episode_id}/soundbites/{soundbite_id}/video/settings")
async def update_clip_settings(episode_id: int, soundbite_id: int, request: Request, db: Session = Depends(get_db)):
    soundbite = db.get(Soundbite, soundbite_id)
    clip = _get_or_create_clip(db, soundbite)
    body = await request.json()
    if "brightness" in body:
        clip.brightness = max(0.4, min(1.6, float(body["brightness"])))
    if "waveform_offset_y" in body:
        clip.waveform_offset_y = max(-380, min(60, int(body["waveform_offset_y"])))
    if "caption" in body:
        clip.caption = str(body["caption"])[:500]
    if "waveform_color" in body:
        clip.waveform_color = str(body["waveform_color"])[:20]
    if "download_filename" in body:
        clip.download_filename = str(body["download_filename"])[:80] or None
    db.commit()
    return {"ok": True}


@router.post("/episodes/{episode_id}/soundbites/{soundbite_id}/video/export")
def export_video(episode_id: int, soundbite_id: int, db: Session = Depends(get_db)):
    soundbite = db.get(Soundbite, soundbite_id)
    _get_or_create_clip(db, soundbite)
    job = Job(episode_id=episode_id, soundbite_id=soundbite_id, job_type="video_export", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    submit_video_export(job.id)
    return {"job_id": job.id}


@router.get("/episodes/{episode_id}/soundbites/{soundbite_id}/video/status/stream")
def video_status_stream(episode_id: int, soundbite_id: int):
    import time as time_module

    from app.db import SessionLocal

    def event_source():
        db = SessionLocal()
        try:
            last_payload = None
            for _ in range(1200):  # ~10 min ceiling
                db.commit()  # release the read transaction so we see the export job's commits
                job = db.execute(
                    select(Job)
                    .where(Job.soundbite_id == soundbite_id, Job.job_type == "video_export")
                    .order_by(Job.created_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if job is None:
                    payload = {"status": "pending", "progress_pct": 0}
                else:
                    payload = {"status": job.status, "progress_pct": job.progress_pct, "error_message": job.error_message}
                if payload != last_payload:
                    yield f"data: {json.dumps(payload)}\n\n"
                    last_payload = payload
                if job is not None and job.status in ("done", "error"):
                    break
                time_module.sleep(0.5)
        finally:
            db.close()

    from fastapi.responses import StreamingResponse

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.get("/episodes/{episode_id}/soundbites/{soundbite_id}/video/download")
def download_video(episode_id: int, soundbite_id: int, db: Session = Depends(get_db)):
    soundbite = db.get(Soundbite, soundbite_id)
    clip = soundbite.video_clip if soundbite else None
    if clip is None or not clip.exported_video_path:
        return PlainTextResponse("No exported video yet.", status_code=404)
    filename = sanitize_download_filename(clip.download_filename, fallback=f"soundbite-{soundbite_id}")
    return FileResponse(clip.exported_video_path, filename=filename, media_type="video/mp4")
