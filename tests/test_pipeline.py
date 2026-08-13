from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.services import pipeline, storage


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    from app import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _make_failed_episode(db, tmp_path, monkeypatch):
    from app.models import Chapter, Episode, GeneratedContent, Soundbite, Transcript

    monkeypatch.setattr(storage.config, "media_dir", tmp_path)

    episode = Episode(title="Ep", original_filename="ep.mp3", file_path=str(tmp_path / "ep.mp3"), status="error")
    db.add(episode)
    db.commit()
    db.refresh(episode)

    db.add(Transcript(episode_id=episode.id, full_text="hello world", provider="local_whisper"))
    db.add(GeneratedContent(episode_id=episode.id, description="desc", titles=[{"text": "t", "score": 50}]))

    clip_path = storage.clips_dir(episode.id) / "1.mp3"
    clip_path.write_bytes(b"fake audio")
    db.add(
        Soundbite(
            episode_id=episode.id,
            quote="a quote",
            start_ms=0,
            end_ms=1000,
            clip_audio_path=str(clip_path),
        )
    )
    db.add(Chapter(episode_id=episode.id, index=0, title="Intro", start_ms=0))
    db.commit()
    db.refresh(episode)
    return episode


def test_reset_episode_for_retry_clears_rows_and_files(db, tmp_path, monkeypatch):
    episode = _make_failed_episode(db, tmp_path, monkeypatch)
    clips_dir = storage.clips_dir(episode.id)
    assert any(clips_dir.iterdir())

    pipeline.reset_episode_for_retry(db, episode)
    db.commit()

    assert episode.transcript is None
    assert episode.generated_content is None
    assert episode.soundbites == []
    assert episode.chapters == []
    assert not Path(clips_dir).exists()
    # the original uploaded audio file itself is untouched
    assert episode.file_path == str(tmp_path / "ep.mp3")


def test_reset_episode_for_retry_is_a_noop_on_a_fresh_episode(db, tmp_path, monkeypatch):
    from app.models import Episode

    monkeypatch.setattr(storage.config, "media_dir", tmp_path)
    episode = Episode(title="", original_filename="ep.mp3", file_path=str(tmp_path / "ep.mp3"), status="draft")
    db.add(episode)
    db.commit()
    db.refresh(episode)

    pipeline.reset_episode_for_retry(db, episode)
    db.commit()

    assert episode.transcript is None
    assert episode.generated_content is None


class _FakeTranscriptionProvider:
    def transcribe(self, audio_path):
        from app.services.transcription.base import TranscriptResult, TranscriptSegmentResult

        return TranscriptResult(
            segments=[TranscriptSegmentResult(index=0, start_ms=0, end_ms=1000, text="hello world")],
            language="en",
            duration_seconds=1.0,
        )


class _FakeLLMProvider:
    def generate_titles(self, transcript_text):
        from app.services.llm.base import TitleCandidate

        return [TitleCandidate(text="A great title", score=90)]

    def generate_description_and_keywords(self, transcript_text):
        raise AssertionError("description step should have been skipped")

    def generate_social_posts(self, transcript_text, description, tone="casual"):
        raise AssertionError("social step should have been skipped")

    def select_soundbites(self, transcript_text):
        raise AssertionError("soundbites step should have been skipped")

    def generate_chapters(self, transcript_text):
        raise AssertionError("chapters step should have been skipped")


def test_run_episode_processing_only_runs_selected_steps(db, tmp_path, monkeypatch):
    from app.models import Episode, Job

    monkeypatch.setattr(storage.config, "media_dir", tmp_path)
    episode = Episode(title="", original_filename="ep.mp3", file_path=str(tmp_path / "ep.mp3"), status="processing")
    db.add(episode)
    db.commit()
    db.refresh(episode)

    job = Job(episode_id=episode.id, job_type="episode_processing", status="pending", steps=["transcribing", "titles"])
    db.add(job)
    db.commit()
    db.refresh(job)

    monkeypatch.setattr(pipeline, "get_transcription_provider", lambda db: _FakeTranscriptionProvider())
    monkeypatch.setattr(pipeline, "get_llm_provider", lambda db: _FakeLLMProvider())
    monkeypatch.setattr(pipeline, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)

    pipeline.run_episode_processing(job.id)

    assert job.status == "done"
    assert episode.status == "processed"
    assert episode.transcript is not None
    assert episode.generated_content.titles == [{"text": "A great title", "score": 90}]
    assert episode.generated_content.description == ""
    assert episode.generated_content.social_posts == []
    assert episode.soundbites == []
    assert episode.chapters == []
