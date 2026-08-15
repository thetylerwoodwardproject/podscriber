"""Fetches and caches the podcast's full RSS back catalog via PodcastIndex.

Shared by the Improvements router (page rendering) and the feed-SEO background job
(app/services/feed_seo.py) — pulled out of app/routers/improvements.py so a service
doesn't need to import from a router.
"""

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.services import podcast_index, settings_store, stats_cache

logger = logging.getLogger("podscriber.improvements")

PI_EPISODES_TTL = timedelta(hours=6)
MAX_FEED_EPISODES = 1000
CACHE_KEY = "podcast_index:episodes"


def load_feed_episodes(db: Session, s: dict, force: bool) -> dict:
    api_key, api_secret, feed_url = s["podcast_index_api_key"], s["podcast_index_api_secret"], s["podcast_feed_url"]
    if not (api_key and api_secret and feed_url):
        return {"state": "not_configured"}

    feed_id = s.get("podcast_index_feed_id")
    if not feed_id:
        try:
            info = podcast_index.lookup_feed_by_url(api_key, api_secret, feed_url)
        except podcast_index.PodcastIndexNotFoundError:
            return {"state": "feed_not_found"}
        except podcast_index.PodcastIndexError:
            logger.exception("PodcastIndex feed lookup failed")
            return {"state": "error"}
        feed_id = info.feed_id
        saved = {"podcast_index_feed_id": str(info.feed_id)}
        if info.guid:
            saved["podcast_guid"] = info.guid
        settings_store.set_many(db, saved)

    cached = stats_cache.get(db, CACHE_KEY)
    should_fetch = stats_cache.should_refetch(cached, force, PI_EPISODES_TTL)

    if not should_fetch and cached is not None:
        if cached.ok:
            return {"state": "ok", "episodes": cached.payload["episodes"], "fetched_at": cached.fetched_at, "stale": False}
        return {"state": "error"}

    try:
        episodes = podcast_index.list_episodes_by_feed_id(
            api_key, api_secret, int(feed_id), max_results=MAX_FEED_EPISODES
        )
    except podcast_index.PodcastIndexError:
        logger.exception("PodcastIndex episode list fetch failed")
        if cached is not None and cached.ok:
            return {"state": "ok", "episodes": cached.payload["episodes"], "fetched_at": cached.fetched_at, "stale": True}
        return {"state": "error"}

    payload = {
        "episodes": [
            {
                "title": e.title,
                "description": e.description,
                "pub_date": e.pub_date,
                "guid": e.guid,
                "enclosure_url": e.enclosure_url,
            }
            for e in episodes
        ]
    }
    row = stats_cache.save(db, CACHE_KEY, payload)
    return {"state": "ok", "episodes": payload["episodes"], "fetched_at": row.fetched_at, "stale": False}
