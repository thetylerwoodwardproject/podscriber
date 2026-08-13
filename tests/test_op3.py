import base64

import httpx
import pytest

from app.services import op3


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_auth_headers():
    assert op3._auth_headers("tok123") == {"Authorization": "Bearer tok123"}


def test_show_ref_prefers_guid():
    assert op3._show_ref("some-guid", "https://feeds.example.com/show.xml") == "some-guid"


def test_show_ref_falls_back_to_base64_feed_url():
    ref = op3._show_ref("", "https://feeds.example.com/show.xml")
    expected = base64.urlsafe_b64encode(b"https://feeds.example.com/show.xml").decode("ascii")
    assert ref == expected


def test_resolve_show_uuid_found(monkeypatch):
    payload = {
        "showUuid": "a18389b8a52d4112a782b32f40f73df6",
        "title": "My Show",
        "podcastGuid": "3b69fa45-1f57-5aaf-a7fd-d80ee934e01c",
        "statsPageUrl": "https://op3.dev/show/a18389b8a52d4112a782b32f40f73df6",
    }
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(200, payload))
    show_uuid = op3.resolve_show_uuid("tok", "3b69fa45-1f57-5aaf-a7fd-d80ee934e01c", "")
    assert show_uuid == "a18389b8a52d4112a782b32f40f73df6"


def test_resolve_show_uuid_not_found_returns_none(monkeypatch):
    # OP3 returns HTTP 404 with {"message": "not found"} for a show it has never seen,
    # which is exactly the "feed not routed through OP3 yet" state.
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(404, {"message": "not found"}))
    assert op3.resolve_show_uuid("tok", "", "https://unregistered.example.com/feed.xml") is None


def test_resolve_show_uuid_other_error_raises(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(401, {"message": "unauthorized"}))
    with pytest.raises(op3.Op3Error):
        op3.resolve_show_uuid("bad-token", "", "https://feeds.example.com/show.xml")


def test_get_show_download_counts(monkeypatch):
    payload = {
        "asof": "2026-08-11",
        "showDownloadCounts": {
            "a18389b8a52d4112a782b32f40f73df6": {
                "days": "1" * 30,
                "monthlyDownloads": 37970,
                "weeklyDownloads": [7484, 16270, 8145, 4463],
                "weeklyAvgDownloads": 9091,
                "numWeeks": 4,
            }
        },
        "queryTime": 109,
    }
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(200, payload))
    stats = op3.get_show_download_counts("tok", "a18389b8a52d4112a782b32f40f73df6")
    assert stats.monthly_downloads == 37970
    assert stats.weekly_downloads == [7484, 16270, 8145, 4463]
    assert stats.num_weeks == 4
    assert stats.as_of == "2026-08-11"


def test_get_episode_download_counts(monkeypatch):
    payload = {
        "showUuid": "a18389b8a52d4112a782b32f40f73df6",
        "showTitle": "My Show",
        "minDownloadHour": "2026-07-01T00",
        "maxDownloadHour": "2026-08-11T00",
        "episodes": [
            {
                "itemGuid": "ep-1",
                "title": "Episode 1",
                "pubdate": "2026-08-01T00:00:00Z",
                "downloads1": 100,
                "downloads7": 500,
                "downloads30": 900,
                "downloadsAll": 950,
            }
        ],
        "queryTime": 50,
    }
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(200, payload))
    episodes = op3.get_episode_download_counts("tok", "a18389b8a52d4112a782b32f40f73df6")
    assert len(episodes) == 1
    assert episodes[0].title == "Episode 1"
    assert episodes[0].downloads_all == 950


def test_op3_prefix_example_with_guid():
    assert op3.op3_prefix_example("abc-guid") == "https://op3.dev/e,pg=abc-guid/"


def test_op3_prefix_example_without_guid():
    assert op3.op3_prefix_example("") == "https://op3.dev/e/"
