from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import now_utc
from app.services import stats_cache


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


def test_get_missing_key_returns_none(db):
    assert stats_cache.get(db, "podcast_index:feed") is None


def test_save_and_get_roundtrip(db):
    stats_cache.save(db, "podcast_index:feed", {"title": "My Show"})
    row = stats_cache.get(db, "podcast_index:feed")
    assert row.payload == {"title": "My Show"}
    assert row.ok is True
    assert row.error_message is None


def test_save_overwrites_existing_row(db):
    stats_cache.save(db, "podcast_index:feed", {"title": "Old"})
    stats_cache.save(db, "podcast_index:feed", {"title": "New"})
    row = stats_cache.get(db, "podcast_index:feed")
    assert row.payload == {"title": "New"}


def test_save_failure_keeps_last_good_payload_when_caller_preserves_it(db):
    stats_cache.save(db, "op3:show_downloads", {"total": 42})
    stats_cache.save(db, "op3:show_downloads", {"total": 42}, ok=False, error_message="timeout")
    row = stats_cache.get(db, "op3:show_downloads")
    assert row.payload == {"total": 42}
    assert row.ok is False
    assert row.error_message == "timeout"


def test_is_stale(db):
    row = stats_cache.save(db, "podcast_index:feed", {"title": "My Show"})
    assert stats_cache.is_stale(row, timedelta(hours=24)) is False
    row.fetched_at = now_utc() - timedelta(hours=25)
    assert stats_cache.is_stale(row, timedelta(hours=24)) is True
