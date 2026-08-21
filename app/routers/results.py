import shutil
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import config
from app.db import get_db
from app.models import Chapter, Episode, SocialAttachment, Soundbite
from app.routers._shared import latest_job, recent_episodes, sse_job_stream, submit_and_track_job
from app.services import settings_store, storage
from app.services.chapters_export import build_chapters_json
from app.services.jobs import submit_episode_social_publish, submit_social_regenerate
from app.services.llm.factory import get_llm_provider
from app.services.llm.prompts import SOCIAL_TONES
from app.services.postiz import PLATFORMS
from app.services.social_attachments import (
    ALLOWED_ATTACHMENT_IMAGE_EXTENSIONS,
    ALLOWED_ATTACHMENT_VIDEO_EXTENSIONS,
    decode_image_dimensions,
    episode_video_options,
    guess_content_type,
    instagram_image_ok,
    resolve_image_attachment,
    resolve_video_source,
    validate_instagram_requirement,
)
from app.services.vtt import build_vtt
from app.templating import templates

router = APIRouter()

TABS = [
    ("titles", "Titles"),
    ("description", "Description"),
    ("social", "Social Posts"),
    ("keywords", "Keywords"),
    ("chapters", "Chapters"),
    ("soundbites", "Soundbites"),
    ("video", "Video"),
    ("transcript", "Transcript"),
]


def _get_or_404(db: Session, episode_id: int) -> Episode:
    episode = db.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail=f"No episode {episode_id}")
    return episode


@router.get("/episodes/{episode_id}", response_class=HTMLResponse)
def results_page(episode_id: int, request: Request, tab: str = "titles", db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    if episode is None:
        return RedirectResponse(url="/")
    if episode.status == "processing":
        return RedirectResponse(url=f"/episodes/{episode_id}/processing")
    if episode.status == "draft":
        return RedirectResponse(url="/upload")

    valid_keys = [k for k, _ in TABS]
    if tab not in valid_keys:
        tab = "titles"

    content = episode.generated_content
    transcript = episode.transcript

    last_error = None
    if episode.status == "error":
        failed_job = latest_job(db, "episode_processing", episode_id=episode_id)
        if failed_job is not None:
            last_error = failed_job.error_message

    context = {
        "active_nav": "library",
        "recent_episodes": recent_episodes(db),
        "episode": episode,
        "content": content,
        "transcript": transcript,
        "soundbites": episode.soundbites,
        "chapters": episode.chapters,
        "episode_video": episode.video,
        "tabs": TABS,
        "active_tab": tab,
        "last_error": last_error,
        "social_tones": SOCIAL_TONES,
        "postiz_configured": bool(settings_store.get(db, "postiz_base_url") and settings_store.get(db, "postiz_api_key")),
        "video_options": episode_video_options(episode),
    }
    return templates.TemplateResponse(request, "results.html", context)


@router.post("/episodes/{episode_id}/delete")
def delete_episode(episode_id: int, db: Session = Depends(get_db)):
    episode = _get_or_404(db, episode_id)
    db.delete(episode)
    db.commit()
    shutil.rmtree(config.uploads_dir / str(episode_id), ignore_errors=True)
    return RedirectResponse(url="/", status_code=303)


# ---- Titles ----
@router.post("/episodes/{episode_id}/titles/select")
def select_title(episode_id: int, index: int = Form(...), db: Session = Depends(get_db)):
    episode = _get_or_404(db, episode_id)
    content = episode.generated_content
    if content and 0 <= index < len(content.titles):
        content.selected_title_index = index
        episode.title = content.titles[index]["text"]
        db.commit()
    return {"ok": True, "index": index}


@router.post("/episodes/{episode_id}/titles/{index}/edit")
def edit_title(episode_id: int, index: int, text: str = Form(...), db: Session = Depends(get_db)):
    episode = _get_or_404(db, episode_id)
    content = episode.generated_content
    if content and 0 <= index < len(content.titles):
        titles = list(content.titles)
        titles[index] = {**titles[index], "text": text}
        content.titles = titles
        if content.selected_title_index == index:
            episode.title = text
        db.commit()
    return {"ok": True, "index": index, "text": text}


# ---- Description ----
@router.post("/episodes/{episode_id}/description/edit")
def edit_description(episode_id: int, text: str = Form(...), db: Session = Depends(get_db)):
    episode = _get_or_404(db, episode_id)
    if episode.generated_content:
        episode.generated_content.description = text
        db.commit()
    return {"ok": True, "text": text}


@router.post("/episodes/{episode_id}/description/regenerate")
def regenerate_description(episode_id: int, db: Session = Depends(get_db)):
    episode = _get_or_404(db, episode_id)
    try:
        llm = get_llm_provider(db)
        result = llm.generate_description_and_keywords(episode.transcript.full_text if episode.transcript else "")
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Couldn't regenerate — check your text-generation provider in Settings and try again.",
        ) from None
    if episode.generated_content:
        episode.generated_content.description = result.description
        episode.generated_content.keywords = result.keywords
        db.commit()
    return {"ok": True, "text": result.description}


# ---- Social posts ----
@router.post("/episodes/{episode_id}/social/{group_index}/{post_index}/edit")
def edit_social_post(episode_id: int, group_index: int, post_index: int, text: str = Form(...), db: Session = Depends(get_db)):
    episode = _get_or_404(db, episode_id)
    content = episode.generated_content
    if content and 0 <= group_index < len(content.social_posts):
        groups = list(content.social_posts)
        posts = list(groups[group_index]["posts"])
        if 0 <= post_index < len(posts):
            posts[post_index] = text
            groups[group_index] = {**groups[group_index], "posts": posts}
            content.social_posts = groups
            db.commit()
    return {"ok": True, "text": text}


@router.post("/episodes/{episode_id}/social/regenerate")
def regenerate_social_posts(episode_id: int, tone: str = Form("casual"), db: Session = Depends(get_db)):
    _get_or_404(db, episode_id)
    return submit_and_track_job(
        db,
        job_type="social_regenerate",
        submit_fn=lambda job_id: submit_social_regenerate(job_id, tone),
        episode_id=episode_id,
    )


@router.get("/episodes/{episode_id}/social/regenerate/status/stream")
def social_regenerate_status_stream(episode_id: int):
    return sse_job_stream(
        query_fn=lambda db: latest_job(db, "social_regenerate", episode_id=episode_id),
        payload_fn=lambda job: {"status": job.status, "error_message": job.error_message},
        not_found_payload={"status": "pending"},
    )


@router.get("/episodes/{episode_id}/social/posts-fragment", response_class=HTMLResponse)
def social_posts_fragment(episode_id: int, request: Request, db: Session = Depends(get_db)):
    episode = _get_or_404(db, episode_id)
    context = {
        "episode": episode,
        "content": episode.generated_content,
        "postiz_configured": bool(settings_store.get(db, "postiz_base_url") and settings_store.get(db, "postiz_api_key")),
        "video_options": episode_video_options(episode),
    }
    return templates.TemplateResponse(request, "results/_social_posts_grid.html", context)


@router.post("/episodes/{episode_id}/social/attachments")
async def upload_social_attachment(
    episode_id: int, file: UploadFile, kind: str = Form(...), db: Session = Depends(get_db)
):
    episode = _get_or_404(db, episode_id)
    if kind not in ("video", "image"):
        return {"ok": False, "error": "Unsupported attachment kind."}
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    allowed = ALLOWED_ATTACHMENT_IMAGE_EXTENSIONS if kind == "image" else ALLOWED_ATTACHMENT_VIDEO_EXTENSIONS
    if ext not in allowed:
        return {"ok": False, "error": f"Unsupported file type: .{ext}"}

    content = await file.read()
    if len(content) > config.max_upload_bytes:
        return {"ok": False, "error": "File is too large."}

    dest_name = f"{uuid4().hex}_{storage.safe_filename(file.filename or f'upload.{ext}')}"
    dest = storage.social_attachments_dir(episode_id) / dest_name
    with open(dest, "wb") as f:
        f.write(content)

    width = height = None
    if kind == "image":
        try:
            width, height = decode_image_dimensions(str(dest))
        except ValueError as exc:
            dest.unlink(missing_ok=True)
            return {"ok": False, "error": str(exc)}

    attachment = SocialAttachment(
        episode_id=episode.id,
        kind=kind,
        file_path=str(dest),
        original_filename=file.filename or dest.name,
        content_type=guess_content_type(dest.name),
        width=width,
        height=height,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    payload = {
        "id": attachment.id,
        "kind": kind,
        "url": f"/media/uploads/{episode_id}/social/{dest.name}",
        "filename": attachment.original_filename,
        "width": width,
        "height": height,
    }
    if kind == "image":
        payload["instagram_ok"] = instagram_image_ok(width, height)
    return {"ok": True, "attachment": payload}


@router.post("/episodes/{episode_id}/social/publish")
async def publish_social_posts(episode_id: int, request: Request, db: Session = Depends(get_db)):
    episode = _get_or_404(db, episode_id)
    body = await request.json()
    selections = []
    for sel in body.get("selections", []):
        if sel.get("platform") not in PLATFORMS:
            continue
        try:
            group_index = int(sel["group_index"])
            post_index = int(sel["post_index"])
            platform = sel["platform"]
        except (KeyError, TypeError, ValueError):
            continue

        video_source = sel.get("video_source") if isinstance(sel.get("video_source"), dict) else None
        image_source = sel.get("image_source") if isinstance(sel.get("image_source"), dict) else None

        video_path, video_err = resolve_video_source(db, episode, video_source)
        if video_source and video_err:
            return {"ok": False, "error": video_err}
        image_attachment, image_err = resolve_image_attachment(db, episode, image_source)
        if image_source and image_err:
            return {"ok": False, "error": image_err}
        instagram_err = validate_instagram_requirement([platform], image_attachment, has_video=bool(video_path))
        if instagram_err:
            return {"ok": False, "error": instagram_err}

        selections.append(
            {
                "group_index": group_index,
                "post_index": post_index,
                "platform": platform,
                "video_source": video_source,
                "image_source": image_source,
            }
        )
    mode = "scheduled" if body.get("mode") == "scheduled" else "now"
    scheduled_at = str(body["scheduled_at"]) if mode == "scheduled" and body.get("scheduled_at") else None
    if not selections or (mode == "scheduled" and not scheduled_at):
        return {"ok": False, "error": "Nothing to publish (or missing a scheduled date/time)."}
    return submit_and_track_job(
        db,
        job_type="episode_social_publish",
        submit_fn=lambda job_id: submit_episode_social_publish(job_id, selections, mode, scheduled_at),
        episode_id=episode_id,
    )


@router.get("/episodes/{episode_id}/social/publish/status/stream")
def social_publish_status_stream(episode_id: int):
    def payload_fn(job) -> dict:
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
                for pub in job.social_publishes
            ]
        return payload

    return sse_job_stream(
        query_fn=lambda db: latest_job(db, "episode_social_publish", episode_id=episode_id),
        payload_fn=payload_fn,
        not_found_payload={"status": "pending"},
    )


# ---- Keywords ----
@router.post("/episodes/{episode_id}/keywords/add")
def add_keyword(episode_id: int, text: str = Form(...), db: Session = Depends(get_db)):
    episode = _get_or_404(db, episode_id)
    text = text.strip()
    added = False
    if episode.generated_content and text:
        kws = list(episode.generated_content.keywords)
        if text not in kws:
            kws.append(text)
            episode.generated_content.keywords = kws
            db.commit()
            added = True
    return {"ok": added, "text": text}


@router.post("/episodes/{episode_id}/keywords/{index}/remove")
def remove_keyword(episode_id: int, index: int, db: Session = Depends(get_db)):
    episode = _get_or_404(db, episode_id)
    if episode.generated_content:
        kws = list(episode.generated_content.keywords)
        if 0 <= index < len(kws):
            kws.pop(index)
            episode.generated_content.keywords = kws
            db.commit()
    return {"ok": True}


# ---- Chapters ----
@router.post("/episodes/{episode_id}/chapters/{chapter_id}/edit")
def edit_chapter(episode_id: int, chapter_id: int, title: str = Form(...), db: Session = Depends(get_db)):
    chapter = db.get(Chapter, chapter_id)
    if chapter and chapter.episode_id == episode_id:
        chapter.title = title.strip() or chapter.title
        db.commit()
        title = chapter.title
    return {"ok": True, "title": title}


@router.post("/episodes/{episode_id}/chapters/{chapter_id}/delete")
def delete_chapter(episode_id: int, chapter_id: int, db: Session = Depends(get_db)):
    chapter = db.get(Chapter, chapter_id)
    if chapter and chapter.episode_id == episode_id:
        db.delete(chapter)
        db.commit()
    return {"ok": True}


@router.get("/episodes/{episode_id}/chapters.json")
def download_chapters(episode_id: int, db: Session = Depends(get_db)):
    episode = _get_or_404(db, episode_id)
    body = build_chapters_json(list(episode.chapters))
    slug = (episode.title or episode.original_filename or "episode").strip().replace(" ", "-").lower()
    return PlainTextResponse(
        body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{slug}.chapters.json"'},
    )


# ---- Transcript / VTT ----
@router.get("/episodes/{episode_id}/transcript.vtt")
def download_vtt(episode_id: int, db: Session = Depends(get_db)):
    episode = _get_or_404(db, episode_id)
    if not episode.transcript:
        return PlainTextResponse("No transcript available.", status_code=404)
    body = build_vtt(list(episode.transcript.segments))
    slug = (episode.title or episode.original_filename or "episode").strip().replace(" ", "-").lower()
    return PlainTextResponse(
        body,
        media_type="text/vtt",
        headers={"Content-Disposition": f'attachment; filename="{slug}.vtt"'},
    )


# ---- Soundbites ----
@router.post("/episodes/{episode_id}/soundbites/{soundbite_id}/toggle-include")
def toggle_soundbite_include(episode_id: int, soundbite_id: int, db: Session = Depends(get_db)):
    sb = db.get(Soundbite, soundbite_id)
    if sb and sb.episode_id == episode_id:
        sb.include = not sb.include
        db.commit()
        return {"ok": True, "include": sb.include}
    return {"ok": False, "include": None}


@router.get("/episodes/{episode_id}/soundbites/{soundbite_id}/download")
def download_soundbite(episode_id: int, soundbite_id: int, db: Session = Depends(get_db)):
    sb = db.get(Soundbite, soundbite_id)
    if sb is None or sb.episode_id != episode_id or not sb.clip_audio_path:
        return PlainTextResponse("Soundbite clip not available.", status_code=404)
    return FileResponse(sb.clip_audio_path, filename=f"soundbite-{soundbite_id}.mp3", media_type="audio/mpeg")
