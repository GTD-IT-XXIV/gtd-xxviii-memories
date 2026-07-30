"""Rename files in "Self Portrait (File responses)" to the respondent's full name,
using the "Full Name" column from "GTD XXVIII Freshie Registration Form (Responses).xlsx".

The form-response sheet's file-upload column stores the *original* filename each
file had at upload time (e.g. "17845411382746597526654339963733 - Aaron Revel.jpg").
Most files in the folder still have that exact original name, so we match on it
and rename to "<Full Name>.<ext>".

A handful of rows don't have an exact filename match (the sheet cell was blank,
held a bare Drive link, or the file was uploaded under a nickname/placeholder
name). Those files are left untouched and reported rather than guessed.

Usage:
    python rename_self_portraits.py            # dry run, just prints the plan
    python rename_self_portraits.py --apply     # actually renames the files
"""

import argparse
import os
import re
import sys

import openpyxl

sys.stdout.reconfigure(encoding="utf-8")

XLSX_PATH = "GTD XXVIII Freshie Registration Form (Responses).xlsx"
FOLDER = "Self Portrait (File responses)"
SHEET = "Form responses 1"

INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')


def load_name_by_filename():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    ws = wb[SHEET]
    mapping = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        full_name, upload_filename = row[1], row[3]
        if not full_name or not upload_filename:
            continue
        mapping[upload_filename] = full_name.strip()
    return mapping


def sanitize(name):
    name = INVALID_CHARS.sub("", name).strip()
    return re.sub(r"\s+", " ", name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="actually rename files (default: dry run)")
    args = parser.parse_args()

    name_by_filename = load_name_by_filename()
    files = sorted(os.listdir(FOLDER))

    plan = []  # (old_filename, new_filename)
    unmatched_files = []

    for filename in files:
        full_name = name_by_filename.get(filename)
        if full_name is None:
            unmatched_files.append(filename)
            continue
        ext = os.path.splitext(filename)[1]
        new_name = sanitize(full_name) + ext
        plan.append((filename, new_name))

    # Avoid clobbering files if two respondents resolve to the same target name.
    seen = {}
    for old_name, new_name in plan:
        seen.setdefault(new_name, []).append(old_name)
    collisions = {new: olds for new, olds in seen.items() if len(olds) > 1}

    print(f"{len(plan)} file(s) matched to a full name, {len(unmatched_files)} unmatched.\n")

    for old_name, new_name in plan:
        if old_name == new_name:
            continue
        marker = "  [COLLISION]" if new_name in collisions else ""
        print(f"  {old_name!r} -> {new_name!r}{marker}")

    if unmatched_files:
        print("\nUnmatched files (left as-is; no confident full-name match found):")
        for filename in unmatched_files:
            print(f"  {filename!r}")

    if collisions:
        print("\nCollisions (two source files would get the same target name; skipping these):")
        for new_name, olds in collisions.items():
            print(f"  {new_name!r} <- {olds!r}")

    if not args.apply:
        print("\nDry run only. Re-run with --apply to actually rename files.")
        return

    renamed, skipped = 0, 0
    for old_name, new_name in plan:
        if old_name == new_name or new_name in collisions:
            continue
        old_path = os.path.join(FOLDER, old_name)
        new_path = os.path.join(FOLDER, new_name)
        if os.path.exists(new_path):
            print(f"SKIP (target already exists): {new_name!r}")
            skipped += 1
            continue
        os.rename(old_path, new_path)
        renamed += 1

    print(f"\nRenamed {renamed} file(s), skipped {skipped}.")


if __name__ == "__main__":
    main()
