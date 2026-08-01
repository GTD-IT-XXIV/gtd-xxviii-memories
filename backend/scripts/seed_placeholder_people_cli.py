"""One-off: creates name-only "placeholder" labeled clusters for people whose
reference photo produced no usable face, so they still appear in the review page's
person picker and can be assigned clusters manually.

Background: import_reference_folder() (app/scanning/reference_import.py) only creates
a labeled cluster for a person when at least one of their reference photos yields a
face embedding; everyone else lands in ImportCounters.people_failed and gets no row at
all. The review page's picker is built from `SELECT person_name, MAX(og) ... WHERE
status = 'labeled'` (web/src/app/review/page.tsx), so those people are invisible there
- a reviewer looking at one of their clusters in Others has no way to pick their name,
and typing it free-hand risks typos/duplicates across the dozens of clusters that
person appears in.

The centroid is an all-zeros vector. This is deliberate and is what makes the row
inert to matching: every centroid/embedding in the system is L2-normalized and
compared by plain dot product (app/clustering/similarity.py's ClusterIndex.best_match,
`self.matrix @ embedding`), so a zero centroid scores EXACTLY 0.0 against every face -
far below both cluster_join_threshold (0.58) and cluster_suggestion_threshold (0.3) in
app/config.py. It can therefore never auto-capture a face nor be offered as a
suggested match; it exists purely so the name is pickable. Once a reviewer assigns a
real cluster to that person via the picker, that cluster carries the real centroid and
the placeholder just sits alongside it, still matching nothing.

face_count is 0 and no thumbnail is set, which is how you can tell a placeholder from
a genuine single-photo reference cluster later.

Idempotent: skips any person whose name already exists as a labeled cluster, so it's
safe to re-run after fixing some people's photos.

Defaults to a dry run (reports what WOULD be created, writes nothing). Pass --yes to
actually apply.

Run from backend/:
    .venv/Scripts/python.exe -m scripts.seed_placeholder_people_cli            # dry run
    .venv/Scripts/python.exe -m scripts.seed_placeholder_people_cli --yes      # for real
"""

import argparse
import sys
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select

from app.clustering.similarity import EMBEDDING_DIM
from app.config import settings
from app.db.models import Cluster
from app.db.postgres import build_postgres_session_factory

# People whose GTD XXVIII self-portraits produced no detectable face during the
# reference import, with the OG they belong to. Edit this list rather than passing
# names on the command line - it doubles as the record of who needed this.
PLACEHOLDER_PEOPLE: list[tuple[str, str]] = [
    ("Alif Danendra", "OG7"),
    ("Anderson Andrew Chandra", "OG7"),
    ("Daniel Surya Chandra", "OG3"),
    ("David Christopher Purnama", "OG2"),
    ("Dimitry Marvello", "OG7"),
    ("Dominiques Kevin Tjemerlang", "OG8"),
    ("Edbert Vianco Lim", "OG6"),
    ("Gabriela Yocelyn", "OG8"),
    ("Harley Nielsen", "OG8"),
    ("Kevin Austin", "OG2"),
    ("Marco Winardy", "OG2"),
    ("Michelle Stephanie Martin", "OG1"),
    ("Nathanael Dean Janvierino", "OG8"),
    ("Owen Valianto Tandova", "OG3"),
    ("Shereen Aurelia Utama", "OG8"),
    ("Sherlyta Iffaqotrunnada Puteri Ayu Hapsari", "OG2"),
    ("William Putra Herel", "OG1"),
    ("Zachary Timothy Johanes", "OG7"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually create the placeholder clusters. Without this flag, only reports what would change (dry run).",
    )
    args = parser.parse_args()

    if not settings.database_url:
        print("DATABASE_URL is not set. Set it in backend/.env or the environment (see backend/.env.example).")
        sys.exit(1)

    session_factory = build_postgres_session_factory(settings.database_url)
    zero_centroid = np.zeros(EMBEDDING_DIM, dtype=np.float32).tobytes()

    created: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []

    with session_factory() as session:
        existing = {
            name
            for (name,) in session.execute(
                select(Cluster.person_name).where(Cluster.status == "labeled", Cluster.person_name.is_not(None))
            ).all()
        }

        for person_name, og in PLACEHOLDER_PEOPLE:
            if person_name in existing:
                skipped.append((person_name, og))
                continue
            session.add(
                Cluster(
                    person_name=person_name,
                    og=og,
                    centroid=zero_centroid,
                    face_count=0,
                    status="labeled",
                    created_at=_now(),
                    updated_at=_now(),
                )
            )
            created.append((person_name, og))

        if args.yes:
            session.commit()
        else:
            session.rollback()

    for person_name, og in created:
        print(f"  + {og:5s} {person_name}")
    for person_name, og in skipped:
        print(f"  = {og:5s} {person_name} (already labeled, skipped)")

    print()
    print(f"Would create: {len(created)}" if not args.yes else f"Created: {len(created)}")
    print(f"Skipped:      {len(skipped)}")

    if not args.yes:
        print("\nDry run only - nothing written. Re-run with --yes to actually apply.")


if __name__ == "__main__":
    main()
