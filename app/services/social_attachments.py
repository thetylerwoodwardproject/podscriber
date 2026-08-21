"""Resolves and validates the video/image a social post can be attached to.

Used by both publish flows (`episode_social_publish.py`, `clip_social_publish.py`) and
their routers. A "source" is a small dict describing where to find a file — either an
already-exported episode/clip video, or a previously-uploaded `SocialAttachment` — and is
always re-resolved against the database rather than trusted as a client-supplied path, so
a stale or forged ID can't be used to read an arbitrary file or reach across episodes.
"""

import mimetypes
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.models import Episode, SocialAttachment, VideoClip

INSTAGRAM_MIN_ASPECT_RATIO = 0.8  # 4:5 portrait — Instagram's tightest accepted feed ratio
INSTAGRAM_MAX_ASPECT_RATIO = 1.91  # 1.91:1 landscape — Instagram's widest accepted feed ratio

ALLOWED_ATTACHMENT_VIDEO_EXTENSIONS = ("mp4", "mov", "m4v", "webm")
ALLOWED_ATTACHMENT_IMAGE_EXTENSIONS = ("png", "jpg", "jpeg", "webp")


def decode_image_dimensions(file_path: str) -> tuple[int, int]:
    """Raises ValueError with a user-facing message if the file isn't a decodable image."""
    try:
        with Image.open(file_path) as img:
            img.verify()
        with Image.open(file_path) as img:  # re-open: verify() leaves the handle unusable
            return img.width, img.height
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("That doesn't look like a valid image file.") from exc


def instagram_image_ok(width: int | None, height: int | None) -> bool:
    if not width or not height:
        return False
    ratio = width / height
    return INSTAGRAM_MIN_ASPECT_RATIO <= ratio <= INSTAGRAM_MAX_ASPECT_RATIO


def guess_content_type(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _video_url(episode_id: int, exported_video_path: str) -> str:
    return f"/media/uploads/{episode_id}/video/{Path(exported_video_path).name}"


def episode_video_options(episode: Episode) -> list[dict]:
    """[{value, label, url}] for every already-exported video available to attach to a post
    for this episode — the full-episode 16:9 export plus each soundbite's exported 9:16 clip.
    `url` lets the picker show a preview without a server round trip."""
    options = []
    if episode.video and episode.video.exported_video_path:
        options.append(
            {
                "value": "episode_video",
                "label": "Full episode video (16:9)",
                "url": _video_url(episode.id, episode.video.exported_video_path),
            }
        )
    for sb in episode.soundbites:
        exported_clips = [c for c in sb.video_clips if c.exported_video_path]
        label = sb.quote if len(sb.quote) <= 40 else sb.quote[:40] + "…"
        for i, clip in enumerate(exported_clips, start=1):
            # Only number variants when a soundbite has more than one exported clip — most
            # soundbites have exactly one, and "(v1)" on every option would be noise.
            suffix = f" (v{i})" if len(exported_clips) > 1 else ""
            options.append(
                {
                    "value": f"clip:{clip.id}",
                    "label": f'Clip: "{label}"{suffix}',
                    "url": _video_url(episode.id, clip.exported_video_path),
                }
            )
    return options


def resolve_video_source(db, episode: Episode, source: dict | None) -> tuple[str | None, str | None]:
    """Returns (file_path, error). Never trusts a client-supplied path — resolves the
    source id/type against the DB every time this is called."""
    if not source:
        return None, None
    kind = source.get("type")
    if kind == "episode_video":
        if episode.video and episode.video.exported_video_path:
            return episode.video.exported_video_path, None
        return None, "This episode has no exported full video."
    if kind == "clip":
        clip = db.get(VideoClip, source.get("clip_id"))
        if clip is not None and clip.soundbite.episode_id != episode.id:
            clip = None
        if clip is None or not clip.exported_video_path:
            return None, "That clip has no exported video."
        return clip.exported_video_path, None
    if kind == "upload":
        attachment = db.get(SocialAttachment, source.get("attachment_id"))
        if attachment is None or attachment.episode_id != episode.id or attachment.kind != "video":
            return None, "Uploaded video not found — try uploading it again."
        return attachment.file_path, None
    return None, "Unrecognized video source."


def resolve_image_attachment(
    db, episode: Episode, source: dict | None
) -> tuple[SocialAttachment | None, str | None]:
    if not source:
        return None, None
    if source.get("type") != "upload":
        return None, "Unrecognized image source."
    attachment = db.get(SocialAttachment, source.get("attachment_id"))
    if attachment is None or attachment.episode_id != episode.id or attachment.kind != "image":
        return None, "Uploaded image not found — try uploading it again."
    return attachment, None


def validate_instagram_requirement(
    platforms: list[str], attachment: SocialAttachment | None, *, has_video: bool = False
) -> str | None:
    """None if OK, else a user-facing error. Instagram accepts either a video-only post
    (Reels/feed both support video) or an image whose aspect ratio falls in Instagram's
    accepted feed range. An attached image is still validated for aspect ratio even when a
    video is also present."""
    if "instagram" not in platforms:
        return None
    if attachment is None:
        if has_video:
            return None
        return (
            "Instagram requires a video or an image attached to the post — "
            "pick or upload one, or deselect Instagram."
        )
    if not instagram_image_ok(attachment.width, attachment.height):
        dims = f"{attachment.width}×{attachment.height}" if attachment.width and attachment.height else "unreadable"
        return (
            f"This image ({dims}) doesn't fit Instagram's accepted aspect-ratio range "
            "(between 4:5 portrait and 1.91:1 landscape). Pick a different image or crop this one, "
            "then try again."
        )
    return None
