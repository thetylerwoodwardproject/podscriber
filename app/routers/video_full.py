import json

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Episode, EpisodeVideo
from app.routers._shared import export_status_stream, recent_episodes, submit_and_track_job
from app.services.jobs import submit_full_video_export
from app.services.video_editor_shared import apply_clip_settings, download_response, save_clip_image
from app.services.waveform import amplitude_envelope
from app.templating import templates

router = APIRouter()


def _get_or_create_video(db: Session, episode: Episode) -> EpisodeVideo:
    if episode.video is None:
        video = EpisodeVideo(episode_id=episode.id, caption=episode.title or episode.original_filename)
        db.add(video)
        db.commit()
        db.refresh(episode)
    return episode.video


@router.get("/episodes/{episode_id}/video", response_class=HTMLResponse)
def full_video_editor_page(episode_id: int, request: Request, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    if episode is None:
        return RedirectResponse(url="/")

    video = _get_or_create_video(db, episode)

    envelope = []
    if episode.file_path:
        try:
            envelope = amplitude_envelope(episode.file_path, buckets=36)
        except Exception:
            envelope = [0.3] * 36
    else:
        envelope = [0.3] * 36

    swatches = ["#e2572c", "#0f8a6c", "#5b5bd6", "#c2410c", "#ffffff", "#c0ff00"]

    return templates.TemplateResponse(
        request,
        "video_full.html",
        {
            "active_nav": "library",
            "recent_episodes": recent_episodes(db),
            "episode": episode,
            "video": video,
            "envelope_json": json.dumps(envelope),
            "swatches": swatches,
        },
    )


@router.post("/episodes/{episode_id}/video/image")
async def upload_full_background_image(episode_id: int, file: UploadFile, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    video = _get_or_create_video(db, episode)
    path, url = await save_clip_image(episode_id, file, f"bg_full_{episode_id}")
    video.background_image_path = path
    db.commit()
    return {"url": url}


@router.post("/episodes/{episode_id}/video/logo")
async def upload_full_logo_image(episode_id: int, file: UploadFile, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    video = _get_or_create_video(db, episode)
    path, url = await save_clip_image(episode_id, file, f"logo_full_{episode_id}")
    video.logo_image_path = path
    db.commit()
    return {"url": url}


@router.post("/episodes/{episode_id}/video/remove-image")
def remove_full_background_image(episode_id: int, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    video = _get_or_create_video(db, episode)
    video.background_image_path = None
    db.commit()
    return {"ok": True}


@router.post("/episodes/{episode_id}/video/remove-logo")
def remove_full_logo_image(episode_id: int, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    video = _get_or_create_video(db, episode)
    video.logo_image_path = None
    db.commit()
    return {"ok": True}


@router.post("/episodes/{episode_id}/video/settings")
async def update_full_video_settings(episode_id: int, request: Request, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    video = _get_or_create_video(db, episode)
    body = await request.json()
    apply_clip_settings(video, body, waveform_offset_range=(-120, 20))
    if "caption" in body:
        video.caption = str(body["caption"])[:500]
    db.commit()
    return {"ok": True}


@router.post("/episodes/{episode_id}/video/export")
def export_full_video(episode_id: int, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    _get_or_create_video(db, episode)
    return submit_and_track_job(
        db, job_type="video_export_full", submit_fn=submit_full_video_export, episode_id=episode_id
    )


@router.get("/episodes/{episode_id}/video/status/stream")
def full_video_status_stream(episode_id: int):
    return export_status_stream("video_export_full", episode_id=episode_id)


@router.get("/episodes/{episode_id}/video/download")
def download_full_video(episode_id: int, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    video = episode.video if episode else None
    return download_response(video, fallback_stem=f"episode-{episode_id}")
