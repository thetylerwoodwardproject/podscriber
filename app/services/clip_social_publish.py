import logging
import traceback
from datetime import UTC, datetime

from app.db import SessionLocal
from app.models import Episode, Job, VideoClip
from app.services import settings_store
from app.services.postiz import PostizError, upload_media
from app.services.social_attachments import (
    resolve_image_attachment,
    resolve_video_source,
    validate_instagram_requirement,
)
from app.services.social_publish import (
    default_settings_for_platform,
    publish_one_platform,
    record_publish_error,
    resolve_integrations,
)

logger = logging.getLogger("podscriber.jobs")


def run_clip_social_publish(
    job_id: int,
    platforms: list[str],
    mode: str,
    scheduled_at: str | None,
    video_source: dict | None,
    image_source: dict | None,
) -> None:
    """`video_source`/`image_source` are re-resolved server-side against the DB (see
    `app.services.social_attachments`) rather than trusted from the client. A video source
    is required — the clip flow keeps mandatory video attach — but it no longer has to be
    the clip's own export; it can be any already-exported video in the episode, or an
    uploaded one."""
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.status = "running"
        db.commit()

        clip = db.get(VideoClip, job.video_clip_id) if job.video_clip_id else None
        soundbite = clip.soundbite if clip else None
        episode = db.get(Episode, soundbite.episode_id) if soundbite else None
        if clip is None or episode is None:
            job.status = "error"
            job.error_message = "No clip to publish."
            db.commit()
            return

        video_path, video_err = resolve_video_source(db, episode, video_source)
        if not video_source:
            job.status = "error"
            job.error_message = "Pick a video to attach."
            db.commit()
            return
        if video_err:
            job.status = "error"
            job.error_message = video_err
            db.commit()
            return

        image_attachment, image_err = resolve_image_attachment(db, episode, image_source)
        if image_source and image_err:
            job.status = "error"
            job.error_message = image_err
            db.commit()
            return

        instagram_err = validate_instagram_requirement(platforms, image_attachment, has_video=bool(video_path))
        if instagram_err:
            for platform in platforms:
                record_publish_error(db, job=job, platform=platform, message=instagram_err, video_clip_id=clip.id)
            job.status = "error"
            job.error_message = instagram_err
            db.commit()
            return

        base_url = settings_store.get(db, "postiz_base_url")
        api_key = settings_store.get(db, "postiz_api_key")
        if not base_url or not api_key:
            job.status = "error"
            job.error_message = "Postiz isn't configured — add a base URL and API key in Settings."
            db.commit()
            return

        date = scheduled_at if mode == "scheduled" and scheduled_at else datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        post_type = "schedule" if mode == "scheduled" else "now"

        try:
            integrations = resolve_integrations(base_url, api_key)
        except PostizError as exc:
            job.status = "error"
            job.error_message = f"Couldn't reach Postiz: {exc}"
            db.commit()
            return

        try:
            media_items = [upload_media(base_url, api_key, video_path)]
            if image_attachment:
                media_items.append(
                    upload_media(base_url, api_key, image_attachment.file_path, content_type=image_attachment.content_type)
                )
        except PostizError as exc:
            # Record the same upload failure against every requested platform, since the
            # editor's status list reads per-platform SocialPublish rows, not the job itself.
            for platform in platforms:
                record_publish_error(db, job=job, platform=platform, message=str(exc), video_clip_id=clip.id)
            job.status = "error"
            job.error_message = f"Couldn't upload media to Postiz: {exc}"
            db.commit()
            return

        any_ok = False
        for platform in platforms:
            settings = default_settings_for_platform(platform, youtube_title=clip.youtube_title)
            ok = publish_one_platform(
                db,
                job=job,
                base_url=base_url,
                api_key=api_key,
                integrations=integrations,
                platform=platform,
                content=clip.social_post,
                media=media_items,
                post_type=post_type,
                date=date,
                settings=settings,
                video_clip_id=clip.id,
            )
            any_ok = any_ok or ok
        db.commit()

        job.status = "done" if any_ok else "error"
        if not any_ok:
            job.error_message = "Publishing failed for every selected platform — see per-platform status."
        db.commit()
    except Exception:
        logger.exception("Clip social publish job %s failed", job_id)
        job = db.get(Job, job_id)
        if job is not None:
            job.status = "error"
            job.error_message = traceback.format_exc(limit=5)
            db.commit()
    finally:
        db.close()
