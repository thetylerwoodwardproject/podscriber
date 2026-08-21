import logging
import traceback
from datetime import UTC, datetime

from app.db import SessionLocal
from app.models import Episode, Job
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


def _default_youtube_title(content, episode) -> str:
    titles = content.titles or []
    idx = content.selected_title_index
    if 0 <= idx < len(titles) and isinstance(titles[idx], dict):
        text = (titles[idx].get("text") or "").strip()
        if text:
            return text
    return episode.title or "Untitled"


def run_episode_social_publish(job_id: int, selections: list[dict], mode: str, scheduled_at: str | None) -> None:
    """`selections` is `[{group_index, post_index, platform, video_source, image_source}]` —
    the post text is looked up server-side from `GeneratedContent.social_posts` at publish
    time rather than trusting client-sent text, so it reflects any edits made since the page
    loaded. `video_source`/`image_source` are similarly re-resolved server-side against the
    DB (see `app.services.social_attachments`) rather than trusted from the client."""
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.status = "running"
        db.commit()

        episode = db.get(Episode, job.episode_id) if job.episode_id else None
        content = episode.generated_content if episode else None
        if content is None:
            job.status = "error"
            job.error_message = "No generated content found for this episode."
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

        video_media_cache: dict[str, dict] = {}
        image_media_cache: dict[int, dict] = {}
        youtube_title = _default_youtube_title(content, episode)

        any_ok = False
        for sel in selections:
            platform = sel["platform"]
            try:
                text = content.social_posts[sel["group_index"]]["posts"][sel["post_index"]]
            except (IndexError, KeyError, TypeError):
                record_publish_error(
                    db,
                    job=job,
                    platform=platform,
                    message="This post no longer exists — it may have been regenerated or edited.",
                    episode_id=episode.id,
                )
                continue

            video_path, video_err = resolve_video_source(db, episode, sel.get("video_source"))
            if sel.get("video_source") and video_err:
                record_publish_error(db, job=job, platform=platform, message=video_err, episode_id=episode.id)
                continue
            image_attachment, image_err = resolve_image_attachment(db, episode, sel.get("image_source"))
            if sel.get("image_source") and image_err:
                record_publish_error(db, job=job, platform=platform, message=image_err, episode_id=episode.id)
                continue
            instagram_err = validate_instagram_requirement([platform], image_attachment, has_video=bool(video_path))
            if instagram_err:
                record_publish_error(db, job=job, platform=platform, message=instagram_err, episode_id=episode.id)
                continue

            media_items = []
            try:
                if video_path:
                    if video_path not in video_media_cache:
                        video_media_cache[video_path] = upload_media(base_url, api_key, video_path)
                    media_items.append(video_media_cache[video_path])
                if image_attachment:
                    if image_attachment.id not in image_media_cache:
                        image_media_cache[image_attachment.id] = upload_media(
                            base_url, api_key, image_attachment.file_path, content_type=image_attachment.content_type
                        )
                    media_items.append(image_media_cache[image_attachment.id])
            except PostizError as exc:
                record_publish_error(
                    db, job=job, platform=platform, message=f"Couldn't upload media to Postiz: {exc}",
                    episode_id=episode.id,
                )
                continue

            settings = default_settings_for_platform(platform, youtube_title=youtube_title)
            ok = publish_one_platform(
                db,
                job=job,
                base_url=base_url,
                api_key=api_key,
                integrations=integrations,
                platform=platform,
                content=text,
                media=media_items or None,
                post_type=post_type,
                date=date,
                settings=settings,
                episode_id=episode.id,
            )
            any_ok = any_ok or ok
        db.commit()

        job.status = "done" if any_ok else "error"
        if not any_ok:
            job.error_message = "Publishing failed for every selected post — see per-platform status."
        db.commit()
    except Exception:
        logger.exception("Episode social publish job %s failed", job_id)
        job = db.get(Job, job_id)
        if job is not None:
            job.status = "error"
            job.error_message = traceback.format_exc(limit=5)
            db.commit()
    finally:
        db.close()
