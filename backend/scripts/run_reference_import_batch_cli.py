"""Postgres/R2 variant of run_reference_import_cli.py: seeds labeled person clusters
from a folder of named reference photos (e.g. committee/) directly into the shared
Neon database and Cloudflare R2 bucket, instead of local SQLite + local disk.

Setup (once): set DATABASE_URL and the R2_* vars in backend/.env (see
backend/.env.example), then run with --init-db once to create the Postgres tables
(idempotent - safe to pass on every run too, if preferred).

Run from backend/:
    .venv/Scripts/python.exe -m scripts.run_reference_import_batch_cli "C:\\path\\to\\committee" --init-db
"""

import argparse
import sys
import time

from app.config import settings
from app.db.postgres import build_postgres_session_factory, init_postgres_db
from app.scanning.reference_import import ImportCounters, import_reference_folder
from app.storage.r2 import R2Client, r2_config_from_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reference_root", help="Local path to the reference-photo folder (e.g. committee/)")
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="Idempotently create Postgres tables from the SQLAlchemy models before importing (safe to pass every run)",
    )
    parser.add_argument(
        "--single-photo",
        action="store_true",
        help=(
            "Folder has exactly one reference photo per person, already named after "
            "them (e.g. 'Aaron Revel.jpg') - skip the trailing-digit/multi-photo-"
            "grouping convention required for folders like committee/ that also "
            "contain group/logo photos to filter out."
        ),
    )
    args = parser.parse_args()

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

    def on_progress(counters: ImportCounters) -> None:
        print(
            f"\rpeople_created={counters.people_created}/{counters.people_found} "
            f"files_used={counters.files_used} no_face={counters.files_skipped_no_face} "
            f"multi_face={counters.files_skipped_multi_face} no_pattern={counters.files_skipped_no_pattern} "
            f"current={counters.current_person[:40]}",
            end="",
            flush=True,
        )

    start = time.time()
    counters = import_reference_folder(
        session_factory,
        args.reference_root,
        on_progress=on_progress,
        r2_client=r2_client,
        require_trailing_digit=not args.single_photo,
    )
    elapsed = time.time() - start

    print()
    print(f"Done in {elapsed:.1f}s")
    print(f"Total files seen:      {counters.total_files_seen}")
    print(f"People found:          {counters.people_found}")
    print(f"People created:        {counters.people_created}")
    print(f"Files used:            {counters.files_used}")
    print(f"Skipped (no pattern):  {counters.files_skipped_no_pattern}")
    print(f"Skipped (no face):     {counters.files_skipped_no_face}")
    print(f"Multi-face (best kept):{counters.files_skipped_multi_face}")
    if counters.people_failed:
        print(f"People with NO usable face ({len(counters.people_failed)}):")
        for name in counters.people_failed:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
