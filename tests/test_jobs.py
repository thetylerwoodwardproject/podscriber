from app.services import jobs


def test_episode_processing_uses_dedicated_single_worker_executor():
    assert jobs._episode_executor._max_workers == 1


def test_submit_episode_processing_submits_to_episode_executor(monkeypatch):
    submitted_to = {}

    def fake_submit(self, fn, *args):
        submitted_to["executor"] = self
        submitted_to["job_id"] = args[0]

    monkeypatch.setattr(type(jobs._episode_executor), "submit", fake_submit)

    jobs.submit_episode_processing(123)

    assert submitted_to["executor"] is jobs._episode_executor
    assert submitted_to["job_id"] == 123


def test_submit_video_export_still_uses_shared_executor(monkeypatch):
    submitted_to = {}

    def fake_submit(self, fn, *args):
        submitted_to["executor"] = self

    monkeypatch.setattr(type(jobs._executor), "submit", fake_submit)

    jobs.submit_video_export(456)

    assert submitted_to["executor"] is jobs._executor
