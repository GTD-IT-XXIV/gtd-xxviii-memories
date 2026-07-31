"""One-off cleanup: deletes all photos (Postgres rows + their R2 originals/thumbnails)
while PRESERVING every face - embeddings, cluster assignments, and each face's own
thumbnail (faces.r2_thumbnail_key is never touched here).

Faces survive because app/db/postgres.py's migrate_faces_photo_id_nullable() migrates
faces.photo_id from `NOT NULL ... ON DELETE CASCADE` to `NULL ... ON DELETE SET NULL`
before any photos are deleted - Postgres then nulls out faces.photo_id automatically
as each photo row is deleted, instead of cascading the delete onto faces.

Defaults to a dry run (reports counts, deletes nothing). Pass --yes to actually run it.

    .venv/Scripts/python.exe -m scripts.cleanup_photos_cli            # dry run
    .venv/Scripts/python.exe -m scripts.cleanup_photos_cli --yes      # for real

After this runs, `photos` is empty, so scripts/run_batch_scan_cli.py's per-file
resumability dedup (keyed on photos.path) is reset - a future re-scan of the same
folder will reprocess every file from scratch (new Photo/Face rows), rather than
skipping files as "already processed". Existing faces/clusters/embeddings from before
the cleanup are unaffected by that - a re-scan's new faces just get matched against
the same existing clusters via the normal similarity-matching path.
"""

import argparse
import sys

from sqlalchemy import delete, func, select

from app.config import settings
from app.db.models import Face, Photo
from app.db.postgres import build_postgres_session_factory, migrate_faces_photo_id_nullable
from app.storage.r2 import R2Client, r2_config_from_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually perform the deletion. Without this flag, only reports counts (dry run, no writes).",
    )
    args = parser.parse_args()

    if not settings.database_url:
        print("DATABASE_URL is not set. Set it in backend/.env or the environment (see backend/.env.example).")
        sys.exit(1)

    try:
        r2_client = R2Client(r2_config_from_settings(settings))
    except RuntimeError as exc:
        print(str(exc))
        sys.exit(1)

    session_factory = build_postgres_session_factory(settings.database_url)

    with session_factory() as session:
        photo_count = session.scalar(select(func.count()).select_from(Photo))
        r2_key_count = session.scalar(select(func.count()).where(Photo.r2_key.is_not(None)))
        r2_thumb_count = session.scalar(select(func.count()).where(Photo.r2_thumbnail_key.is_not(None)))
        face_count = session.scalar(select(func.count()).select_from(Face))

    print(f"photos to delete:              {photo_count}")
    print(f"  with an R2 original:          {r2_key_count}")
    print(f"  with an R2 photo-thumbnail:   {r2_thumb_count}")
    print(f"faces that will be preserved:  {face_count} (embeddings + face thumbnails untouched)")

    if not args.yes:
        print("\nDry run only - nothing deleted. Re-run with --yes to actually delete.")
        return

    print("\nMigrating faces.photo_id to nullable/SET NULL (idempotent)...")
    migrate_faces_photo_id_nullable(settings.database_url)

    with session_factory() as session:
        keys: list[str] = []
        for r2_key, r2_thumbnail_key in session.execute(select(Photo.r2_key, Photo.r2_thumbnail_key)):
            if r2_key:
                keys.append(r2_key)
            if r2_thumbnail_key:
                keys.append(r2_thumbnail_key)

    print(f"Deleting {len(keys)} R2 objects (originals + photo-thumbnails)...")
    failed_keys = r2_client.delete_objects(keys) if keys else []
    if failed_keys:
        print(f"WARNING: {len(failed_keys)} R2 objects failed to delete (left in bucket):")
        for k in failed_keys:
            print(f"  {k}")

    with session_factory() as session:
        result = session.execute(delete(Photo))
        session.commit()
        deleted_count = result.rowcount

    with session_factory() as session:
        remaining_faces = session.scalar(select(func.count()).select_from(Face))
        orphaned_faces = session.scalar(select(func.count()).where(Face.photo_id.is_(None)))

    print(f"\nDone. Deleted {deleted_count} photo rows.")
    print(f"R2 objects deleted: {len(keys) - len(failed_keys)} (failed: {len(failed_keys)})")
    print(f"Faces remaining: {remaining_faces} (now orphaned from any photo: {orphaned_faces})")


if __name__ == "__main__":
    main()
