import io
from pathlib import Path

from PIL import Image

from app.config import settings


def _image_to_jpeg_bytes(image: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _photo_thumbnail_image(image: Image.Image) -> Image.Image:
    thumb = image.copy()
    thumb.thumbnail((settings.photo_thumb_max_dim, settings.photo_thumb_max_dim))
    return thumb


def save_photo_thumbnail(image: Image.Image, photo_id: int) -> str:
    thumb = _photo_thumbnail_image(image)
    out_path = settings.photo_thumb_dir / f"{photo_id}.jpg"
    thumb.convert("RGB").save(out_path, "JPEG", quality=80)
    return str(out_path)


def photo_thumbnail_bytes(image: Image.Image) -> bytes:
    """Same crop/resize as save_photo_thumbnail, returned as JPEG bytes instead of
    written to local disk - used by the R2-backed batch scan
    (app/scanning/batch_pipeline.py)."""
    return _image_to_jpeg_bytes(_photo_thumbnail_image(image), quality=80)


def _crop_face(image: Image.Image, bbox: tuple[float, float, float, float]) -> Image.Image:
    x, y, w, h = bbox
    img_w, img_h = image.size

    # Pad the crop by 40% on each side so the review UI shows context around the face,
    # clamped to image bounds.
    pad_x, pad_y = w * 0.4, h * 0.4
    left = max(0, int(x - pad_x))
    top = max(0, int(y - pad_y))
    right = min(img_w, int(x + w + pad_x))
    bottom = min(img_h, int(y + h + pad_y))

    crop = image.crop((left, top, right, bottom))
    crop.thumbnail((settings.face_thumb_size, settings.face_thumb_size))
    return crop.convert("RGB")


def save_face_thumbnail(image: Image.Image, face_id: int, bbox: tuple[float, float, float, float]) -> str:
    out_path = settings.face_thumb_dir / f"{face_id}.jpg"
    _crop_face(image, bbox).save(out_path, "JPEG", quality=85)
    return str(out_path)


def face_thumbnail_bytes(image: Image.Image, bbox: tuple[float, float, float, float]) -> bytes:
    """Same crop as save_face_thumbnail, returned as JPEG bytes instead of written to
    local disk - used by the R2-backed batch scan (app/scanning/batch_pipeline.py)."""
    return _image_to_jpeg_bytes(_crop_face(image, bbox), quality=85)


def save_cluster_thumbnail(image: Image.Image, cluster_id: int, bbox: tuple[float, float, float, float]) -> str:
    out_path: Path = settings.cluster_thumb_dir / f"{cluster_id}.jpg"
    _crop_face(image, bbox).save(out_path, "JPEG", quality=85)
    return str(out_path)


def cluster_thumbnail_bytes(image: Image.Image, bbox: tuple[float, float, float, float]) -> bytes:
    """Same crop as save_cluster_thumbnail, returned as JPEG bytes instead of written
    to local disk - used by the R2-backed batch scan (app/scanning/batch_pipeline.py)."""
    return _image_to_jpeg_bytes(_crop_face(image, bbox), quality=85)
