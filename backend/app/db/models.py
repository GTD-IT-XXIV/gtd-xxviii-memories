from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # NOTE on meaning of `path` across the two deployments this table is used in:
    # - Local single-machine SQLite dev (app/db/database.py, app/scanning/pipeline.py):
    #   the machine-local ABSOLUTE filesystem path. Unique/dedup key for one machine.
    # - Shared multi-machine Postgres batch scan (scripts/run_batch_scan_cli.py):
    #   the POSIX-normalized path RELATIVE to scan_root. Different laptops mount the
    #   same shared folder under different absolute paths (different drive letters/
    #   usernames), so an absolute path can't be used as a cross-machine dedup/unique
    #   key there - the relative path is the only thing guaranteed identical across
    #   machines for "the same file".
    path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mtime: Mapped[float] = mapped_column(Float, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    taken_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_scanned_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    # Populated only by the Postgres/R2 batch scan; left NULL for local SQLite dev
    # (which keeps serving originals/thumbnails straight from local disk).
    r2_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    r2_thumbnail_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Event day this photo was taken on (1, 2, 3, ...), set once per batch-scan run
    # via --day (see scripts/run_batch_scan_cli.py) - the whole run's photos share one
    # day, since organizers scan one day's folder at a time. Nullable: older rows
    # imported before this existed, and local single-machine dev, won't have it set.
    day: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # No delete cascade: faces (including their embeddings) must survive a photo
    # being deleted - see faces.photo_id below and app/db/postgres.py's
    # migrate_faces_photo_id_nullable().
    faces: Mapped[list["Face"]] = relationship(back_populates="photo")


class Cluster(Base):
    __tablename__ = "clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    centroid: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    face_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="unlabeled")
    merged_into_cluster_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("clusters.id"), nullable=True
    )
    representative_face_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    representative_thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    # Populated only by the Postgres/R2 batch scan; left NULL for local SQLite dev.
    r2_thumbnail_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Person's committee/group code (e.g. "BFM", "GL", "POLOG", "PPIT"). Set by the
    # reference-import path (app/scanning/reference_import.py) / frontend, not by the
    # batch scan itself - this column just needs to exist here so reads/writes from
    # either side don't break.
    og: Mapped[str | None] = mapped_column(Text, nullable=True)

    faces: Mapped[list["Face"]] = relationship(back_populates="cluster")


class Face(Base):
    __tablename__ = "faces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Nullable + SET NULL (not CASCADE): a face's embedding/thumbnail must outlive its
    # source photo being deleted (e.g. the one-off photo-cleanup script) - only the
    # link back to the photo is severed, not the face row itself.
    photo_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("photos.id", ondelete="SET NULL"), nullable=True)
    bbox_x: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_y: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_w: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_h: Mapped[float] = mapped_column(Float, nullable=False)
    det_score: Mapped[float] = mapped_column(Float, nullable=False)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    cluster_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("clusters.id"), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    # Populated only by the Postgres/R2 batch scan; left NULL for local SQLite dev.
    r2_thumbnail_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    photo: Mapped["Photo | None"] = relationship(back_populates="faces")
    cluster: Mapped["Cluster | None"] = relationship(back_populates="faces")


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_root: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    total_files_seen: Mapped[int] = mapped_column(Integer, default=0)
    files_processed: Mapped[int] = mapped_column(Integer, default=0)
    files_skipped_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    files_skipped_placeholder: Mapped[int] = mapped_column(Integer, default=0)
    files_errored: Mapped[int] = mapped_column(Integer, default=0)
    faces_detected: Mapped[int] = mapped_column(Integer, default=0)
    current_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
