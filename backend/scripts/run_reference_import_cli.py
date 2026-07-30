"""Standalone CLI to validate the reference-photo auto-enrollment importer. Run from
backend/ with:

    .venv/Scripts/python.exe -m scripts.run_reference_import_cli "C:\\path\\to\\committee"
"""

import sys
import time

from app.db.database import SessionLocal, init_db
from app.scanning.reference_import import ImportCounters, import_reference_folder


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: run_reference_import_cli.py <reference_folder>")
        sys.exit(1)

    reference_root = sys.argv[1]
    init_db()

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
    counters = import_reference_folder(SessionLocal, reference_root, on_progress=on_progress)
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
