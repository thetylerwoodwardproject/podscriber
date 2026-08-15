import asyncio
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.routers import improvements as improvements_router
from app.services import feed_catalog, podcast_index, settings_store
from app.services.llm.base import SeoSuggestion


def test_not_configured_by_default(db):
    s = settings_store.get_all(db)
    ctx = feed_catalog.load_feed_episodes(db, s, force=False)
    assert ctx == {"state": "not_configured"}


def test_feed_not_found(db, monkeypatch):
    settings_store.set_many(
        db,
        {
            "podcast_index_api_key": "k",
            "podcast_index_api_secret": "s",
            "podcast_feed_url": "https://unknown.example.com/feed.xml",
        },
    )

    def _raise(*a, **k):
        raise podcast_index.PodcastIndexNotFoundError("not found")

    monkeypatch.setattr(podcast_index, "lookup_feed_by_url", _raise)
    s = settings_store.get_all(db)
    ctx = feed_catalog.load_feed_episodes(db, s, force=False)
    assert ctx == {"state": "feed_not_found"}


def test_ok_fetches_and_caches(db, monkeypatch):
    settings_store.set_many(
        db,
        {
            "podcast_index_api_key": "k",
            "podcast_index_api_secret": "s",
            "podcast_feed_url": "https://feeds.example.com/show.xml",
            "podcast_index_feed_id": "123",
        },
    )
    calls = []
    ep = podcast_index.PodcastIndexEpisode(
        title="Ep 1", pub_date=1700000000, duration_seconds=1800, guid="g1", description="notes"
    )
    monkeypatch.setattr(
        podcast_index, "list_episodes_by_feed_id", lambda *a, **k: calls.append(1) or [ep]
    )
    s = settings_store.get_all(db)
    ctx = feed_catalog.load_feed_episodes(db, s, force=False)
    assert ctx["state"] == "ok"
    assert ctx["episodes"][0]["title"] == "Ep 1"
    assert len(calls) == 1

    ctx2 = feed_catalog.load_feed_episodes(db, s, force=False)
    assert ctx2["state"] == "ok"
    assert len(calls) == 1


def test_error_falls_back_to_stale_cache(db, monkeypatch):
    settings_store.set_many(
        db,
        {
            "podcast_index_api_key": "k",
            "podcast_index_api_secret": "s",
            "podcast_feed_url": "https://feeds.example.com/show.xml",
            "podcast_index_feed_id": "123",
        },
    )
    ep = podcast_index.PodcastIndexEpisode(
        title="Ep 1", pub_date=1700000000, duration_seconds=1800, guid="g1", description="notes"
    )
    monkeypatch.setattr(podcast_index, "list_episodes_by_feed_id", lambda *a, **k: [ep])
    s = settings_store.get_all(db)
    feed_catalog.load_feed_episodes(db, s, force=False)

    def _raise(*a, **k):
        raise podcast_index.PodcastIndexError("boom")

    monkeypatch.setattr(podcast_index, "list_episodes_by_feed_id", _raise)
    monkeypatch.setattr(feed_catalog, "PI_EPISODES_TTL", timedelta(seconds=-1))
    ctx = feed_catalog.load_feed_episodes(db, s, force=False)
    assert ctx["state"] == "ok"
    assert ctx["stale"] is True


class _FakeRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


class _StubProvider:
    def generate_seo_suggestion(self, title, description, transcript_text=None):
        suffix = " (from transcript)" if transcript_text else ""
        return SeoSuggestion(title=f"Better: {title}{suffix}", description=f"Better: {description}{suffix}")


class _FailingProvider:
    def generate_seo_suggestion(self, title, description, transcript_text=None):
        raise RuntimeError("boom")


def _feed_ctx(*episodes):
    return {"state": "ok", "episodes": list(episodes)}


def test_improvements_page_shows_existing_suggestions_and_ungenerated_rows(db, monkeypatch):
    from app.models import FeedEpisodeSuggestion

    db.add(
        FeedEpisodeSuggestion(
            episode_key="g0",
            original_title="A",
            original_description="A desc",
            suggested_title="Better: A",
            suggested_description="Better: A desc",
        )
    )
    db.commit()
    monkeypatch.setattr(
        improvements_router,
        "load_feed_episodes",
        lambda db, s, force: _feed_ctx(
            {"title": "A", "description": "A desc", "pub_date": 1, "guid": "g0"},
            {"title": "B", "description": "B desc", "pub_date": 2, "guid": "g1"},
        ),
    )
    ctx = improvements_router._build_improvements_ctx(db, force=False)
    rows = {r["key"]: r for r in ctx["rows"]}
    assert rows["g0"]["suggestion"].suggested_title == "Better: A"
    assert rows["g1"]["suggestion"] is None


def test_suggest_route_creates_suggestion(db, monkeypatch):
    from app.models import FeedEpisodeSuggestion

    monkeypatch.setattr(
        improvements_router,
        "load_feed_episodes",
        lambda db, s, force: _feed_ctx({"title": "A", "description": "A desc", "pub_date": 1, "guid": "g0"}),
    )
    monkeypatch.setattr(improvements_router, "get_llm_provider", lambda db: _StubProvider())

    response = asyncio.run(improvements_router.suggest_feed_episode(_FakeRequest({"episode_key": "g0"}), db))

    assert response.status_code == 200
    html = response.body.decode()
    assert "Better: A" in html
    assert "Better: A desc" in html
    assert "Regenerate" in html  # confirms it rendered the "has a suggestion" branch, not the empty state
    row = db.execute(select(FeedEpisodeSuggestion).where(FeedEpisodeSuggestion.episode_key == "g0")).scalar_one()
    assert row.suggested_title == "Better: A"


def test_suggest_route_404_for_unknown_key(db, monkeypatch):
    monkeypatch.setattr(improvements_router, "load_feed_episodes", lambda db, s, force: _feed_ctx())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(improvements_router.suggest_feed_episode(_FakeRequest({"episode_key": "missing"}), db))
    assert exc_info.value.status_code == 404


def test_suggest_route_502_on_llm_failure(db, monkeypatch):
    monkeypatch.setattr(
        improvements_router,
        "load_feed_episodes",
        lambda db, s, force: _feed_ctx({"title": "A", "description": "A desc", "pub_date": 1, "guid": "g0"}),
    )
    monkeypatch.setattr(improvements_router, "get_llm_provider", lambda db: _FailingProvider())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(improvements_router.suggest_feed_episode(_FakeRequest({"episode_key": "g0"}), db))
    assert exc_info.value.status_code == 502


def test_generate_all_creates_pending_job_and_submits_it(db, monkeypatch):
    submitted = []
    monkeypatch.setattr(improvements_router, "submit_feed_seo_bulk", lambda job_id: submitted.append(job_id))

    result = improvements_router.generate_all(db)

    from app.models import Job

    job = db.get(Job, result["job_id"])
    assert job.job_type == "feed_seo_suggestions"
    assert submitted == [job.id]


def test_suggest_deep_route_creates_episode_and_job(db, monkeypatch):
    from app.models import Episode, FeedEpisodeSuggestion, Job

    monkeypatch.setattr(
        improvements_router,
        "load_feed_episodes",
        lambda db, s, force: _feed_ctx(
            {
                "title": "A",
                "description": "A desc",
                "pub_date": 1,
                "guid": "g0",
                "enclosure_url": "https://example.com/ep.mp3",
            }
        ),
    )
    submitted = []
    monkeypatch.setattr(
        improvements_router, "submit_feed_episode_deep_suggest", lambda job_id: submitted.append(job_id)
    )

    result = asyncio.run(improvements_router.suggest_feed_episode_deep(_FakeRequest({"episode_key": "g0"}), db))

    job = db.get(Job, result["job_id"])
    assert job.job_type == "feed_episode_deep_suggest"
    assert submitted == [job.id]

    episode = db.get(Episode, job.episode_id)
    assert episode.source == "feed"
    assert episode.status == "draft"

    row = db.execute(select(FeedEpisodeSuggestion).where(FeedEpisodeSuggestion.episode_key == "g0")).scalar_one()
    assert row.episode_id == episode.id

    # a second call reuses the same episode/suggestion row rather than creating another one
    result2 = asyncio.run(improvements_router.suggest_feed_episode_deep(_FakeRequest({"episode_key": "g0"}), db))
    job2 = db.get(Job, result2["job_id"])
    assert job2.episode_id == episode.id
    assert len(db.execute(select(Episode)).scalars().all()) == 1


def test_suggest_deep_route_400_without_enclosure_url(db, monkeypatch):
    monkeypatch.setattr(
        improvements_router,
        "load_feed_episodes",
        lambda db, s, force: _feed_ctx({"title": "A", "description": "A desc", "pub_date": 1, "guid": "g0"}),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(improvements_router.suggest_feed_episode_deep(_FakeRequest({"episode_key": "g0"}), db))
    assert exc_info.value.status_code == 400


def test_suggest_deep_route_404_for_unknown_key(db, monkeypatch):
    monkeypatch.setattr(improvements_router, "load_feed_episodes", lambda db, s, force: _feed_ctx())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(improvements_router.suggest_feed_episode_deep(_FakeRequest({"episode_key": "missing"}), db))
    assert exc_info.value.status_code == 404


def test_suggest_deep_result_renders_current_suggestion(db):
    from app.models import FeedEpisodeSuggestion

    db.add(
        FeedEpisodeSuggestion(
            episode_key="g0",
            original_title="A",
            suggested_title="Better: A",
            suggested_description="Better: A desc",
            used_transcript=True,
        )
    )
    db.commit()

    response = improvements_router.suggest_deep_result(_FakeRequest({}), key="g0", db=db)
    html = response.body.decode()
    assert "Better: A" in html
    assert "Based on full transcript" in html
