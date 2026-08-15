import pytest
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
