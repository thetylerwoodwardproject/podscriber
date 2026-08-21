"""Shared image-upload/settings-clamping/download logic for the two video editors —
the per-soundbite clip editor (`app/routers/video_clip.py`) and the full-episode video
editor (`app/routers/video_full.py`). Both operate on a record (`VideoClip` /
`EpisodeVideo`) that shares the same `background_image_path`/`logo_image_path`/
`brightness`/`waveform_offset_y`/`waveform_color`/`download_filename`/
`exported_video_path` fields; only the caption/social-copy fields and the
waveform-offset clamp range differ per record type, so those stay with each caller.
"""

from fastapi import UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from app.routers._shared import sanitize_download_filename
from app.services import storage

_ALLOWED_IMAGE_EXTENSIONS = ("png", "jpg", "jpeg", "webp")


async def save_clip_image(episode_id: int, file: UploadFile, filename_stem: str) -> tuple[str, str]:
    """Writes an uploaded background/logo image to the episode's images dir.

    Returns `(absolute_path, public_url)`.
    """
    ext = (file.filename or "image.png").rsplit(".", 1)[-1].lower()
    if ext not in _ALLOWED_IMAGE_EXTENSIONS:
        ext = "png"
    dest = storage.images_dir(episode_id) / f"{filename_stem}.{ext}"
    with open(dest, "wb") as f:
        f.write(await file.read())
    return str(dest), f"/media/uploads/{episode_id}/images/{dest.name}"


def apply_clip_settings(record, body: dict, *, waveform_offset_range: tuple[int, int]) -> None:
    """Applies the settings fields common to both editors, when present in `body`."""
    if "brightness" in body:
        record.brightness = max(0.4, min(1.6, float(body["brightness"])))
    if "waveform_offset_y" in body:
        lo, hi = waveform_offset_range
        record.waveform_offset_y = max(lo, min(hi, int(body["waveform_offset_y"])))
    if "waveform_color" in body:
        record.waveform_color = str(body["waveform_color"])[:20]
    if "download_filename" in body:
        record.download_filename = str(body["download_filename"])[:80] or None


def download_response(record, fallback_stem: str) -> FileResponse | PlainTextResponse:
    if record is None or not record.exported_video_path:
        return PlainTextResponse("No exported video yet.", status_code=404)
    filename = sanitize_download_filename(record.download_filename, fallback=fallback_stem)
    return FileResponse(record.exported_video_path, filename=filename, media_type="video/mp4")
