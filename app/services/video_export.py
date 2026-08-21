import logging
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

from app.db import SessionLocal
from app.models import Job, VideoClip
from app.services import storage
from app.services.llm.factory import get_llm_provider

logger = logging.getLogger("podscriber.video_export")

CANVAS_W, CANVAS_H = 1080, 1920
EDITOR_FRAME_W = 280  # matches the CSS preview frame width; offsets recorded there are scaled up by this ratio
SCALE = CANVAS_W / EDITOR_FRAME_W

# Bottom-band layout: the waveform band sits directly above the bottom margin by default, then
# shifts by the user's dragged clip.waveform_offset_y (editor-pixel space, scaled up by SCALE).
# Computed once in _composite_base_frame and the resulting waveform Y position is threaded through
# to the ffmpeg command rather than each guessing independently.
WAVEFORM_W, WAVEFORM_H = 1000, 320
WAVEFORM_GAP = 28
BOTTOM_MARGIN = 90


def _probe_duration_seconds(audio_path: str) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return float(result.stdout.strip())


def _cover_fit(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    scale = max(target_w / img.width, target_h / img.height)
    return img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)


def _composite_base_frame(clip: VideoClip, out_path: Path) -> int:
    """Renders the static background+logo frame and returns the waveform band's top Y."""
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (26, 24, 21))

    if clip.background_image_path and Path(clip.background_image_path).exists():
        bg = Image.open(clip.background_image_path).convert("RGB")
        bg = _cover_fit(bg, CANVAS_W, CANVAS_H)
        paste_x = (CANVAS_W - bg.width) // 2
        paste_y = (CANVAS_H - bg.height) // 2
        bg = ImageEnhance.Brightness(bg).enhance(clip.brightness)
        canvas.paste(bg, (paste_x, paste_y))

    draw = ImageDraw.Draw(canvas, "RGBA")

    # Top gradient behind logo
    if clip.logo_image_path and Path(clip.logo_image_path).exists():
        for i in range(220):
            alpha = int(140 * (1 - i / 220))
            draw.line([(0, i), (CANVAS_W, i)], fill=(0, 0, 0, alpha))

        logo = Image.open(clip.logo_image_path).convert("RGBA")
        logo_size = 220
        logo = _cover_fit(logo, logo_size, logo_size)
        logo = logo.crop((0, 0, logo_size, logo_size))
        corner_mask = Image.new("L", (logo_size, logo_size), 0)
        ImageDraw.Draw(corner_mask).rounded_rectangle([0, 0, logo_size, logo_size], radius=44, fill=255)
        badge = Image.new("RGBA", (logo_size, logo_size), (255, 255, 255, 255))
        badge.paste(logo, (0, 0), logo)  # use the logo's own alpha channel, not the corner mask
        canvas.paste(badge, (85, 70), corner_mask)  # corner mask only clips the badge's outer shape

    base_waveform_top_y = (CANVAS_H - BOTTOM_MARGIN) - WAVEFORM_GAP - WAVEFORM_H
    scaled_offset = round(clip.waveform_offset_y * SCALE)
    waveform_top_y = max(0, min(CANVAS_H - WAVEFORM_H, base_waveform_top_y + scaled_offset))

    canvas.save(out_path)
    return waveform_top_y


def run_video_export(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        clip = db.get(VideoClip, job.video_clip_id) if job.video_clip_id else None
        soundbite = clip.soundbite if clip else None
        if soundbite is None or clip is None:
            raise RuntimeError("Soundbite or its video clip settings could not be found.")
        if not soundbite.clip_audio_path or not Path(soundbite.clip_audio_path).exists():
            raise RuntimeError("Soundbite audio has not been clipped yet.")

        job.status = "running"
        job.started_at = datetime.now(UTC)
        db.commit()

        if not clip.social_post and not clip.youtube_title:
            job.current_step = "writing social copy"
            job.progress_pct = 10
            db.commit()
            try:
                llm = get_llm_provider(db)
                result = llm.generate_clip_social(
                    soundbite.quote, soundbite.episode.title or soundbite.episode.original_filename
                )
                clip.social_post = result.social_post
                clip.youtube_title = result.youtube_title
                db.commit()
            except Exception:
                logger.warning("Clip social generation failed for job %s", job_id, exc_info=True)

        job.current_step = "compositing"
        job.progress_pct = 20
        db.commit()

        with tempfile.TemporaryDirectory() as tmp:
            base_frame_path = Path(tmp) / "base.png"
            waveform_top_y = _composite_base_frame(clip, base_frame_path)

            job.current_step = "rendering"
            job.progress_pct = 60
            db.commit()

            color_hex = (clip.waveform_color or "#e2572c").lstrip("#")
            if len(color_hex) not in (6, 8):
                color_hex = "e2572c"
            ffmpeg_color = f"0x{color_hex}"

            # Keyed by clip id, not soundbite id: a soundbite can have several video
            # variants (duplicates), and they must not overwrite each other's export file.
            out_path = storage.video_dir(soundbite.episode_id) / f"clip-{clip.id}.mp4"

            # `-loop 1` on the still-image input makes it an infinite-duration stream. `-shortest`
            # alone is not reliable here: it only trims at the muxer once it sees packets past the
            # end of the shortest *mapped* stream, but the overlay filter (fed by that infinite
            # main input) can run far ahead generating frames before the muxer catches up — in
            # testing this produced an ffmpeg process that never stopped, still encoding output
            # minutes later while burning multiple GB of memory. An explicit `-t` bound on the
            # output makes the render duration deterministic regardless of that filter-graph
            # interaction; `-shortest` is kept only as a secondary safety net.
            duration_s = _probe_duration_seconds(soundbite.clip_audio_path)

            # showwaves renders on an opaque black canvas (no alpha channel) — composited directly,
            # that black canvas would paint a solid rectangle over the background instead of just
            # the waveform line. colorkey keys out that black background to transparent so overlay
            # only draws the waveform itself.
            filter_complex = (
                "[1:a]asplit=2[a1][a2];"
                # draw=full (vs. the default draw=scale) draws each sample as a solid pixel of
                # `colors` rather than scaling its value by amplitude — on real speech (dense,
                # fast-changing, unlike a clean test tone) draw=scale's per-sample blending pushes
                # overlapping samples toward red regardless of the requested color.
                f"[a1]showwaves=s={WAVEFORM_W}x{WAVEFORM_H}:mode=cline:rate=25:colors={ffmpeg_color}:draw=full,"
                "format=rgba,colorkey=0x000000:0.15:0.1[wave];"
                # x is always centered and fixed; y is the static position (base layout + the
                # user's dragged offset, already resolved in _composite_base_frame) — vertical
                # placement only, no horizontal motion.
                f"[0:v][wave]overlay=x=(W-w)/2:y={waveform_top_y}:format=auto,format=yuv420p[vout]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", str(base_frame_path),
                "-i", soundbite.clip_audio_path,
                "-filter_complex", filter_complex,
                "-map", "[vout]", "-map", "[a2]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k",
                "-t", f"{duration_s:.3f}",
                "-shortest", "-movflags", "+faststart",
                str(out_path),
            ]
            subprocess.run(cmd, check=True, capture_output=True, timeout=180)

        clip.exported_video_path = str(out_path)
        clip.exported_at = datetime.now(UTC)
        job.status = "done"
        job.progress_pct = 100
        job.finished_at = datetime.now(UTC)
        db.commit()
    finally:
        db.close()
