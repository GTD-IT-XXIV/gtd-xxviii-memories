"""Generates the mid-size gallery preview (settings.photo_preview_max_dim) for photos
scanned before previews existed, and uploads it to R2 under previews/photos/{id}.jpg.

Why this exists: the gallery grid stores a 480px thumbnail, which looks soft when
clicked and blown up to a lightbox. Serving the untouched original instead means 8-15MB
per click. app/scanning/batch_pipeline.py now writes a ~200-400KB preview at scan time,
but every photo scanned before that change has r2_preview_key = NULL. This backfills
them. The gallery falls back to the thumbnail wherever it's still NULL, so running this
is not required for the site to work - it just improves preview quality photo by photo.

Reads each original back from R2, downscales it, uploads the preview, and sets
photos.r2_preview_key. Nothing is deleted or overwritten: originals and existing
thumbnails are untouched, and photos that already have a preview are skipped, so this
is safe to interrupt and re-run - a re-run only does what's still missing. Progress is
committed every FLUSH_EVERY photos (and on Ctrl-C), so an interrupted run keeps what it
already finished.

Note this DOES cost R2 Class B (GET) operations to re-read each original, unlike the
scan-time path which already has the decoded image in memory. At ~2k photos that is
negligible (well under a cent), but it is why this is a one-off script rather than
something to run repeatedly.

Run from backend/:
    # see what would happen, no writes
    .venv/Scripts/python.exe -m scripts.backfill_photo_previews_cli

    # do it
    .venv/Scripts/python.exe -m scripts.backfill_photo_previews_cli --yes

    # redo previews that already exist (e.g. after changing photo_preview_max_dim)
    .venv/Scripts/python.exe -m scripts.backfill_photo_previews_cli --yes --force
"""

import argparse
import io
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text

from app.config import settings
from app.db.postgres import build_postgres_session_factory
from app.scanning.heic import register_heif_opener
from app.scanning.imaging import load_rgb_and_bgr
from app.scanning.thumbnails import photo_preview_bytes
from app.storage.r2 import R2Client, r2_config_from_settings

DEFAULT_WORKERS = 8
# Persist r2_preview_key every N photos. Small enough that an interrupted run loses
# only a partial chunk, large enough that a 10k-photo run isn't 10k round trips to a
# serverless Postgres.
FLUSH_EVERY = 200


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="Actually generate and upload. Without this, dry run.")
    parser.add_argument("--force", action="store_true", help="Also regenerate photos that already have a preview.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N photos.")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"Parallelism (default {DEFAULT_WORKERS}).")
    args = parser.parse_args()

    if not settings.database_url:
        print("DATABASE_URL is not set. Set it in backend/.env or the environment (see backend/.env.example).")
        sys.exit(1)
    try:
        # Pool must match worker count or botocore serializes requests behind it.
        r2 = R2Client(r2_config_from_settings(settings), max_pool_connections=args.workers)
    except RuntimeError as exc:
        print(str(exc))
        sys.exit(1)

    register_heif_opener()
    session_factory = build_postgres_session_factory(settings.database_url)

    where = "p.status = 'processed' AND p.r2_key IS NOT NULL"
    if not args.force:
        where += " AND p.r2_preview_key IS NULL"

    with session_factory() as session:
        rows = session.execute(
            text(f"SELECT p.id, p.r2_key FROM photos p WHERE {where} ORDER BY p.id")
        ).all()

    todo = [tuple(r) for r in rows]
    if args.limit is not None:
        todo = todo[: args.limit]

    print(f"Photos needing a preview: {len(todo)}")
    if not todo:
        print("Nothing to do.")
        return
    print(f"Target max dimension: {settings.photo_preview_max_dim}px, quality {settings.photo_preview_quality}")

    if not args.yes:
        print("\nDry run only - nothing written. Re-run with --yes to actually generate.")
        return

    done = 0
    failed = 0
    total_bytes = 0
    lock = threading.Lock()
    start = time.time()
    results: list[tuple[int, str]] = []

    def work(item: tuple[int, str]) -> None:
        nonlocal done, failed, total_bytes
        photo_id, r2_key = item
        try:
            data = r2.download_bytes(r2_key)
            # Same decode call the scan pipeline uses, so a backfilled preview is
            # byte-for-byte what a fresh scan would have produced. (max_dim is only a
            # hint - draft() applies to JPEG and snaps to power-of-two ratios, so large
            # originals often decode at full size. Fine: more pixels to downscale from.)
            pil_image, _bgr, _size = load_rgb_and_bgr(io.BytesIO(data), max_dim=settings.detect_max_dim)
            preview = photo_preview_bytes(pil_image)
            key = f"previews/photos/{photo_id}.jpg"
            r2.upload_bytes(key, preview, content_type="image/jpeg")
            with lock:
                results.append((photo_id, key))
                done += 1
                total_bytes += len(preview)
        except Exception as exc:  # noqa: BLE001 - one bad photo must not abort the run
            with lock:
                failed += 1
            print(f"\nERROR photo {photo_id} ({r2_key}): {exc}")

    def flush_results() -> int:
        """Writes the r2_preview_key values accumulated so far and clears the buffer.

        Called periodically rather than only at the end. Batching every write to the
        very end keeps round trips down, but it makes the whole run all-or-nothing for
        DB state: killing it after an hour leaves thousands of previews sitting in R2
        that the database knows nothing about, so a resumed run regenerates every one
        of them (this happened, and the state had to be reconstructed by hand from an
        R2 listing). Flushing in chunks keeps the resume contract honest - whatever
        finished stays finished.
        """
        with lock:
            pending, results[:] = list(results), []
        if not pending:
            return 0
        with session_factory() as session:
            for photo_id, key in pending:
                session.execute(
                    text("UPDATE photos SET r2_preview_key = :key WHERE id = :id"),
                    {"key": key, "id": photo_id},
                )
            session.commit()
        return len(pending)

    flushed = 0
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for i, _ in enumerate(pool.map(work, todo), 1):
                if i % FLUSH_EVERY == 0:
                    flushed += flush_results()
                if i % 25 == 0 or i == len(todo):
                    elapsed = time.time() - start
                    print(
                        f"\r  {i}/{len(todo)}  ok={done} failed={failed} saved={flushed}  "
                        f"{i / max(1e-6, elapsed):.1f}/s",
                        end="",
                        flush=True,
                    )
    except KeyboardInterrupt:
        # Persist what already succeeded before exiting, so Ctrl-C costs at most one
        # partial chunk instead of the entire run's DB state.
        print("\n\nInterrupted - saving completed previews...")
        flushed += flush_results()
        print(f"Saved {flushed} preview key(s). Re-run to continue where this left off.")
        raise SystemExit(130)
    print("\n")

    flushed += flush_results()

    elapsed = time.time() - start
    print(f"Done in {elapsed:.1f}s. Generated: {done}, failed: {failed}")
    if done:
        print(f"Average preview size: {total_bytes / done / 1024:.0f} KB  (total {total_bytes / 1e6:.1f} MB added to R2)")


if __name__ == "__main__":
    main()
