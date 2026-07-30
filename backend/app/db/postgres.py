"""Postgres engine/session-factory builder for the multi-machine batch scan
(app/scanning/batch_pipeline.py, driven by scripts/run_batch_scan_cli.py).

Deliberately separate from the module-level `engine`/`SessionLocal` in
app/db/database.py, which stay wired to local SQLite for the FastAPI app and the
other local CLI scripts (scripts/run_scan_cli.py, scripts/run_reference_import_cli.py)
- nothing in this module changes that local-dev path.
"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base

# Columns added to app/db/models.py after tables may already exist in a shared Neon
# DB - create_all() only creates missing tables, it never ALTERs existing ones, so
# these need adding explicitly (idempotent). Mirrors app/db/database.py's
# _migrate_add_missing_columns for SQLite - keep both lists in sync.
_NEW_NULLABLE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "photos": [("day", "INTEGER")],
}


def build_postgres_engine(database_url: str) -> Engine:
    # pool_pre_ping guards against a pooled connection going stale mid-run (e.g.
    # Neon's serverless autosuspend/idle-connection termination) by testing it with a
    # cheap round-trip before handing it out, transparently reconnecting if needed -
    # important for a scan that can run for a long time against a serverless DB.
    return create_engine(database_url, future=True, pool_pre_ping=True)


def build_postgres_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = build_postgres_engine(database_url)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_postgres_db(database_url: str) -> None:
    """Idempotent initial table creation for Postgres, generated straight from the
    same SQLAlchemy models used for local SQLite (app/db/models.py) - deliberately no
    hand-written Postgres schema.sql to keep a single source of truth for the table
    shape. Safe to call on every run: create_all() no-ops for tables that already
    exist and never alters/drops existing tables or columns - so any column added to
    a model after tables were first created also needs an explicit, idempotent ALTER
    here (see _NEW_NULLABLE_COLUMNS)."""
    engine = build_postgres_engine(database_url)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for table, columns in _NEW_NULLABLE_COLUMNS.items():
            existing = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = :table"
                    ),
                    {"table": table},
                )
            }
            for col_name, col_type in columns:
                if col_name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
