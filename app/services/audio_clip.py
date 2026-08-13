import subprocess
from pathlib import Path

from app.models import Episode, Soundbite
from app.services import storage


def clip_soundbite_audio(episode: Episode, soundbite: Soundbite) -> Path:
    """Cuts [start_ms, end_ms) from the episode's source audio into its own mp3 file via ffmpeg."""
    out_dir = storage.clips_dir(episode.id)
    out_path = out_dir / f"{soundbite.id}.mp3"

    start_s = max(0, soundbite.start_ms) / 1000.0
    duration_s = max(0.05, (soundbite.end_ms - soundbite.start_ms) / 1000.0)

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_s:.3f}",
        "-i", episode.file_path,
        "-t", f"{duration_s:.3f}",
        "-vn", "-acodec", "libmp3lame", "-q:a", "3",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    soundbite.clip_audio_path = str(out_path)
    return out_path
