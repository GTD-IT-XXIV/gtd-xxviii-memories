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
    # Lowered from 35 because upscaling a genuinely small (but in-focus) crop up to
    # the fixed measurement size naturally reads as "less sharp" than a larger face -
    # the old threshold was disproportionately rejecting small faces in group photos.
    min_face_sharpness: float = 20.0

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
