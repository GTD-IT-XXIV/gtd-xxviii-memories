"""Multi-machine batch scan: several laptops each run this against their own
deterministic slice of a shared scan_root, writing to a shared Neon Postgres DB and
uploading originals/thumbnails to a shared Cloudflare R2 bucket, instead of the local
SQLite + local-disk-thumbnails single-machine pipeline in app/scanning/pipeline.py
(which this module does not modify or depend on beyond sharing helpers).

Entry point: run_batch_scan(), invoked by scripts/run_batch_scan_cli.py.
"""

import hashlib
import io
import logging
import os
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from PIL import Image
from sqlalchemy.orm import Session

from app.clustering.incremental import assign_face_locked
from app.clustering.similarity import ClusterIndex
from app.config import settings
from app.db.models import Face, Photo
from app.scanning import thumbnails
from app.scanning.face_engine import DetectedFace, detect_faces
from app.scanning.heic import register_heif_opener
from app.scanning.imaging import load_rgb_and_bgr, read_taken_at
from app.scanning.onedrive import is_cloud_placeholder
from app.scanning.walker import FoundFile, walk_images
from app.storage.r2 import R2Client, R2Object, guess_content_type

logger = logging.getLogger(__name__)

DEFAULT_MAX_WORKERS = min(8, os.cpu_count() or 4)

# How often (in files processed) to reload the in-memory ClusterIndex from the DB, so
# this machine picks up clusters created/updated by *other* machines running
# concurrently. See the docstring on app.clustering.incremental.assign_face_locked for
# the race this mitigates (and the one it doesn't fully close).
DEFAULT_REFRESH_EVERY = 200


def relative_posix_path(scan_root: str, file_path: str) -> str:
    """The stable, machine-independent identity of a file: its path relative to
    scan_root, normalized to forward slashes. Different laptops mount "the same
    shared folder" under different absolute paths (different drive letters/
    usernames), so this - not the absolute path - is what must be used both as the
    batch-partition key and as the cross-machine dedup key stored in photos.path.

    Uses os.path.relpath (purely lexical string manipulation) rather than
    Path.resolve()+relative_to: file_path always comes from walk_images(scan_root),
    which builds every entry's path via os.path.join starting from the exact same
    scan_root string, so a lexical relpath is both correct and cheap - no extra
    filesystem/symlink resolution, and no risk of Path.resolve() prepending a
    Windows "\\\\?\\" extended-length prefix that would otherwise leak into the
    stored relative path.
    """
    rel = os.path.relpath(file_path, scan_root)
    if rel.startswith(".."):
        raise ValueError(f"{file_path!r} is not under scan_root {scan_root!r}")
    return Path(rel).as_posix()


def belongs_to_batch(rel_path: str, batch: int, total_batches: int) -> bool:
    """Deterministic partitioning by a stable hash of the relative path - NOT by
    enumeration order/index. os.scandir order isn't guaranteed stable, and any
    index-based scheme (e.g. "every Nth file seen") reshuffles which files belong to
    which batch whenever a file is added/removed anywhere earlier in the walk. Hashing
    the relative path means a fixed --total-batches always yields the identical file
    set for a given --batch, regardless of what else in scan_root has changed, so
    re-running the same args after photos are added/removed elsewhere never moves a
    file between batches or drops/duplicates it. Changing --total-batches between runs
    is an inherent re-partitioning (expected and fine) - just not something file
    additions/deletions should ever trigger on their own for a fixed N.
    """
    h = int(hashlib.sha256(rel_path.encode("utf-8")).hexdigest(), 16)
    return (h % total_batches) == batch


@dataclass
class BatchScanCounters:
    total_files_seen: int = 0
    files_in_batch: int = 0
    files_processed: int = 0
    files_skipped_unchanged: int = 0
    files_skipped_placeholder: int = 0
    files_errored: int = 0
    faces_detected: int = 0
    current_file: str = ""


@dataclass
class _DecodeResult:
    pil_image: Image.Image | None
    original_size: tuple[int, int] | None
    detected: list[DetectedFace]
    error: Exception | None


@dataclass
class _BatchFile:
    found: FoundFile
    rel_path: str


@dataclass
class _R2BatchFile:
    """The R2-sourced counterpart of _BatchFile: `key` is the full R2 object key
    (prefix + rel_path), `rel_path` is the same stable cross-machine identity used for
    both batch-partitioning and the photos.path dedup key - the R2 upload
    (scripts/upload_originals_to_r2_cli.py) preserves the source folder's relative
    path structure under the prefix, so stripping the prefix recovers it exactly."""

    key: str
    rel_path: str
    size_bytes: int
    mtime: float


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _basename(path: str) -> str:
    return path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]


def _decode_and_detect(path: str) -> _DecodeResult:
    """Pure worker function - no DB/session/R2 access, safe to run in a thread pool.
    Mirrors app.scanning.pipeline._decode_and_detect exactly."""
    try:
        pil_image, bgr_array, original_size = load_rgb_and_bgr(path, max_dim=settings.detect_max_dim)
        detected = detect_faces(bgr_array)
        return _DecodeResult(pil_image=pil_image, original_size=original_size, detected=detected, error=None)
    except Exception as exc:  # noqa: BLE001 - reported to the caller, not raised here
        return _DecodeResult(pil_image=None, original_size=None, detected=[], error=exc)


def _select_batch_files(scan_root: str, batch: int, total_batches: int) -> tuple[list[_BatchFile], int]:
    found = walk_images(scan_root)
    total_files_seen = len(found)
    batch_files: list[_BatchFile] = []
    for f in found:
        try:
            rel = relative_posix_path(scan_root, f.path)
        except ValueError:
            # f.path isn't actually under scan_root (shouldn't happen - walk_images
            # only descends from scan_root - but skip defensively rather than crash a
            # multi-hour scan over one odd path).
            logger.warning("Skipping file outside scan_root: %s", f.path)
            continue
        if belongs_to_batch(rel, batch, total_batches):
            batch_files.append(_BatchFile(found=f, rel_path=rel))
    return batch_files, total_files_seen


def _select_batch_files_r2(r2_client: R2Client, prefix: str, batch: int, total_batches: int) -> tuple[list[_R2BatchFile], int]:
    """R2-sourced counterpart of _select_batch_files: lists objects under `prefix`
    (uploaded by scripts/upload_originals_to_r2_cli.py) instead of walking a local
    scan_root, then applies the identical belongs_to_batch() partitioning to the
    prefix-stripped key."""
    objects = r2_client.list_objects(prefix)
    total_files_seen = len(objects)
    norm_prefix = prefix.rstrip("/") + "/"
    batch_files: list[_R2BatchFile] = []
    for obj in objects:
        if not obj.key.startswith(norm_prefix):
            continue
        rel = obj.key[len(norm_prefix) :]
        if belongs_to_batch(rel, batch, total_batches):
            batch_files.append(_R2BatchFile(key=obj.key, rel_path=rel, size_bytes=obj.size, mtime=obj.last_modified))
    return batch_files, total_files_seen


def _check_skip_r2(session: Session, bf: _R2BatchFile) -> str | None:
    """R2-sourced counterpart of _check_skip. No cloud-placeholder concept here (R2
    objects are always fully present once listed) - only 'unchanged' or None."""
    existing = session.query(Photo).filter(Photo.path == bf.rel_path).one_or_none()
    if existing is not None and existing.size_bytes == bf.size_bytes and existing.mtime == bf.mtime and existing.status == "processed":
        return "unchanged"
    return None


def _decode_and_detect_r2(r2_client: R2Client, key: str) -> _DecodeResult:
    """R2-sourced counterpart of _decode_and_detect: downloads the object's bytes from
    R2 (network I/O, releases the GIL like the local version's disk read/libjpeg
    decode does) instead of reading a local path, then decodes+detects identically.
    Safe to run in the thread pool alongside other downloads."""
    try:
        data = r2_client.download_bytes(key)
        pil_image, bgr_array, original_size = load_rgb_and_bgr(io.BytesIO(data), max_dim=settings.detect_max_dim)
        detected = detect_faces(bgr_array)
        return _DecodeResult(pil_image=pil_image, original_size=original_size, detected=detected, error=None)
    except Exception as exc:  # noqa: BLE001 - reported to the caller, not raised here
        return _DecodeResult(pil_image=None, original_size=None, detected=[], error=exc)


def _write_result_r2(
    session: Session,
    bf: _R2BatchFile,
    result: _DecodeResult,
    counters: BatchScanCounters,
    r2_client: R2Client,
    cluster_index: ClusterIndex,
    day: int | None,
) -> None:
    """R2-sourced counterpart of _write_result. The original is already sitting in R2
    (uploaded by scripts/upload_originals_to_r2_cli.py before this scan ever ran), so
    unlike _write_result there is no original-bytes upload here - photo.r2_key is set
    directly to the pre-existing key, saving a redundant download+reupload round trip.
    Everything after that (thumbnail + faces) is identical, via _finish_processed_photo."""
    existing = session.query(Photo).filter(Photo.path == bf.rel_path).one_or_none()
    if existing is None:
        photo = Photo(
            path=bf.rel_path,
            filename=_basename(bf.rel_path),
            size_bytes=bf.size_bytes,
            mtime=bf.mtime,
            status="pending",
            created_at=_now(),
        )
        session.add(photo)
    else:
        photo = existing
        photo.size_bytes = bf.size_bytes
        photo.mtime = bf.mtime
        # Re-processing a changed/interrupted file: drop its old faces so stale
        # embeddings/clusters don't linger - see _write_result's resumability note.
        session.query(Face).filter(Face.photo_id == photo.id).delete()

    if day is not None:
        photo.day = day

    if result.error is not None:
        logger.exception("Failed to process %s", bf.key, exc_info=result.error)
        session.flush()
        photo.status = "error"
        photo.error_message = str(result.error)[:500]
        counters.files_errored += 1
        session.commit()
        return

    pil_image = result.pil_image
    assert pil_image is not None
    photo.width, photo.height = result.original_size
    photo.taken_at = read_taken_at(pil_image)
    photo.r2_key = bf.key

    session.flush()  # assign photo.id

    _finish_processed_photo(session, photo, pil_image, result.detected, counters, r2_client, cluster_index)


def _check_skip(session: Session, bf: _BatchFile) -> str | None:
    """Cheap sequential pre-check so unchanged/placeholder files never reach the
    thread pool or R2. Dedup key is the relative path (rel_path), not the absolute
    path, so a file already processed by another laptop - or in a prior run on this
    laptop - is recognized regardless of which machine's absolute mount path it
    currently has. Returns 'unchanged', 'placeholder', or None if it needs decoding."""
    f = bf.found
    existing = session.query(Photo).filter(Photo.path == bf.rel_path).one_or_none()

    if existing is not None and existing.size_bytes == f.size_bytes and existing.mtime == f.mtime and existing.status == "processed":
        return "unchanged"

    if is_cloud_placeholder(f.path):
        if existing is None:
            session.add(
                Photo(
                    path=bf.rel_path,
                    filename=_basename(f.path),
                    size_bytes=f.size_bytes,
                    mtime=f.mtime,
                    status="skipped_placeholder",
                    created_at=_now(),
                )
            )
        else:
            existing.status = "skipped_placeholder"
            existing.size_bytes = f.size_bytes
            existing.mtime = f.mtime
        return "placeholder"

    return None


def _write_result(
    session: Session,
    bf: _BatchFile,
    result: _DecodeResult,
    counters: BatchScanCounters,
    r2_client: R2Client,
    cluster_index: ClusterIndex,
    day: int | None,
) -> None:
    """Writes one file's Photo/Face rows, uploads its original + thumbnails to R2, and
    incrementally cluster-assigns each face - committing promptly after each
    cluster-touching step (see assign_face_locked's docstring for why: short
    transactions keep the row-level cluster lock held only briefly, so other machines
    scanning concurrently aren't blocked long).

    Resumability note: DB commits only happen AFTER the corresponding R2 upload
    succeeds, so if this process is killed mid-file, the in-flight transaction is
    never committed and a re-run's _check_skip sees the photo as not yet
    'processed' and reprocesses it from scratch (existing Face rows for that photo_id,
    if any were already committed for earlier faces in the same file before the crash,
    are deleted and recreated below - this mirrors the same limitation already present
    in app.scanning.pipeline._write_result for a changed/reprocessed file: the
    cluster-centroid contribution from those deleted faces isn't retroactively
    reverted. In practice this only matters for a crash occurring mid-file, not
    between files, and is cleaned up the same way as any other clustering drift - via
    the manual merge/review workflow.
    """
    f = bf.found
    existing = session.query(Photo).filter(Photo.path == bf.rel_path).one_or_none()
    if existing is None:
        photo = Photo(
            path=bf.rel_path,
            filename=_basename(f.path),
            size_bytes=f.size_bytes,
            mtime=f.mtime,
            status="pending",
            created_at=_now(),
        )
        session.add(photo)
    else:
        photo = existing
        photo.size_bytes = f.size_bytes
        photo.mtime = f.mtime
        # Re-processing a changed/interrupted file: drop its old faces (cascades via
        # FK) so stale embeddings/clusters don't linger. See resumability note above.
        session.query(Face).filter(Face.photo_id == photo.id).delete()

    if day is not None:
        photo.day = day

    if result.error is not None:
        logger.exception("Failed to process %s", f.path, exc_info=result.error)
        session.flush()
        photo.status = "error"
        photo.error_message = str(result.error)[:500]
        counters.files_errored += 1
        session.commit()
        return

    pil_image = result.pil_image
    assert pil_image is not None
    photo.width, photo.height = result.original_size
    photo.taken_at = read_taken_at(pil_image)

    session.flush()  # assign photo.id

    try:
        original_bytes = Path(f.path).read_bytes()
        # Preserve the source file's own extension (.jpg/.png/.heic/...) rather than
        # hardcoding ".jpg" - the object's bytes are the untouched original file, and
        # local dev's GET /photos/{id}/full (FileResponse) also just serves the
        # original file's actual bytes/type as-is, so this stays consistent with that
        # existing "full" meaning originals/{photo_id}<original-ext>.
        ext = Path(f.path).suffix.lower() or ".jpg"
        original_key = f"originals/{photo.id}{ext}"
        r2_client.upload_bytes(original_key, original_bytes, content_type=guess_content_type(f.path))
        photo.r2_key = original_key
    except Exception as exc:  # noqa: BLE001 - R2/network failure treated like a decode error
        logger.exception("Failed to upload %s to R2", f.path)
        photo.status = "error"
        photo.error_message = f"R2 upload failed: {exc}"[:500]
        counters.files_errored += 1
        session.commit()
        return

    _finish_processed_photo(session, photo, pil_image, result.detected, counters, r2_client, cluster_index)


def _finish_processed_photo(
    session: Session,
    photo: Photo,
    pil_image: Image.Image,
    detected: list[DetectedFace],
    counters: BatchScanCounters,
    r2_client: R2Client,
    cluster_index: ClusterIndex,
) -> None:
    """Shared tail end of processing one decoded photo, once its original is already
    stored in R2 (either just-uploaded by _write_result, or pre-existing from a prior
    upload_originals_to_r2_cli.py run, in _write_result_r2's case): uploads the photo
    thumbnail, then each detected face's thumbnail + cluster assignment, and marks the
    photo 'processed'. Identical regardless of where the original came from."""
    thumb_key = f"thumbnails/photos/{photo.id}.jpg"
    r2_client.upload_bytes(thumb_key, thumbnails.photo_thumbnail_bytes(pil_image), content_type="image/jpeg")
    photo.r2_thumbnail_key = thumb_key

    counters.faces_detected += len(detected)

    for det in detected:
        face = Face(
            photo_id=photo.id,
            bbox_x=det.bbox[0],
            bbox_y=det.bbox[1],
            bbox_w=det.bbox[2],
            bbox_h=det.bbox[3],
            det_score=det.det_score,
            embedding=det.embedding.tobytes(),
            created_at=_now(),
        )
        session.add(face)
        session.flush()  # assign face.id

        face_thumb_key = f"thumbnails/faces/{face.id}.jpg"
        r2_client.upload_bytes(
            face_thumb_key, thumbnails.face_thumbnail_bytes(pil_image, det.bbox), content_type="image/jpeg"
        )
        face.r2_thumbnail_key = face_thumb_key

        assign_face_locked(session, cluster_index, face)
        # Commit now - see docstring: keeps the cluster row-lock (if one was taken)
        # held only as long as this one face's read-modify-write, not the whole photo.
        session.commit()

    photo.status = "processed"
    photo.error_message = None
    photo.last_scanned_at = _now()
    counters.files_processed += 1
    session.commit()


def run_batch_scan(
    session_factory: Callable[[], Session],
    scan_root: str,
    batch: int,
    total_batches: int,
    r2_client: R2Client,
    on_progress: Callable[[BatchScanCounters], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    refresh_every: int = DEFAULT_REFRESH_EVERY,
    day: int | None = None,
) -> BatchScanCounters:
    """Walks scan_root, keeps only the files whose relative-path hash belongs to this
    machine's batch (see belongs_to_batch), detects+embeds faces, uploads originals
    and thumbnails to R2, and incrementally cluster-assigns each face against the
    shared Postgres DB - safe to run concurrently with other machines doing the same
    against different batches of the same scan_root (see assign_face_locked).

    Safely re-runnable: already-'processed' files (by relative-path dedup key) are
    skipped without re-decoding or re-uploading; interrupted files are reprocessed
    from scratch on the next run (see _write_result's resumability note).

    `day` (e.g. 1, 2, 3 - the event day this scan_root's photos were taken on, since
    organizers run one batch scan per day against that day's photo folder) is stamped
    onto every photo this run creates or reprocesses; pass None to leave it untouched
    (e.g. a local test scan not tied to a specific event day).
    """
    register_heif_opener()
    counters = BatchScanCounters()

    batch_files, total_files_seen = _select_batch_files(scan_root, batch, total_batches)
    counters.total_files_seen = total_files_seen
    counters.files_in_batch = len(batch_files)
    if on_progress:
        on_progress(counters)

    session = session_factory()
    try:
        cluster_index = ClusterIndex.load(session)

        # Phase 1: cheap sequential pass - skip unchanged/placeholder files before
        # they'd ever reach the thread pool or R2.
        to_process: list[_BatchFile] = []
        for bf in batch_files:
            if should_stop is not None and should_stop():
                session.commit()
                return counters
            reason = _check_skip(session, bf)
            if reason == "unchanged":
                counters.files_skipped_unchanged += 1
            elif reason == "placeholder":
                counters.files_skipped_placeholder += 1
            else:
                to_process.append(bf)
            if on_progress:
                on_progress(counters)
        session.commit()

        # Phase 2: bounded sliding-window thread pool for decode+detect (pure,
        # network/DB-free - safe off the main thread); DB writes, R2 uploads, and
        # cluster assignment stay sequential in the calling thread, same structure as
        # app.scanning.pipeline.run_scan.
        processed_since_refresh = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            window: deque[tuple[_BatchFile, Future]] = deque()
            it = iter(to_process)

            def submit_next() -> bool:
                nxt = next(it, None)
                if nxt is None:
                    return False
                window.append((nxt, executor.submit(_decode_and_detect, nxt.found.path)))
                return True

            for _ in range(max_workers * 2):
                if not submit_next():
                    break

            while window:
                if should_stop is not None and should_stop():
                    break
                bf, fut = window.popleft()
                result = fut.result()
                counters.current_file = bf.found.path
                _write_result(session, bf, result, counters, r2_client, cluster_index, day)

                if on_progress:
                    on_progress(counters)

                processed_since_refresh += 1
                if processed_since_refresh >= refresh_every:
                    # Pick up clusters created/updated by OTHER machines running
                    # concurrently, so this machine doesn't spawn a duplicate
                    # unlabeled cluster for a person another machine already just
                    # created one for. Does not fully close that race (see
                    # assign_face_locked's docstring) - just narrows the window.
                    cluster_index = ClusterIndex.load(session)
                    processed_since_refresh = 0

                submit_next()

        if on_progress:
            on_progress(counters)
    finally:
        session.close()

    return counters


def run_batch_scan_from_r2(
    session_factory: Callable[[], Session],
    r2_client: R2Client,
    prefix: str,
    batch: int,
    total_batches: int,
    on_progress: Callable[[BatchScanCounters], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    refresh_every: int = DEFAULT_REFRESH_EVERY,
    day: int | None = None,
) -> BatchScanCounters:
    """R2-sourced counterpart of run_batch_scan: instead of walking a local scan_root
    that every laptop must have synced/downloaded, lists objects already uploaded to
    R2 under `prefix` (by scripts/upload_originals_to_r2_cli.py, typically run once by
    a single machine after a manual OneDrive download) and downloads only this
    machine's batch slice from R2 - same belongs_to_batch() partitioning, same
    resumability guarantees, same concurrent-multi-machine clustering safety as
    run_batch_scan. See scripts/run_batch_scan_from_r2_cli.py.

    No is_cloud_placeholder handling here - unlike a local OneDrive Files-On-Demand
    mount, an object listed by R2 is always fully present, so there's no
    'skipped_placeholder' status/counter in this path (files_skipped_placeholder stays
    0 for an R2-sourced run).
    """
    register_heif_opener()
    counters = BatchScanCounters()

    batch_files, total_files_seen = _select_batch_files_r2(r2_client, prefix, batch, total_batches)
    counters.total_files_seen = total_files_seen
    counters.files_in_batch = len(batch_files)
    if on_progress:
        on_progress(counters)

    session = session_factory()
    try:
        cluster_index = ClusterIndex.load(session)

        to_process: list[_R2BatchFile] = []
        for bf in batch_files:
            if should_stop is not None and should_stop():
                session.commit()
                return counters
            reason = _check_skip_r2(session, bf)
            if reason == "unchanged":
                counters.files_skipped_unchanged += 1
            else:
                to_process.append(bf)
            if on_progress:
                on_progress(counters)
        session.commit()

        processed_since_refresh = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            window: deque[tuple[_R2BatchFile, Future]] = deque()
            it = iter(to_process)

            def submit_next() -> bool:
                nxt = next(it, None)
                if nxt is None:
                    return False
                window.append((nxt, executor.submit(_decode_and_detect_r2, r2_client, nxt.key)))
                return True

            for _ in range(max_workers * 2):
                if not submit_next():
                    break

            while window:
                if should_stop is not None and should_stop():
                    break
                bf, fut = window.popleft()
                result = fut.result()
                counters.current_file = bf.rel_path
                _write_result_r2(session, bf, result, counters, r2_client, cluster_index, day)

                if on_progress:
                    on_progress(counters)

                processed_since_refresh += 1
                if processed_since_refresh >= refresh_every:
                    cluster_index = ClusterIndex.load(session)
                    processed_since_refresh = 0

                submit_next()

        if on_progress:
            on_progress(counters)
    finally:
        session.close()

    return counters
