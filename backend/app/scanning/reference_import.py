import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
from sqlalchemy.orm import Session

from app.clustering.similarity import normalize
from app.config import settings
from app.db.models import Cluster
from app.scanning import thumbnails
from app.scanning.face_engine import detect_faces
from app.scanning.heic import register_heif_opener
from app.scanning.imaging import load_rgb_and_bgr
from app.scanning.walker import walk_images

logger = logging.getLogger(__name__)

_TRAILING_DIGITS = re.compile(r"(\d+)$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ImportCounters:
    total_files_seen: int = 0
    people_found: int = 0
    files_used: int = 0
    files_skipped_no_pattern: int = 0
    files_skipped_no_face: int = 0
    files_skipped_multi_face: int = 0
    people_created: int = 0
    people_failed: list[str] = field(default_factory=list)
    current_person: str = ""


def parse_person(reference_root: str, path: str) -> tuple[str, str] | None:
    """Parses a reference photo's path into (person_key, display_name).

    Expects filenames like "audria1.jpg" / "AARON2.jpeg" - a name followed by a
    REQUIRED trailing digit/index - grouped by their immediate parent folder(s) so
    that same first names in different sub-teams (e.g. two different "Thomas"es in
    different committees) don't collide. Files with no trailing digit (e.g. a group
    or logo photo like "BFM_MC.jpg") are treated as non-individual and skipped -
    without this, a random face from a group photo would get misattributed as if it
    were a named individual's reference photo.
    """
    rel = Path(path).relative_to(reference_root)
    stem = rel.stem
    if not _TRAILING_DIGITS.search(stem):
        return None
    name_part = _TRAILING_DIGITS.sub("", stem).strip("_- ")
    if not name_part:
        return None
    # "-" not "/" as the join separator: person_name flows straight into URL path
    # segments (GET /persons/{name}/photos), and a literal "/" there breaks routing
    # even when percent-encoded (the ASGI server decodes %2F before route matching).
    group_key = "-".join(rel.parts[:-1]) or "misc"
    display_name = f"{name_part.title()} ({group_key.upper()})"
    person_key = f"{group_key.lower()}/{name_part.lower()}"
    return person_key, display_name


def import_reference_folder(
    session_factory: Callable[[], Session],
    reference_root: str,
    on_progress: Callable[[ImportCounters], None] | None = None,
) -> ImportCounters:
    """Seeds labeled person clusters directly from a folder of named reference
    photos (e.g. committee member headshots), so those people are auto-recognized
    during the main library scan instead of needing manual cluster labeling."""
    register_heif_opener()
    counters = ImportCounters()

    found = walk_images(reference_root)
    counters.total_files_seen = len(found)

    by_person: dict[str, dict] = {}
    for f in found:
        parsed = parse_person(reference_root, f.path)
        if parsed is None:
            counters.files_skipped_no_pattern += 1
            continue
        person_key, display_name = parsed
        by_person.setdefault(person_key, {"display_name": display_name, "files": []})
        by_person[person_key]["files"].append(f.path)
    counters.people_found = len(by_person)
    if on_progress:
        on_progress(counters)

    session = session_factory()
    try:
        for i, (person_key, info) in enumerate(by_person.items()):
            counters.current_person = info["display_name"]
            embeddings: list[np.ndarray] = []
            best_crop: tuple[float, "object", tuple[float, float, float, float]] | None = None

            for path in info["files"]:
                try:
                    pil_image, bgr_array, _original_size = load_rgb_and_bgr(path, max_dim=settings.detect_max_dim)
                except Exception:
                    logger.exception("Failed to open reference photo %s", path)
                    continue

                detected = detect_faces(bgr_array)
                if len(detected) == 0:
                    counters.files_skipped_no_face += 1
                    continue
                if len(detected) > 1:
                    counters.files_skipped_multi_face += 1
                    detected = [max(detected, key=lambda d: d.det_score)]

                chosen = detected[0]
                embeddings.append(chosen.embedding)
                counters.files_used += 1
                if best_crop is None or chosen.det_score > best_crop[0]:
                    best_crop = (chosen.det_score, pil_image, chosen.bbox)

            if not embeddings:
                counters.people_failed.append(info["display_name"])
                continue

            centroid = normalize(np.mean(np.stack(embeddings), axis=0)).astype(np.float32)
            cluster = Cluster(
                person_name=info["display_name"],
                centroid=centroid.tobytes(),
                face_count=len(embeddings),
                status="labeled",
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(cluster)
            session.flush()  # assign cluster.id for the thumbnail filename

            if best_crop is not None:
                _, pil_image, bbox = best_crop
                cluster.representative_thumbnail_path = thumbnails.save_cluster_thumbnail(
                    pil_image, cluster.id, bbox
                )

            counters.people_created += 1

            if (i + 1) % 25 == 0:
                session.commit()
                if on_progress:
                    on_progress(counters)

        session.commit()
        if on_progress:
            on_progress(counters)
    finally:
        session.close()

    return counters
