from datetime import datetime, timezone

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Cluster, Face


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_clusters(session: Session, status: str | None, limit: int, offset: int) -> tuple[list[Cluster], int]:
    query = select(Cluster)
    count_query = select(func.count()).select_from(Cluster)
    if status:
        query = query.where(Cluster.status == status)
        count_query = count_query.where(Cluster.status == status)

    total_count = session.scalar(count_query) or 0
    rows = (
        session.execute(query.order_by(Cluster.face_count.desc()).limit(limit).offset(offset))
        .scalars()
        .all()
    )
    return list(rows), total_count


def get_cluster(session: Session, cluster_id: int) -> Cluster | None:
    return session.get(Cluster, cluster_id)


def name_cluster(session: Session, cluster_id: int, name: str) -> Cluster:
    cluster = session.get(Cluster, cluster_id)
    if cluster is None:
        raise ValueError("Cluster not found")
    cluster.person_name = name.strip()
    cluster.status = "labeled"
    cluster.updated_at = _now()
    session.commit()
    return cluster


def discard_cluster(session: Session, cluster_id: int) -> Cluster:
    cluster = session.get(Cluster, cluster_id)
    if cluster is None:
        raise ValueError("Cluster not found")
    cluster.status = "discarded"
    cluster.updated_at = _now()
    session.commit()
    return cluster


def merge_clusters(session: Session, source_id: int, target_id: int) -> Cluster:
    if source_id == target_id:
        raise ValueError("Cannot merge a cluster into itself")
    source = session.get(Cluster, source_id)
    target = session.get(Cluster, target_id)
    if source is None or target is None:
        raise ValueError("Cluster not found")

    faces = session.execute(select(Face).where(Face.cluster_id == source.id)).scalars().all()
    for face in faces:
        face.cluster_id = target.id

    if faces:
        source_centroid = np.frombuffer(source.centroid, dtype=np.float32)
        target_centroid = np.frombuffer(target.centroid, dtype=np.float32)
        combined = (
            target_centroid * target.face_count + source_centroid * source.face_count
        ) / (target.face_count + source.face_count)
        combined = combined / np.linalg.norm(combined)
        target.centroid = combined.astype(np.float32).tobytes()
        target.face_count += source.face_count

    source.status = "merged"
    source.merged_into_cluster_id = target.id
    source.updated_at = _now()
    target.updated_at = _now()
    session.commit()
    return target


def remove_face_from_cluster(session: Session, cluster_id: int, face_id: int) -> Cluster:
    """Pulls one mis-clustered face out into its own brand-new unlabeled cluster."""
    face = session.get(Face, face_id)
    if face is None or face.cluster_id != cluster_id:
        raise ValueError("Face not found in cluster")
    old_cluster = session.get(Cluster, cluster_id)
    if old_cluster is None:
        raise ValueError("Cluster not found")

    embedding = np.frombuffer(face.embedding, dtype=np.float32)
    new_cluster = Cluster(
        person_name=None,
        centroid=embedding.tobytes(),
        face_count=1,
        status="unlabeled",
        representative_face_id=face.id,
        representative_thumbnail_path=face.thumbnail_path,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(new_cluster)
    session.flush()

    face.cluster_id = new_cluster.id

    remaining = session.execute(select(Face).where(Face.cluster_id == old_cluster.id)).scalars().all()
    if remaining:
        remaining_embeddings = np.stack([np.frombuffer(f.embedding, dtype=np.float32) for f in remaining])
        new_centroid = remaining_embeddings.mean(axis=0)
        new_centroid = new_centroid / np.linalg.norm(new_centroid)
        old_cluster.centroid = new_centroid.astype(np.float32).tobytes()
    old_cluster.face_count = len(remaining)
    old_cluster.updated_at = _now()

    session.commit()
    return new_cluster
