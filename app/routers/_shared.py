import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Episode

_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_download_filename(name: str | None, fallback: str) -> str:
    """Turns user-entered text into a safe `<name>.mp4` download filename.

    Strips path separators and other characters that would confuse a Content-Disposition
    header or a filesystem, and falls back to `fallback` if nothing usable is left.
    """
    name = _UNSAFE_FILENAME_CHARS.sub("", (name or "").strip())
    name = re.sub(r"\s+", " ", name).strip(" .")
    if name.lower().endswith(".mp4"):
        name = name[:-4].strip(" .")
    name = name[:80].strip(" .")
    return f"{name}.mp4" if name else f"{fallback}.mp4"


def recent_episodes(db: Session, limit: int = 6) -> list[Episode]:
    return list(
        db.execute(
            select(Episode).where(Episode.source == "upload").order_by(Episode.created_at.desc()).limit(limit)
        ).scalars()
    )


def status_label(status: str) -> str:
    return {"processed": "Processed", "processing": "Processing", "draft": "Draft", "error": "Error"}.get(
        status, status.title()
    )


def format_duration(seconds: float | None) -> str:
    if not seconds:
        return "—"
    minutes = round(seconds / 60)
    return f"{minutes} min"


def ms_to_clock(ms: int) -> str:
    total_seconds = ms // 1000
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
