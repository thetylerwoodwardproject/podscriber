from unittest.mock import MagicMock, patch

from app.services import clip_social_publish, settings_store, social_publish
from app.services.postiz import Integration


def _make_episode_with_soundbite(db, own_export=True, with_episode_video=False, youtube_title=""):
    from app.models import Episode, EpisodeVideo, Soundbite, VideoClip

    episode = Episode(title="Ep", original_filename="ep.mp3", file_path="/tmp/ep.mp3", status="processed")
    db.add(episode)
    db.commit()
    db.refresh(episode)
    if with_episode_video:
        db.add(EpisodeVideo(episode_id=episode.id, exported_video_path="/media/episode.mp4"))
        db.commit()

    sb = Soundbite(episode_id=episode.id, quote="a great quote", start_ms=0, end_ms=1000)
    db.add(sb)
    db.commit()
    db.refresh(sb)
    clip = VideoClip(
        soundbite_id=sb.id,
        social_post="check this out",
        youtube_title=youtube_title,
        exported_video_path="/media/clip.mp4" if own_export else None,
    )
    db.add(clip)
    db.commit()
    db.refresh(clip)
    return episode, sb, clip


def _make_job(db, episode_id, soundbite_id, clip_id):
    from app.models import Job

    job = Job(
        episode_id=episode_id,
        soundbite_id=soundbite_id,
        video_clip_id=clip_id,
        job_type="clip_social_publish",
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _wire(db, monkeypatch):
    settings_store.set_many(db, {"postiz_base_url": "https://postiz.example.com/api", "postiz_api_key": "key"})
    monkeypatch.setattr(clip_social_publish, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    integrations = [
        Integration(id="int-1", platform="x", name="X"),
        Integration(id="int-2", platform="instagram", name="IG"),
        Integration(id="int-3", platform="tiktok", name="TikTok"),
        Integration(id="int-4", platform="youtube", name="YouTube"),
    ]
    monkeypatch.setattr(social_publish, "list_integrations", lambda *a, **k: integrations)


def test_publishes_with_explicit_clip_video_source(db, monkeypatch):
    episode, sb, clip = _make_episode_with_soundbite(db)
    job = _make_job(db, episode.id, sb.id, clip.id)
    _wire(db, monkeypatch)

    upload_mock = MagicMock(return_value={"id": "media-1"})
    monkeypatch.setattr(clip_social_publish, "upload_media", upload_mock)
    with patch("app.services.social_publish.create_post", return_value=[{"postId": "p1"}]):
        clip_social_publish.run_clip_social_publish(
            job.id, ["x"], "now", None, {"type": "clip", "clip_id": clip.id}, None
        )

    assert job.status == "done"
    upload_mock.assert_called_once_with("https://postiz.example.com/api", "key", "/media/clip.mp4")


def test_can_attach_a_different_video_than_its_own_clip(db, monkeypatch):
    episode, sb, clip = _make_episode_with_soundbite(db, own_export=False, with_episode_video=True)
    job = _make_job(db, episode.id, sb.id, clip.id)
    _wire(db, monkeypatch)

    upload_mock = MagicMock(return_value={"id": "media-1"})
    monkeypatch.setattr(clip_social_publish, "upload_media", upload_mock)
    with patch("app.services.social_publish.create_post", return_value=[{"postId": "p1"}]):
        clip_social_publish.run_clip_social_publish(job.id, ["x"], "now", None, {"type": "episode_video"}, None)

    assert job.status == "done"
    upload_mock.assert_called_once_with("https://postiz.example.com/api", "key", "/media/episode.mp4")


def test_with_image_attachment_success(db, monkeypatch):
    from app.models import SocialAttachment

    episode, sb, clip = _make_episode_with_soundbite(db)
    attachment = SocialAttachment(episode_id=episode.id, kind="image", file_path="/media/img.png", content_type="image/png", width=1080, height=1080)
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    job = _make_job(db, episode.id, sb.id, clip.id)
    _wire(db, monkeypatch)

    monkeypatch.setattr(
        clip_social_publish, "upload_media", MagicMock(side_effect=[{"id": "video-media"}, {"id": "image-media"}])
    )
    with patch("app.services.social_publish.create_post", return_value=[{"postId": "p1"}]) as create_mock:
        clip_social_publish.run_clip_social_publish(
            job.id,
            ["instagram"],
            "now",
            None,
            {"type": "clip", "clip_id": clip.id},
            {"type": "upload", "attachment_id": attachment.id},
        )

    assert job.status == "done"
    assert create_mock.call_args.kwargs["media"] == [{"id": "video-media"}, {"id": "image-media"}]


def test_instagram_video_only_succeeds_with_post_post_type(db, monkeypatch):
    # Postiz's Instagram DTO only accepts post_type "post" or "story" (not "reel"), so a
    # vertical clip source is published as a regular feed post regardless of aspect ratio.
    episode, sb, clip = _make_episode_with_soundbite(db)
    job = _make_job(db, episode.id, sb.id, clip.id)
    _wire(db, monkeypatch)

    monkeypatch.setattr(clip_social_publish, "upload_media", MagicMock(return_value={"id": "media-1"}))
    with patch("app.services.social_publish.create_post", return_value=[{"postId": "p1"}]) as create_mock:
        clip_social_publish.run_clip_social_publish(
            job.id, ["instagram"], "now", None, {"type": "clip", "clip_id": clip.id}, None
        )

    assert job.status == "done"
    assert create_mock.call_args.kwargs["settings"] == {"post_type": "post"}


def test_tiktok_settings_include_direct_post_and_privacy(db, monkeypatch):
    from app.services.social_publish import TIKTOK_DEFAULT_SETTINGS

    episode, sb, clip = _make_episode_with_soundbite(db)
    job = _make_job(db, episode.id, sb.id, clip.id)
    _wire(db, monkeypatch)

    monkeypatch.setattr(clip_social_publish, "upload_media", MagicMock(return_value={"id": "media-1"}))
    with patch("app.services.social_publish.create_post", return_value=[{"postId": "p1"}]) as create_mock:
        clip_social_publish.run_clip_social_publish(
            job.id, ["tiktok"], "now", None, {"type": "clip", "clip_id": clip.id}, None
        )

    assert job.status == "done"
    assert create_mock.call_args.kwargs["settings"] == TIKTOK_DEFAULT_SETTINGS


def test_youtube_settings_include_clip_youtube_title(db, monkeypatch):
    episode, sb, clip = _make_episode_with_soundbite(db, youtube_title="Great clip")
    job = _make_job(db, episode.id, sb.id, clip.id)
    _wire(db, monkeypatch)

    monkeypatch.setattr(clip_social_publish, "upload_media", MagicMock(return_value={"id": "media-1"}))
    with patch("app.services.social_publish.create_post", return_value=[{"postId": "p1"}]) as create_mock:
        clip_social_publish.run_clip_social_publish(
            job.id, ["youtube"], "now", None, {"type": "clip", "clip_id": clip.id}, None
        )

    assert job.status == "done"
    assert create_mock.call_args.kwargs["settings"] == {"title": "Great clip", "type": "public"}


def test_missing_video_source_fails_fast_with_no_postiz_call(db, monkeypatch):
    episode, sb, clip = _make_episode_with_soundbite(db)
    job = _make_job(db, episode.id, sb.id, clip.id)
    _wire(db, monkeypatch)

    upload_mock = MagicMock()
    monkeypatch.setattr(clip_social_publish, "upload_media", upload_mock)
    with patch("app.services.social_publish.create_post") as create_mock:
        clip_social_publish.run_clip_social_publish(job.id, ["x"], "now", None, None, None)

    assert job.status == "error"
    assert "Pick a video" in job.error_message
    upload_mock.assert_not_called()
    create_mock.assert_not_called()
