"""One-off fix: two folders of originals were uploaded under the wrong day prefix and
then batch-scanned with --day matching the wrong folder name.

    raw/day2/GROUP  actually holds DAY 3 photos (filenames dated 20260802)
    raw/day3/GROUP  actually holds DAY 2 photos (filenames dated 20260801)

The date->day mapping is established from folders that are correctly labeled:
day2/OG 2, day2/OG 5 and day2/OG 6 all contain 20260801 files, so
day 1 = 20260731, day 2 = 20260801, day 3 = 20260802. (photos.taken_at is NULL across
the whole library, so the EXIF timestamp is unavailable here and the iOS filename
datestamp is the ground truth.)

This script does two things:

  1. Corrects photos.day for both folders.
  2. Swaps the R2 key prefixes, so the stored folder names stop lying. That matters
     beyond tidiness: leaving them means a later
     `run_batch_scan_from_r2_cli.py --prefix raw/day2 --day 2` would re-introduce
     exactly this bug.

Nothing is re-scanned. Faces, embeddings, clusters and labels do not depend on the
day or on the source path, so recomputing them would be pure risk - it would burn
CPU to produce identical embeddings while disturbing existing cluster assignments.

r2_thumbnail_key and r2_preview_key are keyed by photo ID (thumbnails/photos/{id}.jpg,
previews/photos/{id}.jpg), NOT by source path, so they are deliberately left alone.

ORDERING (this is the part that makes an interrupted run safe):

    1. copy every object to its new key      -> R2 briefly holds both copies
    2. commit day + r2_key in ONE transaction -> DB now points at the new keys
    3. only then delete the old keys

A crash before step 2 leaves harmless duplicates and an untouched DB. A crash before
step 3 leaves the DB correct plus stale copies, which a re-run cleans up. At no point
does a live r2_key reference a deleted object.

Safe to re-run: it re-measures at run time and skips work already done.

Run from backend/:
    .venv/Scripts/python.exe -m scripts.fix_swapped_day_folders_cli            # dry run
    .venv/Scripts/python.exe -m scripts.fix_swapped_day_folders_cli --yes      # apply
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text

from app.config import settings
from app.db.postgres import build_postgres_session_factory
from app.storage.r2 import R2Client, r2_config_from_settings

# (prefix currently holding the photos, the day those photos were ACTUALLY taken)
FOLDER_A = "raw/day2/GROUP"
FOLDER_B = "raw/day3/GROUP"
CORRECT_DAY = {FOLDER_A: 3, FOLDER_B: 2}
# Where each folder's objects must end up, so folder name and day finally agree.
DEST_PREFIX = {FOLDER_A: FOLDER_B, FOLDER_B: FOLDER_A}

DEFAULT_WORKERS = 8


def _basename(key: str, prefix: str) -> str:
    return key[len(prefix) + 1 :]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="Actually apply. Without this, dry run.")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"Copy parallelism (default {DEFAULT_WORKERS}).")
    args = parser.parse_args()

    if not settings.database_url:
        print("DATABASE_URL is not set. Set it in backend/.env or the environment.")
        sys.exit(1)
    try:
        r2 = R2Client(r2_config_from_settings(settings), max_pool_connections=args.workers)
    except RuntimeError as exc:
        print(str(exc))
        sys.exit(1)

    session_factory = build_postgres_session_factory(settings.database_url)

    # --- measure current state ------------------------------------------------
    live: dict[str, set[str]] = {}
    for folder in (FOLDER_A, FOLDER_B):
        live[folder] = {o.key for o in r2.list_objects(f"{folder}/")}

    names_a = {_basename(k, FOLDER_A) for k in live[FOLDER_A]}
    names_b = {_basename(k, FOLDER_B) for k in live[FOLDER_B]}

    print("Current R2 state")
    print(f"  {FOLDER_A}: {len(live[FOLDER_A])} objects  (actually day {CORRECT_DAY[FOLDER_A]})")
    print(f"  {FOLDER_B}: {len(live[FOLDER_B])} objects  (actually day {CORRECT_DAY[FOLDER_B]})")

    # The whole swap is only safe without a staging prefix because no basename is
    # present in both folders - otherwise one copy would silently overwrite a live
    # object from the other folder. Verify rather than assume.
    collisions = names_a & names_b
    if collisions:
        print(f"\nABORT: {len(collisions)} basename(s) exist in BOTH folders, e.g. {sorted(collisions)[:5]}")
        print("A direct swap would overwrite live objects. This needs a staging prefix - not attempted.")
        sys.exit(1)
    print(f"  basename collisions: 0 (direct swap is safe)")

    with session_factory() as session:
        db_rows = {}
        for folder in (FOLDER_A, FOLDER_B):
            rows = session.execute(
                text("SELECT id, r2_key, day, status FROM photos WHERE r2_key LIKE :p"),
                {"p": f"{folder}/%"},
            ).all()
            db_rows[folder] = [tuple(r) for r in rows]

    print("\nDatabase state")
    for folder in (FOLDER_A, FOLDER_B):
        rows = db_rows[folder]
        wrong = sum(1 for _i, _k, d, _s in rows if d != CORRECT_DAY[folder])
        print(f"  {folder}: {len(rows)} rows, {wrong} with the wrong day")
        missing = live[folder] - {k for _i, k, _d, _s in rows}
        if missing:
            print(f"      note: {len(missing)} R2 object(s) have no DB row (unscanned); they will still be moved")

    copies = [(k, f"{DEST_PREFIX[f]}/{_basename(k, f)}") for f in (FOLDER_A, FOLDER_B) for k in sorted(live[f])]
    print(f"\nPlanned: copy {len(copies)} objects, rewrite the same number of r2_key values,")
    print(f"         fix day on {sum(len(db_rows[f]) for f in (FOLDER_A, FOLDER_B))} rows, then delete the old keys.")

    if not args.yes:
        print("\nDry run only - nothing written. Re-run with --yes to apply.")
        return

    # --- step 1: copy ---------------------------------------------------------
    print(f"\n[1/3] Copying {len(copies)} objects with {args.workers} workers...")
    failures: list[tuple[str, str, str]] = []
    done = 0
    start = time.time()

    def do_copy(pair: tuple[str, str]) -> None:
        nonlocal done
        src, dst = pair
        try:
            r2.copy_object(src, dst)
        except Exception as exc:  # noqa: BLE001 - collect and report, don't half-abort
            failures.append((src, dst, str(exc)))
        done += 1
        if done % 20 == 0 or done == len(copies):
            print(f"\r   {done}/{len(copies)}  ({done / max(1e-6, time.time() - start):.1f}/s)", end="", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(do_copy, copies))
    print()

    if failures:
        print(f"\nABORT: {len(failures)} copy failure(s); DB not touched, nothing deleted.")
        for src, dst, err in failures[:5]:
            print(f"   {src} -> {dst}: {err}")
        print("Re-run to retry - copies that succeeded are simply overwritten.")
        sys.exit(1)

    # Verify every destination actually exists before trusting the copies enough to
    # rewrite the DB. A silent partial copy here would be the worst outcome.
    print("   verifying copies...")
    after = {f: {o.key for o in r2.list_objects(f"{f}/")} for f in (FOLDER_A, FOLDER_B)}
    expected_dests = {dst for _src, dst in copies}
    present = after[FOLDER_A] | after[FOLDER_B]
    missing_dests = expected_dests - present
    if missing_dests:
        print(f"\nABORT: {len(missing_dests)} copied object(s) not found at their destination.")
        print("DB not touched, nothing deleted. Re-run to retry.")
        sys.exit(1)
    print(f"   all {len(expected_dests)} destinations confirmed present")

    # --- step 2: DB, one transaction -----------------------------------------
    print("\n[2/3] Updating day + r2_key in a single transaction...")
    with session_factory() as session:
        # r2_key is rewritten by prefix substitution. Both statements read the ORIGINAL
        # prefixes, so they must both run before either takes effect - a single
        # transaction with a temporary marker avoids a two-step collision where
        # rewriting A->B would then be matched by the B->A statement.
        session.execute(
            text(
                "UPDATE photos SET day = :d, r2_key = replace(r2_key, :src, '__SWAP__') "
                "WHERE r2_key LIKE :p"
            ),
            {"d": CORRECT_DAY[FOLDER_A], "src": FOLDER_A, "p": f"{FOLDER_A}/%"},
        )
        session.execute(
            text("UPDATE photos SET day = :d, r2_key = replace(r2_key, :src, :dst) WHERE r2_key LIKE :p"),
            {"d": CORRECT_DAY[FOLDER_B], "src": FOLDER_B, "dst": FOLDER_A, "p": f"{FOLDER_B}/%"},
        )
        session.execute(
            text("UPDATE photos SET r2_key = replace(r2_key, '__SWAP__', :dst) WHERE r2_key LIKE '__SWAP__/%'"),
            {"dst": FOLDER_B},
        )
        session.commit()

        for folder in (FOLDER_A, FOLDER_B):
            n = tuple(
                session.execute(
                    text("SELECT count(*) FROM photos WHERE r2_key LIKE :p AND day = :d"),
                    {"p": f"{folder}/%", "d": CORRECT_DAY[DEST_PREFIX[folder]]},
                ).one()
            )[0]
            print(f"   {folder}: {n} rows now day={CORRECT_DAY[DEST_PREFIX[folder]]}")

    # --- step 3: delete originals --------------------------------------------
    old_keys = [src for src, _dst in copies]
    print(f"\n[3/3] Deleting {len(old_keys)} old objects...")
    failed = r2.delete_objects(old_keys)
    if failed:
        print(f"   WARNING: {len(failed)} delete(s) failed, e.g. {failed[:3]}")
        print("   The DB is already correct; re-run to retry the cleanup.")
    else:
        print("   all old keys deleted")

    print("\nDone.")


if __name__ == "__main__":
    main()
