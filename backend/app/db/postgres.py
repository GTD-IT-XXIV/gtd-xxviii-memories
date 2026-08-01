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
    "clusters": [
        ("deferred_to_others", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("suggested_cluster_id", "INTEGER REFERENCES clusters(id) ON DELETE SET NULL"),
        ("suggested_similarity", "DOUBLE PRECISION"),
    ],
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


def migrate_faces_photo_id_nullable(database_url: str) -> None:
    """One-off structural migration (not part of init_postgres_db/_NEW_NULLABLE_COLUMNS
    since it changes an existing column's nullability/FK behavior, not just adds a
    column): makes faces.photo_id nullable with ON DELETE SET NULL instead of the
    original NOT NULL / ON DELETE CASCADE, so a face (embedding + thumbnail) survives
    its source photo being deleted - see scripts/cleanup_photos_cli.py, the only
    caller. Matches the nullable/SET NULL shape already declared in app/db/models.py.

    Idempotent: safe to call every run. Checks the live schema before altering
    anything, so it no-ops once already migrated."""
    engine = build_postgres_engine(database_url)
    with engine.begin() as conn:
        is_nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'faces' AND column_name = 'photo_id'"
            )
        ).scalar_one()

        # confdeltype: 'n' = ON DELETE SET NULL, 'c' = ON DELETE CASCADE, 'a' = NO ACTION.
        # Joined via pg_attribute/conkey (not information_schema) because
        # information_schema.referential_constraints doesn't expose delete-rule per
        # column for a single-column FK lookup as directly as pg_constraint does.
        fk_row = conn.execute(
            text(
                """
                SELECT con.conname, con.confdeltype
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
                JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ANY(con.conkey)
                WHERE nsp.nspname = 'public' AND rel.relname = 'faces'
                  AND con.contype = 'f' AND att.attname = 'photo_id'
                """
            )
        ).one_or_none()

        if is_nullable == "YES" and fk_row is not None and fk_row.confdeltype == "n":
            return  # already migrated

        if fk_row is not None:
            conn.execute(text(f'ALTER TABLE faces DROP CONSTRAINT "{fk_row.conname}"'))
        if is_nullable == "NO":
            conn.execute(text("ALTER TABLE faces ALTER COLUMN photo_id DROP NOT NULL"))
        conn.execute(
            text(
                "ALTER TABLE faces ADD CONSTRAINT faces_photo_id_fkey "
                "FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE SET NULL"
            )
        )
