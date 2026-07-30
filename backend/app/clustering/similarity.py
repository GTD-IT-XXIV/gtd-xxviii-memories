import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Cluster

EMBEDDING_DIM = 512


class ClusterIndex:
    """In-memory brute-force cosine-similarity index over cluster centroids.

    All centroids and face embeddings are stored L2-normalized, so cosine
    similarity reduces to a plain dot product. Rebuilt from the DB on startup
    and updated incrementally as faces are assigned/clusters created, avoiding
    a native vector-search extension at this scale (hundreds-low-thousands of
    clusters).
    """

    def __init__(self) -> None:
        self.cluster_ids: list[int] = []
        self.statuses: list[str] = []
        self._id_to_row: dict[int, int] = {}
        self.matrix: np.ndarray = np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

    @classmethod
    def load(cls, session: Session) -> "ClusterIndex":
        idx = cls()
        rows = session.execute(
            select(Cluster.id, Cluster.centroid, Cluster.status).where(Cluster.status.in_(["unlabeled", "labeled"]))
        ).all()
        if rows:
            idx.cluster_ids = [r[0] for r in rows]
            idx.statuses = [r[2] for r in rows]
            idx._id_to_row = {cid: i for i, cid in enumerate(idx.cluster_ids)}
            idx.matrix = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
        return idx

    def best_match(self, embedding: np.ndarray, statuses: set[str] | None = None) -> tuple[int, float] | None:
        """Best cosine match, optionally restricted to clusters with one of the given
        statuses (e.g. only "labeled") so a named person can be preferred over an
        unlabeled fragment even when the fragment happens to score slightly higher."""
        if self.matrix.shape[0] == 0:
            return None
        sims = self.matrix @ embedding
        if statuses is not None:
            mask = np.fromiter((s in statuses for s in self.statuses), dtype=bool, count=len(self.statuses))
            if not mask.any():
                return None
            sims = np.where(mask, sims, -np.inf)
        best_i = int(np.argmax(sims))
        return self.cluster_ids[best_i], float(sims[best_i])

    def upsert(self, cluster_id: int, centroid: np.ndarray, status: str = "unlabeled") -> None:
        centroid = centroid.astype(np.float32)
        i = self._id_to_row.get(cluster_id)
        if i is not None:
            self.matrix[i] = centroid
        else:
            self._id_to_row[cluster_id] = len(self.cluster_ids)
            self.cluster_ids.append(cluster_id)
            self.statuses.append(status)
            self.matrix = np.vstack([self.matrix, centroid[None, :]])

    def remove(self, cluster_id: int) -> None:
        i = self._id_to_row.pop(cluster_id, None)
        if i is None:
            return
        self.cluster_ids.pop(i)
        self.statuses.pop(i)
        self.matrix = np.delete(self.matrix, i, axis=0)
        for cid, row in self._id_to_row.items():
            if row > i:
                self._id_to_row[cid] = row - 1


def normalize(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec
    return vec / norm
