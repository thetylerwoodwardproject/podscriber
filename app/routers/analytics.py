import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers._shared import recent_episodes
from app.services import op3, podcast_index, settings_store, stats_cache
from app.templating import templates

router = APIRouter()
logger = logging.getLogger("podscriber.stats")

PI_FEED_TTL = timedelta(hours=24)
OP3_TTL = timedelta(hours=6)


def _load_podcast_index_section(db: Session, s: dict, force: bool) -> dict:
    api_key, api_secret, feed_url = s["podcast_index_api_key"], s["podcast_index_api_secret"], s["podcast_feed_url"]
    if not (api_key and api_secret and feed_url):
        return {"state": "not_configured"}

    cached = stats_cache.get(db, "podcast_index:feed")
    should_fetch = stats_cache.should_refetch(cached, force, PI_FEED_TTL)

    if not should_fetch and cached is not None:
        if cached.ok:
            return {"state": "ok", "feed": cached.payload, "fetched_at": cached.fetched_at, "stale": False}
        return {"state": "feed_not_found"} if cached.error_message == "not_found" else {"state": "error"}

    try:
        info = podcast_index.lookup_feed_by_url(api_key, api_secret, feed_url)
    except podcast_index.PodcastIndexNotFoundError:
        stats_cache.save(db, "podcast_index:feed", {}, ok=False, error_message="not_found")
        return {"state": "feed_not_found"}
    except podcast_index.PodcastIndexError:
        logger.exception("PodcastIndex feed lookup failed")
        if cached is not None and cached.ok:
            return {"state": "ok", "feed": cached.payload, "fetched_at": cached.fetched_at, "stale": True}
        return {"state": "error"}

    payload = {
        "feed_id": info.feed_id,
        "guid": info.guid,
        "title": info.title,
        "author": info.author,
        "description": info.description,
        "artwork_url": info.artwork_url,
        "link": info.link,
        "episode_count": info.episode_count,
        "categories": info.categories,
        "value_enabled": info.value_enabled,
    }
    saved_updates = {"podcast_index_feed_id": str(info.feed_id)}
    if info.guid:
        saved_updates["podcast_guid"] = info.guid
    settings_store.set_many(db, saved_updates)
    row = stats_cache.save(db, "podcast_index:feed", payload)
    return {"state": "ok", "feed": payload, "fetched_at": row.fetched_at, "stale": False}


def _load_podcast_index_episodes_section(db: Session, s: dict, force: bool) -> dict:
    api_key, api_secret, feed_id_str = s["podcast_index_api_key"], s["podcast_index_api_secret"], s["podcast_index_feed_id"]
    if not (api_key and api_secret and feed_id_str):
        return {"state": "not_configured"}

    cached = stats_cache.get(db, "podcast_index:episodes:analytics")
    should_fetch = stats_cache.should_refetch(cached, force, PI_FEED_TTL)

    if not should_fetch and cached is not None:
        if cached.ok:
            return {"state": "ok", "episodes": cached.payload["episodes"], "fetched_at": cached.fetched_at, "stale": False}
        return {"state": "error"}

    try:
        episodes = podcast_index.list_episodes_by_feed_id(api_key, api_secret, int(feed_id_str), max_results=50)
    except podcast_index.PodcastIndexError:
        logger.exception("PodcastIndex episode list fetch failed")
        if cached is not None and cached.ok:
            return {"state": "ok", "episodes": cached.payload["episodes"], "fetched_at": cached.fetched_at, "stale": True}
        return {"state": "error"}

    payload = {
        "episodes": [
            {
                "title": ep.title,
                "pub_date": datetime.fromtimestamp(ep.pub_date, tz=UTC).strftime("%b %-d, %Y") if ep.pub_date else "",
                "duration_seconds": ep.duration_seconds,
                "guid": ep.guid,
                "description": ep.description,
            }
            for ep in episodes
        ]
    }
    row = stats_cache.save(db, "podcast_index:episodes:analytics", payload)
    return {"state": "ok", "episodes": payload["episodes"], "fetched_at": row.fetched_at, "stale": False}


def _joined_episode_rows(pi_episodes: list[dict], op3_downloads: dict | None) -> list[dict]:
    # OP3 and PodcastIndex share no common id in what either API returns here, so titles are
    # the only practical join key between "this show's episode metadata" and "its download counts".
    # Read with .get() rather than [] — these dicts round-trip through the JSON stats_cache table,
    # so a row cached under an older payload shape must degrade gracefully, not 500 the page.
    op3_by_title = {ep.get("title"): ep for ep in (op3_downloads["episodes"] if op3_downloads else [])}
    rows = []
    for ep in pi_episodes:
        op3_ep = op3_by_title.get(ep.get("title"))
        rows.append(
            {
                "title": ep.get("title", ""),
                "pub_date": ep.get("pub_date", ""),
                "duration_seconds": ep.get("duration_seconds"),
                "description": ep.get("description", ""),
                "downloads_7": op3_ep.get("downloads_7") if op3_ep else None,
                "downloads_30": op3_ep.get("downloads_30") if op3_ep else None,
                "downloads_all": op3_ep.get("downloads_all") if op3_ep else None,
            }
        )
    return rows


def _load_op3_section(db: Session, s: dict, force: bool) -> dict:
    api_key = s["op3_api_key"]
    podcast_guid, feed_url = s["podcast_guid"], s["podcast_feed_url"]
    if not (api_key and (podcast_guid or feed_url)):
        return {"state": "not_configured"}

    show_uuid = s["op3_show_uuid"]
    if not show_uuid:
        try:
            show_uuid = op3.resolve_show_uuid(api_key, podcast_guid, feed_url)
        except op3.Op3Error:
            logger.exception("OP3 show lookup failed")
            return {"state": "error"}
        if show_uuid is None:
            return {"state": "not_enabled", "prefix_example": op3.op3_prefix_example(podcast_guid)}
        settings_store.set_many(db, {"op3_show_uuid": show_uuid})

    cached = stats_cache.get(db, "op3:show_downloads")
    should_fetch = stats_cache.should_refetch(cached, force, OP3_TTL)

    if not should_fetch and cached is not None:
        if cached.ok:
            return {"state": "ok", "downloads": cached.payload, "fetched_at": cached.fetched_at, "stale": False}
        return {"state": "error"}

    try:
        show_stats = op3.get_show_download_counts(api_key, show_uuid)
        episodes = op3.get_episode_download_counts(api_key, show_uuid)
    except op3.Op3Error:
        logger.exception("OP3 download counts fetch failed")
        if cached is not None and cached.ok:
            return {"state": "ok", "downloads": cached.payload, "fetched_at": cached.fetched_at, "stale": True}
        return {"state": "error"}

    payload = {
        "as_of": show_stats.as_of,
        "monthly_downloads": show_stats.monthly_downloads,
        "weekly_avg_downloads": show_stats.weekly_avg_downloads,
        "weekly_downloads": show_stats.weekly_downloads,
        "num_weeks": show_stats.num_weeks,
        "episodes": [
            {
                "title": ep.title,
                "pub_date": ep.pub_date,
                "downloads_1": ep.downloads_1,
                "downloads_7": ep.downloads_7,
                "downloads_30": ep.downloads_30,
                "downloads_all": ep.downloads_all,
            }
            for ep in episodes
        ],
    }
    row = stats_cache.save(db, "op3:show_downloads", payload)
    return {"state": "ok", "downloads": payload, "fetched_at": row.fetched_at, "stale": False}


def _load_stats_context(db: Session, force: bool = False) -> dict:
    s = settings_store.get_all(db)
    return {
        "pi": _load_podcast_index_section(db, s, force),
        "pi_episodes": _load_podcast_index_episodes_section(db, s, force),
        "op3": _load_op3_section(db, s, force),
    }


MAX_TREND_WEEKS = 12


def _weekly_chart_bars(downloads: dict) -> list[dict]:
    # OP3 only exposes weekly (not daily) totals for a show, ascending in time. A show that's
    # been on OP3 for a long time can return far more weeks than fit legibly on one trend line,
    # so the chart only plots the most recent MAX_TREND_WEEKS (the table/tooltip still cover
    # the exact numbers).
    weekly = downloads["weekly_downloads"][-MAX_TREND_WEEKS:]
    n = len(weekly)
    bars = []
    for i, count in enumerate(weekly):
        weeks_ago = n - 1 - i
        label = "This week" if weeks_ago == 0 else f"{weeks_ago}w ago"
        bars.append({"label": label, "count": count})
    return bars


def _top_episodes(downloads: dict, limit: int = 10) -> list[dict]:
    return sorted(downloads["episodes"], key=lambda ep: ep["downloads_all"], reverse=True)[:limit]


def _duration_histogram(rows: list[dict]) -> list[dict]:
    buckets = [
        (0, 900, "<15m"),
        (900, 1800, "15-30m"),
        (1800, 2700, "30-45m"),
        (2700, 3600, "45-60m"),
        (3600, 5400, "60-90m"),
        (5400, None, "90m+"),
    ]
    counts = [0] * len(buckets)
    for ep in rows:
        d = ep["duration_seconds"]
        if not d:
            continue
        for i, (lo, hi, _label) in enumerate(buckets):
            if d >= lo and (hi is None or d < hi):
                counts[i] += 1
                break
    return [{"label": label, "count": counts[i]} for i, (_lo, _hi, label) in enumerate(buckets)]


def _build_stats_ctx(db: Session, force: bool) -> dict:
    ctx = _load_stats_context(db, force=force)
    if ctx["op3"]["state"] == "ok":
        ctx["op3"]["weekly_bars"] = _weekly_chart_bars(ctx["op3"]["downloads"])
        ctx["op3"]["top_episodes"] = _top_episodes(ctx["op3"]["downloads"])
    if ctx["pi_episodes"]["state"] == "ok":
        op3_downloads = ctx["op3"]["downloads"] if ctx["op3"]["state"] == "ok" else None
        ctx["pi_episodes"]["rows"] = _joined_episode_rows(ctx["pi_episodes"]["episodes"], op3_downloads)
        ctx["pi_episodes"]["duration_histogram"] = _duration_histogram(ctx["pi_episodes"]["rows"])
    return ctx


@router.get("/stats")
def stats_redirect():
    return RedirectResponse(url="/analytics", status_code=301)


@router.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request, db: Session = Depends(get_db)):
    ctx = _build_stats_ctx(db, force=False)
    return templates.TemplateResponse(
        request,
        "analytics.html",
        {
            "active_nav": "analytics",
            "recent_episodes": recent_episodes(db),
            **ctx,
        },
    )


@router.post("/analytics/refresh", response_class=HTMLResponse)
def refresh_analytics(request: Request, db: Session = Depends(get_db)):
    ctx = _build_stats_ctx(db, force=True)
    return templates.TemplateResponse(request, "analytics/_analytics_content.html", ctx)
