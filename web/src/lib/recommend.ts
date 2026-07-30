import { decodeEmbedding, dotProduct } from "./embeddings";

/** Below this cosine similarity, a "closest match" is more noise than signal. */
export const RECOMMENDATION_THRESHOLD = 0.3;

export interface LabeledClusterRow {
  id: number;
  person_name: string;
  og: string | null;
  centroid: Buffer;
}

export interface DecodedLabeledCluster {
  id: number;
  person_name: string;
  og: string | null;
  vec: Float32Array;
}

export interface Recommendation {
  cluster_id: number;
  person_name: string;
  og: string | null;
  similarity: number;
}

/**
 * Decodes every labeled cluster's centroid once, up front, so scoring N
 * unlabeled clusters against it doesn't redo the same decode work N times.
 */
export function decodeLabeledClusters(
  labeledClusters: LabeledClusterRow[]
): DecodedLabeledCluster[] {
  return labeledClusters.map((c) => ({
    id: c.id,
    person_name: c.person_name,
    og: c.og,
    vec: decodeEmbedding(c.centroid),
  }));
}

/**
 * Finds the closest-matching labeled cluster (by cosine similarity of
 * centroids) for a given unlabeled cluster's centroid. Returns null if
 * there are no labeled clusters, or the best match is below
 * RECOMMENDATION_THRESHOLD (i.e. not worth suggesting).
 *
 * At "low thousands of clusters" scale this brute-force O(n) scan per
 * target cluster is cheap enough to do in Node on every page render --
 * no vector index / extension needed.
 */
export function findBestMatch(
  targetCentroid: Buffer,
  decodedLabeledClusters: DecodedLabeledCluster[]
): Recommendation | null {
  const target = decodeEmbedding(targetCentroid);

  let best: Recommendation | null = null;
  for (const candidate of decodedLabeledClusters) {
    const similarity = dotProduct(target, candidate.vec);
    if (!best || similarity > best.similarity) {
      best = {
        cluster_id: candidate.id,
        person_name: candidate.person_name,
        og: candidate.og,
        similarity,
      };
    }
  }

  if (!best || best.similarity < RECOMMENDATION_THRESHOLD) {
    return null;
  }
  return best;
}
