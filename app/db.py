from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import config

# check_same_thread=False: background job threads and the request-handling thread each
# open their own Session, but share the underlying sqlite3 module-level thread-safety.
# WAL mode + a busy timeout let the background pipeline write while request handlers
# and SSE polling loops read, instead of hitting "database is locked" under the default
# rollback-journal mode's more restrictive locking.
# A default pool of 5 + 10 overflow is easy to exhaust here: every open SSE status-stream
# tab (processing, social regen, deep-suggest, script generation) briefly checks out a
# connection on each poll tick, and several can land in the same instant when multiple
# streams are polling in lockstep. SQLite/WAL has no trouble serving many short-lived
# connections, so give the pool generous headroom rather than let pollers queue for one.
engine = create_engine(
    f"sqlite:///{config.db_path}",
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_size=20,
    max_overflow=20,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from app import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=engine)
    _add_column_if_missing("feed_episode_suggestions", "suggested_keywords", "JSON DEFAULT '[]'")
    _add_column_if_missing("video_clips", "download_filename", "VARCHAR")
    _add_column_if_missing("video_clips", "waveform_offset_y", "INTEGER DEFAULT 0")
    _add_column_if_missing("episodes", "source", "VARCHAR DEFAULT 'upload'")
    _add_column_if_missing("feed_episode_suggestions", "episode_id", "INTEGER REFERENCES episodes(id)")
    _add_column_if_missing("feed_episode_suggestions", "used_transcript", "BOOLEAN DEFAULT 0")
    _add_column_if_missing("jobs", "steps", "JSON")
    _add_column_if_missing("jobs", "generated_script_id", "INTEGER REFERENCES generated_scripts(id)")


def _add_column_if_missing(table: str, column: str, ddl_type: str) -> None:
    # create_all() only creates missing tables, it never alters existing ones — so a
    # newly added column needs an explicit ALTER TABLE for installs with a pre-existing db file.
    with engine.begin() as conn:
        existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
