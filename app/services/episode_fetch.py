"""Downloads back-catalog episode audio (from an RSS enclosure URL) to disk.

Mirrors the size-cap/streaming discipline of the multipart upload path in
app/routers/upload.py, but for a server-side URL fetch instead of a client-supplied file.
"""

from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.services import storage

DOWNLOAD_TIMEOUT = 30.0


class AudioDownloadError(Exception):
    pass


def _extension_from_url(url: str) -> str:
    ext = Path(urlparse(url).path).suffix.lower()
    return ext if ext in storage.ALLOWED_AUDIO_EXTENSIONS else ".mp3"


def download_audio(url: str, episode_id: int, max_bytes: int) -> Path:
    dest = storage.episode_dir(episode_id) / f"original{_extension_from_url(url)}"
    size = 0
    try:
        with httpx.stream("GET", url, timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as resp:
            if resp.status_code != 200:
                raise AudioDownloadError(f"Download failed: HTTP {resp.status_code}")
            with open(dest, "wb") as f:
                for chunk in resp.iter_bytes(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise AudioDownloadError("Audio file exceeds the upload size limit.")
                    f.write(chunk)
    except httpx.HTTPError as exc:
        dest.unlink(missing_ok=True)
        raise AudioDownloadError(f"Download failed: {exc}") from exc
    except AudioDownloadError:
        dest.unlink(missing_ok=True)
        raise

    if size == 0:
        dest.unlink(missing_ok=True)
        raise AudioDownloadError("Downloaded audio file is empty.")

    return dest
