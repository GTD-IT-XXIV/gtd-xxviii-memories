"""Multi-machine batch scan CLI. Several laptops run this in parallel, each scanning
its own deterministic, non-overlapping slice of a SHARED photo folder (mounted
locally on each machine, e.g. under different drive letters/usernames), and writing
results to a SHARED Neon Postgres database + Cloudflare R2 bucket instead of the local
SQLite DB + local-disk thumbnails used by scripts/run_scan_cli.py.

Batches are partitioned by a stable hash of each file's path relative to --scan-root
(see app.scanning.batch_pipeline.belongs_to_batch) - NOT by enumeration order - so the
same --batch/--total-batches always resolves to the same file set regardless of what
else changes in the folder, making a re-run after an interruption safe.

Setup (once): set DATABASE_URL and the R2_* vars in backend/.env (see
backend/.env.example), then run any one machine with --init-db once to create the
Postgres tables (idempotent - safe to pass on every run too, if preferred).

Run from backend/, one process per laptop, e.g. for a 4-way split:
    .venv/Scripts/python.exe -m scripts.run_batch_scan_cli --scan-root "C:\\path\\to\\shared\\folder" --batch 0 --total-batches 4 --init-db
    .venv/Scripts/python.exe -m scripts.run_batch_scan_cli --scan-root "D:\\shared\\folder" --batch 1 --total-batches 4
    .venv/Scripts/python.exe -m scripts.run_batch_scan_cli --scan-root "C:\\Users\\other\\shared\\folder" --batch 2 --total-batches 4
    .venv/Scripts/python.exe -m scripts.run_batch_scan_cli --scan-root "C:\\shared\\folder" --batch 3 --total-batches 4
"""

import argparse
import sys
import time

from app.config import settings
from app.db.postgres import build_postgres_session_factory, init_postgres_db
from app.scanning.batch_pipeline import BatchScanCounters, run_batch_scan
from app.storage.r2 import R2Client, r2_config_from_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scan-root", required=True, help="This machine's local path to the shared photo folder")
    parser.add_argument("--batch", type=int, required=True, help="0-based index of this machine's batch")
    parser.add_argument("--total-batches", type=int, required=True, help="Total number of batches/machines splitting the scan")
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="Idempotently create Postgres tables from the SQLAlchemy models before scanning (safe to pass every run)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Decode/detect thread pool size (default: min(8, cpu_count))",
    )
    parser.add_argument(
        "--refresh-every",
        type=int,
        default=None,
        help="Reload the in-memory cluster index from the DB every N processed files, to pick up clusters created by other machines (default: 200)",
    )
    args = parser.parse_args()

    if args.total_batches < 1:
        print("--total-batches must be >= 1")
        sys.exit(1)
    if not (0 <= args.batch < args.total_batches):
        print(f"--batch must be in [0, {args.total_batches - 1}]")
        sys.exit(1)

    if not settings.database_url:
        print("DATABASE_URL is not set. Set it in backend/.env or the environment (see backend/.env.example).")
        sys.exit(1)

    if args.init_db:
        print("Initializing Postgres schema (idempotent, safe if tables already exist)...")
        init_postgres_db(settings.database_url)

    try:
        r2_client = R2Client(r2_config_from_settings(settings))
    except RuntimeError as exc:
        print(str(exc))
        sys.exit(1)

    session_factory = build_postgres_session_factory(settings.database_url)

    def on_progress(counters: BatchScanCounters) -> None:
        print(
            f"\rbatch={args.batch}/{args.total_batches} "
            f"in_batch={counters.files_in_batch} "
            f"processed={counters.files_processed} "
            f"skipped_unchanged={counters.files_skipped_unchanged} "
            f"skipped_placeholder={counters.files_skipped_placeholder} "
            f"errored={counters.files_errored} "
            f"faces={counters.faces_detected} "
            f"/ total_seen={counters.total_files_seen}  current={counters.current_file[-60:]}",
            end="",
            flush=True,
        )

    kwargs = {}
    if args.max_workers is not None:
        kwargs["max_workers"] = args.max_workers
    if args.refresh_every is not None:
        kwargs["refresh_every"] = args.refresh_every

    start = time.time()
    counters = run_batch_scan(
        session_factory,
        args.scan_root,
        batch=args.batch,
        total_batches=args.total_batches,
        r2_client=r2_client,
        on_progress=on_progress,
        **kwargs,
    )
    elapsed = time.time() - start

    print()
    print(f"Done in {elapsed:.1f}s")
    print(f"Total files seen (whole scan_root): {counters.total_files_seen}")
    print(f"Files in this batch:         {counters.files_in_batch}")
    print(f"Processed:                   {counters.files_processed}")
    print(f"Skipped (unchanged):         {counters.files_skipped_unchanged}")
    print(f"Skipped (cloud placeholder): {counters.files_skipped_placeholder}")
    print(f"Errored:                     {counters.files_errored}")
    print(f"Faces detected:              {counters.faces_detected}")


if __name__ == "__main__":
    main()
