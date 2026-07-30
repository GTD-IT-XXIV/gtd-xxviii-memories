import threading
from dataclasses import dataclass

import cv2
import numpy as np

from app.config import settings


@dataclass
class DetectedFace:
    bbox: tuple[float, float, float, float]  # x, y, w, h
    det_score: float
    embedding: np.ndarray  # float32[512], L2-normalized
    sharpness: float


_analysis_app = None
_init_lock = threading.Lock()

_SHARPNESS_CROP_SIZE = 128


def _get_app():
    global _analysis_app
    # Double-checked locking: the scan pipeline calls this from multiple worker
    # threads concurrently. Without the lock, concurrent first-callers would each
    # see _analysis_app as None and race to construct+prepare their own separate
    # ~275MB model instance (observed: several redundant model loads competing for
    # CPU at once). Once initialized, FaceAnalysis.get() itself is safe to call
    # concurrently from multiple threads on the shared instance (onnxruntime
    # InferenceSession.Run() supports concurrent calls).
    if _analysis_app is None:
        with _init_lock:
            if _analysis_app is None:
                from insightface.app import FaceAnalysis

                app = FaceAnalysis(
                    name=settings.insightface_model_pack,
                    providers=["CPUExecutionProvider"],
                )
                app.prepare(ctx_id=-1, det_size=(settings.det_size, settings.det_size))
                _analysis_app = app
    return _analysis_app


def _face_sharpness(bgr_image: np.ndarray, bbox: tuple[float, float, float, float]) -> float:
    """Variance of the Laplacian of the face crop - a standard fast blur-detection
    heuristic (sharp edges/in-focus -> high variance, smooth/blurry -> low variance).
    The crop is resized to a fixed size first so the score isn't just a proxy for
    face size (a bigger crop has more edge pixels regardless of focus quality)."""
    img_h, img_w = bgr_image.shape[:2]
    x, y, w, h = bbox
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(img_w, int(x + w)), min(img_h, int(y + h))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    crop = bgr_image[y0:y1, x0:x1]
    crop = cv2.resize(crop, (_SHARPNESS_CROP_SIZE, _SHARPNESS_CROP_SIZE), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def detect_faces(bgr_image: np.ndarray) -> list[DetectedFace]:
    """Run detection + embedding on an image already loaded as a BGR numpy array
    (the format InsightFace/OpenCV expect). Filters out low-confidence, too-small,
    and out-of-focus/blurry detections per configured thresholds.
    """
    app = _get_app()
    raw_faces = app.get(bgr_image)

    results: list[DetectedFace] = []
    for f in raw_faces:
        x1, y1, x2, y2 = f.bbox
        w, h = x2 - x1, y2 - y1
        if f.det_score < settings.min_det_score:
            continue
        if min(w, h) < settings.min_face_px:
            continue
        bbox = (float(x1), float(y1), float(w), float(h))
        sharpness = _face_sharpness(bgr_image, bbox)
        if sharpness < settings.min_face_sharpness:
            continue
        embedding = f.normed_embedding.astype(np.float32)
        results.append(
            DetectedFace(
                bbox=bbox,
                det_score=float(f.det_score),
                embedding=embedding,
                sharpness=sharpness,
            )
        )
    return results
