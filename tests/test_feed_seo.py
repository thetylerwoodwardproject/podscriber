import pytest
from sqlalchemy import select

from app.services import feed_seo
from app.services.llm.base import SeoSuggestion


def _make_job(db):
    from app.models import Job

    job = Job(job_type="feed_seo_suggestions", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


class _StubProvider:
    def generate_seo_suggestion(self, title, description, transcript_text=None):
        return SeoSuggestion(title=f"Better: {title}", description=f"Better: {description}")


class _PerTitleFailingProvider:
    def __init__(self, fail_titles):
        self.fail_titles = fail_titles

    def generate_seo_suggestion(self, title, description, transcript_text=None):
        if title in self.fail_titles:
            raise RuntimeError("boom")
        return SeoSuggestion(title=f"Better: {title}", description=f"Better: {description}")


# --- episode_key ---


def test_episode_key_uses_guid_when_present():
    assert feed_seo.episode_key("guid-123", "Title", 1700000000) == "guid-123"


def test_episode_key_strips_guid():
    assert feed_seo.episode_key("  guid-123  ", "Title", 1700000000) == "guid-123"


def test_episode_key_falls_back_to_hash_when_guid_blank():
    key = feed_seo.episode_key("", "Title", 1700000000)
    assert key.startswith("fallback:")


def test_episode_key_fallback_is_deterministic():
    k1 = feed_seo.episode_key(None, "Title", 1700000000)
    k2 = feed_seo.episode_key(None, "Title", 1700000000)
    assert k1 == k2


def test_episode_key_fallback_differs_per_title_and_pub_date():
    k1 = feed_seo.episode_key(None, "Title A", 1700000000)
    k2 = feed_seo.episode_key(None, "Title B", 1700000000)
    k3 = feed_seo.episode_key(None, "Title A", 1800000000)
    assert len({k1, k2, k3}) == 3


# --- generate_suggestion_for_episode ---


def test_generate_suggestion_for_episode_inserts_then_updates_in_place(db):
    from app.models import FeedEpisodeSuggestion

    row1 = feed_seo.generate_suggestion_for_episode(db, _StubProvider(), "k1", "Title", "Desc")
    assert row1.suggested_title == "Better: Title"
    assert len(db.execute(select(FeedEpisodeSuggestion)).scalars().all()) == 1

    row2 = feed_seo.generate_suggestion_for_episode(db, _StubProvider(), "k1", "New Title", "New Desc")
    assert row2.id == row1.id
    assert row2.suggested_title == "Better: New Title"
    assert len(db.execute(select(FeedEpisodeSuggestion)).scalars().all()) == 1


def test_generate_suggestion_for_episode_marks_used_transcript(db):
    row = feed_seo.generate_suggestion_for_episode(
        db, _StubProvider(), "k1", "Title", "Desc", transcript_text="full transcript text"
    )
    assert row.used_transcript is True

    row_no_transcript = feed_seo.generate_suggestion_for_episode(db, _StubProvider(), "k2", "Title", "Desc")
    assert row_no_transcript.used_transcript is False


# --- run_feed_seo_bulk ---


def _episodes(*titles):
    return {
        "state": "ok",
        "episodes": [
            {"title": t, "description": f"{t} desc", "pub_date": i, "guid": f"g{i}"}
            for i, t in enumerate(titles)
        ],
    }


def test_run_feed_seo_bulk_success(db, monkeypatch):
    from app.models import FeedEpisodeSuggestion

    job = _make_job(db)
    monkeypatch.setattr(feed_seo, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(feed_seo, "get_llm_provider", lambda db: _StubProvider())
    monkeypatch.setattr(feed_seo, "load_feed_episodes", lambda db, s, force: _episodes("A", "B", "C"))

    feed_seo.run_feed_seo_bulk(job.id)

    db.refresh(job)
    assert job.status == "done"
    assert job.progress_pct == 100
    assert job.error_message is None
    rows = db.execute(select(FeedEpisodeSuggestion)).scalars().all()
    assert len(rows) == 3
    assert {r.suggested_title for r in rows} == {"Better: A", "Better: B", "Better: C"}


def test_run_feed_seo_bulk_continues_after_single_episode_failure(db, monkeypatch):
    from app.models import FeedEpisodeSuggestion

    job = _make_job(db)
    monkeypatch.setattr(feed_seo, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(feed_seo, "get_llm_provider", lambda db: _PerTitleFailingProvider({"B"}))
    monkeypatch.setattr(feed_seo, "load_feed_episodes", lambda db, s, force: _episodes("A", "B", "C"))

    feed_seo.run_feed_seo_bulk(job.id)

    db.refresh(job)
    assert job.status == "done"  # a single episode failing must not abort the whole batch
    assert job.error_message == "1 of 3 episode(s) failed"
    rows = db.execute(select(FeedEpisodeSuggestion)).scalars().all()
    assert {r.suggested_title for r in rows} == {"Better: A", "Better: C"}


def test_run_feed_seo_bulk_skips_episodes_already_suggested(db, monkeypatch):
    from app.models import FeedEpisodeSuggestion

    existing = FeedEpisodeSuggestion(
        episode_key="g0",
        original_title="A",
        original_description="A desc",
        suggested_title="Already suggested",
        suggested_description="Already suggested desc",
    )
    db.add(existing)
    db.commit()

    job = _make_job(db)
    monkeypatch.setattr(feed_seo, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(feed_seo, "get_llm_provider", lambda db: _StubProvider())
    monkeypatch.setattr(feed_seo, "load_feed_episodes", lambda db, s, force: _episodes("A", "B"))

    feed_seo.run_feed_seo_bulk(job.id)

    db.refresh(job)
    assert job.status == "done"
    rows = {r.episode_key: r for r in db.execute(select(FeedEpisodeSuggestion)).scalars().all()}
    assert rows["g0"].suggested_title == "Already suggested"  # untouched, not regenerated
    assert rows["g1"].suggested_title == "Better: B"


# --- run_feed_episode_deep_suggest ---


class _StubTranscriptionProvider:
    def __init__(self, audio_path_holder):
        self.audio_path_holder = audio_path_holder

    def transcribe(self, audio_path):
        from app.services.transcription.base import TranscriptResult, TranscriptSegmentResult

        self.audio_path_holder.append(audio_path)
        return TranscriptResult(
            segments=[TranscriptSegmentResult(index=0, start_ms=0, end_ms=1000, text="hello world")],
            language="en",
            duration_seconds=1.0,
        )


def _make_deep_episode_and_job(db, tmp_path, enclosure_url="https://example.com/ep.mp3"):
    from app.models import Episode, FeedEpisodeSuggestion, Job

    episode = Episode(title="A", original_filename="A", file_path="", source="feed", status="draft")
    db.add(episode)
    db.flush()
    row = FeedEpisodeSuggestion(episode_key="g0", original_title="A", original_description="A desc", episode_id=episode.id)
    db.add(row)
    job = Job(episode_id=episode.id, job_type="feed_episode_deep_suggest", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    db.refresh(episode)
    return episode, job


def test_run_feed_episode_deep_suggest_downloads_transcribes_and_suggests(db, monkeypatch, tmp_path):
    episode, job = _make_deep_episode_and_job(db, tmp_path)
    audio_file = tmp_path / "audio.mp3"
    audio_file.write_bytes(b"fake audio")
    audio_paths = []

    monkeypatch.setattr(feed_seo, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(
        feed_seo,
        "load_feed_episodes",
        lambda db, s, force: _episodes_with_enclosure(("A", "https://example.com/ep.mp3")),
    )
    monkeypatch.setattr(feed_seo, "download_audio", lambda url, episode_id, max_bytes: audio_file)
    monkeypatch.setattr(feed_seo, "get_transcription_provider", lambda db: _StubTranscriptionProvider(audio_paths))
    monkeypatch.setattr(feed_seo, "get_llm_provider", lambda db: _StubProvider())

    feed_seo.run_feed_episode_deep_suggest(job.id)

    db.refresh(job)
    assert job.status == "done"
    assert job.progress_pct == 100
    assert audio_paths == [audio_file]

    db.refresh(episode)
    assert episode.status == "processed"
    assert episode.transcript.full_text == "hello world"

    from app.models import FeedEpisodeSuggestion

    row = db.execute(select(FeedEpisodeSuggestion).where(FeedEpisodeSuggestion.episode_id == episode.id)).scalar_one()
    assert row.used_transcript is True
    assert row.suggested_title == "Better: A"


def test_run_feed_episode_deep_suggest_skips_download_when_transcript_exists(db, monkeypatch, tmp_path):
    from app.models import Transcript

    episode, job = _make_deep_episode_and_job(db, tmp_path)
    db.add(Transcript(episode_id=episode.id, full_text="already transcribed", provider="LocalWhisperProvider"))
    db.commit()

    called = []
    monkeypatch.setattr(feed_seo, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(
        feed_seo,
        "load_feed_episodes",
        lambda db, s, force: _episodes_with_enclosure(("A", "https://example.com/ep.mp3")),
    )
    monkeypatch.setattr(feed_seo, "download_audio", lambda *a, **k: called.append(1))
    monkeypatch.setattr(feed_seo, "get_llm_provider", lambda db: _StubProvider())

    feed_seo.run_feed_episode_deep_suggest(job.id)

    db.refresh(job)
    assert job.status == "done"
    assert called == []  # download must not run when a transcript already exists


def test_run_feed_episode_deep_suggest_errors_without_enclosure_url(db, monkeypatch, tmp_path):
    episode, job = _make_deep_episode_and_job(db, tmp_path)
    monkeypatch.setattr(feed_seo, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(
        feed_seo, "load_feed_episodes", lambda db, s, force: _episodes_with_enclosure(("A", None))
    )

    with pytest.raises(RuntimeError, match="no audio URL"):
        feed_seo.run_feed_episode_deep_suggest(job.id)


def _episodes_with_enclosure(*title_url_pairs):
    return {
        "state": "ok",
        "episodes": [
            {"title": t, "description": f"{t} desc", "pub_date": 0, "guid": "g0", "enclosure_url": u}
            for t, u in title_url_pairs
        ],
    }
