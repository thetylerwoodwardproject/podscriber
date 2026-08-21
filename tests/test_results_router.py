import asyncio
import io

import pytest
from PIL import Image
from sqlalchemy import select

from app.config import config
from app.routers import results as results_router


def _make_episode(db):
    from app.models import Chapter, Episode, GeneratedContent, Job, Soundbite, Transcript

    episode = Episode(title="Ep", original_filename="ep.mp3", file_path="/tmp/ep.mp3", status="processed")
    db.add(episode)
    db.commit()
    db.refresh(episode)
    db.add(Transcript(episode_id=episode.id, full_text="hello world", provider="local_whisper"))
    db.add(GeneratedContent(episode_id=episode.id, description="desc"))
    db.add(Soundbite(episode_id=episode.id, quote="q", start_ms=0, end_ms=1000))
    db.add(Chapter(episode_id=episode.id, index=0, title="Intro", start_ms=0))
    db.add(Job(episode_id=episode.id, job_type="episode_processing", status="done"))
    db.commit()
    db.refresh(episode)
    return episode


def test_delete_episode_removes_row_and_children(db):
    from app.models import Chapter, Episode, GeneratedContent, Job, Soundbite, Transcript

    episode = _make_episode(db)
    episode_id = episode.id

    results_router.delete_episode(episode_id, db)

    assert db.get(Episode, episode_id) is None
    assert db.execute(select(Transcript).where(Transcript.episode_id == episode_id)).first() is None
    assert db.execute(select(GeneratedContent).where(GeneratedContent.episode_id == episode_id)).first() is None
    assert db.execute(select(Soundbite).where(Soundbite.episode_id == episode_id)).first() is None
    assert db.execute(select(Chapter).where(Chapter.episode_id == episode_id)).first() is None
    assert db.execute(select(Job).where(Job.episode_id == episode_id)).first() is None


def test_delete_episode_removes_media_dir(db, tmp_path, monkeypatch):
    monkeypatch.setattr(type(config), "uploads_dir", property(lambda self: tmp_path))
    episode = _make_episode(db)
    episode_dir = tmp_path / str(episode.id)
    episode_dir.mkdir()
    (episode_dir / "original.mp3").write_bytes(b"fake audio")

    results_router.delete_episode(episode.id, db)

    assert not episode_dir.exists()


def test_delete_episode_404_for_unknown_id(db):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        results_router.delete_episode(999, db)
    assert exc_info.value.status_code == 404


class _FakeRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


class _FakeUploadFile:
    def __init__(self, filename, content):
        self.filename = filename
        self._content = content

    async def read(self):
        return self._content


def test_upload_social_attachment_valid_image_records_dimensions(db, tmp_path, monkeypatch):
    from app.models import SocialAttachment

    monkeypatch.setattr(type(config), "uploads_dir", property(lambda self: tmp_path))
    episode = _make_episode(db)
    buf = io.BytesIO()
    Image.new("RGB", (1080, 1080), color="blue").save(buf, format="PNG")

    result = asyncio.run(
        results_router.upload_social_attachment(
            episode.id, _FakeUploadFile("pic.png", buf.getvalue()), kind="image", db=db
        )
    )

    assert result["ok"] is True
    assert result["attachment"]["width"] == 1080
    assert result["attachment"]["height"] == 1080
    assert result["attachment"]["instagram_ok"] is True
    row = db.query(SocialAttachment).one()
    assert row.kind == "image"
    assert row.width == 1080


def test_upload_social_attachment_rejects_undecodable_image_and_deletes_file(db, tmp_path, monkeypatch):
    from app.models import SocialAttachment

    monkeypatch.setattr(type(config), "uploads_dir", property(lambda self: tmp_path))
    episode = _make_episode(db)

    result = asyncio.run(
        results_router.upload_social_attachment(
            episode.id, _FakeUploadFile("pic.jpg", b"not an image"), kind="image", db=db
        )
    )

    assert result["ok"] is False
    assert db.query(SocialAttachment).count() == 0
    social_dir = tmp_path / str(episode.id) / "social"
    assert not any(social_dir.iterdir()) if social_dir.exists() else True


def test_upload_social_attachment_rejects_bad_extension(db, tmp_path, monkeypatch):
    monkeypatch.setattr(type(config), "uploads_dir", property(lambda self: tmp_path))
    episode = _make_episode(db)

    result = asyncio.run(
        results_router.upload_social_attachment(
            episode.id, _FakeUploadFile("notes.txt", b"hello"), kind="image", db=db
        )
    )

    assert result["ok"] is False
    assert "Unsupported file type" in result["error"]


def test_publish_social_posts_returns_ok_false_for_instagram_without_image_and_creates_no_job(db):
    from app.models import Job

    episode = _make_episode(db)
    before = db.query(Job).count()

    result = asyncio.run(
        results_router.publish_social_posts(
            episode.id,
            _FakeRequest({"selections": [{"group_index": 0, "post_index": 0, "platform": "instagram"}], "mode": "now"}),
            db,
        )
    )

    assert result["ok"] is False
    assert "requires a video or an image" in result["error"]
    assert db.query(Job).count() == before
