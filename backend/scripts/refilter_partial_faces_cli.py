"""Retroactively applies the partial-face keypoint filter to faces that were detected
BEFORE that filter existed, to cut down the review queue.

Background: the keypoint check in app/scanning/face_engine.py (_keypoints_within_bbox,
added in commit e9e34f6) rejects detections where the 5 landmarks are missing or fall
well outside the face's own bbox - a reliable "the detector only saw part of a face"
signal. It is a DETECTION-time gate: it decides whether a face row is ever created and
does nothing to rows already in the database. Faces scanned before it landed therefore
still carry partial-face detections, and those inflate the review queue.

Why this has to re-open the source images: the check needs InsightFace's 5-point
landmarks (`f.kps`), and those are NOT persisted anywhere - the faces table stores only
bbox/det_score/embedding. So there is no DB-only way to re-evaluate an existing row.
This script re-downloads each candidate's source photo from R2, re-runs detection, and
matches the fresh detections back to the stored faces by bbox IoU.

What it marks (never DELETEs):
  - A stored face is judged "partial" when the re-detection finds an overlapping
    detection that FAILS the keypoint check, or finds no overlapping detection at all
    at today's thresholds (i.e. today's pipeline would not have produced this face).
  - A cluster is marked status='discarded' only when EVERY one of its faces is judged
    partial. A cluster with even one good face is left completely alone - it still
    represents a real person and belongs in review.
  - 'discarded' is the same non-destructive status the review page's "Discard (not a
    person)" button sets (web/src/app/api/clusters/[id]/discard). It drops the cluster
    out of ClusterIndex.load() (app/clustering/similarity.py loads only unlabeled/
    labeled), so it stops matching and stops appearing in review, but every row and
    embedding is preserved and the decision is reversible with an UPDATE.

Scope guards - this only ever considers clusters that are status='unlabeled'. Labeled
people are never touched, so a bad judgment here can't lose someone's identified
photos.

Defaults to a DRY RUN: reports exactly how many clusters/faces would be discarded and
writes nothing. Pass --yes to apply.

Run from backend/:
    .venv/Scripts/python.exe -m scripts.refilter_partial_faces_cli                  # dry run, whole backlog
    .venv/Scripts/python.exe -m scripts.refilter_partial_faces_cli --limit 50       # dry run, quick sample
    .venv/Scripts/python.exe -m scripts.refilter_partial_faces_cli --yes            # apply
"""

import argparse
import io
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import text

from app.config import settings
from app.db.postgres import build_postgres_session_factory
from app.scanning.face_engine import _get_app, _keypoints_within_bbox
from app.scanning.heic import register_heif_opener
from app.scanning.imaging import load_rgb_and_bgr
from app.storage.r2 import R2Client, r2_config_from_settings

# Faces created before this instant predate the keypoint filter (commit e9e34f6,
# authored 2026-08-01 04:57 +0800 == 2026-07-31T20:57Z). faces.created_at is stored as
# an ISO-8601 TEXT column, so a plain string comparison is a correct ordering here.
KEYPOINT_FILTER_CUTOFF = "2026-07-31T20:57:00"

# Minimum IoU for a fresh detection to be considered "the same face" as a stored row.
# Generous: the same detector on the same image reproduces a near-identical box, so a
# genuine re-find scores far above this; this only needs to reject unrelated faces
# elsewhere in the photo.
MATCH_IOU_THRESHOLD = 0.5


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix0, iy0 = max(ax, bx), max(ay, by)
    ix1, iy1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _full_faces_in_image(bgr_image: np.ndarray) -> list[tuple[float, float, float, float]]:
    """Bboxes of detections in this image that PASS today's keypoint check. Deliberately
    re-implements the relevant slice of detect_faces() rather than calling it, because
    detect_faces() discards the keypoints and the pass/fail reason we need here."""
    app = _get_app()
    kept: list[tuple[float, float, float, float]] = []
    for f in app.get(bgr_image):
        x1, y1, x2, y2 = f.bbox
        w, h = x2 - x1, y2 - y1
        if f.det_score < settings.min_det_score:
            continue
        if min(w, h) < settings.min_face_px:
            continue
        bbox = (float(x1), float(y1), float(w), float(h))
        if f.kps is None or not _keypoints_within_bbox(f.kps, bbox, settings.keypoint_bbox_margin_ratio):
            continue
        kept.append(bbox)
    return kept


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="Actually mark clusters discarded. Without this, dry run.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N source photos (sampling).")
    parser.add_argument("--max-workers", type=int, default=8, help="Download+decode+detect thread pool size.")
    args = parser.parse_args()

    if not settings.database_url:
        print("DATABASE_URL is not set. Set it in backend/.env or the environment (see backend/.env.example).")
        sys.exit(1)
    try:
        r2 = R2Client(r2_config_from_settings(settings))
    except RuntimeError as exc:
        print(str(exc))
        sys.exit(1)

    register_heif_opener()
    session_factory = build_postgres_session_factory(settings.database_url)

    with session_factory() as session:
        rows = session.execute(
            text(
                """
                SELECT f.id, f.cluster_id, f.bbox_x, f.bbox_y, f.bbox_w, f.bbox_h, p.id, p.r2_key
                FROM faces f
                JOIN clusters c ON c.id = f.cluster_id
                JOIN photos  p ON p.id = f.photo_id
                WHERE f.created_at < :cut
                  AND c.status = 'unlabeled'
                  AND p.r2_key IS NOT NULL
                ORDER BY p.id
                """
            ),
            {"cut": KEYPOINT_FILTER_CUTOFF},
        ).all()

        # Every face of each candidate cluster, including ones detected AFTER the
        # cutoff - "all faces are partial" must be judged over the WHOLE cluster, or a
        # cluster with one old bad face and one new good face would be wrongly discarded.
        cluster_ids = sorted({r[1] for r in rows})
        total_by_cluster: dict[int, int] = {}
        if cluster_ids:
            for cid, n in session.execute(
                text("SELECT cluster_id, count(*) FROM faces WHERE cluster_id = ANY(:ids) GROUP BY cluster_id"),
                {"ids": cluster_ids},
            ).all():
                total_by_cluster[cid] = n

    by_photo: dict[tuple[int, str], list[tuple]] = defaultdict(list)
    for face_id, cluster_id, bx, by, bw, bh, photo_id, r2_key in rows:
        by_photo[(photo_id, r2_key)].append((face_id, cluster_id, (bx, by, bw, bh)))

    photos = sorted(by_photo.keys())
    if args.limit is not None:
        photos = photos[: args.limit]

    print(f"Candidate faces: {len(rows)} across {len(by_photo)} photos / {len(cluster_ids)} unlabeled clusters")
    print(f"Processing {len(photos)} photos with {args.max_workers} workers...\n")

    partial_face_ids: set[int] = set()
    faces_checked = 0
    photos_failed = 0
    processed = 0
    start = time.time()

    def work(item):
        (photo_id, r2_key) = item
        entries = by_photo[(photo_id, r2_key)]
        try:
            data = r2.download_bytes(r2_key)
            # load_rgb_and_bgr accepts a file-like object as well as a path - the same
            # BytesIO route the R2-sourced batch scan uses (batch_pipeline's
            # _decode_and_detect_r2), so decoding matches the original scan exactly.
            _pil, bgr, _size = load_rgb_and_bgr(io.BytesIO(data), max_dim=settings.detect_max_dim)
        except Exception:
            return None
        good = _full_faces_in_image(bgr)
        bad: list[int] = []
        for face_id, _cluster_id, bbox in entries:
            # No surviving detection overlaps this stored face => today's pipeline
            # would not have produced it (either it fails the keypoint check now, or
            # it no longer clears the other thresholds at all).
            if not any(_iou(bbox, g) >= MATCH_IOU_THRESHOLD for g in good):
                bad.append(face_id)
        return bad, len(entries)

    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        for result in pool.map(work, photos):
            processed += 1
            if result is None:
                photos_failed += 1
            else:
                bad, n = result
                partial_face_ids.update(bad)
                faces_checked += n
            if processed % 25 == 0 or processed == len(photos):
                rate = processed / max(1e-6, time.time() - start)
                print(
                    f"\r  photos {processed}/{len(photos)}  faces_checked={faces_checked} "
                    f"partial={len(partial_face_ids)} failed_downloads={photos_failed} "
                    f"({rate:.1f}/s)",
                    end="",
                    flush=True,
                )
    print("\n")

    partial_by_cluster: dict[int, int] = defaultdict(int)
    for face_id, cluster_id, *_rest in rows:
        if face_id in partial_face_ids:
            partial_by_cluster[cluster_id] += 1

    # Only clusters we fully examined can be judged. If --limit skipped some of a
    # cluster's photos, its unchecked faces make "all partial" unprovable - skip it.
    checked_face_ids = set()
    for (photo_id, r2_key) in photos:
        for face_id, _cid, _bb in by_photo[(photo_id, r2_key)]:
            checked_face_ids.add(face_id)
    checked_by_cluster: dict[int, int] = defaultdict(int)
    for face_id, cluster_id, *_rest in rows:
        if face_id in checked_face_ids:
            checked_by_cluster[cluster_id] += 1

    to_discard = [
        cid
        for cid, n_partial in partial_by_cluster.items()
        # every face in the cluster was examined AND every one was judged partial
        if checked_by_cluster.get(cid, 0) == total_by_cluster.get(cid, -1) and n_partial == total_by_cluster.get(cid)
    ]
    faces_in_discarded = sum(total_by_cluster.get(cid, 0) for cid in to_discard)

    print(f"Faces examined:                 {faces_checked}")
    print(f"Faces judged partial:           {len(partial_face_ids)}")
    print(f"Photos that failed to download: {photos_failed}")
    print(f"Clusters with >=1 partial face: {len(partial_by_cluster)}")
    print(f"Clusters ENTIRELY partial:      {len(to_discard)}   <- would be discarded")
    print(f"Faces inside those clusters:    {faces_in_discarded}")

    if not to_discard:
        print("\nNothing to discard.")
        return

    if not args.yes:
        print("\nDry run only - nothing written. Re-run with --yes to actually apply.")
        return

    with session_factory() as session:
        res = session.execute(
            text(
                "UPDATE clusters SET status='discarded', updated_at=:now "
                "WHERE id = ANY(:ids) AND status='unlabeled'"
            ),
            {"now": _now(), "ids": to_discard},
        )
        session.commit()
        print(f"\nDiscarded {res.rowcount} clusters.")
    print("Reversible: UPDATE clusters SET status='unlabeled' WHERE id = ANY(...) for the ids above.")


if __name__ == "__main__":
    main()
