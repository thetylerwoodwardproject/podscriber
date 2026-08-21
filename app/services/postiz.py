"""Thin client for Postiz's public API (docs.postiz.com/public-api) — used to publish an
exported video clip straight from Podscriber. Auth is a raw `Authorization: <api_key>`
header (not "Bearer ..."). `create_post`'s `settings` kwarg is merged under `__type` as
given by the caller — Podscriber's own per-platform defaults (TikTok's required posting
fields, YouTube's title, Instagram's post_type, ...) live in `app.services.social_publish`,
not here; this module stays a mechanical payload/HTTP layer.
"""

import mimetypes
from dataclasses import dataclass
from pathlib import Path

import httpx

DEFAULT_TIMEOUT = 30.0
UPLOAD_TIMEOUT = 120.0  # video files are large; uploads take longer than a typical API call

PLATFORMS = ["tiktok", "youtube", "x", "instagram", "bluesky", "threads", "facebook"]


class PostizError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _headers(api_key: str, *, json_body: bool = False) -> dict[str, str]:
    headers = {"Authorization": api_key}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


@dataclass
class Integration:
    id: str
    platform: str
    name: str


def _check_status(resp: httpx.Response, ok_codes: tuple[int, ...]) -> None:
    if resp.status_code in ok_codes:
        return
    if 300 <= resp.status_code < 400:
        location = resp.headers.get("location", "")
        raise PostizError(
            "Postiz redirected this request (HTTP "
            f"{resp.status_code}{f' to {location}' if location else ''}) instead of answering it. "
            "This usually means the base URL points at the Postiz web app rather than its API — "
            "for self-hosted Postiz, use the backend URL (often the same domain with /api appended, "
            "e.g. https://postiz.example.com/api), not the frontend URL.",
            status_code=resp.status_code,
        )
    raise PostizError(f"Postiz returned HTTP {resp.status_code}: {resp.text[:300]}", status_code=resp.status_code)


def list_integrations(base_url: str, api_key: str, timeout: float = DEFAULT_TIMEOUT) -> list[Integration]:
    try:
        resp = httpx.get(f"{base_url}/public/v1/integrations", headers=_headers(api_key), timeout=timeout)
    except httpx.HTTPError as exc:
        raise PostizError(f"Postiz request failed: {exc}") from exc
    _check_status(resp, (200,))
    data = resp.json()
    rows = data if isinstance(data, list) else data.get("integrations", [])
    return [
        Integration(
            id=str(row["id"]),
            platform=row.get("identifier") or row.get("platform") or row.get("provider") or "",
            name=row.get("name", ""),
        )
        for row in rows
    ]


def upload_media(
    base_url: str, api_key: str, file_path: str, *, content_type: str | None = None, timeout: float = UPLOAD_TIMEOUT
) -> dict:
    """Uploads a local file to Postiz's media library. Returns the raw `{"id", "path", ...}`
    response, which gets passed straight through to `create_post`'s `media` argument.
    `content_type` should be given explicitly when the caller knows it (e.g. from a
    `SocialAttachment` row); otherwise it's guessed from the file extension."""
    path = Path(file_path)
    guessed_type = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        with open(path, "rb") as f:
            resp = httpx.post(
                f"{base_url}/public/v1/upload",
                headers=_headers(api_key),
                files={"file": (path.name, f, guessed_type)},
                timeout=timeout,
            )
    except httpx.HTTPError as exc:
        raise PostizError(f"Postiz upload failed: {exc}") from exc
    _check_status(resp, (200, 201))
    return resp.json()


def create_post(
    base_url: str,
    api_key: str,
    *,
    integration_id: str,
    platform: str,
    content: str,
    media: list[dict] | None,
    post_type: str,
    date: str,
    settings: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> list | dict:
    """Creates or schedules a single-platform post. `post_type` is one of Postiz's
    `now`/`schedule`/`draft`; `date` is an ISO-8601 UTC timestamp (required even for `now`).
    `media`, if given, is a list of dicts as returned by `upload_media` — e.g. a video and
    an image attached together. `settings`, if given, is merged into the post's `settings`
    object alongside the `__type` discriminator (see `app.services.social_publish` for
    Podscriber's per-platform defaults — several platforms reject the post outright without
    them). Returns the raw parsed JSON — normally a list of `{"postId", "integration"}`
    objects, per Postiz's public API docs.
    """
    payload = {
        "type": post_type,
        "date": date,
        "shortLink": False,
        "tags": [],
        "posts": [
            {
                "integration": {"id": integration_id},
                "value": [{"content": content, "image": media or []}],
                "settings": {"__type": platform, **(settings or {})},
            }
        ],
    }
    try:
        resp = httpx.post(
            f"{base_url}/public/v1/posts", headers=_headers(api_key, json_body=True), json=payload, timeout=timeout
        )
    except httpx.HTTPError as exc:
        raise PostizError(f"Postiz post failed: {exc}") from exc
    _check_status(resp, (200, 201))
    return resp.json()
