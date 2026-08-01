"""Computes and stores the "suggested match" the review page (web/src/app/review)
reads instead of recomputing a brute-force cosine scan on every request.

See app/db/models.py's Cluster.suggested_cluster_id docstring for why this is an FK
(not denormalized name/og columns), and app/config.py's cluster_suggestion_threshold
for the bar a match must clear to be stored at all - much lower than
cluster_join_threshold, since this is "worth hinting to a human reviewer", not
"confidently the same person".
"""

from dataclasses import dataclass

import numpy as np
from sqlalchemy.orm import Session

from app.clustering.similarity import ClusterIndex
from app.config import settings
from app.db.models import Cluster


def compute_suggestion(index: ClusterIndex, centroid: np.ndarray) -> tuple[int, float] | None:
    """Best labeled-cluster match for `centroid`, or None if there isn't one that
    clears cluster_suggestion_threshold (including: no labeled clusters exist yet)."""
    match = index.best_match(centroid, statuses={"labeled"})
    if match is not None and match[1] >= settings.cluster_suggestion_threshold:
        return match
    return None


@dataclass
class RecomputeCounters:
    unlabeled_seen: int = 0
    changed: int = 0


def recompute_all_suggestions(session: Session, commit_every: int = 200, dry_run: bool = False) -> RecomputeCounters:
    """Bulk pass over every unlabeled cluster, refreshing its stored suggestion
    against the CURRENT set of labeled clusters. Needed because suggestions are only
    otherwise kept fresh incrementally as individual clusters' centroids change
    (app/clustering/incremental.py) - a newly-labeled cluster elsewhere doesn't
    retroactively improve other clusters' stored suggestions until this runs. Called
    automatically at the end of a reference import (app/scanning/reference_import.py,
    the dominant source of new labeled clusters); otherwise run manually via
    scripts/recompute_suggested_matches_cli.py after a batch of web-side relabeling.

    dry_run=True computes and counts everything but rolls back instead of committing
    - used by the CLI's default preview mode. Never pass dry_run=True from
    reference_import.py's automatic call; it exists purely for the CLI's benefit.
    """
    index = ClusterIndex.load(session)
    counters = RecomputeCounters()

    unlabeled = [
        (cluster_id, index.matrix[i])
        for i, (cluster_id, status) in enumerate(zip(index.cluster_ids, index.statuses))
        if status == "unlabeled"
    ]

    for cluster_id, centroid in unlabeled:
        counters.unlabeled_seen += 1
        cluster = session.get(Cluster, cluster_id)
        if cluster is None:
            continue

        match = compute_suggestion(index, centroid)
        new_id, new_sim = match if match is not None else (None, None)

        if cluster.suggested_cluster_id != new_id or cluster.suggested_similarity != new_sim:
            cluster.suggested_cluster_id = new_id
            cluster.suggested_similarity = new_sim
            counters.changed += 1

        if not dry_run and counters.unlabeled_seen % commit_every == 0:
            session.commit()

    if dry_run:
        session.rollback()
    else:
        session.commit()
    return counters
