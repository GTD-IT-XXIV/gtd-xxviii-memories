"""Read-only benchmark: does threading actually speed up decode+detect given the
GIL? Uses disjoint file slices per configuration to avoid OS file-cache bias. No DB
writes at all - safe to run alongside a live scan (touches the same source files
read-only and the same in-process model, nothing else)."""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from app.config import settings
from app.scanning.face_engine import detect_faces
from app.scanning.heic import register_heif_opener
from app.scanning.imaging import load_rgb_and_bgr


def work(path: str) -> int:
    _, bgr, _ = load_rgb_and_bgr(path, max_dim=settings.detect_max_dim)
    faces = detect_faces(bgr)
    return len(faces)


def main() -> None:
    folder = sys.argv[1]
    register_heif_opener()
    all_paths = sorted(
        os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith((".jpg", ".jpeg"))
    )
    n = 30
    slices = [all_paths[i * n : (i + 1) * n] for i in range(4)]

    print(f"warming up model on {slices[0][0]}...")
    work(slices[0][0])

    t0 = time.time()
    seq_faces = [work(p) for p in slices[0]]
    t1 = time.time()
    print(f"sequential:      {t1 - t0:6.1f}s for {n} files = {(t1 - t0) / n:.2f}s/file, faces={sum(seq_faces)}")

    for workers, sl in zip([4, 8, 16], slices[1:]):
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            par_faces = list(ex.map(work, sl))
        t1 = time.time()
        print(
            f"threaded(w={workers:2d}):  {t1 - t0:6.1f}s for {n} files = {(t1 - t0) / n:.2f}s/file, faces={sum(par_faces)}"
        )


if __name__ == "__main__":
    main()
