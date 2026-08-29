from app.services import soundbite_regen


def _make_episode_with_soundbite(db, tmp_path, monkeypatch):
    from app.services import storage

    monkeypatch.setattr(storage.config, "media_dir", tmp_path)

    from app.models import Episode, GeneratedContent, Soundbite, Transcript, TranscriptSegment, VideoClip

    episode = Episode(title="Ep", original_filename="ep.mp3", file_path=str(tmp_path / "ep.mp3"), status="processed")
    db.add(episode)
    db.commit()
    db.refresh(episode)

    transcript = Transcript(episode_id=episode.id, full_text="someone elses guess", provider="local_whisper")
    db.add(transcript)
    db.flush()
    words = [
        {"word": w, "start_ms": i * 500, "end_ms": 500 + i * 500}
        for i, w in enumerate(["someone", "elses", "guess"])
    ]
    db.add(
        TranscriptSegment(transcript_id=transcript.id, index=0, start_ms=0, end_ms=1500, text="someone elses guess", words=words)
    )
    db.add(GeneratedContent(episode_id=episode.id, description="desc", titles=[{"text": "t", "score": 50}]))

    old_sb = Soundbite(episode_id=episode.id, quote="old quote", start_ms=0, end_ms=1000, order_index=0)
    db.add(old_sb)
    db.flush()
    db.add(VideoClip(soundbite_id=old_sb.id))
    db.commit()
    db.refresh(episode)
    return episode


def _make_job(db, episode_id):
    from app.models import Job

    job = Job(episode_id=episode_id, job_type="soundbite_regenerate", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


class _FakeProvider:
    def select_soundbites(self, transcript_text):
        from app.services.llm.base import SoundbiteCandidate

        return [SoundbiteCandidate(quote="someone elses guess")]

    def generate_clip_social(self, quote, episode_title):
        from app.services.llm.base import ClipSocial

        return ClipSocial(social_post="post", youtube_title="title")


class _FailingProvider:
    def select_soundbites(self, transcript_text):
        raise RuntimeError("boom")


def test_run_soundbite_regenerate_replaces_old_soundbites(db, tmp_path, monkeypatch):
    episode = _make_episode_with_soundbite(db, tmp_path, monkeypatch)
    old_soundbite_id = episode.soundbites[0].id
    job = _make_job(db, episode.id)

    monkeypatch.setattr(soundbite_regen, "get_llm_provider", lambda db: _FakeProvider())
    monkeypatch.setattr(soundbite_regen, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)

    soundbite_regen.run_soundbite_regenerate(job.id)

    assert job.status == "done"
    assert episode.status == "processed"  # unaffected by regeneration
    assert [sb.id for sb in episode.soundbites] != [old_soundbite_id]
    assert [sb.quote for sb in episode.soundbites] == ["someone elses guess"]
    # transcript and other generated content are untouched
    assert episode.transcript is not None
    assert episode.generated_content.description == "desc"


def test_run_soundbite_regenerate_failure_marks_job_only_and_keeps_old_soundbites(db, tmp_path, monkeypatch):
    episode = _make_episode_with_soundbite(db, tmp_path, monkeypatch)
    old_quote = episode.soundbites[0].quote
    job = _make_job(db, episode.id)

    monkeypatch.setattr(soundbite_regen, "get_llm_provider", lambda db: _FailingProvider())
    monkeypatch.setattr(soundbite_regen, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)

    soundbite_regen.run_soundbite_regenerate(job.id)

    assert job.status == "error"
    assert job.error_message
    assert episode.status == "processed"  # must not be flipped to "error"
    # a failed LLM call shouldn't have wiped the existing soundbites
    assert [sb.quote for sb in episode.soundbites] == [old_quote]
