import re
from pathlib import Path

from app.config import config

ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a"}


def safe_filename(filename: str) -> str:
    """Strip any directory components and non-portable characters from a client-supplied filename."""
    name = Path(filename).name  # drops any path components, defeats traversal
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name or "upload"


def episode_dir(episode_id: int) -> Path:
    d = config.uploads_dir / str(episode_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def clips_dir(episode_id: int) -> Path:
    d = episode_dir(episode_id) / "clips"
    d.mkdir(parents=True, exist_ok=True)
    return d


def images_dir(episode_id: int) -> Path:
    d = episode_dir(episode_id) / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def video_dir(episode_id: int) -> Path:
    d = episode_dir(episode_id) / "video"
    d.mkdir(parents=True, exist_ok=True)
    return d


def social_attachments_dir(episode_id: int) -> Path:
    d = episode_dir(episode_id) / "social"
    d.mkdir(parents=True, exist_ok=True)
    return d
