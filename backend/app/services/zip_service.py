import os
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from stream_zip import ZIP_32, stream_zip
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Photo


class InvalidPhotoSelection(ValueError):
    pass


def _member_chunks(path: Path, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                return
            yield chunk


def _unique_names(filenames: Iterable[str]) -> Iterator[str]:
    """Disambiguates duplicate filenames (common across a big photo library) by
    appending a numeric suffix before the extension."""
    seen: dict[str, int] = {}
    for name in filenames:
        if name not in seen:
            seen[name] = 0
            yield name
        else:
            seen[name] += 1
            stem, dot, ext = name.rpartition(".")
            yield f"{stem}_{seen[name]}{dot}{ext}" if dot else f"{name}_{seen[name]}"


def build_zip_stream(session: Session, photo_ids: list[int]) -> Iterator[bytes]:
    """Streams selected photos as a ZIP. photo_ids are only ever accepted from our
    own `photos` table, whose rows are exclusively created by walking a scan root we
    control (see app.scanning.walker) - so there's no client-suppliable filesystem
    path here, only a defensive existence check before opening each file."""
    if not photo_ids:
        raise InvalidPhotoSelection("No photos selected")

    photos = session.execute(select(Photo).where(Photo.id.in_(photo_ids))).scalars().all()
    by_id = {p.id: p for p in photos}
    ordered = [by_id[pid] for pid in photo_ids if pid in by_id]
    if not ordered:
        raise InvalidPhotoSelection("None of the selected photos were found")

    for photo in ordered:
        if not os.path.exists(photo.path):
            raise InvalidPhotoSelection(f"File missing on disk: {photo.path}")

    names = list(_unique_names(p.filename for p in ordered))

    def members():
        now = datetime.now()
        for photo, name in zip(ordered, names):
            yield (
                name,
                now,
                0o600,
                ZIP_32,
                _member_chunks(Path(photo.path)),
            )

    return stream_zip(members())
