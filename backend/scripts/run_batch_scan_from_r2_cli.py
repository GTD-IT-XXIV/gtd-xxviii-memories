"""Multi-machine batch scan, R2-sourced variant of scripts/run_batch_scan_cli.py.

Use this instead of run_batch_scan_cli.py when photos have already been bulk-uploaded
to R2 by scripts/upload_originals_to_r2_cli.py (e.g. after a manual OneDrive zip
download on one machine), so each laptop here pulls only its own batch slice straight
from R2 - none of them need OneDrive access or a local copy of the whole folder.

Setup (once): set DATABASE_URL and the R2_* vars in backend/.env (see
backend/.env.example), run scripts/upload_originals_to_r2_cli.py once to populate R2,
then run any one machine here with --init-db once to create the Postgres tables
(idempotent - safe to pass on every run too).

Run once per event day, with --day set so the gallery's day filter works - one process
per laptop, e.g. for a 4-way split on day 1 (assuming upload_originals_to_r2_cli.py
was run with the default --prefix "raw"):
    .venv/Scripts/python.exe -m scripts.run_batch_scan_from_r2_cli --prefix raw --batch 0 --total-batches 4 --day 1 --init-db
    .venv/Scripts/python.exe -m scripts.run_batch_scan_from_r2_cli --prefix raw --batch 1 --total-batches 4 --day 1
    .venv/Scripts/python.exe -m scripts.run_batch_scan_from_r2_cli --prefix raw --batch 2 --total-batches 4 --day 1
    .venv/Scripts/python.exe -m scripts.run_batch_scan_from_r2_cli --prefix raw --batch 3 --total-batches 4 --day 1
"""

import argparse
import sys
import time

from app.config import settings
from app.db.postgres import build_postgres_session_factory, init_postgres_db
from app.scanning.batch_pipeline import BatchScanCounters, run_batch_scan_from_r2
from app.storage.r2 import R2Client, r2_config_from_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--prefix",
        required=True,
        help="R2 key prefix to scan (must match the --prefix used with upload_originals_to_r2_cli.py)",
    )
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
        help="Download+decode+detect thread pool size (default: min(8, cpu_count))",
    )
    parser.add_argument(
        "--refresh-every",
        type=int,
        default=None,
        help="Reload the in-memory cluster index from the DB every N processed files, to pick up clusters created by other machines (default: 200)",
    )
    parser.add_argument(
        "--day",
        type=int,
        default=None,
        help="Event day this prefix's photos were taken on (e.g. 1, 2, 3), for the gallery's day filter. "
        "Stamped onto every photo this run creates/reprocesses. Omit only for a one-off test scan.",
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
    if args.day is not None:
        kwargs["day"] = args.day

    start = time.time()
    counters = run_batch_scan_from_r2(
        session_factory,
        r2_client,
        args.prefix,
        batch=args.batch,
        total_batches=args.total_batches,
        on_progress=on_progress,
        **kwargs,
    )
    elapsed = time.time() - start

    print()
    print(f"Done in {elapsed:.1f}s")
    print(f"Total files seen (whole prefix): {counters.total_files_seen}")
    print(f"Files in this batch:         {counters.files_in_batch}")
    print(f"Processed:                   {counters.files_processed}")
    print(f"Skipped (unchanged):         {counters.files_skipped_unchanged}")
    print(f"Errored:                     {counters.files_errored}")
    print(f"Faces detected:              {counters.faces_detected}")


if __name__ == "__main__":
    main()
