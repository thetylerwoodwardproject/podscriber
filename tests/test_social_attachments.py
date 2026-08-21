import pytest
from PIL import Image

from app.services.social_attachments import (
    decode_image_dimensions,
    episode_video_options,
    instagram_image_ok,
    resolve_image_attachment,
    resolve_video_source,
    validate_instagram_requirement,
)


@pytest.mark.parametrize(
    "width,height,expected",
    [
        (800, 1010, False),  # ratio 0.792 — just under 4:5
        (800, 1000, True),  # ratio 0.8 — exactly 4:5
        (1910, 1000, True),  # ratio 1.91 — exactly 1.91:1
        (1920, 1000, False),  # ratio 1.92 — just over
        (None, 1000, False),
        (800, 0, False),
    ],
)
def test_instagram_image_ok_boundaries(width, height, expected):
    assert instagram_image_ok(width, height) is expected


def test_decode_image_dimensions_valid_image(tmp_path):
    path = tmp_path / "pic.png"
    Image.new("RGB", (400, 300), color="red").save(path)
    assert decode_image_dimensions(str(path)) == (400, 300)


def test_decode_image_dimensions_rejects_garbage_bytes(tmp_path):
    path = tmp_path / "pic.png"
    path.write_bytes(b"not an image")
    with pytest.raises(ValueError):
        decode_image_dimensions(str(path))


def _make_episode(db, with_video=False):
    from app.models import Episode, EpisodeVideo

    episode = Episode(title="Ep", original_filename="ep.mp3", file_path="/tmp/ep.mp3", status="processed")
    db.add(episode)
    db.commit()
    db.refresh(episode)
    if with_video:
        db.add(EpisodeVideo(episode_id=episode.id, exported_video_path="/media/episode.mp4"))
        db.commit()
        db.refresh(episode)
    return episode


def _make_soundbite_with_clip(db, episode_id, exported=True):
    from app.models import Soundbite, VideoClip

    sb = Soundbite(episode_id=episode_id, quote="a great quote here", start_ms=0, end_ms=1000)
    db.add(sb)
    db.commit()
    db.refresh(sb)
    clip = VideoClip(soundbite_id=sb.id, exported_video_path="/media/clip.mp4" if exported else None)
    db.add(clip)
    db.commit()
    db.refresh(clip)
    return clip


def test_resolve_video_source_episode_video(db):
    episode = _make_episode(db, with_video=True)
    path, err = resolve_video_source(db, episode, {"type": "episode_video"})
    assert err is None
    assert path == "/media/episode.mp4"


def test_resolve_video_source_episode_video_missing(db):
    episode = _make_episode(db, with_video=False)
    path, err = resolve_video_source(db, episode, {"type": "episode_video"})
    assert path is None
    assert "no exported full video" in err


def test_resolve_video_source_clip(db):
    episode = _make_episode(db)
    clip = _make_soundbite_with_clip(db, episode.id)
    db.refresh(episode)
    path, err = resolve_video_source(db, episode, {"type": "clip", "clip_id": clip.id})
    assert err is None
    assert path == "/media/clip.mp4"


def test_resolve_video_source_clip_no_export(db):
    episode = _make_episode(db)
    clip = _make_soundbite_with_clip(db, episode.id, exported=False)
    path, err = resolve_video_source(db, episode, {"type": "clip", "clip_id": clip.id})
    assert path is None
    assert "no exported video" in err


def test_resolve_video_source_upload(db):
    from app.models import SocialAttachment

    episode = _make_episode(db)
    attachment = SocialAttachment(episode_id=episode.id, kind="video", file_path="/media/upload.mp4")
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    path, err = resolve_video_source(db, episode, {"type": "upload", "attachment_id": attachment.id})
    assert err is None
    assert path == "/media/upload.mp4"


def test_resolve_video_source_unknown_type(db):
    episode = _make_episode(db)
    path, err = resolve_video_source(db, episode, {"type": "bogus"})
    assert path is None
    assert "Unrecognized" in err


def test_resolve_video_source_none_returns_none_none(db):
    episode = _make_episode(db)
    assert resolve_video_source(db, episode, None) == (None, None)


def test_resolve_image_attachment_rejects_cross_episode_id(db):
    from app.models import SocialAttachment

    episode_a = _make_episode(db)
    episode_b = _make_episode(db)
    attachment = SocialAttachment(episode_id=episode_a.id, kind="image", file_path="/media/img.png", width=800, height=800)
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    result, err = resolve_image_attachment(db, episode_b, {"type": "upload", "attachment_id": attachment.id})
    assert result is None
    assert "not found" in err


def test_resolve_image_attachment_success(db):
    from app.models import SocialAttachment

    episode = _make_episode(db)
    attachment = SocialAttachment(episode_id=episode.id, kind="image", file_path="/media/img.png", width=800, height=800)
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    result, err = resolve_image_attachment(db, episode, {"type": "upload", "attachment_id": attachment.id})
    assert err is None
    assert result.id == attachment.id


def test_validate_instagram_requirement_not_applicable_without_instagram():
    assert validate_instagram_requirement(["tiktok"], None) is None


def test_validate_instagram_requirement_blocks_missing_image_and_video():
    err = validate_instagram_requirement(["instagram"], None)
    assert "requires a video or an image" in err


def test_validate_instagram_requirement_passes_with_video_only():
    assert validate_instagram_requirement(["instagram"], None, has_video=True) is None


def test_validate_instagram_requirement_still_validates_image_ratio_when_video_present():
    from app.models import SocialAttachment

    attachment = SocialAttachment(episode_id=1, kind="image", file_path="x", width=2000, height=800)
    err = validate_instagram_requirement(["instagram"], attachment, has_video=True)
    assert "doesn't fit Instagram's accepted aspect-ratio range" in err


def test_validate_instagram_requirement_blocks_bad_ratio():
    from app.models import SocialAttachment

    attachment = SocialAttachment(episode_id=1, kind="image", file_path="x", width=2000, height=800)
    err = validate_instagram_requirement(["instagram"], attachment)
    assert "doesn't fit Instagram's accepted aspect-ratio range" in err


def test_validate_instagram_requirement_passes_good_ratio():
    from app.models import SocialAttachment

    attachment = SocialAttachment(episode_id=1, kind="image", file_path="x", width=1080, height=1080)
    assert validate_instagram_requirement(["instagram"], attachment) is None


def test_episode_video_options_lists_full_video_and_exported_clips_only(db):
    episode = _make_episode(db, with_video=True)
    _make_soundbite_with_clip(db, episode.id, exported=True)
    _make_soundbite_with_clip(db, episode.id, exported=False)
    db.refresh(episode)

    options = episode_video_options(episode)
    values = [o["value"] for o in options]
    assert "episode_video" in values
    assert sum(1 for v in values if v.startswith("clip:")) == 1


def test_episode_video_options_labels_multiple_exported_variants(db):
    from app.models import Soundbite, VideoClip

    episode = _make_episode(db)
    sb = Soundbite(episode_id=episode.id, quote="a great quote here", start_ms=0, end_ms=1000)
    db.add(sb)
    db.commit()
    db.refresh(sb)
    db.add(VideoClip(soundbite_id=sb.id, exported_video_path="/media/clip-1.mp4"))
    db.add(VideoClip(soundbite_id=sb.id, exported_video_path="/media/clip-2.mp4"))
    db.commit()
    db.refresh(episode)

    options = episode_video_options(episode)
    clip_options = [o for o in options if o["value"].startswith("clip:")]
    assert len(clip_options) == 2
    assert clip_options[0]["label"].endswith("(v1)")
    assert clip_options[1]["label"].endswith("(v2)")
