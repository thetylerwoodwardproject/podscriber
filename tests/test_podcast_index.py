import httpx
import pytest

from app.services import podcast_index


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_strip_html_removes_tags_and_decodes_entities():
    assert podcast_index._strip_html("<p>Hi &amp; welcome</p>") == "Hi & welcome"


def test_strip_html_collapses_horizontal_whitespace_but_keeps_linebreaks():
    assert podcast_index._strip_html("a\n\n<br>  b   c") == "a\n\nb c"


def test_strip_html_plain_text_unchanged():
    assert podcast_index._strip_html("Just plain text.") == "Just plain text."


def test_strip_html_br_becomes_single_newline():
    assert podcast_index._strip_html("line one<br>line two") == "line one\nline two"


def test_strip_html_paragraphs_become_blank_line_separated():
    assert podcast_index._strip_html("<p>First</p><p>Second</p>") == "First\n\nSecond"


def test_strip_html_collapses_excess_blank_lines():
    assert podcast_index._strip_html("<p>First</p><br><br><br><p>Second</p>") == "First\n\nSecond"


def test_auth_headers_shape():
    headers = podcast_index._auth_headers("key123", "secret456")
    assert headers["X-Auth-Key"] == "key123"
    assert headers["User-Agent"]
    assert headers["X-Auth-Date"].isdigit()
    assert len(headers["Authorization"]) == 40  # sha1 hex digest length


def test_lookup_feed_by_url_success(monkeypatch):
    payload = {
        "status": "true",
        "feed": {
            "id": 12345,
            "podcastGuid": "abc-guid",
            "title": "My Show",
            "author": "Jane Doe",
            "description": "A great show",
            "image": "https://example.com/art.jpg",
            "link": "https://example.com",
            "episodeCount": 42,
            "categories": {"104": "Technology", "102": "News"},
            "value": {"destinations": [{"address": "abc"}]},
            "lastUpdateTime": 1700000000,
        },
    }
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(200, payload))
    info = podcast_index.lookup_feed_by_url("key", "secret", "https://feeds.example.com/show.xml")
    assert info.feed_id == 12345
    assert info.guid == "abc-guid"
    assert info.title == "My Show"
    assert info.episode_count == 42
    assert set(info.categories) == {"Technology", "News"}
    assert info.value_enabled is True


def test_lookup_feed_by_url_not_found_raises(monkeypatch):
    # PodcastIndex returns HTTP 200 with feed.id == 0 for an unrecognized feed URL.
    payload = {"status": "true", "feed": {"id": 0}}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(200, payload))
    with pytest.raises(podcast_index.PodcastIndexNotFoundError):
        podcast_index.lookup_feed_by_url("key", "secret", "https://unknown.example.com/feed.xml")


def test_lookup_feed_by_url_http_error_raises(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(500, {}))
    with pytest.raises(podcast_index.PodcastIndexError):
        podcast_index.lookup_feed_by_url("key", "secret", "https://feeds.example.com/show.xml")


def test_lookup_feed_by_url_network_error_raises(monkeypatch):
    def _raise(*a, **k):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "get", _raise)
    with pytest.raises(podcast_index.PodcastIndexError):
        podcast_index.lookup_feed_by_url("key", "secret", "https://feeds.example.com/show.xml")


def test_list_episodes_by_feed_id(monkeypatch):
    payload = {
        "status": "true",
        "items": [
            {
                "title": "Ep 1",
                "datePublished": 1700000000,
                "duration": 1800,
                "guid": "guid-1",
                "description": "Show notes for ep 1",
            },
            {"title": "Ep 2", "datePublished": 1700100000, "duration": None, "guid": "guid-2"},
        ],
    }
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(200, payload))
    episodes = podcast_index.list_episodes_by_feed_id("key", "secret", 12345)
    assert len(episodes) == 2
    assert episodes[0].title == "Ep 1"
    assert episodes[0].duration_seconds == 1800
    assert episodes[0].description == "Show notes for ep 1"
    assert episodes[1].duration_seconds is None
    assert episodes[1].description == ""


def test_list_episodes_by_feed_id_falls_back_to_content_html(monkeypatch):
    payload = {
        "status": "true",
        "items": [
            {"title": "Ep 1", "datePublished": 1700000000, "duration": 1800, "guid": "guid-1", "contentHtml": "<p>Notes</p>"},
        ],
    }
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(200, payload))
    episodes = podcast_index.list_episodes_by_feed_id("key", "secret", 12345)
    assert episodes[0].description == "Notes"


def test_list_episodes_by_feed_id_strips_tags_and_decodes_entities(monkeypatch):
    payload = {
        "status": "true",
        "items": [
            {
                "title": "Ep 1",
                "datePublished": 1700000000,
                "duration": 1800,
                "guid": "guid-1",
                "description": "<p>Hi &amp; welcome</p>\n<br><a href='x'>link</a>   text",
            },
        ],
    }
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(200, payload))
    episodes = podcast_index.list_episodes_by_feed_id("key", "secret", 12345)
    assert episodes[0].description == "Hi & welcome\n\nlink text"
