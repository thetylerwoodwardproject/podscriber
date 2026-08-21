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

    # social_publishes shipped in two steps within the same unreleased feature: first with
    # video_clip_id NOT NULL and no episode_id/job_id, then widened to also support
    # episode-level publishes. create_all() never alters an existing table, so an install that
    # already created the table under the old shape would keep failing on "no such column:
    # social_publishes.episode_id" (and later, a NOT NULL violation on video_clip_id) forever.
    # The table had no real usage under the old shape, so drop-and-let-create_all-rebuild is
    # safe here — this is a one-time reset, not a pattern to repeat for tables with real data.
    _reset_table_if_missing_column("social_publishes", "episode_id")
    _rename_table_if_unique_column("video_clips", "soundbite_id", "video_clips_pre_multi")

    Base.metadata.create_all(bind=engine)
    _add_column_if_missing("feed_episode_suggestions", "suggested_keywords", "JSON DEFAULT '[]'")
    _add_column_if_missing("video_clips", "download_filename", "VARCHAR")
    _add_column_if_missing("video_clips", "waveform_offset_y", "INTEGER DEFAULT 0")
    _add_column_if_missing("episodes", "source", "VARCHAR DEFAULT 'upload'")
    _add_column_if_missing("feed_episode_suggestions", "episode_id", "INTEGER REFERENCES episodes(id)")
    _add_column_if_missing("feed_episode_suggestions", "used_transcript", "BOOLEAN DEFAULT 0")
    _add_column_if_missing("jobs", "steps", "JSON")
    _add_column_if_missing("jobs", "generated_script_id", "INTEGER REFERENCES generated_scripts(id)")
    _add_column_if_missing("video_clips", "social_post", "TEXT DEFAULT ''")
    _add_column_if_missing("video_clips", "youtube_title", "VARCHAR DEFAULT ''")
    _drop_column_if_exists("video_clips", "caption")
    _add_column_if_missing("jobs", "video_clip_id", "INTEGER REFERENCES video_clips(id)")
    _copy_rows_and_drop("video_clips_pre_multi", "video_clips")


def _reset_table_if_missing_column(table: str, required_column: str) -> None:
    with engine.begin() as conn:
        tables = {
            row[0] for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        }
        if table not in tables:
            return
        existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        if required_column not in existing:
            conn.exec_driver_sql(f"DROP TABLE {table}")


def _rename_table_if_unique_column(table: str, column: str, rename_to: str) -> None:
    # video_clips.soundbite_id shipped UNIQUE (one clip per soundbite); the "duplicate to a
    # new video" feature needs several clips per soundbite. SQLite's ALTER TABLE can't drop a
    # column constraint, so rename the old table out of the way here and let create_all()
    # (called right after) build the new, non-unique-constrained table under that name;
    # _copy_rows_and_drop then moves the existing rows across and removes the renamed table.
    with engine.begin() as conn:
        tables = {row[0] for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))}
        if table not in tables:
            return
        for _seq, index_name, is_unique, *_rest in conn.exec_driver_sql(f"PRAGMA index_list({table})").fetchall():
            if not is_unique:
                continue
            cols = [row[2] for row in conn.exec_driver_sql(f"PRAGMA index_info({index_name})")]
            if cols == [column]:
                conn.exec_driver_sql(f"ALTER TABLE {table} RENAME TO {rename_to}")
                return


def _copy_rows_and_drop(old_table: str, new_table: str) -> None:
    with engine.begin() as conn:
        tables = {row[0] for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (old_table,))}
        if old_table not in tables:
            return
        columns = [row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({old_table})")]
        col_list = ", ".join(columns)
        conn.exec_driver_sql(f"INSERT INTO {new_table} ({col_list}) SELECT {col_list} FROM {old_table}")
        conn.exec_driver_sql(f"DROP TABLE {old_table}")


def _add_column_if_missing(table: str, column: str, ddl_type: str) -> None:
    # create_all() only creates missing tables, it never alters existing ones — so a
    # newly added column needs an explicit ALTER TABLE for installs with a pre-existing db file.
    with engine.begin() as conn:
        existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


def _drop_column_if_exists(table: str, column: str) -> None:
    with engine.begin() as conn:
        existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        if column in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN {column}")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
