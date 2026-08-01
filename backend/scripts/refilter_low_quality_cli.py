"""Retroactively discards unlabeled clusters whose faces are too BLURRY or too DARK
to be identifiable, to cut the manual review queue down to something completable.

Why this exists: min_face_sharpness (app/config.py) is applied at detection time and is
currently 20.0, which a visual audit of 1218 sampled unlabeled faces showed catches
essentially nothing - the whole population sits above it (p10 ~27, p25 ~44). The
blurriest decile is near-uniformly unusable (motion smear, near-black frames, backs of
heads), yet all of it is sitting in review. There is no brightness filter at all, so
faces lost in shadow are kept too.

Neither quality can be judged from the DB alone: sharpness is never persisted, and the
faces table stores no pixel data - only bbox/det_score/embedding. So this re-downloads
each candidate's source photo from R2 and measures the actual crop, using the pipeline's
own _face_sharpness() so the numbers are directly comparable to min_face_sharpness.

Metrics per face:
  sharpness  - variance of the Laplacian of the crop (app/scanning/face_engine.py's
               _face_sharpness, resized to a fixed 128x128 first so the score isn't a
               proxy for face size). Lower = blurrier.
  brightness - mean of the crop's V channel in HSV, 0-255. Low = lost in shadow. Uses
               the same fixed-size resize so it isn't skewed by crop size either.

What it marks (never DELETEs):
  - A face is "low quality" when sharpness < --min-sharpness OR brightness <
    --min-brightness.
  - A cluster is discarded only when EVERY face in it is low quality. A cluster with
    even one good face is left alone - it still represents a real person, and this is
    what protects the large clusters (e.g. an 86-face cluster with one blurry member).
  - 'discarded' is the same reversible status the review page's "Discard (not a person)"
    button sets. It drops the cluster out of ClusterIndex.load()
    (app/clustering/similarity.py loads only unlabeled/labeled), so it stops matching and
    stops appearing in review, but every row and embedding is preserved.

Only status='unlabeled' clusters are ever considered - labeled people are untouched.

Defaults to a DRY RUN. With --contact-sheet it also renders what WOULD be discarded (and
a sample of what would be KEPT, for false-positive checking) so the thresholds can be
eyeballed before applying.

Run from backend/:
    # preview thresholds + write contact sheets, nothing written to the DB
    .venv/Scripts/python.exe -m scripts.refilter_low_quality_cli --contact-sheet ./out

    # sample first (faster) to sanity-check a threshold
    .venv/Scripts/python.exe -m scripts.refilter_low_quality_cli --limit 300 --contact-sheet ./out

    # apply
    .venv/Scripts/python.exe -m scripts.refilter_low_quality_cli --min-sharpness 35 --min-brightness 40 --yes
"""

import argparse
import io
import os
import random
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import cv2
import numpy as np
from sqlalchemy import text

from app.config import settings
from app.db.postgres import build_postgres_session_factory
from app.scanning.face_engine import _SHARPNESS_CROP_SIZE, _face_sharpness
from app.scanning.heic import register_heif_opener
from app.scanning.imaging import load_rgb_and_bgr
from app.storage.r2 import R2Client, r2_config_from_settings

DEFAULT_MIN_SHARPNESS = 35.0
DEFAULT_MIN_BRIGHTNESS = 40.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# NOTE on a rejected alternative: CLAHE-equalized variance-of-Laplacian was tried here
# and measured WORSE, despite looking better on paper. Plain VoL measures edge amplitude,
# which scales with contrast, so it does carry a real exposure bias - on 1806 sampled
# faces it rejected 32% of the darkest quartile vs 11% of the brightest at a matched
# rejection rate, and equalizing first narrowed that gap to 25%/17%. But the gap is not
# the thing that matters. Comparing the two at matched rejection rates and inspecting the
# faces where they DISAGREE (82 each way): the faces plain rejects and CLAHE keeps are
# genuinely soft, and the faces CLAHE rejects and plain keeps are sharp and identifiable
# (often profiles, whose reduced edge texture CLAHE punishes). Plain VoL wins in both
# directions. Equalization amplifies noise in flat/dark regions, inflating scores for
# blurry crops, and discards the contrast information that separates crisp from soft.
# Lower brightness correlation, worse discrimination. Use plain _face_sharpness, and let
# the separate brightness filter below handle darkness explicitly.


def _face_brightness(bgr_image: np.ndarray, bbox: tuple[float, float, float, float]) -> float:
    """Mean V (value/brightness) of the face crop in HSV, 0-255. Mirrors _face_sharpness's
    fixed-size resize so the metric isn't skewed by how large the crop is."""
    img_h, img_w = bgr_image.shape[:2]
    x, y, w, h = bbox
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(img_w, int(x + w)), min(img_h, int(y + h))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    crop = bgr_image[y0:y1, x0:x1]
    crop = cv2.resize(crop, (_SHARPNESS_CROP_SIZE, _SHARPNESS_CROP_SIZE), interpolation=cv2.INTER_AREA)
    return float(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 2].mean())


def _render_sheet(r2: R2Client, items: list, path: str, cols: int = 5, cell: int = 300) -> str | None:
    """Contact sheet of (cluster_id, sharpness, brightness, side_px, det, thumb_key)."""
    from PIL import Image, ImageDraw

    def grab(it):
        try:
            return (it, Image.open(io.BytesIO(r2.download_bytes(it[5]))).convert("RGB"))
        except Exception:
            return (it, None)

    imgs = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for it, im in pool.map(grab, items):
            if im is not None:
                imgs.append((it, im))
    if not imgs:
        return None
    rows_n = (len(imgs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows_n * (cell + 28)), "white")
    draw = ImageDraw.Draw(sheet)
    for i, ((cid, sharp, bright, side, det, _k), im) in enumerate(imgs):
        cx, cy = (i % cols) * cell, (i // cols) * (cell + 28)
        t = im.copy()
        t.thumbnail((cell - 8, cell - 8))
        sheet.paste(t, (cx + 4, cy + 4))
        draw.text(
            (cx + 4, cy + cell + 3),
            "c%s sh=%.0f br=%.0f %.0fpx det=%.2f" % (cid, sharp, bright, side, det),
            fill="black",
        )
    sheet.save(path, quality=92)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="Actually mark clusters discarded. Without this, dry run.")
    parser.add_argument("--min-sharpness", type=float, default=DEFAULT_MIN_SHARPNESS,
                        help=f"Faces below this Laplacian variance are low quality (default {DEFAULT_MIN_SHARPNESS}).")
    parser.add_argument("--min-brightness", type=float, default=DEFAULT_MIN_BRIGHTNESS,
                        help=f"Faces below this mean HSV V are low quality (default {DEFAULT_MIN_BRIGHTNESS}).")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N source photos (sampling).")
    parser.add_argument("--max-workers", type=int, default=8, help="Download+decode thread pool size.")
    parser.add_argument("--contact-sheet", metavar="DIR", default=None,
                        help="Render contact sheets of what would be discarded / kept into DIR.")
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
                SELECT f.id, f.cluster_id, f.bbox_x, f.bbox_y, f.bbox_w, f.bbox_h,
                       f.det_score, f.r2_thumbnail_key, p.id, p.r2_key
                FROM faces f
                JOIN clusters c ON c.id = f.cluster_id
                JOIN photos  p ON p.id = f.photo_id
                WHERE c.status = 'unlabeled' AND p.r2_key IS NOT NULL
                """
            )
        ).all()
        # Whole-cluster face counts, so "every face is low quality" is judged over the
        # entire cluster - including faces whose photo is missing from R2 and therefore
        # can't be measured. Those make the all-bad claim unprovable, which is correct:
        # such a cluster is skipped rather than assumed bad.
        total_by_cluster = {}
        cluster_ids = sorted({r[1] for r in rows})
        if cluster_ids:
            for cid, n in session.execute(
                text("SELECT cluster_id, count(*) FROM faces WHERE cluster_id = ANY(:ids) GROUP BY cluster_id"),
                {"ids": cluster_ids},
            ).all():
                total_by_cluster[cid] = n

    by_photo: dict[tuple[int, str], list] = defaultdict(list)
    for fid, cid, bx, by, bw, bh, det, tkey, pid, pkey in rows:
        by_photo[(pid, pkey)].append((fid, cid, (bx, by, bw, bh), det, tkey))

    photos = sorted(by_photo.keys())
    if args.limit is not None:
        random.seed(0)
        random.shuffle(photos)
        photos = photos[: args.limit]

    print(f"Unlabeled faces with a source photo: {len(rows)} across {len(by_photo)} photos / {len(cluster_ids)} clusters")
    print(f"Measuring {len(photos)} photos with {args.max_workers} workers...")
    print(f"Thresholds: sharpness < {args.min_sharpness}  OR  brightness < {args.min_brightness}\n")

    measured: list[tuple] = []  # (face_id, cluster_id, sharp, bright, side, det, thumb_key)
    photos_failed = 0
    processed = 0
    start = time.time()

    def work(item):
        pid, pkey = item
        try:
            data = r2.download_bytes(pkey)
            _pil, bgr, _sz = load_rgb_and_bgr(io.BytesIO(data), max_dim=settings.detect_max_dim)
        except Exception:
            return None
        out = []
        for fid, cid, bbox, det, tkey in by_photo[(pid, pkey)]:
            try:
                out.append((fid, cid, _face_sharpness(bgr, bbox), _face_brightness(bgr, bbox),
                            min(bbox[2], bbox[3]), det, tkey))
            except Exception:
                pass
        return out

    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        for res in pool.map(work, photos):
            processed += 1
            if res is None:
                photos_failed += 1
            else:
                measured.extend(res)
            if processed % 50 == 0 or processed == len(photos):
                rate = processed / max(1e-6, time.time() - start)
                print(f"\r  photos {processed}/{len(photos)}  faces={len(measured)} "
                      f"failed={photos_failed} ({rate:.1f}/s)", end="", flush=True)
    print("\n")

    if not measured:
        print("Nothing measured.")
        return

    def is_bad(m):
        return m[2] < args.min_sharpness or m[3] < args.min_brightness

    sharps = sorted(m[2] for m in measured)
    brights = sorted(m[3] for m in measured)
    n = len(measured)
    print("Measured %d faces" % n)
    print("  sharpness  p10=%.1f p25=%.1f p50=%.1f p75=%.1f" % (
        sharps[int(n*.10)], sharps[int(n*.25)], sharps[int(n*.50)], sharps[int(n*.75)]))
    print("  brightness p10=%.1f p25=%.1f p50=%.1f p75=%.1f" % (
        brights[int(n*.10)], brights[int(n*.25)], brights[int(n*.50)], brights[int(n*.75)]))
    n_blur = sum(1 for m in measured if m[2] < args.min_sharpness)
    n_dark = sum(1 for m in measured if m[3] < args.min_brightness)
    n_bad = sum(1 for m in measured if is_bad(m))
    print("  faces failing sharpness: %d (%.0f%%)" % (n_blur, 100.0*n_blur/n))
    print("  faces failing brightness: %d (%.0f%%)" % (n_dark, 100.0*n_dark/n))
    print("  faces failing either:     %d (%.0f%%)" % (n_bad, 100.0*n_bad/n))

    measured_by_cluster: dict[int, list] = defaultdict(list)
    for m in measured:
        measured_by_cluster[m[1]].append(m)

    to_discard = []
    for cid, ms in measured_by_cluster.items():
        total = total_by_cluster.get(cid)
        if total is None or len(ms) != total:
            continue  # not every face measured -> can't prove all-bad
        if all(is_bad(m) for m in ms):
            to_discard.append(cid)

    faces_in_discarded = sum(total_by_cluster.get(c, 0) for c in to_discard)
    print("\nClusters fully measured:     %d" % sum(
        1 for cid, ms in measured_by_cluster.items() if len(ms) == total_by_cluster.get(cid, -1)))
    print("Clusters ENTIRELY low-quality: %d   <- would be discarded" % len(to_discard))
    print("Faces inside those clusters:   %d" % faces_in_discarded)

    if args.contact_sheet:
        os.makedirs(args.contact_sheet, exist_ok=True)
        discard_set = set(to_discard)
        bad_items = [(m[1], m[2], m[3], m[4], m[5], m[6]) for m in measured
                     if m[1] in discard_set and m[6]]
        keep_items = [(m[1], m[2], m[3], m[4], m[5], m[6]) for m in measured
                      if m[1] not in discard_set and m[6]]
        random.seed(5)
        bad_sample = random.sample(bad_items, min(40, len(bad_items)))
        keep_sample = random.sample(keep_items, min(40, len(keep_items)))
        p1 = _render_sheet(r2, bad_sample, os.path.join(args.contact_sheet, "would_discard.jpg"))
        p2 = _render_sheet(r2, keep_sample, os.path.join(args.contact_sheet, "would_keep.jpg"))
        print("\nContact sheets: %s | %s" % (p1, p2))

    if not to_discard:
        print("\nNothing to discard.")
        return

    if not args.yes:
        print("\nDry run only - nothing written. Re-run with --yes to actually apply.")
        return

    with session_factory() as session:
        res = session.execute(
            text("UPDATE clusters SET status='discarded', updated_at=:now "
                 "WHERE id = ANY(:ids) AND status='unlabeled'"),
            {"now": _now(), "ids": to_discard},
        )
        session.commit()
        print("\nDiscarded %d clusters." % res.rowcount)
    print("Reversible: UPDATE clusters SET status='unlabeled' WHERE id = ANY(ARRAY[...]);")


if __name__ == "__main__":
    main()
