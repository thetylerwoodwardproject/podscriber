import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

from app.db import SessionLocal
from app.models import Episode, Job
from app.services import storage
from app.services.video_export import _cover_fit, _probe_duration_seconds

CANVAS_W, CANVAS_H = 1920, 1080
EDITOR_FRAME_W = 320  # matches the CSS preview frame width; offsets recorded there are scaled up by this ratio
SCALE = CANVAS_W / EDITOR_FRAME_W

# Bottom-band layout, same approach as video_export.py's vertical canvas: the waveform band
# sits above the bottom margin by default, then shifts by the user's dragged
# video.waveform_offset_y (editor-pixel space, scaled up by SCALE).
WAVEFORM_W, WAVEFORM_H = 1600, 260
WAVEFORM_GAP = 24
BOTTOM_MARGIN = 70


def _composite_full_base_frame(video, out_path: Path) -> int:
    """Renders the static background+logo frame and returns the waveform band's top Y."""
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (26, 24, 21))

    if video.background_image_path and Path(video.background_image_path).exists():
        bg = Image.open(video.background_image_path).convert("RGB")
        bg = _cover_fit(bg, CANVAS_W, CANVAS_H)
        paste_x = (CANVAS_W - bg.width) // 2
        paste_y = (CANVAS_H - bg.height) // 2
        bg = ImageEnhance.Brightness(bg).enhance(video.brightness)
        canvas.paste(bg, (paste_x, paste_y))

    draw = ImageDraw.Draw(canvas, "RGBA")

    # Top gradient behind logo
    if video.logo_image_path and Path(video.logo_image_path).exists():
        for i in range(220):
            alpha = int(140 * (1 - i / 220))
            draw.line([(0, i), (CANVAS_W, i)], fill=(0, 0, 0, alpha))

        logo = Image.open(video.logo_image_path).convert("RGBA")
        logo_size = 220
        logo = _cover_fit(logo, logo_size, logo_size)
        logo = logo.crop((0, 0, logo_size, logo_size))
        corner_mask = Image.new("L", (logo_size, logo_size), 0)
        ImageDraw.Draw(corner_mask).rounded_rectangle([0, 0, logo_size, logo_size], radius=44, fill=255)
        badge = Image.new("RGBA", (logo_size, logo_size), (255, 255, 255, 255))
        badge.paste(logo, (0, 0), logo)  # use the logo's own alpha channel, not the corner mask
        canvas.paste(badge, (85, 70), corner_mask)  # corner mask only clips the badge's outer shape

    base_waveform_top_y = (CANVAS_H - BOTTOM_MARGIN) - WAVEFORM_GAP - WAVEFORM_H
    scaled_offset = round(video.waveform_offset_y * SCALE)
    waveform_top_y = max(0, min(CANVAS_H - WAVEFORM_H, base_waveform_top_y + scaled_offset))

    canvas.save(out_path)
    return waveform_top_y


def run_full_video_export(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        episode = db.get(Episode, job.episode_id)
        video = episode.video if episode else None
        if episode is None or video is None:
            raise RuntimeError("Episode or its video settings could not be found.")
        if not episode.file_path or not Path(episode.file_path).exists():
            raise RuntimeError("Episode audio file is missing.")

        job.status = "running"
        job.current_step = "compositing"
        job.progress_pct = 20
        job.started_at = datetime.now(UTC)
        db.commit()

        with tempfile.TemporaryDirectory() as tmp:
            base_frame_path = Path(tmp) / "base.png"
            waveform_top_y = _composite_full_base_frame(video, base_frame_path)

            job.current_step = "rendering"
            job.progress_pct = 60
            db.commit()

            color_hex = (video.waveform_color or "#e2572c").lstrip("#")
            if len(color_hex) not in (6, 8):
                color_hex = "e2572c"
            ffmpeg_color = f"0x{color_hex}"

            out_path = storage.video_dir(episode.id) / f"episode-{episode.id}.mp4"

            # Same `-loop 1` + explicit `-t` requirement documented in video_export.py: the
            # still-image input is an infinite-duration stream, and `-shortest` alone is not
            # reliable when it feeds an overlay filter graph — it can run away generating
            # frames faster than the muxer catches up. An explicit `-t` bound makes render
            # duration deterministic; `-shortest` stays as a secondary safety net.
            duration_s = _probe_duration_seconds(episode.file_path)

            filter_complex = (
                "[1:a]asplit=2[a1][a2];"
                f"[a1]showwaves=s={WAVEFORM_W}x{WAVEFORM_H}:mode=cline:rate=25:colors={ffmpeg_color}:draw=full,"
                "format=rgba,colorkey=0x000000:0.15:0.1[wave];"
                f"[0:v][wave]overlay=x=(W-w)/2:y={waveform_top_y}:format=auto,format=yuv420p[vout]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", str(base_frame_path),
                "-i", episode.file_path,
                "-filter_complex", filter_complex,
                "-map", "[vout]", "-map", "[a2]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k",
                "-t", f"{duration_s:.3f}",
                "-shortest", "-movflags", "+faststart",
                str(out_path),
            ]
            # Full episodes run far longer than a soundbite clip, so the render itself takes
            # proportionally longer — give the subprocess headroom scaled to source duration
            # rather than the short clip export's fixed 180s timeout.
            subprocess.run(cmd, check=True, capture_output=True, timeout=max(300, int(duration_s * 3)))

        video.exported_video_path = str(out_path)
        video.exported_at = datetime.now(UTC)
        job.status = "done"
        job.progress_pct = 100
        job.finished_at = datetime.now(UTC)
        db.commit()
    finally:
        db.close()
