import hashlib
import html
import re
import time
from dataclasses import dataclass

import httpx

BASE_URL = "https://api.podcastindex.org/api/1.0"
USER_AGENT = "Podscriber/1.0"

_BR_RE = re.compile(r"(?i)<br\s*/?>")
_BLOCK_RE = re.compile(r"(?i)</?(?:p|div|li|h[1-6]|ul|ol)\b[^>]*>")
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    # Episode descriptions often come back as the show notes' original HTML (PodcastIndex's
    # "contentHtml" field is even named for it) — this app only ever displays/prompts with
    # plain text, but line breaks are meaningful (paragraphs, list items), so <br> and block
    # boundaries are turned into real newlines before the remaining (inline) tags are dropped.
    text = _BR_RE.sub("\n", text)
    text = _BLOCK_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return text.strip()


class PodcastIndexError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class PodcastIndexNotFoundError(PodcastIndexError):
    pass


def _auth_headers(api_key: str, api_secret: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    auth_hash = hashlib.sha1((api_key + api_secret + timestamp).encode("utf-8")).hexdigest()
    return {
        "User-Agent": USER_AGENT,
        "X-Auth-Date": timestamp,
        "X-Auth-Key": api_key,
        "Authorization": auth_hash,
    }


def _get(api_key: str, api_secret: str, path: str, params: dict, timeout: float) -> dict:
    try:
        resp = httpx.get(
            f"{BASE_URL}{path}", params=params, headers=_auth_headers(api_key, api_secret), timeout=timeout
        )
    except httpx.HTTPError as exc:
        raise PodcastIndexError(f"PodcastIndex request failed: {exc}") from exc
    if resp.status_code != 200:
        raise PodcastIndexError(f"PodcastIndex returned HTTP {resp.status_code}", status_code=resp.status_code)
    return resp.json()


@dataclass
class PodcastFeedInfo:
    feed_id: int
    guid: str
    title: str
    author: str
    description: str
    artwork_url: str
    link: str
    episode_count: int
    categories: list[str]
    value_enabled: bool
    last_update_time: int


def lookup_feed_by_url(api_key: str, api_secret: str, feed_url: str, timeout: float = 10.0) -> PodcastFeedInfo:
    data = _get(api_key, api_secret, "/podcasts/byfeedurl", {"url": feed_url}, timeout)
    feed = data.get("feed") or {}
    # PodcastIndex returns HTTP 200 for an unrecognized feed URL too — the only signal
    # that nothing was found is feed.id being 0 (or the feed key being absent).
    if not feed or not feed.get("id"):
        raise PodcastIndexNotFoundError(f"No PodcastIndex feed found for URL: {feed_url}")
    categories = feed.get("categories") or {}
    value = feed.get("value") or {}
    return PodcastFeedInfo(
        feed_id=feed["id"],
        guid=feed.get("podcastGuid", ""),
        title=feed.get("title", ""),
        author=feed.get("author", ""),
        description=feed.get("description", ""),
        artwork_url=feed.get("image") or feed.get("artwork") or "",
        link=feed.get("link", ""),
        episode_count=feed.get("episodeCount", 0),
        categories=list(categories.values()),
        value_enabled=bool(value.get("destinations")),
        last_update_time=feed.get("lastUpdateTime", 0),
    )


@dataclass
class PodcastIndexEpisode:
    title: str
    pub_date: int
    duration_seconds: int | None
    guid: str
    description: str
    enclosure_url: str | None = None


def list_episodes_by_feed_id(
    api_key: str, api_secret: str, feed_id: int, max_results: int = 20, timeout: float = 10.0
) -> list[PodcastIndexEpisode]:
    data = _get(api_key, api_secret, "/episodes/byfeedid", {"id": feed_id, "max": max_results}, timeout)
    items = data.get("items") or []
    return [
        PodcastIndexEpisode(
            title=item.get("title", ""),
            pub_date=item.get("datePublished", 0),
            duration_seconds=item.get("duration"),
            guid=item.get("guid", ""),
            # PodcastIndex is inconsistent about which key carries the episode description.
            description=_strip_html(item.get("description") or item.get("contentHtml") or ""),
            enclosure_url=item.get("enclosureUrl") or None,
        )
        for item in items
    ]
