from unittest.mock import patch

import pytest

from app.models import Job, SocialPublish
from app.services import social_publish
from app.services.postiz import Integration
from app.services.social_publish import (
    TIKTOK_DEFAULT_SETTINGS,
    default_settings_for_platform,
    publish_one_platform,
    resolve_integrations,
    truncate_content_for_platform,
)


def test_publish_one_platform_parses_list_response(db):
    job = Job(job_type="episode_processing")
    db.add(job)
    db.commit()

    integrations = {"tiktok": Integration(id="int-1", platform="tiktok", name="My TikTok")}
    with patch(
        "app.services.social_publish.create_post",
        return_value=[{"postId": "abc123", "integration": "int-1"}],
    ):
        ok = publish_one_platform(
            db,
            job=job,
            base_url="https://postiz.example.com/api",
            api_key="key",
            integrations=integrations,
            platform="tiktok",
            content="hello world",
            media=None,
            post_type="now",
            date="2026-08-20T00:00:00.000Z",
            episode_id=1,
        )

    assert ok is True
    row = db.query(SocialPublish).one()
    assert row.status == "done"
    assert row.postiz_post_id == "abc123"


def test_publish_one_platform_media_list_passed_through_to_create_post(db):
    job = Job(job_type="episode_processing")
    db.add(job)
    db.commit()

    integrations = {"instagram": Integration(id="int-1", platform="instagram", name="My IG")}
    media_items = [{"id": "video-media"}, {"id": "image-media"}]
    with patch(
        "app.services.social_publish.create_post", return_value=[{"postId": "p1"}]
    ) as mock_create_post:
        publish_one_platform(
            db,
            job=job,
            base_url="https://postiz.example.com/api",
            api_key="key",
            integrations=integrations,
            platform="instagram",
            content="hello world",
            media=media_items,
            post_type="now",
            date="2026-08-20T00:00:00.000Z",
            episode_id=1,
        )
    assert mock_create_post.call_args.kwargs["media"] == media_items


def test_resolve_integrations_aliases_standalone_instagram(monkeypatch):
    standalone = Integration(id="int-1", platform="instagram-standalone", name="IG")
    monkeypatch.setattr(social_publish, "list_integrations", lambda *a, **k: [standalone])

    integrations = resolve_integrations("https://postiz.example.com/api", "key")

    assert integrations["instagram-standalone"] is standalone
    assert integrations["instagram"] is standalone


def test_resolve_integrations_prefers_real_instagram_over_standalone(monkeypatch):
    real = Integration(id="int-1", platform="instagram", name="IG")
    standalone = Integration(id="int-2", platform="instagram-standalone", name="IG Standalone")
    monkeypatch.setattr(social_publish, "list_integrations", lambda *a, **k: [real, standalone])

    integrations = resolve_integrations("https://postiz.example.com/api", "key")

    assert integrations["instagram"] is real


def test_publish_one_platform_sends_integrations_own_identifier_to_postiz(db):
    job = Job(job_type="episode_processing")
    db.add(job)
    db.commit()

    # Looked up by the logical "instagram" key, but the connected integration's real
    # identifier is "instagram-standalone" — Postiz's settings.__type must reflect that.
    standalone = Integration(id="int-1", platform="instagram-standalone", name="IG")
    integrations = {"instagram": standalone}
    with patch(
        "app.services.social_publish.create_post", return_value=[{"postId": "p1"}]
    ) as mock_create_post:
        publish_one_platform(
            db,
            job=job,
            base_url="https://postiz.example.com/api",
            api_key="key",
            integrations=integrations,
            platform="instagram",
            content="hello world",
            media=None,
            post_type="now",
            date="2026-08-20T00:00:00.000Z",
            settings={"post_type": "reel"},
            episode_id=1,
        )
    assert mock_create_post.call_args.kwargs["platform"] == "instagram-standalone"
    # The SocialPublish row should still record the logical platform, not the raw identifier.
    row = db.query(SocialPublish).one()
    assert row.platform == "instagram"


def test_publish_one_platform_forwards_settings_unchanged(db):
    job = Job(job_type="episode_processing")
    db.add(job)
    db.commit()

    integrations = {"tiktok": Integration(id="int-1", platform="tiktok", name="My TikTok")}
    with patch(
        "app.services.social_publish.create_post", return_value=[{"postId": "p1"}]
    ) as mock_create_post:
        publish_one_platform(
            db,
            job=job,
            base_url="https://postiz.example.com/api",
            api_key="key",
            integrations=integrations,
            platform="tiktok",
            content="hello world",
            media=None,
            post_type="now",
            date="2026-08-20T00:00:00.000Z",
            settings={"post_type": "reel"},
            episode_id=1,
        )
    assert mock_create_post.call_args.kwargs["settings"] == {"post_type": "reel"}


def test_publish_one_platform_truncates_outgoing_content_without_mutating_caller(db):
    job = Job(job_type="episode_processing")
    db.add(job)
    db.commit()

    integrations = {"x": Integration(id="int-1", platform="x", name="My X")}
    original = "word " * 100
    with patch(
        "app.services.social_publish.create_post", return_value=[{"postId": "p1"}]
    ) as mock_create_post:
        publish_one_platform(
            db,
            job=job,
            base_url="https://postiz.example.com/api",
            api_key="key",
            integrations=integrations,
            platform="x",
            content=original,
            media=None,
            post_type="now",
            date="2026-08-20T00:00:00.000Z",
            episode_id=1,
        )
    assert len(mock_create_post.call_args.kwargs["content"]) <= 280
    assert len(original) > 280  # sanity: the fixture text really did need truncating


@pytest.mark.parametrize(
    "platform,kwargs,expected",
    [
        ("tiktok", {}, TIKTOK_DEFAULT_SETTINGS),
        ("youtube", {"youtube_title": "My Video"}, {"title": "My Video", "type": "public"}),
        ("youtube", {}, {"title": "Untitled", "type": "public"}),
        ("instagram", {"instagram_post_type": "story"}, {"post_type": "story"}),
        ("instagram", {}, {"post_type": "post"}),
        # "reel" isn't a value Postiz's Instagram DTO accepts (only post/story) — an invalid
        # value should never reach the outgoing payload, it should fall back to "post".
        ("instagram", {"instagram_post_type": "reel"}, {"post_type": "post"}),
        ("x", {}, {"who_can_reply_post": "everyone"}),
        ("bluesky", {}, {}),
        ("threads", {}, {}),
        ("facebook", {}, {}),
    ],
)
def test_default_settings_for_platform(platform, kwargs, expected):
    assert default_settings_for_platform(platform, **kwargs) == expected


@pytest.mark.parametrize("platform", ["threads", "facebook", "tiktok", "youtube", "instagram"])
def test_truncate_content_for_platform_passthrough_when_no_cap(platform):
    content = "word " * 100
    assert truncate_content_for_platform(content, platform) == content


def test_truncate_content_for_platform_passthrough_under_limit():
    assert truncate_content_for_platform("short post", "x") == "short post"


def test_truncate_content_for_platform_drops_trailing_hashtags_first():
    content = "a" * 270 + " #one #two #three #four #five #six #seven #eight"
    result = truncate_content_for_platform(content, "x")
    # Hashtags are dropped from the end only until it fits — the hook body is never touched
    # and no ellipsis/word-boundary fallback is needed since dropping hashtags was enough.
    assert len(result) <= 280
    assert result.startswith("a" * 270)
    assert "#eight" not in result
    assert not result.endswith("…")


def test_truncate_content_for_platform_falls_back_to_word_boundary_ellipsis():
    content = "supercalifragilisticexpialidocious " * 20  # no hashtags to drop
    result = truncate_content_for_platform(content, "bluesky")
    assert len(result) <= 300
    assert result.endswith("…")
