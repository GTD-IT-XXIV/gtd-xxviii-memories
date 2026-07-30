import logging
import os
from collections import deque
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from PIL import Image
from sqlalchemy.orm import Session

from app.clustering.incremental import assign_face
from app.clustering.similarity import ClusterIndex
from app.config import settings
from app.db.models import Face, Photo
from app.scanning import thumbnails
from app.scanning.face_engine import DetectedFace, detect_faces
from app.scanning.heic import register_heif_opener
from app.scanning.imaging import load_rgb_and_bgr, read_taken_at
from app.scanning.onedrive import is_cloud_placeholder
from app.scanning.walker import FoundFile, walk_images

logger = logging.getLogger(__name__)

# Detection+embedding (onnxruntime) and JPEG decode (libjpeg via Pillow) both release
# the GIL for their actual C-level work, so a thread pool gives real parallelism here
# despite Python's GIL - verified empirically (scripts/bench_parallel.py) to give a
# ~3-7x speedup on this machine before adding this. DB writes, thumbnailing, and
# cluster-centroid updates stay single-threaded in the caller (SQLAlchemy Sessions
# aren't thread-safe, and incremental cluster assignment is inherently sequential).
DEFAULT_MAX_WORKERS = min(8, os.cpu_count() or 4)


@dataclass
class ScanCounters:
    total_files_seen: int = 0
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _basename(path: str) -> str:
    return path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]


def _decode_and_detect(path: str) -> _DecodeResult:
    """Pure worker function - no DB/session access, safe to run in a thread pool."""
    try:
        pil_image, bgr_array, original_size = load_rgb_and_bgr(path, max_dim=settings.detect_max_dim)
        detected = detect_faces(bgr_array)
        return _DecodeResult(pil_image=pil_image, original_size=original_size, detected=detected, error=None)
    except Exception as exc:  # noqa: BLE001 - reported to the caller, not raised here
        return _DecodeResult(pil_image=None, original_size=None, detected=[], error=exc)


def _check_skip(session: Session, f: FoundFile) -> str | None:
    """Cheap sequential pre-check so unchanged/placeholder files never reach the
    thread pool. Returns 'unchanged', 'placeholder', or None if it needs decoding."""
    existing = session.query(Photo).filter(Photo.path == f.path).one_or_none()

    if existing is not None and existing.size_bytes == f.size_bytes and existing.mtime == f.mtime and existing.status == "processed":
        return "unchanged"

    if is_cloud_placeholder(f.path):
        if existing is None:
            session.add(
                Photo(
                    path=f.path,
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
    f: FoundFile,
    result: _DecodeResult,
    counters: ScanCounters,
    on_face_inserted: Callable[[Session, Face], None],
) -> None:
    existing = session.query(Photo).filter(Photo.path == f.path).one_or_none()
    if existing is None:
        photo = Photo(
            path=f.path,
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
        # Re-processing a changed file: drop its old faces (cascades via FK) so
        # stale embeddings/clusters don't linger.
        session.query(Face).filter(Face.photo_id == photo.id).delete()

    if result.error is not None:
        logger.exception("Failed to process %s", f.path, exc_info=result.error)
        session.flush()
        photo.status = "error"
        photo.error_message = str(result.error)[:500]
        counters.files_errored += 1
        return

    pil_image = result.pil_image
    photo.width, photo.height = result.original_size
    photo.taken_at = read_taken_at(pil_image)

    session.flush()  # assign photo.id

    thumbnails.save_photo_thumbnail(pil_image, photo.id)

    counters.faces_detected += len(result.detected)

    for det in result.detected:
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
        face.thumbnail_path = thumbnails.save_face_thumbnail(pil_image, face.id, det.bbox)
        on_face_inserted(session, face)

    photo.status = "processed"
    photo.error_message = None
    photo.last_scanned_at = _now()
    counters.files_processed += 1


def run_scan(
    session_factory: Callable[[], Session],
    scan_root: str,
    on_progress: Callable[[ScanCounters], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> ScanCounters:
    """Walks scan_root, detects+embeds faces in new/changed images, and incrementally
    assigns each face to a cluster (joining an existing person if the embedding is a
    close enough match, otherwise starting a new unlabeled cluster) - see
    app.clustering.incremental.assign_face.

    Decode+detect (the expensive part) runs in a bounded thread pool; DB writes,
    thumbnailing, and cluster assignment stay sequential in the calling thread.
    """
    register_heif_opener()
    counters = ScanCounters()

    found = walk_images(scan_root)
    counters.total_files_seen = len(found)
    if on_progress:
        on_progress(counters)

    session = session_factory()
    try:
        cluster_index = ClusterIndex.load(session)

        def on_face_inserted(s: Session, face: Face) -> None:
            assign_face(s, cluster_index, face)

        # Phase 1: cheap sequential pass - skip unchanged/placeholder files before
        # they'd ever reach the thread pool.
        to_process: list[FoundFile] = []
        for f in found:
            if should_stop is not None and should_stop():
                session.commit()
                return counters
            reason = _check_skip(session, f)
            if reason == "unchanged":
                counters.files_skipped_unchanged += 1
            elif reason == "placeholder":
                counters.files_skipped_placeholder += 1
            else:
                to_process.append(f)
            if on_progress:
                on_progress(counters)
        session.commit()

        # Phase 2: bounded sliding-window thread pool for decode+detect, sequential
        # DB write as each result comes back (in submission order).
        processed_since_commit = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            window: deque[tuple[FoundFile, Future]] = deque()
            it = iter(to_process)

            def submit_next() -> bool:
                nxt = next(it, None)
                if nxt is None:
                    return False
                window.append((nxt, executor.submit(_decode_and_detect, nxt.path)))
                return True

            for _ in range(max_workers * 2):
                if not submit_next():
                    break

            while window:
                if should_stop is not None and should_stop():
                    break
                f, fut = window.popleft()
                result = fut.result()
                counters.current_file = f.path
                _write_result(session, f, result, counters, on_face_inserted)

                if on_progress:
                    on_progress(counters)

                processed_since_commit += 1
                if processed_since_commit >= settings.commit_batch_size:
                    session.commit()
                    processed_since_commit = 0

                submit_next()

        session.commit()
        if on_progress:
            on_progress(counters)
    finally:
        session.close()

    return counters
