from app.services import social_regen
from app.services.llm.base import SocialGroup


def _make_episode(db):
    from app.models import Episode, GeneratedContent, Transcript

    episode = Episode(title="Ep", original_filename="ep.mp3", file_path="/tmp/ep.mp3", status="processed")
    db.add(episode)
    db.commit()
    db.refresh(episode)
    db.add(Transcript(episode_id=episode.id, full_text="hello world", provider="local_whisper"))
    db.add(GeneratedContent(episode_id=episode.id, description="desc", social_posts=[]))
    db.commit()
    db.refresh(episode)
    return episode


def _make_job(db, episode_id):
    from app.models import Job

    job = Job(episode_id=episode_id, job_type="social_regenerate", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


class _FakeProvider:
    def generate_social_posts(self, transcript_text, description, tone="casual"):
        return [SocialGroup(platform="X", initial="X", color="#111", platform_key="x", posts=["p1", "p2", "p3", "p4"])]


class _FailingProvider:
    def generate_social_posts(self, transcript_text, description, tone="casual"):
        raise RuntimeError("boom")


def test_run_social_regenerate_success(db, monkeypatch):
    episode = _make_episode(db)
    job = _make_job(db, episode.id)
    monkeypatch.setattr(social_regen, "get_llm_provider", lambda db: _FakeProvider())
    # run_social_regenerate opens its own SessionLocal and closes it when done; point it at
    # this test's session but keep it open afterward so assertions below can still read it.
    monkeypatch.setattr(social_regen, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)

    social_regen.run_social_regenerate(job.id, tone="formal")

    assert job.status == "done"
    assert episode.generated_content.social_posts == [
        {"platform": "X", "initial": "X", "color": "#111", "platform_key": "x", "posts": ["p1", "p2", "p3", "p4"]}
    ]
    assert episode.status == "processed"  # unaffected by regeneration


def test_run_social_regenerate_failure_marks_job_only(db, monkeypatch):
    episode = _make_episode(db)
    job = _make_job(db, episode.id)
    monkeypatch.setattr(social_regen, "get_llm_provider", lambda db: _FailingProvider())
    monkeypatch.setattr(social_regen, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)

    social_regen.run_social_regenerate(job.id)

    assert job.status == "error"
    assert job.error_message
    assert episode.status == "processed"  # must not be flipped to "error"
