import asyncio
import json
import shutil

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import config
from app.db import SessionLocal, get_db
from app.models import Chapter, Episode, Job, Soundbite
from app.routers._shared import recent_episodes
from app.services.chapters_export import build_chapters_json
from app.services.jobs import submit_social_regenerate
from app.services.llm.factory import get_llm_provider
from app.services.llm.prompts import SOCIAL_TONES
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
        failed_job = db.execute(
            select(Job)
            .where(Job.episode_id == episode_id, Job.job_type == "episode_processing")
            .order_by(Job.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
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
    job = Job(episode_id=episode_id, job_type="social_regenerate", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    submit_social_regenerate(job.id, tone)
    return {"job_id": job.id}


@router.get("/episodes/{episode_id}/social/regenerate/status/stream")
def social_regenerate_status_stream(episode_id: int):
    async def event_source():
        # Async, not sync — see processing.py's status_stream for why a sync generator
        # here would starve FastAPI's worker thread pool when the job status is idle.
        last_payload = None
        for _ in range(1200):  # ~10 min ceiling, matches the video-export status stream
            # Open a fresh, short-lived session per poll instead of holding one for the
            # whole loop — see the matching comment in processing.py's status_stream.
            db = SessionLocal()
            try:
                job = db.execute(
                    select(Job)
                    .where(Job.episode_id == episode_id, Job.job_type == "social_regenerate")
                    .order_by(Job.created_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
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


@router.get("/episodes/{episode_id}/social/posts-fragment", response_class=HTMLResponse)
def social_posts_fragment(episode_id: int, request: Request, db: Session = Depends(get_db)):
    episode = _get_or_404(db, episode_id)
    context = {"episode": episode, "content": episode.generated_content}
    return templates.TemplateResponse(request, "results/_social_posts_grid.html", context)


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
