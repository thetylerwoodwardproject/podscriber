import json

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Episode, Job, Soundbite, VideoClip
from app.routers._shared import export_status_stream, latest_job, recent_episodes, sse_job_stream, submit_and_track_job
from app.services import settings_store
from app.services.jobs import submit_clip_social_publish, submit_clip_social_regenerate, submit_video_export
from app.services.postiz import PLATFORMS
from app.services.social_attachments import (
    episode_video_options,
    resolve_image_attachment,
    resolve_video_source,
    validate_instagram_requirement,
)
from app.services.video_editor_shared import apply_clip_settings, download_response, save_clip_image
from app.services.waveform import amplitude_envelope
from app.templating import templates

router = APIRouter()


def _get_or_create_first_clip(db: Session, soundbite: Soundbite) -> VideoClip:
    """The soundbite's earliest-created clip, creating one if it has none yet. Used only by
    entry points that don't know a specific clip id (the bare `/video` link, bulk export)."""
    if not soundbite.video_clips:
        clip = VideoClip(soundbite_id=soundbite.id)
        db.add(clip)
        db.commit()
        db.refresh(soundbite)
    return soundbite.video_clips[0]


def _get_clip_or_404(db: Session, soundbite_id: int, clip_id: int) -> VideoClip | None:
    clip = db.get(VideoClip, clip_id)
    if clip is None or clip.soundbite_id != soundbite_id:
        return None
    return clip


@router.get("/episodes/{episode_id}/soundbites/{soundbite_id}/video", response_class=HTMLResponse)
def video_editor_entry(episode_id: int, soundbite_id: int, db: Session = Depends(get_db)):
    """No clip id yet — used by the soundbites list's "Edit video" link when a soundbite has
    exactly one (or no) video variant. Resolves to that variant, creating it if needed, and
    redirects into the clip-scoped editor URL below."""
    soundbite = db.get(Soundbite, soundbite_id)
    if soundbite is None or soundbite.episode_id != episode_id:
        return RedirectResponse(url=f"/episodes/{episode_id}?tab=soundbites")
    clip = _get_or_create_first_clip(db, soundbite)
    return RedirectResponse(url=f"/episodes/{episode_id}/soundbites/{soundbite_id}/video/{clip.id}")


@router.get("/episodes/{episode_id}/soundbites/{soundbite_id}/video/{clip_id}", response_class=HTMLResponse)
def video_editor_page(episode_id: int, soundbite_id: int, clip_id: int, request: Request, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    soundbite = db.get(Soundbite, soundbite_id)
    if episode is None or soundbite is None or soundbite.episode_id != episode_id:
        return RedirectResponse(url=f"/episodes/{episode_id}?tab=soundbites")

    clip = _get_clip_or_404(db, soundbite_id, clip_id)
    if clip is None:
        return RedirectResponse(url=f"/episodes/{episode_id}/soundbites/{soundbite_id}/video")

    envelope = []
    if soundbite.clip_audio_path:
        try:
            envelope = amplitude_envelope(soundbite.clip_audio_path, buckets=36)
        except Exception:
            envelope = [0.3] * 36
    else:
        envelope = [0.3] * 36

    swatches = ["#e2572c", "#0f8a6c", "#5b5bd6", "#c2410c", "#ffffff", "#c0ff00"]

    latest_publish_by_platform = {}
    for pub in sorted(clip.publishes, key=lambda p: p.created_at):
        latest_publish_by_platform[pub.platform] = pub

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
            "publish_platforms": PLATFORMS,
            "postiz_configured": bool(settings_store.get(db, "postiz_base_url") and settings_store.get(db, "postiz_api_key")),
            "latest_publish_by_platform": latest_publish_by_platform,
            "video_options": episode_video_options(episode),
            "clip_index": soundbite.video_clips.index(clip) + 1,
            "clip_count": len(soundbite.video_clips),
        },
    )


@router.post("/episodes/{episode_id}/soundbites/{soundbite_id}/video/{clip_id}/duplicate")
def duplicate_clip(episode_id: int, soundbite_id: int, clip_id: int, db: Session = Depends(get_db)):
    """Copies a clip's editable settings (background, waveform, social copy, ...) into a new
    variant for the same soundbite, leaving the original's export untouched — lets a user who
    already exported+published one video make a second version without losing the first."""
    clip = _get_clip_or_404(db, soundbite_id, clip_id)
    if clip is None:
        return {"ok": False, "error": "Video not found."}
    new_clip = VideoClip(
        soundbite_id=soundbite_id,
        background_image_path=clip.background_image_path,
        logo_image_path=clip.logo_image_path,
        brightness=clip.brightness,
        offset_x=clip.offset_x,
        offset_y=clip.offset_y,
        waveform_offset_y=clip.waveform_offset_y,
        social_post=clip.social_post,
        youtube_title=clip.youtube_title,
        waveform_color=clip.waveform_color,
        # Not copied: exported_video_path/exported_at/download_filename — the duplicate is a
        # fresh, unexported variant the user will render and name on its own.
    )
    db.add(new_clip)
    db.commit()
    db.refresh(new_clip)
    return {"ok": True, "url": f"/episodes/{episode_id}/soundbites/{soundbite_id}/video/{new_clip.id}"}


@router.post("/episodes/{episode_id}/soundbites/{soundbite_id}/video/{clip_id}/image")
async def upload_background_image(episode_id: int, soundbite_id: int, clip_id: int, file: UploadFile, db: Session = Depends(get_db)):
    clip = _get_clip_or_404(db, soundbite_id, clip_id)
    path, url = await save_clip_image(episode_id, file, f"bg_{clip_id}")
    clip.background_image_path = path
    db.commit()
    return {"url": url}


@router.post("/episodes/{episode_id}/soundbites/{soundbite_id}/video/{clip_id}/logo")
async def upload_logo_image(episode_id: int, soundbite_id: int, clip_id: int, file: UploadFile, db: Session = Depends(get_db)):
    clip = _get_clip_or_404(db, soundbite_id, clip_id)
    path, url = await save_clip_image(episode_id, file, f"logo_{clip_id}")
    clip.logo_image_path = path
    db.commit()
    return {"url": url}


@router.post("/episodes/{episode_id}/soundbites/{soundbite_id}/video/{clip_id}/remove-image")
def remove_background_image(episode_id: int, soundbite_id: int, clip_id: int, db: Session = Depends(get_db)):
    clip = _get_clip_or_404(db, soundbite_id, clip_id)
    clip.background_image_path = None
    db.commit()
    return {"ok": True}


@router.post("/episodes/{episode_id}/soundbites/{soundbite_id}/video/{clip_id}/remove-logo")
def remove_logo_image(episode_id: int, soundbite_id: int, clip_id: int, db: Session = Depends(get_db)):
    clip = _get_clip_or_404(db, soundbite_id, clip_id)
    clip.logo_image_path = None
    db.commit()
    return {"ok": True}


@router.post("/episodes/{episode_id}/soundbites/{soundbite_id}/video/{clip_id}/settings")
async def update_clip_settings(episode_id: int, soundbite_id: int, clip_id: int, request: Request, db: Session = Depends(get_db)):
    clip = _get_clip_or_404(db, soundbite_id, clip_id)
    body = await request.json()
    apply_clip_settings(clip, body, waveform_offset_range=(-380, 60))
    if "social_post" in body:
        clip.social_post = str(body["social_post"])[:2200]
    if "youtube_title" in body:
        clip.youtube_title = str(body["youtube_title"])[:99]
    db.commit()
    return {"ok": True}


@router.post("/episodes/{episode_id}/soundbites/{soundbite_id}/video/{clip_id}/social/regenerate")
def regenerate_clip_social(episode_id: int, soundbite_id: int, clip_id: int, db: Session = Depends(get_db)):
    return submit_and_track_job(
        db,
        job_type="clip_social_regenerate",
        submit_fn=submit_clip_social_regenerate,
        episode_id=episode_id,
        soundbite_id=soundbite_id,
        video_clip_id=clip_id,
    )


@router.get("/episodes/{episode_id}/soundbites/{soundbite_id}/video/{clip_id}/social/status/stream")
def clip_social_status_stream(episode_id: int, soundbite_id: int, clip_id: int):
    def payload_fn(job: Job) -> dict:
        payload = {"status": job.status, "error_message": job.error_message}
        if job.status == "done" and job.video_clip is not None:
            payload["social_post"] = job.video_clip.social_post
            payload["youtube_title"] = job.video_clip.youtube_title
        return payload

    return sse_job_stream(
        query_fn=lambda db: latest_job(db, "clip_social_regenerate", video_clip_id=clip_id),
        payload_fn=payload_fn,
        not_found_payload={"status": "pending"},
    )


@router.post("/episodes/{episode_id}/soundbites/{soundbite_id}/video/{clip_id}/export")
def export_video(episode_id: int, soundbite_id: int, clip_id: int, db: Session = Depends(get_db)):
    return submit_and_track_job(
        db,
        job_type="video_export",
        submit_fn=submit_video_export,
        episode_id=episode_id,
        soundbite_id=soundbite_id,
        video_clip_id=clip_id,
    )


@router.get("/episodes/{episode_id}/soundbites/{soundbite_id}/video/{clip_id}/status/stream")
def video_status_stream(episode_id: int, soundbite_id: int, clip_id: int):
    return export_status_stream("video_export", video_clip_id=clip_id)


@router.get("/episodes/{episode_id}/soundbites/{soundbite_id}/video/{clip_id}/download")
def download_video(episode_id: int, soundbite_id: int, clip_id: int, db: Session = Depends(get_db)):
    clip = _get_clip_or_404(db, soundbite_id, clip_id)
    return download_response(clip, fallback_stem=f"soundbite-{soundbite_id}-{clip_id}")


@router.post("/episodes/{episode_id}/soundbites/{soundbite_id}/video/{clip_id}/social/publish")
async def publish_clip_social(episode_id: int, soundbite_id: int, clip_id: int, request: Request, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    body = await request.json()
    platforms = [p for p in body.get("platforms", []) if p in PLATFORMS]
    mode = "scheduled" if body.get("mode") == "scheduled" else "now"
    scheduled_at = str(body["scheduled_at"]) if mode == "scheduled" and body.get("scheduled_at") else None
    video_source = body.get("video_source") if isinstance(body.get("video_source"), dict) else None
    image_source = body.get("image_source") if isinstance(body.get("image_source"), dict) else None

    if not platforms or (mode == "scheduled" and not scheduled_at):
        return {"ok": False, "error": "Select at least one platform (and a date/time, if scheduling)."}
    if not video_source:
        return {"ok": False, "error": "Pick a video to attach."}
    video_path, video_err = resolve_video_source(db, episode, video_source)
    if video_err:
        return {"ok": False, "error": video_err}
    image_attachment, image_err = resolve_image_attachment(db, episode, image_source)
    if image_source and image_err:
        return {"ok": False, "error": image_err}
    instagram_err = validate_instagram_requirement(platforms, image_attachment, has_video=bool(video_path))
    if instagram_err:
        return {"ok": False, "error": instagram_err}

    return submit_and_track_job(
        db,
        job_type="clip_social_publish",
        submit_fn=lambda job_id: submit_clip_social_publish(job_id, platforms, mode, scheduled_at, video_source, image_source),
        episode_id=episode_id,
        soundbite_id=soundbite_id,
        video_clip_id=clip_id,
    )


@router.get("/episodes/{episode_id}/soundbites/{soundbite_id}/video/{clip_id}/social/publish/status/stream")
def clip_social_publish_status_stream(episode_id: int, soundbite_id: int, clip_id: int):
    def payload_fn(job: Job) -> dict:
        payload = {"status": job.status, "error_message": job.error_message}
        if job.status in ("done", "error"):
            payload["publishes"] = [
                {
                    "platform": pub.platform,
                    "status": pub.status,
                    "error_message": pub.error_message,
                    "postiz_post_id": pub.postiz_post_id,
                    "scheduled_at": pub.scheduled_at.isoformat() if pub.scheduled_at else None,
                }
                # Filtered to this run's own job_id — a "latest per platform of all time" read
                # would show a stale prior success while the current run is still uploading or
                # fails before writing any per-platform rows.
                for pub in job.social_publishes
            ]
        return payload

    return sse_job_stream(
        query_fn=lambda db: latest_job(db, "clip_social_publish", video_clip_id=clip_id),
        payload_fn=payload_fn,
        not_found_payload={"status": "pending"},
    )


@router.post("/episodes/{episode_id}/soundbites/video/export-selected")
async def export_selected_videos(episode_id: int, request: Request, db: Session = Depends(get_db)):
    """Kicks off one `video_export` job per selected soundbite (its first/default video
    variant), so a batch of clips can be exported from the soundbites list without opening
    each one's editor individually."""
    body = await request.json()
    soundbite_ids = [int(x) for x in body.get("soundbite_ids", [])]
    jobs = []
    for soundbite_id in soundbite_ids:
        soundbite = db.get(Soundbite, soundbite_id)
        if soundbite is None or soundbite.episode_id != episode_id:
            continue
        clip = _get_or_create_first_clip(db, soundbite)
        result = submit_and_track_job(
            db,
            job_type="video_export",
            submit_fn=submit_video_export,
            episode_id=episode_id,
            soundbite_id=soundbite_id,
            video_clip_id=clip.id,
        )
        jobs.append({"soundbite_id": soundbite_id, "clip_id": clip.id, "job_id": result["job_id"]})
    return {"jobs": jobs}
