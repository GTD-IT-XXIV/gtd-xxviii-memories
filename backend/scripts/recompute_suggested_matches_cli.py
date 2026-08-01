"""One-off/periodic: refreshes every unlabeled cluster's stored "suggested match"
(clusters.suggested_cluster_id/suggested_similarity) against the CURRENT set of
labeled clusters.

This is normally kept fresh automatically:
- incrementally, at scan time, as each cluster's centroid changes
  (app/clustering/incremental.py)
- in bulk, at the end of every reference import
  (app/scanning/reference_import.py's import_reference_folder())

Run this manually when neither of those just fired but the labeled-cluster set
changed anyway - e.g. after a batch of manual relabeling/corrections via the review
page (renames, merges, new names typed in) - so other unlabeled clusters' stored
suggestions catch up. Also serves as the one-time backfill for clusters created
before this column existed.

Defaults to a dry run (computes and reports what WOULD change, writes nothing).
Pass --yes to actually apply.

    .venv/Scripts/python.exe -m scripts.recompute_suggested_matches_cli            # dry run
    .venv/Scripts/python.exe -m scripts.recompute_suggested_matches_cli --yes      # for real
"""

import argparse
import sys

from app.clustering.suggestions import recompute_all_suggestions
from app.config import settings
from app.db.postgres import build_postgres_session_factory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually write the recomputed suggestions. Without this flag, only reports what would change (dry run).",
    )
    args = parser.parse_args()

    if not settings.database_url:
        print("DATABASE_URL is not set. Set it in backend/.env or the environment (see backend/.env.example).")
        sys.exit(1)

    session_factory = build_postgres_session_factory(settings.database_url)

    with session_factory() as session:
        counters = recompute_all_suggestions(session, dry_run=not args.yes)

    print(f"Unlabeled clusters seen: {counters.unlabeled_seen}")
    print(f"Suggestions changed:     {counters.changed}")

    if not args.yes:
        print("\nDry run only - nothing written. Re-run with --yes to actually apply.")


if __name__ == "__main__":
    main()
