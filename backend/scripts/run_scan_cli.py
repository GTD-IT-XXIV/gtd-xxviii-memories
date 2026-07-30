"""Standalone CLI to validate the scan pipeline against a small folder before wiring up
the API/background job. Run from backend/ with:

    .venv/Scripts/python.exe -m scripts.run_scan_cli "C:\\path\\to\\test\\folder"
"""

import sys
import time

from app.db.database import SessionLocal, init_db
from app.scanning.pipeline import ScanCounters, run_scan


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: run_scan_cli.py <folder_to_scan>")
        sys.exit(1)

    scan_root = sys.argv[1]
    init_db()

    def on_progress(counters: ScanCounters) -> None:
        print(
            f"\rprocessed={counters.files_processed} "
            f"skipped_unchanged={counters.files_skipped_unchanged} "
            f"skipped_placeholder={counters.files_skipped_placeholder} "
            f"errored={counters.files_errored} "
            f"faces={counters.faces_detected} "
            f"/ total={counters.total_files_seen}  current={counters.current_file[-60:]}",
            end="",
            flush=True,
        )

    start = time.time()
    counters = run_scan(SessionLocal, scan_root, on_progress=on_progress)
    elapsed = time.time() - start

    print()
    print(f"Done in {elapsed:.1f}s")
    print(f"Total files seen:        {counters.total_files_seen}")
    print(f"Processed:                {counters.files_processed}")
    print(f"Skipped (unchanged):      {counters.files_skipped_unchanged}")
    print(f"Skipped (cloud placeholder): {counters.files_skipped_placeholder}")
    print(f"Errored:                  {counters.files_errored}")
    print(f"Faces detected:           {counters.faces_detected}")


if __name__ == "__main__":
    main()
