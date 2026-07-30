from datetime import datetime

import numpy as np
from PIL import ExifTags, Image, ImageOps

_EXIF_DATETIME_TAG = next((k for k, v in ExifTags.TAGS.items() if v == "DateTimeOriginal"), None)
_EXIF_ORIENTATION_TAG = next((k for k, v in ExifTags.TAGS.items() if v == "Orientation"), None)

# EXIF orientation values that involve a 90/270-degree rotation, swapping width/height.
_ROTATED_ORIENTATIONS = {5, 6, 7, 8}


def read_taken_at(image: Image.Image) -> str | None:
    if _EXIF_DATETIME_TAG is None:
        return None
    try:
        exif = image.getexif()
        raw = exif.get(_EXIF_DATETIME_TAG)
        if not raw:
            return None
        # EXIF format: "YYYY:MM:DD HH:MM:SS"
        dt = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
        return dt.isoformat()
    except Exception:
        return None


def load_rgb_and_bgr(path: str, max_dim: int | None = None) -> tuple[Image.Image, np.ndarray, tuple[int, int]]:
    """Loads an image (JPEG/PNG/HEIC, via the registered pillow_heif opener), applies
    EXIF-orientation correction, and returns the upright PIL RGB image (for
    thumbnailing), a BGR numpy array (the format InsightFace/OpenCV expect for
    detection), and the ORIGINAL (pre-downscale, post-rotation) pixel dimensions for
    storage.

    Many cameras/phones store pixels in raw sensor orientation and rely on an EXIF
    Orientation tag for display rotation; PIL does not apply this automatically, so
    without correcting it here both our thumbnails and the detector itself would see
    sideways/upside-down images (hurting detection accuracy on top of just looking
    wrong).

    If max_dim is given and the source is a JPEG, decoding uses PIL's draft mode
    (libjpeg DCT scaling) to decode directly at a reduced resolution - much cheaper
    than a full decode followed by a Python-level resize, and detection accuracy is
    unaffected since InsightFace's own detector resizes to its det_size internally
    anyway. PNG/HEIC don't support draft decoding and are always fully decoded.
    """
    image = Image.open(path)
    raw_w, raw_h = image.size

    orientation = None
    if _EXIF_ORIENTATION_TAG is not None:
        try:
            orientation = image.getexif().get(_EXIF_ORIENTATION_TAG)
        except Exception:
            orientation = None

    original_size = (raw_h, raw_w) if orientation in _ROTATED_ORIENTATIONS else (raw_w, raw_h)

    if image.mode == "MPO":
        image.seek(0)
    if max_dim is not None and image.format == "JPEG":
        image.draft("RGB", (max_dim, max_dim))

    image = ImageOps.exif_transpose(image)  # bakes in correct rotation, clears the tag
    image = image.convert("RGB")
    rgb_array = np.array(image)
    bgr_array = rgb_array[:, :, ::-1].copy()
    return image, bgr_array, original_size
