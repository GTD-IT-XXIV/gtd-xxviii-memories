import sqlite3
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

engine = create_engine(f"sqlite:///{settings.db_path}", future=True)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# Columns added to app/db/models.py (and schema.sql, for brand-new DBs) to support the
# Postgres/R2 multi-machine batch scan. CREATE TABLE IF NOT EXISTS in schema.sql only
# affects databases that don't exist yet - an already-existing local db.sqlite3 (e.g.
# a dev's current working DB) needs these columns ADDed explicitly, or SQLAlchemy
# reads/writes against the new model attributes will fail with "no such column". All
# are nullable and unused by local dev, so backfilling them is a no-op for existing rows.
_NEW_NULLABLE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "photos": [("r2_key", "TEXT"), ("r2_thumbnail_key", "TEXT"), ("day", "INTEGER")],
    "clusters": [
        ("r2_thumbnail_key", "TEXT"),
        ("og", "TEXT"),
        ("deferred_to_others", "BOOLEAN NOT NULL DEFAULT 0"),
        ("suggested_cluster_id", "INTEGER REFERENCES clusters(id)"),
        ("suggested_similarity", "REAL"),
    ],
    "faces": [("r2_thumbnail_key", "TEXT")],
}


def _migrate_add_missing_columns(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    for table, columns in _NEW_NULLABLE_COLUMNS.items():
        existing = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
        for col_name, col_type in columns:
            if col_name not in existing:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
    # Must run after the ALTERs above, not from schema.sql's executescript - an index
    # on a column that schema.sql's CREATE TABLE IF NOT EXISTS didn't actually create
    # (because the table already existed from before that column was added) would
    # fail immediately if created any earlier than this.
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_photos_day ON photos(day)")
    conn.commit()


def init_db() -> None:
    settings.ensure_dirs()
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = sqlite3.connect(settings.db_path)
    try:
        conn.executescript(schema_sql)
        conn.commit()
        _migrate_add_missing_columns(conn)
    finally:
        conn.close()
