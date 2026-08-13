import base64
from dataclasses import dataclass

import httpx

BASE_URL = "https://op3.dev/api/1"


class Op3Error(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _show_ref(podcast_guid: str, feed_url: str) -> str:
    # OP3's /shows lookup accepts an OP3 uuid, a podcast:guid, or a feed URL as
    # urlsafe base64 — prefer the guid (shorter, no encoding) and fall back to the feed URL.
    if podcast_guid:
        return podcast_guid
    return base64.urlsafe_b64encode(feed_url.encode("utf-8")).decode("ascii")


def resolve_show_uuid(api_key: str, podcast_guid: str, feed_url: str, timeout: float = 10.0) -> str | None:
    """Look up OP3's internal show uuid for this podcast.

    Returns None if OP3 has never seen this show (HTTP 404) — the expected state
    when the show's feed hasn't been routed through an OP3 redirect prefix yet.
    Raises Op3Error for any other failure (auth, network, unexpected status).
    """
    ref = _show_ref(podcast_guid, feed_url)
    try:
        resp = httpx.get(f"{BASE_URL}/shows/{ref}", headers=_auth_headers(api_key), timeout=timeout)
    except httpx.HTTPError as exc:
        raise Op3Error(f"OP3 request failed: {exc}") from exc
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise Op3Error(f"OP3 returned HTTP {resp.status_code}", status_code=resp.status_code)
    return resp.json()["showUuid"]


def _get(api_key: str, path: str, params: dict, timeout: float) -> dict:
    try:
        resp = httpx.get(f"{BASE_URL}{path}", params=params, headers=_auth_headers(api_key), timeout=timeout)
    except httpx.HTTPError as exc:
        raise Op3Error(f"OP3 request failed: {exc}") from exc
    if resp.status_code != 200:
        raise Op3Error(f"OP3 returned HTTP {resp.status_code}", status_code=resp.status_code)
    return resp.json()


@dataclass
class ShowDownloadStats:
    as_of: str
    monthly_downloads: int
    weekly_avg_downloads: float
    weekly_downloads: list[int]
    num_weeks: int
    days: str  # 30-char string of '0'/'1', whether the show had >=1 download each of the last 30 days


def get_show_download_counts(api_key: str, show_uuid: str, timeout: float = 10.0) -> ShowDownloadStats:
    data = _get(api_key, "/queries/show-download-counts", {"showUuid": show_uuid}, timeout)
    counts = data["showDownloadCounts"][show_uuid]
    return ShowDownloadStats(
        as_of=data["asof"],
        monthly_downloads=counts["monthlyDownloads"],
        weekly_avg_downloads=counts["weeklyAvgDownloads"],
        weekly_downloads=counts["weeklyDownloads"],
        num_weeks=counts["numWeeks"],
        days=counts["days"],
    )


@dataclass
class EpisodeDownloadCounts:
    item_guid: str
    title: str
    pub_date: str
    downloads_1: int
    downloads_7: int
    downloads_30: int
    downloads_all: int


def get_episode_download_counts(api_key: str, show_uuid: str, timeout: float = 10.0) -> list[EpisodeDownloadCounts]:
    data = _get(api_key, "/queries/episode-download-counts", {"showUuid": show_uuid}, timeout)
    return [
        EpisodeDownloadCounts(
            item_guid=ep["itemGuid"],
            title=ep["title"],
            pub_date=ep["pubdate"],
            downloads_1=ep.get("downloads1", 0),
            downloads_7=ep.get("downloads7", 0),
            downloads_30=ep.get("downloads30", 0),
            downloads_all=ep["downloadsAll"],
        )
        for ep in data["episodes"]
    ]


def op3_prefix_example(podcast_guid: str) -> str:
    if podcast_guid:
        return f"https://op3.dev/e,pg={podcast_guid}/"
    return "https://op3.dev/e/"
