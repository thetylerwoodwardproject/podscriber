from app.routers import analytics as stats_router
from app.services import op3, podcast_index, settings_store


def test_both_sections_not_configured_by_default(db):
    ctx = stats_router._load_stats_context(db)
    assert ctx["pi"] == {"state": "not_configured"}
    assert ctx["op3"] == {"state": "not_configured"}


def test_podcast_index_not_configured_without_feed_url(db):
    settings_store.set_many(db, {"podcast_index_api_key": "k", "podcast_index_api_secret": "s"})
    ctx = stats_router._load_stats_context(db)
    assert ctx["pi"] == {"state": "not_configured"}


def test_podcast_index_ok_fetches_and_caches(db, monkeypatch):
    settings_store.set_many(
        db,
        {
            "podcast_index_api_key": "k",
            "podcast_index_api_secret": "s",
            "podcast_feed_url": "https://feeds.example.com/show.xml",
        },
    )
    info = podcast_index.PodcastFeedInfo(
        feed_id=123,
        guid="show-guid",
        title="My Show",
        author="Jane",
        description="desc",
        artwork_url="art.jpg",
        link="https://example.com",
        episode_count=10,
        categories=["Tech"],
        value_enabled=False,
        last_update_time=0,
    )
    calls = []
    monkeypatch.setattr(
        podcast_index, "lookup_feed_by_url", lambda *a, **k: calls.append(1) or info
    )
    ctx = stats_router._load_stats_context(db)
    assert ctx["pi"]["state"] == "ok"
    assert ctx["pi"]["feed"]["title"] == "My Show"
    assert len(calls) == 1
    assert settings_store.get(db, "podcast_index_feed_id") == "123"
    assert settings_store.get(db, "podcast_guid") == "show-guid"

    # Second load within TTL should hit the cache, not the network.
    ctx2 = stats_router._load_stats_context(db)
    assert ctx2["pi"]["state"] == "ok"
    assert len(calls) == 1


def test_podcast_index_feed_not_found(db, monkeypatch):
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
    ctx = stats_router._load_stats_context(db)
    assert ctx["pi"] == {"state": "feed_not_found"}


def test_podcast_index_error_with_no_cache(db, monkeypatch):
    settings_store.set_many(
        db,
        {
            "podcast_index_api_key": "k",
            "podcast_index_api_secret": "s",
            "podcast_feed_url": "https://feeds.example.com/show.xml",
        },
    )

    def _raise(*a, **k):
        raise podcast_index.PodcastIndexError("boom")

    monkeypatch.setattr(podcast_index, "lookup_feed_by_url", _raise)
    ctx = stats_router._load_stats_context(db)
    assert ctx["pi"] == {"state": "error"}


def test_pi_episodes_not_configured_without_feed_id(db):
    settings_store.set_many(db, {"podcast_index_api_key": "k", "podcast_index_api_secret": "s"})
    ctx = stats_router._load_stats_context(db)
    assert ctx["pi_episodes"] == {"state": "not_configured"}


def test_pi_episodes_ok_fetches_and_caches(db, monkeypatch):
    settings_store.set_many(
        db,
        {"podcast_index_api_key": "k", "podcast_index_api_secret": "s", "podcast_index_feed_id": "123"},
    )
    episodes = [
        podcast_index.PodcastIndexEpisode(
            title="Ep 1", pub_date=1700000000, duration_seconds=1800, guid="g1", description="d1"
        )
    ]
    calls = []
    monkeypatch.setattr(
        podcast_index, "list_episodes_by_feed_id", lambda *a, **k: calls.append(1) or episodes
    )
    ctx = stats_router._load_stats_context(db)
    assert ctx["pi_episodes"]["state"] == "ok"
    assert ctx["pi_episodes"]["episodes"][0]["title"] == "Ep 1"
    assert len(calls) == 1

    ctx2 = stats_router._load_stats_context(db)
    assert ctx2["pi_episodes"]["state"] == "ok"
    assert len(calls) == 1


def test_op3_not_configured_without_key(db):
    settings_store.set_many(db, {"podcast_feed_url": "https://feeds.example.com/show.xml"})
    ctx = stats_router._load_stats_context(db)
    assert ctx["op3"] == {"state": "not_configured"}


def test_op3_not_enabled_when_show_unknown(db, monkeypatch):
    settings_store.set_many(
        db, {"op3_api_key": "tok", "podcast_feed_url": "https://unregistered.example.com/feed.xml"}
    )
    monkeypatch.setattr(op3, "resolve_show_uuid", lambda *a, **k: None)
    ctx = stats_router._load_stats_context(db)
    assert ctx["op3"]["state"] == "not_enabled"
    assert "https://op3.dev/e/" in ctx["op3"]["prefix_example"]


def test_op3_ok_resolves_and_caches(db, monkeypatch):
    settings_store.set_many(
        db, {"op3_api_key": "tok", "podcast_guid": "show-guid", "podcast_feed_url": "https://feeds.example.com/x.xml"}
    )
    resolve_calls = []
    monkeypatch.setattr(
        op3, "resolve_show_uuid", lambda *a, **k: resolve_calls.append(1) or "uuid-123"
    )
    monkeypatch.setattr(
        op3,
        "get_show_download_counts",
        lambda *a, **k: op3.ShowDownloadStats(
            as_of="2026-08-11", monthly_downloads=100, weekly_avg_downloads=25.0,
            weekly_downloads=[20, 25, 30, 25], num_weeks=4, days="1" * 30,
        ),
    )
    monkeypatch.setattr(op3, "get_episode_download_counts", lambda *a, **k: [])
    ctx = stats_router._load_stats_context(db)
    assert ctx["op3"]["state"] == "ok"
    assert ctx["op3"]["downloads"]["monthly_downloads"] == 100
    assert settings_store.get(db, "op3_show_uuid") == "uuid-123"
    assert len(resolve_calls) == 1

    # Second load should reuse the persisted show_uuid, not re-resolve it.
    stats_router._load_stats_context(db)
    assert len(resolve_calls) == 1
