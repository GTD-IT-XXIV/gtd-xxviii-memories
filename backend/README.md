# GTD Face Recognition - Backend

Face detection/embedding/clustering pipeline for event photos. Two independent modes
share the same codebase and schema:

- **Local single-machine dev** - SQLite (`data/db.sqlite3`) + thumbnails saved to local
  disk, served by the FastAPI app + local Vite frontend. This is the default; nothing
  below is required to use it.
- **Multi-machine batch scan** - several laptops each scan their own slice of a shared
  event-photo folder in parallel, writing to a shared **Neon Postgres** database and
  uploading images to a shared **Cloudflare R2** bucket. This is what actually gets
  used for real event photos, since face detection is CPU-heavy and splitting the work
  across laptops is much faster than one machine scanning everything.

The Postgres/R2 side is what `web/` (the Next.js gallery/review app) reads from -
those two pieces of this repo are meant to be run together: Python here does the
one-time-per-event compute (detect, embed, cluster, upload), `web/` is the ongoing
read/write UI on top of the result.

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows; use .venv/bin/pip on macOS/Linux
```

## Local single-machine dev

No env vars required. Useful for testing pipeline changes against a small folder
before running a real batch scan.

```bash
.venv/Scripts/python.exe -m scripts.run_scan_cli "C:\path\to\test\folder"
.venv/Scripts/python.exe -m scripts.run_reference_import_cli "C:\path\to\committee"
```

Data lands in `data/db.sqlite3` + `data/thumbnails/`, served by the FastAPI app
(`app/main.py`) to the local Vite frontend (`../frontend`).

## Multi-machine batch scan (Neon + R2)

### One-time setup

Copy `.env.example` to `.env` and fill in:

- `database_url` - Neon Postgres connection string (Neon dashboard -> Connection
  Details). Standard `postgresql://` scheme - matches the `psycopg2-binary` driver in
  `requirements.txt`, no need to rewrite it to `postgresql+psycopg://`.
- `r2_account_id`, `r2_access_key_id`, `r2_secret_access_key`, `r2_bucket_name` -
  Cloudflare R2 (S3-compatible) bucket credentials, from the R2 dashboard -> Manage API
  Tokens. Endpoint is derived as `https://{r2_account_id}.r2.cloudflarestorage.com`.

These are only read by the two `*_batch_cli.py` scripts below - the local single-
machine scripts and the FastAPI app ignore them entirely and keep using SQLite.

### Seed labeled people from reference photos (once per event)

Run against a folder of named reference photos (e.g. `committee/`, filenames like
`audria1.jpg` - a name + trailing digit, grouped by parent folder) to create
`labeled` clusters with real names/OGs before the main scan runs, so those people get
auto-recognized instead of needing manual review:

```bash
.venv/Scripts/python.exe -m scripts.run_reference_import_batch_cli "C:\path\to\committee" --init-db
```

### Scan event photos (once per event day, split across laptops)

```bash
# 4-way split across 4 laptops, day 1:
.venv/Scripts/python.exe -m scripts.run_batch_scan_cli --scan-root "C:\...\day1" --batch 0 --total-batches 4 --day 1 --init-db
.venv/Scripts/python.exe -m scripts.run_batch_scan_cli --scan-root "D:\...\day1" --batch 1 --total-batches 4 --day 1
.venv/Scripts/python.exe -m scripts.run_batch_scan_cli --scan-root "C:\...\day1" --batch 2 --total-batches 4 --day 1
.venv/Scripts/python.exe -m scripts.run_batch_scan_cli --scan-root "C:\...\day1" --batch 3 --total-batches 4 --day 1
```

Repeat with `--day 2` pointed at that day's folder, `--day 3`, etc. - `day` powers the
gallery's day filter in `web/`.

Flags:

- `--scan-root` (required) - this machine's local path to the shared photo folder.
  Different laptops can mount "the same" folder under different drive letters/
  usernames - see splitting algorithm below for why that's fine.
- `--batch` / `--total-batches` (required) - this machine's 0-based batch index and
  the total number of machines splitting the scan.
- `--day` - event day (1, 2, 3, ...) stamped onto every photo this run
  creates/reprocesses. Omit only for a one-off test scan not tied to a specific day.
- `--init-db` - idempotently creates/updates the Postgres schema first. Only one
  machine needs to pass this per database, but it's harmless to pass on every run/
  every machine if that's simpler to remember - it's a no-op once the schema is
  current.
- `--max-workers` - decode/detect thread pool size (default: `min(8, cpu_count)`).
- `--refresh-every` - how often (in files processed) to reload cluster state from the
  DB, to pick up clusters other machines created concurrently (default: 200).

### Alternative: R2-sourced batch scan (skip per-laptop OneDrive downloads)

The flow above requires every laptop to have `--scan-root` locally, which in practice
has meant every laptop syncing/downloading the whole shared OneDrive folder before
scanning even its own slice. An alternative that only needs ONE machine to touch
OneDrive:

```bash
# Once, on a single machine, after downloading+extracting a OneDrive zip locally:
.venv/Scripts/python.exe -m scripts.upload_originals_to_r2_cli --source-root "C:\...\day1" --prefix raw/day1

# Then, on each laptop (no OneDrive access needed - pulls straight from R2):
.venv/Scripts/python.exe -m scripts.run_batch_scan_from_r2_cli --prefix raw/day1 --batch 0 --total-batches 4 --day 1 --init-db
.venv/Scripts/python.exe -m scripts.run_batch_scan_from_r2_cli --prefix raw/day1 --batch 1 --total-batches 4 --day 1
.venv/Scripts/python.exe -m scripts.run_batch_scan_from_r2_cli --prefix raw/day1 --batch 2 --total-batches 4 --day 1
.venv/Scripts/python.exe -m scripts.run_batch_scan_from_r2_cli --prefix raw/day1 --batch 3 --total-batches 4 --day 1
```

`upload_originals_to_r2_cli.py` is a pure storage bulk-upload (no Postgres, no face
detection) - resumable, skips keys already in R2. `run_batch_scan_from_r2_cli.py` then
mirrors `run_batch_scan_cli.py` exactly (same `belongs_to_batch()` partitioning, same
resumability, same concurrent-clustering safety) except it lists/downloads its batch
slice from R2 instead of walking a local folder, and reuses the already-uploaded
original's R2 key directly (`photos.r2_key`) instead of re-uploading it.

### Splitting algorithm

Each file's batch membership is decided by `belongs_to_batch()`
(`app/scanning/batch_pipeline.py`): SHA-256 hash of the file's path **relative to
`--scan-root`** (not its absolute path - different laptops mount the same shared
folder under different absolute paths), modulo `--total-batches`:

```python
h = int(sha256(relative_posix_path).hexdigest(), 16)
belongs_to_this_batch = (h % total_batches) == batch
```

Deliberately **not** index/enumeration-based (e.g. "every Nth file seen") - directory
walk order isn't guaranteed stable, so any position-based scheme reshuffles which
files belong to which batch whenever a photo is added or removed anywhere earlier in
the walk. Hashing the relative path means: for a fixed `--total-batches`, the same
`--batch` always resolves to the identical file set regardless of what else changes in
the folder, so a re-run after photos are added/removed elsewhere never moves a file
between batches, drops it, or double-processes it. Changing `--total-batches` between
runs is an inherent re-partition (expected) - just not something file churn on its own
should ever trigger.

### Concurrency (multiple laptops writing to the same DB at once)

- Batches never overlap by file, so `photos`/`faces` rows never collide between
  machines.
- Cluster centroid updates *can* collide (two machines independently assigning
  different photos to the same person's cluster) - mitigated with a Postgres row lock
  (`SELECT ... FOR UPDATE`, see `assign_face_locked` in `app/clustering/incremental.py`)
  held only for the duration of one face's read-modify-write, plus periodic
  in-memory cluster-index reloads (`--refresh-every`) so a machine picks up clusters
  other machines just created.
- Known, accepted gap: two machines can each spawn a duplicate new (unlabeled) cluster
  for the same previously-unseen person if they process matching faces in the same
  narrow window before either refreshes. Not fully closable without serializing all
  cluster creation globally (which would defeat the point of parallelizing) - cleaned
  up via the existing manual merge workflow in `web/`'s `/review` page, same as any
  other clustering fragmentation.

### Resumability

Safe to interrupt and re-run with the same `--batch`/`--total-batches`/`--scan-root`.
Dedup key is each file's relative path (stored in `photos.path`), not an incrementing
counter, so already-`processed` files are recognized and skipped without re-decoding
or re-uploading. A file interrupted mid-processing has nothing committed for it (DB
commits only happen after the corresponding R2 upload succeeds), so it's naturally
picked up and reprocessed from scratch on the next run.
