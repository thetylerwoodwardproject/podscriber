from unittest.mock import MagicMock, patch

from app.services import episode_social_publish, settings_store, social_publish
from app.services.postiz import Integration


def _make_episode(db, with_video=False):
    from app.models import Episode, EpisodeVideo, GeneratedContent

    episode = Episode(title="Ep", original_filename="ep.mp3", file_path="/tmp/ep.mp3", status="processed")
    db.add(episode)
    db.commit()
    db.refresh(episode)
    db.add(
        GeneratedContent(
            episode_id=episode.id,
            description="desc",
            social_posts=[{"platform": "X", "initial": "X", "color": "#111", "platform_key": "x", "posts": ["hello"]}]
            + [
                {
                    "platform": "Instagram",
                    "initial": "I",
                    "color": "#222",
                    "platform_key": "instagram",
                    "posts": ["hi there"],
                }
            ],
        )
    )
    if with_video:
        db.add(EpisodeVideo(episode_id=episode.id, exported_video_path="/media/episode.mp4"))
    db.commit()
    db.refresh(episode)
    return episode


def _make_soundbite_with_clip(db, episode_id):
    from app.models import Soundbite, VideoClip

    sb = Soundbite(episode_id=episode_id, quote="a great quote", start_ms=0, end_ms=1000)
    db.add(sb)
    db.commit()
    db.refresh(sb)
    clip = VideoClip(soundbite_id=sb.id, exported_video_path="/media/clip.mp4")
    db.add(clip)
    db.commit()
    db.refresh(clip)
    return clip


def _make_job(db, episode_id):
    from app.models import Job

    job = Job(episode_id=episode_id, job_type="episode_social_publish", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _wire(db, monkeypatch):
    settings_store.set_many(db, {"postiz_base_url": "https://postiz.example.com/api", "postiz_api_key": "key"})
    monkeypatch.setattr(episode_social_publish, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    integrations = [
        Integration(id="int-1", platform="x", name="X"),
        Integration(id="int-2", platform="instagram", name="IG"),
        Integration(id="int-3", platform="tiktok", name="TikTok"),
        Integration(id="int-4", platform="youtube", name="YouTube"),
    ]
    monkeypatch.setattr(social_publish, "list_integrations", lambda *a, **k: integrations)


def test_resolves_episode_video_source(db, monkeypatch):
    episode = _make_episode(db, with_video=True)
    job = _make_job(db, episode.id)
    _wire(db, monkeypatch)

    upload_mock = MagicMock(return_value={"id": "media-1"})
    monkeypatch.setattr(episode_social_publish, "upload_media", upload_mock)
    with patch("app.services.social_publish.create_post", return_value=[{"postId": "p1"}]) as create_mock:
        episode_social_publish.run_episode_social_publish(
            job.id,
            [{"group_index": 0, "post_index": 0, "platform": "x", "video_source": {"type": "episode_video"}, "image_source": None}],
            "now",
            None,
        )

    assert job.status == "done"
    upload_mock.assert_called_once_with("https://postiz.example.com/api", "key", "/media/episode.mp4")
    assert create_mock.call_args.kwargs["media"] == [{"id": "media-1"}]


def test_resolves_clip_video_source(db, monkeypatch):
    episode = _make_episode(db)
    clip = _make_soundbite_with_clip(db, episode.id)
    job = _make_job(db, episode.id)
    _wire(db, monkeypatch)

    upload_mock = MagicMock(return_value={"id": "media-1"})
    monkeypatch.setattr(episode_social_publish, "upload_media", upload_mock)
    with patch("app.services.social_publish.create_post", return_value=[{"postId": "p1"}]):
        episode_social_publish.run_episode_social_publish(
            job.id,
            [
                {
                    "group_index": 0,
                    "post_index": 0,
                    "platform": "x",
                    "video_source": {"type": "clip", "clip_id": clip.id},
                    "image_source": None,
                }
            ],
            "now",
            None,
        )

    assert job.status == "done"
    upload_mock.assert_called_once_with("https://postiz.example.com/api", "key", "/media/clip.mp4")


def test_resolves_uploaded_video_attachment(db, monkeypatch):
    from app.models import SocialAttachment

    episode = _make_episode(db)
    attachment = SocialAttachment(episode_id=episode.id, kind="video", file_path="/media/uploaded.mp4", content_type="video/mp4")
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    job = _make_job(db, episode.id)
    _wire(db, monkeypatch)

    upload_mock = MagicMock(return_value={"id": "media-1"})
    monkeypatch.setattr(episode_social_publish, "upload_media", upload_mock)
    with patch("app.services.social_publish.create_post", return_value=[{"postId": "p1"}]):
        episode_social_publish.run_episode_social_publish(
            job.id,
            [
                {
                    "group_index": 0,
                    "post_index": 0,
                    "platform": "x",
                    "video_source": {"type": "upload", "attachment_id": attachment.id},
                    "image_source": None,
                }
            ],
            "now",
            None,
        )

    assert job.status == "done"
    upload_mock.assert_called_once_with("https://postiz.example.com/api", "key", "/media/uploaded.mp4")


def test_rejects_instagram_without_image(db, monkeypatch):
    from app.models import SocialPublish

    episode = _make_episode(db)
    job = _make_job(db, episode.id)
    _wire(db, monkeypatch)

    upload_mock = MagicMock()
    monkeypatch.setattr(episode_social_publish, "upload_media", upload_mock)
    with patch("app.services.social_publish.create_post") as create_mock:
        episode_social_publish.run_episode_social_publish(
            job.id,
            [{"group_index": 1, "post_index": 0, "platform": "instagram", "video_source": None, "image_source": None}],
            "now",
            None,
        )

    assert job.status == "error"
    upload_mock.assert_not_called()
    create_mock.assert_not_called()
    row = db.query(SocialPublish).one()
    assert row.status == "error"
    assert "requires a video or an image" in row.error_message


def test_rejects_instagram_bad_aspect_ratio(db, monkeypatch):
    from app.models import SocialAttachment, SocialPublish

    episode = _make_episode(db)
    attachment = SocialAttachment(episode_id=episode.id, kind="image", file_path="/media/bad.png", width=2000, height=800)
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    job = _make_job(db, episode.id)
    _wire(db, monkeypatch)

    with patch("app.services.social_publish.create_post") as create_mock:
        episode_social_publish.run_episode_social_publish(
            job.id,
            [
                {
                    "group_index": 1,
                    "post_index": 0,
                    "platform": "instagram",
                    "video_source": None,
                    "image_source": {"type": "upload", "attachment_id": attachment.id},
                }
            ],
            "now",
            None,
        )

    assert job.status == "error"
    create_mock.assert_not_called()
    row = db.query(SocialPublish).one()
    assert "doesn't fit Instagram's accepted aspect-ratio range" in row.error_message


def test_dedupes_video_upload_across_multiple_selections_same_source(db, monkeypatch):
    episode = _make_episode(db, with_video=True)
    job = _make_job(db, episode.id)
    _wire(db, monkeypatch)

    upload_mock = MagicMock(return_value={"id": "media-1"})
    monkeypatch.setattr(episode_social_publish, "upload_media", upload_mock)
    with patch("app.services.social_publish.create_post", return_value=[{"postId": "p1"}]):
        episode_social_publish.run_episode_social_publish(
            job.id,
            [
                {
                    "group_index": 0,
                    "post_index": 0,
                    "platform": "x",
                    "video_source": {"type": "episode_video"},
                    "image_source": None,
                },
                {
                    "group_index": 0,
                    "post_index": 0,
                    "platform": "tiktok",
                    "video_source": {"type": "episode_video"},
                    "image_source": None,
                },
            ],
            "now",
            None,
        )

    # Both selections reference the same resolved video path — should be uploaded once and
    # reused for the second platform.
    upload_mock.assert_called_once()


def test_instagram_video_only_succeeds_no_image(db, monkeypatch):
    episode = _make_episode(db, with_video=True)
    job = _make_job(db, episode.id)
    _wire(db, monkeypatch)

    monkeypatch.setattr(episode_social_publish, "upload_media", MagicMock(return_value={"id": "media-1"}))
    with patch("app.services.social_publish.create_post", return_value=[{"postId": "p1"}]) as create_mock:
        episode_social_publish.run_episode_social_publish(
            job.id,
            [
                {
                    "group_index": 1,
                    "post_index": 0,
                    "platform": "instagram",
                    "video_source": {"type": "episode_video"},
                    "image_source": None,
                }
            ],
            "now",
            None,
        )

    assert job.status == "done"
    assert create_mock.call_args.kwargs["settings"] == {"post_type": "post"}


def test_instagram_video_clip_source_still_uses_post_post_type(db, monkeypatch):
    # Postiz's Instagram DTO only accepts post_type "post" or "story" (not "reel"), so a
    # 9:16 clip source is published as a regular feed post, same as any other video source.
    episode = _make_episode(db)
    clip = _make_soundbite_with_clip(db, episode.id)
    job = _make_job(db, episode.id)
    _wire(db, monkeypatch)

    monkeypatch.setattr(episode_social_publish, "upload_media", MagicMock(return_value={"id": "media-1"}))
    with patch("app.services.social_publish.create_post", return_value=[{"postId": "p1"}]) as create_mock:
        episode_social_publish.run_episode_social_publish(
            job.id,
            [
                {
                    "group_index": 1,
                    "post_index": 0,
                    "platform": "instagram",
                    "video_source": {"type": "clip", "clip_id": clip.id},
                    "image_source": None,
                }
            ],
            "now",
            None,
        )

    assert job.status == "done"
    assert create_mock.call_args.kwargs["settings"] == {"post_type": "post"}


def test_youtube_title_falls_back_to_episode_title_when_titles_empty(db, monkeypatch):
    episode = _make_episode(db, with_video=True)
    episode.title = "My Episode"
    episode.generated_content.titles = []
    db.commit()
    job = _make_job(db, episode.id)
    _wire(db, monkeypatch)

    monkeypatch.setattr(episode_social_publish, "upload_media", MagicMock(return_value={"id": "media-1"}))
    with patch("app.services.social_publish.create_post", return_value=[{"postId": "p1"}]) as create_mock:
        episode_social_publish.run_episode_social_publish(
            job.id,
            [{"group_index": 0, "post_index": 0, "platform": "youtube", "video_source": {"type": "episode_video"}, "image_source": None}],
            "now",
            None,
        )

    assert job.status == "done"
    assert create_mock.call_args.kwargs["settings"] == {"title": "My Episode", "type": "public"}


def test_youtube_settings_use_selected_title(db, monkeypatch):
    episode = _make_episode(db, with_video=True)
    episode.generated_content.titles = [{"text": "A", "score": 1}, {"text": "B", "score": 2}]
    episode.generated_content.selected_title_index = 1
    db.commit()
    job = _make_job(db, episode.id)
    _wire(db, monkeypatch)

    monkeypatch.setattr(episode_social_publish, "upload_media", MagicMock(return_value={"id": "media-1"}))
    with patch("app.services.social_publish.create_post", return_value=[{"postId": "p1"}]) as create_mock:
        episode_social_publish.run_episode_social_publish(
            job.id,
            [{"group_index": 0, "post_index": 0, "platform": "youtube", "video_source": {"type": "episode_video"}, "image_source": None}],
            "now",
            None,
        )

    assert job.status == "done"
    assert create_mock.call_args.kwargs["settings"] == {"title": "B", "type": "public"}


def test_tiktok_settings_use_direct_post_and_public_privacy(db, monkeypatch):
    from app.services.social_publish import TIKTOK_DEFAULT_SETTINGS

    episode = _make_episode(db, with_video=True)
    job = _make_job(db, episode.id)
    _wire(db, monkeypatch)

    monkeypatch.setattr(episode_social_publish, "upload_media", MagicMock(return_value={"id": "media-1"}))
    with patch("app.services.social_publish.create_post", return_value=[{"postId": "p1"}]) as create_mock:
        episode_social_publish.run_episode_social_publish(
            job.id,
            [{"group_index": 0, "post_index": 0, "platform": "tiktok", "video_source": {"type": "episode_video"}, "image_source": None}],
            "now",
            None,
        )

    assert job.status == "done"
    assert create_mock.call_args.kwargs["settings"] == TIKTOK_DEFAULT_SETTINGS
