from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clustering.similarity import ClusterIndex
from app.config import settings
from app.db.models import Cluster, Face


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def assign_face(session: Session, index: ClusterIndex, face: Face) -> Cluster:
    """Assign a newly-inserted face to the closest existing cluster if it clears the
    join-similarity threshold, updating that cluster's running-mean centroid;
    otherwise create a new unlabeled cluster. Never merges two existing clusters
    automatically and never touches other faces' assignments (manual merge only).

    Labeled (named) clusters are checked first, ahead of unlabeled ones: an unlabeled
    cluster's centroid is a running mean of real event photos and can end up an even
    closer match for a person's later photos than their own (fewer, posed) reference
    centroid, which would otherwise keep growing an unlabeled fragment of that same
    person indefinitely instead of ever joining their named cluster.
    """
    embedding = np.frombuffer(face.embedding, dtype=np.float32)

    labeled_match = index.best_match(embedding, statuses={"labeled"})
    match = (
        labeled_match
        if labeled_match is not None and labeled_match[1] >= settings.cluster_join_threshold
        else index.best_match(embedding, statuses={"unlabeled"})
    )
    if match is not None and match[1] >= settings.cluster_join_threshold:
        cluster_id, _ = match
        cluster = session.get(Cluster, cluster_id)
        assert cluster is not None
        new_centroid = (
            np.frombuffer(cluster.centroid, dtype=np.float32) * cluster.face_count + embedding
        ) / (cluster.face_count + 1)
        new_centroid = new_centroid / np.linalg.norm(new_centroid)
        cluster.centroid = new_centroid.astype(np.float32).tobytes()
        cluster.face_count += 1
        cluster.updated_at = _now()
        face.cluster_id = cluster.id
        index.upsert(cluster.id, new_centroid.astype(np.float32))
        return cluster

    cluster = Cluster(
        person_name=None,
        centroid=embedding.astype(np.float32).tobytes(),
        face_count=1,
        status="unlabeled",
        representative_face_id=face.id,
        representative_thumbnail_path=face.thumbnail_path,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(cluster)
    session.flush()  # assign cluster.id
    face.cluster_id = cluster.id
    index.upsert(cluster.id, embedding.astype(np.float32))
    return cluster


def assign_face_locked(session: Session, index: ClusterIndex, face: Face) -> Cluster:
    """Multi-writer variant of assign_face() for the Postgres batch scan
    (app/scanning/batch_pipeline.py, driven by scripts/run_batch_scan_cli.py), where
    several laptops run this concurrently against the same shared database.

    Matching logic is identical to assign_face(). The difference: batches are
    non-overlapping by file, so two machines never write the same faces/photos row,
    but they CAN independently pick the same target cluster for two different faces
    (e.g. two photos of the same person, one per machine's batch) and race to update
    its centroid - a lost-update bug where one face's contribution silently drops out
    of the running mean. This closes that race by taking a row-level lock
    (SELECT ... FOR UPDATE) on the target cluster before reading/writing its centroid,
    so a second machine's transaction blocks until the first one commits and sees the
    up-to-date centroid instead of a stale one. Caller is expected to commit promptly
    after calling this (small transaction, short lock hold time) so other machines
    aren't blocked long - see run_batch_scan's per-face commit.

    Known, accepted limitation (not fixed here): two machines can still each create a
    brand-new unlabeled cluster for the same never-before-seen person if they process
    matching faces in the same short window before either has refreshed its in-memory
    ClusterIndex from the DB (see run_batch_scan's periodic index reload). Fully
    closing that would require serializing all cluster *creation* globally, which
    would defeat the purpose of parallelizing the scan across machines. It's mitigated
    by the existing manual cluster-merge review workflow
    (app.services.cluster_service.merge_clusters) as a post-scan cleanup pass.
    """
    embedding = np.frombuffer(face.embedding, dtype=np.float32)

    labeled_match = index.best_match(embedding, statuses={"labeled"})
    match = (
        labeled_match
        if labeled_match is not None and labeled_match[1] >= settings.cluster_join_threshold
        else index.best_match(embedding, statuses={"unlabeled"})
    )
    if match is not None and match[1] >= settings.cluster_join_threshold:
        cluster_id, _ = match
        cluster = session.execute(
            select(Cluster).where(Cluster.id == cluster_id).with_for_update()
        ).scalar_one_or_none()
        if cluster is not None:
            new_centroid = (
                np.frombuffer(cluster.centroid, dtype=np.float32) * cluster.face_count + embedding
            ) / (cluster.face_count + 1)
            new_centroid = new_centroid / np.linalg.norm(new_centroid)
            cluster.centroid = new_centroid.astype(np.float32).tobytes()
            cluster.face_count += 1
            cluster.updated_at = _now()
            face.cluster_id = cluster.id
            index.upsert(cluster.id, new_centroid.astype(np.float32))
            return cluster
        # Cluster vanished (merged/discarded by another machine or a reviewer) between
        # the in-memory index lookup and taking the lock - fall through and create a
        # new cluster instead of crashing.
        index.remove(cluster_id)

    cluster = Cluster(
        person_name=None,
        centroid=embedding.astype(np.float32).tobytes(),
        face_count=1,
        status="unlabeled",
        representative_face_id=face.id,
        representative_thumbnail_path=face.thumbnail_path,
        r2_thumbnail_key=face.r2_thumbnail_key,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(cluster)
    session.flush()  # assign cluster.id
    face.cluster_id = cluster.id
    index.upsert(cluster.id, embedding.astype(np.float32))
    return cluster
