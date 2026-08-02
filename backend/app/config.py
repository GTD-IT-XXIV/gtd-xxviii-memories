from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Root folder to scan for photos (e.g. local OneDrive-synced folder). Can also be
    # set at runtime via POST /scan/start instead of this default.
    scan_root: str = ""

    data_dir: Path = Path(__file__).resolve().parent.parent / "data"

    # Face detection/embedding
    insightface_model_pack: str = "buffalo_l"
    # SCRFD's input resolution. Faces get resized down to fit this square before the
    # network ever sees them, so in a 30+ person group photo where each face is only
    # a few dozen pixels wide to begin with, a small det_size compounds with
    # detect_max_dim's downscale and shrinks those faces past the point of reliable
    # detection. 1024 costs ~2.5x the compute of the old 640 but detects far more of
    # the small/back-row faces in crowded photos; push to 1280-1600 if faces in large
    # groups are still being missed and slower scans are acceptable.
    det_size: int = 1024
    # Slightly more lenient than InsightFace's typical 0.5 default so partially
    # angled/occluded faces common in group shots aren't dropped outright.
    min_det_score: float = 0.45
    min_face_px: int = 28

    # Out-of-focus/motion-blurred face rejection: variance of the Laplacian of the
    # face crop (resized to a fixed size first so the metric isn't skewed by crop
    # size), a standard fast blur-detection heuristic - lower variance means fewer
    # sharp edges means blurrier. Tuned empirically against real event photos;
    # tune lower to keep more marginal faces, higher to be stricter about focus.
    #
    # Raised back to 35 after measuring the GTD XXVIII library: at 20.0 this rejected
    # essentially nothing (the whole population of 1806 sampled unlabeled faces sat
    # above it - p10 ~30, p25 ~47), so thousands of unusable motion-smeared and
    # out-of-focus faces reached the manual review queue. It had been lowered from 35
    # on the theory that upscaling small in-focus crops reads as "less sharp"; the
    # sampled data does not bear that out strongly enough to justify keeping the
    # filter inert, and min_face_px already guards the genuinely tiny faces.
    #
    # A CLAHE-equalized variant of this metric was evaluated and REJECTED - see the
    # note in scripts/refilter_low_quality_cli.py. It has a smaller exposure bias but
    # discriminates worse: at matched rejection rates it keeps soft faces and rejects
    # sharp ones (especially profiles). Plain variance-of-Laplacian won both
    # directions of that comparison.
    min_face_sharpness: float = 35.0

    # Underexposed face rejection: mean V (value) of the face crop in HSV, 0-255,
    # measured on the same fixed-size resize as min_face_sharpness. Faces lost in
    # shadow produce poor embeddings and are not identifiable by a human reviewer
    # either, but nothing rejected them before this existed - the sampled library had
    # near-black crops (mean V in the teens) sitting in the review queue with high
    # det_score. Deliberately a SEPARATE filter from sharpness rather than folded into
    # it: variance-of-Laplacian already correlates with brightness (+0.297 measured),
    # so darkness must be judged on its own terms instead of being counted twice.
    min_face_brightness: float = 40.0

    # How far outside its own bbox a keypoint (eye/nose/mouth corner) may fall before
    # the detection is treated as a partial/occluded face rather than a full one -
    # e.g. only eyes visible would push the mouth-corner keypoints well outside the
    # box. A generous margin so normally-angled faces (still producing all 5 points
    # roughly within the box) aren't affected - see min_det_score's comment above for
    # why this pipeline stays lenient toward angled/partially-occluded group-photo
    # faces; this filter is only meant to catch genuinely degenerate detections.
    keypoint_bbox_margin_ratio: float = 0.15

    # Source photos (esp. modern phone cameras) can be 4000-8000px wide; InsightFace's
    # detector internally resizes to det_size anyway, so decoding at full resolution
    # first just burns CPU. JPEGs are downscaled during decode itself (libjpeg DCT
    # scaling via PIL's draft mode) to roughly this max dimension before detection.
    # Raised from 1600 alongside det_size so more real pixels survive for small faces
    # in large group photos instead of being downscaled away twice (once here, once
    # by det_size).
    detect_max_dim: int = 2000

    # Clustering
    # Cosine-similarity bar a face's embedding must clear against a cluster's
    # centroid to auto-join it (labeled reference-photo clusters included) instead
    # of spawning a new unlabeled cluster that needs manual review. Lowered from
    # 0.65 because single-reference-photo centroids often sat just below that bar
    # for genuine matches, pushing real matches into the review queue unnecessarily.
    cluster_join_threshold: float = 0.58
    # Much lower bar than cluster_join_threshold: "worth suggesting to a human
    # reviewer on the review page" rather than "confidently auto-join". Stored on an
    # unlabeled cluster as suggested_cluster_id/suggested_similarity (see
    # app/clustering/suggestions.py) - single source of truth for this bar now that
    # web/'s former client-side copy (RECOMMENDATION_THRESHOLD) has been removed.
    cluster_suggestion_threshold: float = 0.3

    # Thumbnails
    photo_thumb_max_dim: int = 480
    face_thumb_size: int = 160

    # Mid-size preview served when a gallery thumbnail is clicked. The 480px grid
    # thumbnail looks soft blown up to a lightbox, but serving the untouched original
    # instead means 8-15MB per click on phones at an event. This sits between them:
    # ~200-400KB, sharp at full-screen on any realistic display.
    #
    # Deliberately generated here rather than by next/image on the web side. Routing
    # originals through Vercel's image optimizer would re-introduce exactly the origin
    # transfer that presigning the gallery download removed, and would additionally
    # burn Vercel's capped image-transformation quota. Generated once at scan time and
    # served straight from R2 (whose egress is free), it costs one extra GET per view.
    #
    # Measured on real event photos at 1600px/q85: ~242KB average (194-268KB), 7-19x
    # smaller than the originals, ~0.5GB of R2 storage for a ~1900-photo library.
    photo_preview_max_dim: int = 1600
    # Slightly higher than the grid thumbnail's 80 - this one is viewed full-screen,
    # where JPEG artifacts around faces are actually visible.
    photo_preview_quality: int = 85

    # Scan pipeline
    commit_batch_size: int = 50
    image_extensions: tuple[str, ...] = (
        ".jpg",
        ".jpeg",
        ".png",
        ".heic",
        ".heif",
    )

    # --- Multi-machine batch scan (backend/scripts/run_batch_scan_cli.py) ---
    # All optional/None by default so local single-machine dev (SQLite + local disk
    # thumbnails, driven by app/db/database.py's engine and app/scanning/pipeline.py)
    # is completely unaffected when these are unset. Only read when the batch-scan
    # CLI is actually invoked.

    # Shared Neon Postgres connection string, e.g.
    # postgresql://user:pass@host/db?sslmode=require
    database_url: str | None = None

    # Cloudflare R2 (S3-compatible) credentials for uploading originals/thumbnails
    # instead of saving them to local disk.
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket_name: str | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "db.sqlite3"

    @property
    def photo_thumb_dir(self) -> Path:
        return self.data_dir / "thumbnails" / "photos"

    @property
    def face_thumb_dir(self) -> Path:
        return self.data_dir / "thumbnails" / "faces"

    @property
    def cluster_thumb_dir(self) -> Path:
        return self.data_dir / "thumbnails" / "clusters"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.photo_thumb_dir.mkdir(parents=True, exist_ok=True)
        self.face_thumb_dir.mkdir(parents=True, exist_ok=True)
        self.cluster_thumb_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
