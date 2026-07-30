"""Postgres engine/session-factory builder for the multi-machine batch scan
(app/scanning/batch_pipeline.py, driven by scripts/run_batch_scan_cli.py).

Deliberately separate from the module-level `engine`/`SessionLocal` in
app/db/database.py, which stay wired to local SQLite for the FastAPI app and the
other local CLI scripts (scripts/run_scan_cli.py, scripts/run_reference_import_cli.py)
- nothing in this module changes that local-dev path.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base


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
    exist and never alters/drops existing tables or columns."""
    engine = build_postgres_engine(database_url)
    Base.metadata.create_all(engine)
