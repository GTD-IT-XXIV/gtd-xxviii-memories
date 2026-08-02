import logging
import os
import sys
import threading
from dataclasses import dataclass

import cv2
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class DetectedFace:
    bbox: tuple[float, float, float, float]  # x, y, w, h
    det_score: float
    embedding: np.ndarray  # float32[512], L2-normalized
    sharpness: float


_analysis_app = None
_init_lock = threading.Lock()

_SHARPNESS_CROP_SIZE = 128


def _register_cuda_dll_dirs() -> None:
    """Windows only: put the CUDA/cuDNN DLLs on the loader's search path.

    onnxruntime-gpu's provider DLL links against cublasLt64_13.dll and cudnn64_9.dll,
    but does NOT locate them itself. The NVIDIA pip wheels install into
    site-packages/nvidia/<pkg>/bin (a layout nothing adds to PATH), so without this the
    provider fails to load with "cublasLt64_13.dll is missing" and onnxruntime SILENTLY
    FALLS BACK TO CPU - no exception, just an unexplained lack of speedup. That silent
    fallback is exactly why detect_faces() below asserts on the bound provider rather
    than trusting the requested one.

    Safe on machines without CUDA: every path is existence-checked, so this is a no-op
    when the wheels or toolkit aren't installed and the CPU path is unaffected.
    """
    if not hasattr(os, "add_dll_directory"):  # non-Windows
        return
    site_packages = os.path.join(sys.prefix, "Lib", "site-packages", "nvidia")
    candidates = [
        os.path.join(site_packages, "cu13", "bin", "x86_64"),
        os.path.join(site_packages, "cudnn", "bin"),
        # Toolkit install, as a fallback when the pip wheels aren't present.
        r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.3\bin\x64",
    ]
    found = [d for d in candidates if os.path.isdir(d)]
    for directory in found:
        try:
            os.add_dll_directory(directory)
        except OSError:  # already registered, or not accessible - not fatal
            pass
    # add_dll_directory alone is NOT sufficient here. It governs how Python resolves
    # the DLLs it loads directly, but cublasLt64_13.dll is a TRANSITIVE dependency of
    # onnxruntime_providers_cuda.dll, and the Windows loader resolves those through
    # PATH. Without this prepend the provider still fails with "cublasLt64_13.dll is
    # missing" despite the directory being registered above.
    if found:
        os.environ["PATH"] = os.pathsep.join(found) + os.pathsep + os.environ.get("PATH", "")


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
                _register_cuda_dll_dirs()
                from insightface.app import FaceAnalysis

                # Providers are tried in order, so a machine without a working GPU
                # transparently lands on CPU. CoreML covers Apple Silicon (the M-series
                # Macs some operators scan from); CUDA covers NVIDIA.
                app = FaceAnalysis(
                    name=settings.insightface_model_pack,
                    providers=[
                        "CUDAExecutionProvider",
                        "CoreMLExecutionProvider",
                        "CPUExecutionProvider",
                    ],
                )
                # ctx_id selects the InsightFace device: >=0 is a GPU ordinal, -1 forces
                # CPU regardless of the providers above. Detection is ~85% of scan
                # runtime (measured), so this is the setting that actually matters.
                ctx_id = 0 if settings.use_gpu else -1
                app.prepare(ctx_id=ctx_id, det_size=(settings.det_size, settings.det_size))
                _analysis_app = app

                bound = _bound_providers(app)
                accelerated = {"CUDAExecutionProvider", "CoreMLExecutionProvider"} & bound
                if settings.use_gpu and not accelerated:
                    # Loud on purpose. The failure mode this guards against is a silent
                    # CPU fallback that looks like "the GPU just didn't help much".
                    logger.warning(
                        "GPU was requested (use_gpu=True) but onnxruntime bound only %s. "
                        "Detection is running on CPU. Check that onnxruntime-gpu is installed "
                        "and its CUDA/cuDNN dependencies are importable.",
                        sorted(bound) or ["<none>"],
                    )
                else:
                    logger.info("Face detection providers: %s", sorted(bound))
    return _analysis_app


def _bound_providers(app) -> set[str]:
    """Providers onnxruntime ACTUALLY bound, across every model in the pack - not the
    ones requested. These differ whenever a provider's shared library fails to load,
    which onnxruntime reports only as a log line, never as an exception."""
    bound: set[str] = set()
    for model in getattr(app, "models", {}).values():
        session = getattr(model, "session", None)
        if session is not None:
            bound.update(session.get_providers())
    return bound


def _keypoints_within_bbox(
    kps: np.ndarray, bbox: tuple[float, float, float, float], margin_ratio: float
) -> bool:
    """True if all 5 landmarks (eyes, nose, mouth corners) fall within the face's own
    bbox, padded by margin_ratio on each side. A face with landmarks pushed well
    outside the box - or missing entirely - means the detector only had a
    partial/occluded view (e.g. only eyes visible), not a full face worth embedding.
    A generous margin keeps normally-angled faces (whose 5 points still land roughly
    within the box) from being affected - see settings.keypoint_bbox_margin_ratio."""
    x, y, w, h = bbox
    pad_x, pad_y = w * margin_ratio, h * margin_ratio
    x0, y0 = x - pad_x, y - pad_y
    x1, y1 = x + w + pad_x, y + h + pad_y
    return bool(
        np.all(kps[:, 0] >= x0) and np.all(kps[:, 0] <= x1) and np.all(kps[:, 1] >= y0) and np.all(kps[:, 1] <= y1)
    )


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


def _face_brightness(bgr_image: np.ndarray, bbox: tuple[float, float, float, float]) -> float:
    """Mean V (value/brightness) of the face crop in HSV, 0-255. Uses the same fixed-size
    resize as _face_sharpness so the two metrics are measured over identical pixels, and
    so the score isn't skewed by how large the crop is.

    Separate from sharpness on purpose: variance-of-Laplacian scales with contrast and so
    already partly tracks brightness (+0.297 correlation, measured on 1806 real faces).
    Folding darkness into the blur score would count it twice and mislabel underexposed
    but in-focus faces as blurry - see settings.min_face_brightness."""
    img_h, img_w = bgr_image.shape[:2]
    x, y, w, h = bbox
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(img_w, int(x + w)), min(img_h, int(y + h))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    crop = bgr_image[y0:y1, x0:x1]
    crop = cv2.resize(crop, (_SHARPNESS_CROP_SIZE, _SHARPNESS_CROP_SIZE), interpolation=cv2.INTER_AREA)
    return float(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 2].mean())


def detect_faces(bgr_image: np.ndarray) -> list[DetectedFace]:
    """Run detection + embedding on an image already loaded as a BGR numpy array
    (the format InsightFace/OpenCV expect). Filters out low-confidence, too-small,
    partial/occluded (keypoints outside the bbox), out-of-focus/blurry, and
    underexposed detections per configured thresholds.
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
        if f.kps is None or not _keypoints_within_bbox(f.kps, bbox, settings.keypoint_bbox_margin_ratio):
            continue
        sharpness = _face_sharpness(bgr_image, bbox)
        if sharpness < settings.min_face_sharpness:
            continue
        if _face_brightness(bgr_image, bbox) < settings.min_face_brightness:
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
