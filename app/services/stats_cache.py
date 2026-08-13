from datetime import UTC, timedelta

from sqlalchemy.orm import Session

from app.models import StatsCache, now_utc


def get(db: Session, key: str) -> StatsCache | None:
    return db.get(StatsCache, key)


def is_stale(row: StatsCache, max_age: timedelta) -> bool:
    # SQLite has no timezone type, so a DateTime column round-tripped through commit
    # (expire_on_commit=True) comes back naive even though now_utc() stays aware.
    fetched_at = row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=UTC)
    return now_utc() - fetched_at > max_age


def save(db: Session, key: str, payload: dict, ok: bool = True, error_message: str | None = None) -> StatsCache:
    row = db.get(StatsCache, key)
    if row is None:
        row = StatsCache(key=key)
        db.add(row)
    row.payload = payload
    row.fetched_at = now_utc()
    row.ok = ok
    row.error_message = error_message
    db.commit()
    return row
