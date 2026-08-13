import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models import Episode, FeedEpisodeSuggestion, Job
from app.routers._shared import recent_episodes
from app.services import settings_store
from app.services.feed_catalog import load_feed_episodes
from app.services.feed_seo import episode_key, generate_suggestion_for_episode
from app.services.jobs import submit_feed_episode_deep_suggest, submit_feed_seo_bulk
from app.services.llm.factory import get_llm_provider
from app.templating import templates

router = APIRouter()


def _rows(db: Session, feed: dict) -> list[dict]:
    episodes = feed.get("episodes", [])
    keys = [episode_key(ep.get("guid"), ep["title"], ep["pub_date"]) for ep in episodes]
    suggestions = {
        row.episode_key: row
        for row in db.execute(
            select(FeedEpisodeSuggestion).where(FeedEpisodeSuggestion.episode_key.in_(keys))
        ).scalars()
    }
    return [
        {"episode": ep, "key": k, "suggestion": suggestions.get(k)}
        for ep, k in zip(episodes, keys, strict=True)
    ]


def _build_improvements_ctx(db: Session, force: bool) -> dict:
    s = settings_store.get_all(db)
    feed = load_feed_episodes(db, s, force=force)
    return {
        "feed_state": feed["state"],
        "fetched_at": feed.get("fetched_at"),
        "stale": feed.get("stale", False),
        "rows": _rows(db, feed) if feed["state"] == "ok" else [],
    }


@router.get("/improvements", response_class=HTMLResponse)
def improvements_page(request: Request, db: Session = Depends(get_db)):
    ctx = _build_improvements_ctx(db, force=False)
    return templates.TemplateResponse(
        request,
        "improvements.html",
        {
            "active_nav": "improvements",
            "recent_episodes": recent_episodes(db),
            **ctx,
        },
    )


@router.post("/improvements/refresh", response_class=HTMLResponse)
def refresh_improvements(request: Request, db: Session = Depends(get_db)):
    ctx = _build_improvements_ctx(db, force=True)
    return templates.TemplateResponse(request, "improvements/_content.html", ctx)


@router.get("/improvements/rows-fragment", response_class=HTMLResponse)
def improvements_rows_fragment(request: Request, db: Session = Depends(get_db)):
    ctx = _build_improvements_ctx(db, force=False)
    return templates.TemplateResponse(request, "improvements/_content.html", ctx)


@router.post("/improvements/suggest", response_class=HTMLResponse)
async def suggest_feed_episode(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    key = body["episode_key"]

    s = settings_store.get_all(db)
    feed = load_feed_episodes(db, s, force=False)
    match = next(
        (
            ep
            for ep in feed.get("episodes", [])
            if episode_key(ep.get("guid"), ep["title"], ep["pub_date"]) == key
        ),
        None,
    )
    if match is None:
        raise HTTPException(status_code=404, detail="Episode not found in cached feed")

    try:
        provider = get_llm_provider(db)
        row = generate_suggestion_for_episode(db, provider, key, match["title"], match["description"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Returns just the one row's AI column, rendered fresh — the frontend swaps it in
    # via innerHTML rather than patching individual fields, so the markup for "has a
    # suggestion" vs. "still empty" lives in exactly one place (the template).
    return templates.TemplateResponse(
        request, "improvements/_suggestion_col.html", {"row": {"key": key, "suggestion": row}}
    )


@router.post("/improvements/suggest-deep")
async def suggest_feed_episode_deep(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    key = body["episode_key"]

    s = settings_store.get_all(db)
    feed = load_feed_episodes(db, s, force=False)
    match = next(
        (
            ep
            for ep in feed.get("episodes", [])
            if episode_key(ep.get("guid"), ep["title"], ep["pub_date"]) == key
        ),
        None,
    )
    if match is None:
        raise HTTPException(status_code=404, detail="Episode not found in cached feed")
    if not match.get("enclosure_url"):
        # A cached feed entry missing its enclosure URL is usually a stale/incompatible cache
        # row rather than a real gap in the RSS feed, so force one refetch before giving up.
        feed = load_feed_episodes(db, s, force=True)
        match = next(
            (
                ep
                for ep in feed.get("episodes", [])
                if episode_key(ep.get("guid"), ep["title"], ep["pub_date"]) == key
            ),
            None,
        )
        if match is None:
            raise HTTPException(status_code=404, detail="Episode not found in cached feed")
        if not match.get("enclosure_url"):
            raise HTTPException(status_code=400, detail="This episode's feed entry has no audio URL to download.")

    row = db.execute(
        select(FeedEpisodeSuggestion).where(FeedEpisodeSuggestion.episode_key == key)
    ).scalar_one_or_none()
    if row is None:
        row = FeedEpisodeSuggestion(
            episode_key=key, original_title=match["title"], original_description=match["description"]
        )
        db.add(row)
        db.flush()

    episode = db.get(Episode, row.episode_id) if row.episode_id is not None else None
    if episode is None:
        episode = Episode(
            title=match["title"],
            original_filename=match["title"],
            file_path="",
            source="feed",
            status="draft",
        )
        db.add(episode)
        db.flush()
        row.episode_id = episode.id
    db.commit()

    # feed_episode_deep_suggest shares a single-worker executor with real transcription
    # (see jobs.py), so repeated clicks on the same episode (e.g. while retrying past a
    # transient error) must reuse an already-queued job instead of piling up duplicates
    # that would serialize behind each other for a long time.
    existing = db.execute(
        select(Job)
        .where(
            Job.episode_id == episode.id,
            Job.job_type == "feed_episode_deep_suggest",
            Job.status.in_(["pending", "running"]),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return {"job_id": existing.id}

    job = Job(episode_id=episode.id, job_type="feed_episode_deep_suggest", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    submit_feed_episode_deep_suggest(job.id)
    return {"job_id": job.id}


@router.get("/improvements/suggest-deep/status/stream")
def suggest_deep_status_stream(job_id: int):
    async def event_source():
        # Async, not sync — see processing.py's status_stream for why a sync generator
        # here would starve FastAPI's worker thread pool when the job status is idle.
        last_payload = None
        for _ in range(1200):  # ~10 min ceiling, matches the other status streams
            # Open a fresh, short-lived session per poll instead of holding one for the
            # whole loop — see the matching comment in processing.py's status_stream.
            db = SessionLocal()
            try:
                job = db.get(Job, job_id)
                if job is None:
                    payload = {"status": "error", "current_step": None, "progress_pct": 0, "error_message": "Job not found"}
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
            if job is None or job.status in ("done", "error"):
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.get("/improvements/suggest-deep/result", response_class=HTMLResponse)
def suggest_deep_result(request: Request, key: str, db: Session = Depends(get_db)):
    row = db.execute(
        select(FeedEpisodeSuggestion).where(FeedEpisodeSuggestion.episode_key == key)
    ).scalar_one_or_none()
    return templates.TemplateResponse(
        request, "improvements/_suggestion_col.html", {"row": {"key": key, "suggestion": row}}
    )


@router.post("/improvements/generate-all")
def generate_all(db: Session = Depends(get_db)):
    job = Job(job_type="feed_seo_suggestions", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    submit_feed_seo_bulk(job.id)
    return {"job_id": job.id}


@router.get("/improvements/generate-all/status/stream")
def generate_all_status_stream():
    def event_source():
        db = SessionLocal()
        try:
            last_payload = None
            for _ in range(1200):  # ~10 min ceiling, matches the video-export/social-regen status streams
                # Release the read transaction so we see commits made by the background job
                # thread's own session — see CLAUDE.md's SQLite cross-session polling gotcha.
                db.commit()
                job = db.execute(
                    select(Job)
                    .where(Job.job_type == "feed_seo_suggestions")
                    .order_by(Job.created_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if job is None:
                    payload = {"status": "pending", "current_step": None, "progress_pct": 0, "error_message": None}
                else:
                    payload = {
                        "status": job.status,
                        "current_step": job.current_step,
                        "progress_pct": job.progress_pct,
                        "error_message": job.error_message,
                    }
                if payload != last_payload:
                    yield f"data: {json.dumps(payload)}\n\n"
                    last_payload = payload
                if job is not None and job.status in ("done", "error"):
                    break
                time.sleep(0.5)
        finally:
            db.close()

    return StreamingResponse(event_source(), media_type="text/event-stream")
