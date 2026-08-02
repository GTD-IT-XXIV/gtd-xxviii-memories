"""One-time (per event day), single-machine bulk upload: pushes every image file
under --source-root to the shared R2 bucket under a raw/ prefix, preserving relative
path structure - completely decoupled from face detection.

Run this ONCE, on whichever single machine has the photos locally (e.g. after
manually downloading + extracting a OneDrive zip). It does not touch Postgres at all.
Afterwards, scripts/run_batch_scan_from_r2_cli.py lets N machines each pull their own
batch slice straight from R2 to do face detection - none of them need a local copy of
the whole folder, only this one upload machine does.

    .venv/Scripts/python.exe -m scripts.upload_originals_to_r2_cli --source-root "C:\\...\\DAY 1 PHOTO"

Safe to interrupt and re-run: skips any key that already exists in R2, so a re-run only
uploads what's missing.

Uploads run concurrently (--workers). R2 has no batch/multi-object PUT - one object is
always one HTTP request - so the only way to go faster is to have many requests in
flight at once, which is what this does.
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.config import settings
from app.scanning.batch_pipeline import relative_posix_path
from app.scanning.walker import walk_images
from app.storage.r2 import R2Client, guess_content_type, r2_config_from_settings

DEFAULT_PREFIX = "raw"
DEFAULT_WORKERS = 16


def _upload_one(r2_client: R2Client, path: str, key: str) -> None:
    """Runs on a pool thread. Streams the file straight from disk rather than reading it
    into bytes first - with many workers in flight, buffering whole multi-MB originals
    would mean workers x filesize resident at once."""
    with open(path, "rb") as fh:
        r2_client.upload_fileobj(key, fh, content_type=guess_content_type(path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-root", required=True, help="Local folder to upload (e.g. an extracted OneDrive zip)")
    parser.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help=f"R2 key prefix photos are uploaded under (default: {DEFAULT_PREFIX!r}) - "
        "must match the --prefix passed to run_batch_scan_from_r2_cli.py later",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Concurrent uploads in flight (default: {DEFAULT_WORKERS}). Raise it if the "
        "reported MB/s hasn't saturated the uplink; lower it on a constrained connection.",
    )
    args = parser.parse_args()

    if args.workers < 1:
        print("--workers must be at least 1")
        sys.exit(1)

    try:
        # Pool must be at least as large as the worker count or botocore serializes
        # requests behind it, defeating the point of the threads.
        r2_client = R2Client(r2_config_from_settings(settings), max_pool_connections=args.workers)
    except RuntimeError as exc:
        print(str(exc))
        sys.exit(1)

    print(f"Scanning {args.source_root} ...")
    found = walk_images(args.source_root)
    total = len(found)
    print(f"Found {total} image files")

    # One paginated LIST (~1 request per 1000 keys) in place of a head_object per file.
    # At 10k+ files that removes 10k serial round trips - and on a fresh run every one of
    # those HEADs was a guaranteed 404 anyway. This is a snapshot taken now rather than a
    # live per-file check; for this script (documented above as a single-machine one-time
    # upload) that's equivalent, and the worst case if something else wrote the same
    # prefix concurrently is a harmless re-PUT of identical bytes.
    print(f"Listing existing objects under {args.prefix!r} ...")
    existing_keys = {obj.key for obj in r2_client.list_objects(args.prefix)}
    print(f"Found {len(existing_keys)} objects already in R2")

    pending: list[tuple[str, str]] = []  # (local path, R2 key)
    skipped = 0
    for f in found:
        key = f"{args.prefix}/{relative_posix_path(args.source_root, f.path)}"
        if key in existing_keys:
            skipped += 1
        else:
            pending.append((f.path, key))

    sizes = {f.path: f.size_bytes for f in found}  # walk_images already stat'd these
    pending_bytes = sum(sizes[p] for p, _ in pending)
    print(
        f"Uploading {len(pending)} files ({pending_bytes / 1e9:.2f} GB), "
        f"skipping {skipped} already in R2, with {args.workers} workers"
    )

    uploaded = errored = 0
    done_bytes = 0
    started = time.monotonic()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_upload_one, r2_client, path, key): (path, key) for path, key in pending}
        # Counters are only touched here on the main thread as futures land, so no locking.
        for i, future in enumerate(as_completed(futures), 1):
            path, _ = futures[future]
            try:
                future.result()
                uploaded += 1
                done_bytes += sizes[path]
            except Exception as exc:  # noqa: BLE001 - keep going, report at the end
                print(f"\nERROR uploading {path}: {exc}")
                errored += 1

            elapsed = time.monotonic() - started
            print(
                f"\r{i}/{len(pending)} (uploaded={uploaded} errored={errored}) "
                f"{elapsed:.0f}s  {done_bytes / 1e6 / elapsed:.1f} MB/s  {i / elapsed:.1f} files/s",
                end="",
                flush=True,
            )

    elapsed = time.monotonic() - started
    print()
    print(f"Done in {elapsed:.1f}s. Uploaded: {uploaded}, already in R2: {skipped}, errored: {errored}")
    if uploaded:
        print(f"Throughput: {done_bytes / 1e6 / elapsed:.1f} MB/s average ({done_bytes / 1e9:.2f} GB total)")
    if errored:
        sys.exit(1)


if __name__ == "__main__":
    main()
