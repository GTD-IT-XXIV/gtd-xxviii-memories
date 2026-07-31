"""One-time (per event day), single-machine bulk upload: pushes every image file
under --source-root to the shared R2 bucket under a raw/ prefix, preserving relative
path structure - completely decoupled from face detection.

Run this ONCE, on whichever single machine has the photos locally (e.g. after
manually downloading + extracting a OneDrive zip). It does not touch Postgres at all.
Afterwards, scripts/run_batch_scan_from_r2_cli.py lets N machines each pull their own
batch slice straight from R2 to do face detection - none of them need a local copy of
the whole folder, only this one upload machine does.

    .venv/Scripts/python.exe -m scripts.upload_originals_to_r2_cli --source-root "C:\\...\\DAY 1 PHOTO"

Safe to interrupt and re-run: skips any key that already exists in R2 (checked via
R2Client.object_exists), so a re-run only uploads what's missing.
"""

import argparse
import sys

from app.config import settings
from app.scanning.batch_pipeline import relative_posix_path
from app.scanning.walker import walk_images
from app.storage.r2 import R2Client, guess_content_type, r2_config_from_settings

DEFAULT_PREFIX = "raw"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-root", required=True, help="Local folder to upload (e.g. an extracted OneDrive zip)")
    parser.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help=f"R2 key prefix photos are uploaded under (default: {DEFAULT_PREFIX!r}) - "
        "must match the --prefix passed to run_batch_scan_from_r2_cli.py later",
    )
    args = parser.parse_args()

    try:
        r2_client = R2Client(r2_config_from_settings(settings))
    except RuntimeError as exc:
        print(str(exc))
        sys.exit(1)

    print(f"Scanning {args.source_root} ...")
    found = walk_images(args.source_root)
    total = len(found)
    print(f"Found {total} image files")

    uploaded = skipped = errored = 0
    for i, f in enumerate(found, 1):
        rel = relative_posix_path(args.source_root, f.path)
        key = f"{args.prefix}/{rel}"
        try:
            if r2_client.object_exists(key):
                skipped += 1
            else:
                with open(f.path, "rb") as fh:
                    data = fh.read()
                r2_client.upload_bytes(key, data, content_type=guess_content_type(f.path))
                uploaded += 1
        except Exception as exc:  # noqa: BLE001 - keep going, report at the end
            print(f"\nERROR uploading {f.path}: {exc}")
            errored += 1

        print(
            f"\r{i}/{total} (uploaded={uploaded} skipped_existing={skipped} errored={errored})",
            end="",
            flush=True,
        )

    print()
    print(f"Done. Uploaded: {uploaded}, already in R2: {skipped}, errored: {errored}")
    if errored:
        sys.exit(1)


if __name__ == "__main__":
    main()
