"""Composites a thumbnail image as a video's literal first frame.

Used by `clip_social_publish.py` for platforms with no native cover-image field in Postiz's
public API (everything except YouTube). TikTok in particular auto-locks the very first frame of
an uploaded video as its cover, so prepending the chosen thumbnail for exactly one frame makes
that platform's own behavior pick it up as the cover.
"""

import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

from PIL import Image

from app.services.video_export import _cover_fit

_DEFAULT_FPS = 30.0


def _probe_video_stream(video_path: str) -> tuple[int, int, float]:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    width, height, fps = _DEFAULT_FPS, _DEFAULT_FPS, _DEFAULT_FPS
    try:
        width = int(lines[0])
        height = int(lines[1])
        fps = float(Fraction(lines[2]))
        if fps <= 0:
            fps = _DEFAULT_FPS
    except (IndexError, ValueError, ZeroDivisionError):
        fps = _DEFAULT_FPS
    return width, height, fps


def _probe_audio_stream(video_path: str) -> tuple[int, int] | None:
    """Returns (sample_rate, channels) for the first audio stream, or None if there isn't one."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,channels",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    try:
        return int(lines[0]), int(lines[1])
    except ValueError:
        return None


def _channel_layout(channels: int) -> str:
    if channels == 1:
        return "mono"
    if channels == 2:
        return "stereo"
    return f"{channels}c"


def _composite_thumbnail_frame(image_path: str, width: int, height: int, out_path: Path) -> None:
    """Cover-fits `image_path` to (width, height), mirroring `_composite_base_frame`'s
    scale-then-center-paste approach in `video_export.py` so a portrait/landscape thumbnail
    always fills the frame without distortion."""
    canvas = Image.new("RGB", (width, height), (26, 24, 21))
    img = Image.open(image_path).convert("RGB")
    img = _cover_fit(img, width, height)
    paste_x = (width - img.width) // 2
    paste_y = (height - img.height) // 2
    canvas.paste(img, (paste_x, paste_y))
    canvas.save(out_path)


def prepend_thumbnail_frame(video_path: str, image_path: str, out_path: Path) -> None:
    """Writes a copy of `video_path` to `out_path` with `image_path` composited as its exact
    first frame (duration = 1 / source fps). All intermediate files live in a private temp
    directory; only `out_path` survives past this call.

    Uses the `concat` *filter* (decodes both inputs into frames and concatenates those) rather
    than the concat *demuxer* (stitches containers, and requires near-identical codec
    parameters across inputs to avoid silently dropping streams) — the demuxer approach was
    tried first and, verified against real ffmpeg, silently produced an audio-only output with
    the video stream missing when the prepended segment and the arbitrary source video weren't
    encoded with identical low-level parameters."""
    width, height, fps = _probe_video_stream(video_path)
    audio = _probe_audio_stream(video_path)
    frame_dur = 1.0 / fps

    with tempfile.TemporaryDirectory() as tmp:
        thumb_png = Path(tmp) / "thumb.png"
        _composite_thumbnail_frame(image_path, width, height, thumb_png)

        cmd = ["ffmpeg", "-y", "-loop", "1", "-t", f"{frame_dur:.3f}", "-r", f"{fps:.6f}", "-i", str(thumb_png)]
        if audio is not None:
            sample_rate, channels = audio
            cmd += ["-f", "lavfi", "-t", f"{frame_dur:.3f}", "-i", f"anullsrc=r={sample_rate}:cl={_channel_layout(channels)}"]
        cmd += ["-i", video_path]

        if audio is not None:
            # Inputs: 0 = thumbnail (video only), 1 = anullsrc (audio only), 2 = source video.
            filter_complex = (
                "[0:v]format=yuv420p,setsar=1[v0];"
                "[2:v]format=yuv420p,setsar=1[v1];"
                "[v0][1:a][v1][2:a]concat=n=2:v=1:a=1[outv][outa]"
            )
            cmd += [
                "-filter_complex", filter_complex, "-map", "[outv]", "-map", "[outa]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k",
            ]
        else:
            # Inputs: 0 = thumbnail, 1 = source video (both video-only).
            filter_complex = (
                "[0:v]format=yuv420p,setsar=1[v0];"
                "[1:v]format=yuv420p,setsar=1[v1];"
                "[v0][v1]concat=n=2:v=1:a=0[outv]"
            )
            cmd += ["-filter_complex", filter_complex, "-map", "[outv]", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20"]

        cmd += ["-movflags", "+faststart", str(out_path)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
