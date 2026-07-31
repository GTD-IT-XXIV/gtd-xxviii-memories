import { cookies } from "next/headers";
import { getSql } from "@/lib/db";
import { presignGetUrls } from "@/lib/r2";
import { canReviewerAccessReview } from "@/lib/allowlist";
import { COOKIE_NAME, verifySessionToken } from "@/lib/session";
import {
  decodeLabeledClusters,
  findBestMatch,
  type LabeledClusterRow,
} from "@/lib/recommend";
import type { KnownPerson, ReviewClusterViewModel } from "@/lib/types";
import ReviewFolders, { type ReviewFolder } from "./ReviewFolders";

// This page hits Postgres/R2 on every request and must never be prerendered
// at build time (no DATABASE_URL / R2 credentials exist during `next build`).
export const dynamic = "force-dynamic";

// Folders are an in-memory grouping over every unlabeled cluster (not a SQL
// pagination boundary), so this is a generous cap rather than a page size -
// see recommend.ts's own note on brute-force scoring being cheap at this scale.
const MAX_UNLABELED = 2000;

// Per-cluster cap on how many member faces feed the review-card carousel -
// clusters can have dozens of faces, and presigning/loading all of them just
// to flip through a few examples isn't worth it.
const MAX_CAROUSEL_FACES = 8;

const ALL_OGS = Array.from({ length: 8 }, (_, i) => `OG${i + 1}`);
const OTHERS_KEY = "OTHERS";

interface UnlabeledClusterRow {
  id: number;
  face_count: number;
  r2_thumbnail_key: string | null;
  centroid: Buffer;
}

interface ClusterFaceRow {
  cluster_id: number;
  r2_thumbnail_key: string;
}

export default async function ReviewPage() {
  // proxy.ts already guarantees a logged-in, allowlisted session for every
  // route including this one - this second check is the finer-grained "is
  // this specific account also a reviewer" gate (see
  // sql/001_allowed_reviewers.sql's can_review column).
  const cookieStore = await cookies();
  const token = cookieStore.get(COOKIE_NAME)?.value;
  const session = token ? await verifySessionToken(token) : null;
  const authorized = session ? await canReviewerAccessReview(session.telegram_user_id) : false;

  if (!authorized) {
    return (
      <div className="max-w-2xl mx-auto p-10">
        <h1 className="text-xl font-semibold mb-2">Review faces</h1>
        <p className="text-sm text-gray-600">
          Your account isn&apos;t authorized to review face clusters. Ask an
          admin if you think this is wrong.
        </p>
      </div>
    );
  }

  const sql = getSql();

  const [unlabeledRows, labeledRows, knownPersons] = await Promise.all([
    sql`
      SELECT id, face_count, r2_thumbnail_key, centroid
      FROM clusters
      WHERE status = 'unlabeled'
      ORDER BY face_count DESC, id ASC
      LIMIT ${MAX_UNLABELED}
    ` as unknown as Promise<UnlabeledClusterRow[]>,
    sql`
      SELECT id, person_name, og, centroid
      FROM clusters
      WHERE status = 'labeled' AND person_name IS NOT NULL
    ` as unknown as Promise<LabeledClusterRow[]>,
    sql`
      SELECT person_name, MAX(og) AS og
      FROM clusters
      WHERE status = 'labeled' AND person_name IS NOT NULL
      GROUP BY person_name
      ORDER BY person_name
    ` as unknown as Promise<KnownPerson[]>,
  ]);

  const decodedLabeled = decodeLabeledClusters(labeledRows);

  const unlabeledIds = unlabeledRows.map((c) => c.id);
  const clusterFaceRows =
    unlabeledIds.length === 0
      ? []
      : ((await sql`
          SELECT cluster_id, r2_thumbnail_key FROM (
            SELECT cluster_id, r2_thumbnail_key,
                   ROW_NUMBER() OVER (PARTITION BY cluster_id ORDER BY det_score DESC) AS rn
            FROM faces
            WHERE cluster_id = ANY(${unlabeledIds}::int[]) AND r2_thumbnail_key IS NOT NULL
          ) ranked
          WHERE rn <= ${MAX_CAROUSEL_FACES}
        `) as unknown as ClusterFaceRow[]);

  const facesByCluster = new Map<number, string[]>();
  for (const row of clusterFaceRows) {
    if (!facesByCluster.has(row.cluster_id)) facesByCluster.set(row.cluster_id, []);
    facesByCluster.get(row.cluster_id)!.push(row.r2_thumbnail_key);
  }

  const allFaceKeys = clusterFaceRows.map((r) => r.r2_thumbnail_key);
  const presignedFaceUrls = await presignGetUrls(allFaceKeys);
  const faceUrlByKey = new Map(allFaceKeys.map((key, i) => [key, presignedFaceUrls[i]]));

  // Fallback for the rare cluster with no linked face-thumbnail rows: the
  // cluster's own representative thumbnail.
  const fallbackKeys = unlabeledRows
    .filter((c) => !facesByCluster.has(c.id) && c.r2_thumbnail_key)
    .map((c) => c.r2_thumbnail_key!);
  const fallbackUrls = await presignGetUrls(fallbackKeys);
  const fallbackUrlByKey = new Map(fallbackKeys.map((key, i) => [key, fallbackUrls[i]]));

  const clusters: ReviewClusterViewModel[] = unlabeledRows.map((c) => {
    const match = findBestMatch(c.centroid, decodedLabeled);
    const faceKeys = facesByCluster.get(c.id);
    const thumbnailUrls = faceKeys
      ? faceKeys.map((key) => faceUrlByKey.get(key)).filter((url): url is string => !!url)
      : c.r2_thumbnail_key
        ? [fallbackUrlByKey.get(c.r2_thumbnail_key)].filter((url): url is string => !!url)
        : [];
    return {
      id: c.id,
      face_count: c.face_count,
      thumbnail_urls: thumbnailUrls,
      recommendation: match
        ? {
            person_name: match.person_name,
            og: match.og,
            similarity: match.similarity,
          }
        : null,
    };
  });

  // Bucket by the recommendation's OG - a match with low-but-above-threshold
  // similarity still files under its own OG rather than Others; only clusters
  // with no usable recommendation at all (or whose match has no OG on record)
  // land in Others.
  const folderMap = new Map<string, ReviewClusterViewModel[]>();
  for (const og of ALL_OGS) folderMap.set(og, []);
  folderMap.set(OTHERS_KEY, []);

  for (const cluster of clusters) {
    const og = cluster.recommendation?.og;
    const bucket = og && folderMap.has(og) ? og : OTHERS_KEY;
    folderMap.get(bucket)!.push(cluster);
  }

  const folders: ReviewFolder[] = [
    ...ALL_OGS.map((og) => ({
      key: og,
      label: `OG ${og.replace("OG", "")}`,
      clusters: folderMap.get(og)!,
    })),
    { key: OTHERS_KEY, label: "Others", clusters: folderMap.get(OTHERS_KEY)! },
  ];

  return (
    <div className="max-w-6xl mx-auto p-6">
      <h1 className="text-xl font-semibold mb-1">Review faces</h1>
      <p className="text-sm text-gray-500 mb-4">
        Unlabeled clusters the pipeline couldn&apos;t confidently match to a
        known person, grouped by their suggested OG. {clusters.length} total.
      </p>

      {clusters.length === 0 ? (
        <p className="text-sm text-gray-500">Nothing to review right now.</p>
      ) : (
        <ReviewFolders folders={folders} knownPersons={knownPersons} />
      )}
    </div>
  );
}
