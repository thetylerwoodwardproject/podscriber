"""Shared per-platform Postiz publish step, used by both the per-clip publish flow
(`clip_social_publish.py`) and the episode-level Social Posts tab publish flow
(`episode_social_publish.py`). Exactly one of `video_clip_id`/`episode_id` should be
passed by callers — it records which entity a `SocialPublish` row belongs to.
"""

from datetime import datetime

from app.models import Job, SocialPublish
from app.services.postiz import Integration, PostizError, create_post, list_integrations

# Postiz's public API rejects a TikTok post outright without these — content_posting_method
# must be DIRECT_POST or the post lands as an unpublished inbox draft instead of publishing.
# TikTok's disclosure rules require both toggles: brand_organic_toggle (promoting your own
# business) and brand_content_toggle (paid third-party partnership) are each independently
# validated as required booleans, not either/or.
TIKTOK_DEFAULT_SETTINGS = {
    "content_posting_method": "DIRECT_POST",
    "privacy_level": "PUBLIC_TO_EVERYONE",
    "duet": True,
    "stitch": True,
    "comment": True,
    "autoAddMusic": "no",  # Postiz wants the literal string "yes"/"no", not a bool
    "brand_organic_toggle": False,
    "brand_content_toggle": False,
}

# Hard per-post character caps Postiz enforces on Podscriber's behalf; platforms not listed
# here have no known cap tight enough to matter for a short clip caption.
PLATFORM_CONTENT_LIMITS = {"x": 280, "bluesky": 300}


def default_settings_for_platform(
    platform: str, *, youtube_title: str = "", instagram_post_type: str = "post"
) -> dict:
    """Extra Postiz `settings` fields beyond the `__type` discriminator `create_post`
    always sets. TikTok, YouTube, and X reject posts outright without these; platforms with
    no known extra requirements (bluesky, threads, facebook) get `{}`."""
    if platform == "tiktok":
        return dict(TIKTOK_DEFAULT_SETTINGS)
    if platform == "youtube":
        return {"title": youtube_title or "Untitled", "type": "public"}
    if platform == "instagram":
        # Postiz's Instagram DTO only accepts "post" or "story" — "reel" (what we originally
        # guessed a 9:16 clip should map to) is rejected outright, so vertical clips are just
        # published as a regular feed post; Instagram's feed already supports 9:16 video.
        return {"post_type": instagram_post_type if instagram_post_type in ("post", "story") else "post"}
    if platform == "x":
        return {"who_can_reply_post": "everyone"}
    return {}


def truncate_content_for_platform(content: str, platform: str) -> str:
    """Safety net for `clip_social_prompt` (see `app.services.llm.prompts`), which targets
    only YouTube/TikTok and has no length ceiling — that same text gets reused for every
    selected platform, so X/Bluesky's hard caps need enforcing here. Drops trailing hashtag
    tokens first (losing reach, not the hook), then hard-truncates at a word boundary with
    an ellipsis. Never mutates the caller's stored content — only the outgoing payload."""
    limit = PLATFORM_CONTENT_LIMITS.get(platform)
    if limit is None or len(content) <= limit:
        return content
    tokens = content.split(" ")
    while tokens and len(" ".join(tokens)) > limit and tokens[-1].startswith("#"):
        tokens.pop()
    trimmed = " ".join(tokens)
    if len(trimmed) <= limit:
        return trimmed
    ellipsis = "…"
    truncated = trimmed[: limit - len(ellipsis)]
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated.rstrip() + ellipsis


def resolve_integrations(base_url: str, api_key: str) -> dict[str, Integration]:
    """Postiz exposes Instagram's two connection modes as distinct integration identifiers
    (`"instagram"` via a linked Facebook Page, `"instagram-standalone"` via direct Instagram
    OAuth) even though Podscriber only ever offers a single "Instagram" checkbox/platform key.
    Alias whichever variant is actually connected under `"instagram"` so the lookup in
    `publish_one_platform` succeeds regardless of which one the user connected."""
    integrations = {i.platform: i for i in list_integrations(base_url, api_key)}
    if "instagram" not in integrations and "instagram-standalone" in integrations:
        integrations["instagram"] = integrations["instagram-standalone"]
    return integrations


def record_publish_error(
    db, *, job: Job, platform: str, message: str, video_clip_id: int | None = None, episode_id: int | None = None
) -> None:
    db.add(
        SocialPublish(
            job_id=job.id,
            video_clip_id=video_clip_id,
            episode_id=episode_id,
            platform=platform,
            status="error",
            error_message=message,
        )
    )


def publish_one_platform(
    db,
    *,
    job: Job,
    base_url: str,
    api_key: str,
    integrations: dict[str, Integration],
    platform: str,
    content: str,
    media: list[dict] | None,
    post_type: str,
    date: str,
    settings: dict | None = None,
    video_clip_id: int | None = None,
    episode_id: int | None = None,
) -> bool:
    """Resolves `platform`'s Postiz integration, creates the post, and records a
    `SocialPublish` row (success or failure). Returns True on success. `settings` is a
    prebuilt per-platform dict (see `default_settings_for_platform`) — building it is the
    caller's job since each flow sources its title/post-type differently."""
    integration = integrations.get(platform)
    if integration is None:
        record_publish_error(
            db,
            job=job,
            platform=platform,
            message="No connected Postiz integration for this platform.",
            video_clip_id=video_clip_id,
            episode_id=episode_id,
        )
        return False
    try:
        result = create_post(
            base_url,
            api_key,
            integration_id=integration.id,
            # The integration's own identifier (e.g. "instagram-standalone"), not the
            # logical `platform` key Podscriber's UI/business rules use — Postiz's
            # settings.__type discriminator needs to match the specific connected variant.
            platform=integration.platform,
            content=truncate_content_for_platform(content, platform),
            media=media,
            post_type=post_type,
            date=date,
            settings=settings,
        )
    except PostizError as exc:
        record_publish_error(
            db, job=job, platform=platform, message=str(exc), video_clip_id=video_clip_id, episode_id=episode_id
        )
        return False

    # Postiz's real response to POST /public/v1/posts is a top-level array of
    # {"postId", "integration"} objects, not {"posts": [...], "id": ...} — tolerate both shapes.
    posts = result if isinstance(result, list) else (result.get("posts") or [])
    first = posts[0] if posts else {}
    post_id = str(first.get("postId") or first.get("id") or "")
    db.add(
        SocialPublish(
            job_id=job.id,
            video_clip_id=video_clip_id,
            episode_id=episode_id,
            platform=platform,
            postiz_post_id=post_id or None,
            scheduled_at=datetime.fromisoformat(date.replace("Z", "+00:00")),
            status="done",
        )
    )
    return True
