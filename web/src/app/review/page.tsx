import Link from "next/link";
import { cookies } from "next/headers";
import { getSql } from "@/lib/db";
import { presignGetUrls } from "@/lib/r2";
import { canReviewerAccessReview } from "@/lib/allowlist";
import { COOKIE_NAME, verifySessionToken } from "@/lib/session";
import type { KnownPerson, ReviewClusterViewModel } from "@/lib/types";
import ReviewClusterGrid from "./ReviewClusterGrid";

// This page hits Postgres/R2 on every request and must never be prerendered
// at build time (no DATABASE_URL / R2 credentials exist during `next build`).
export const dynamic = "force-dynamic";

// Folder cards carry an image carousel + correction UI, heavier than a plain
// gallery thumbnail, so smaller than gallery's PAGE_SIZE (48). Deliberately the
// LCM of every grid breakpoint's column count (2/3/4/5, see ReviewClusterGrid's
// grid-cols-*) so a full page never leaves a partial last row at any screen size.
const PAGE_SIZE = 60;

// Per-cluster cap on how many member faces feed the review-card carousel -
// clusters can have dozens of faces, and presigning/loading all of them just
// to flip through a few examples isn't worth it.
const MAX_CAROUSEL_FACES = 8;

const ALL_OGS = Array.from({ length: 8 }, (_, i) => `OG${i + 1}`);
const OTHERS_KEY = "OTHERS";
const VALID_FOLDER_KEYS = new Set<string>([...ALL_OGS, OTHERS_KEY]);

function folderLabel(key: string): string {
  return key === OTHERS_KEY ? "Others" : `OG ${key.replace("OG", "")}`;
}

function buildReviewHref(folder: string, page: number): string {
  const usp = new URLSearchParams({ folder });
  if (page > 1) usp.set("page", String(page));
  return `/review?${usp.toString()}`;
}

interface FolderCountRow {
  folder: string;
  cnt: number;
}

interface BucketedCountRow {
  cnt: number;
}

interface BucketedRow {
  id: number;
  face_count: number;
  r2_thumbnail_key: string | null;
  suggested_person_name: string | null;
  suggested_og: string | null;
  suggested_similarity: number | null;
}

interface ClusterFaceRow {
  cluster_id: number;
  r2_thumbnail_key: string;
}

export default async function ReviewPage({
  searchParams,
}: {
  searchParams: Promise<{ folder?: string; page?: string }>;
}) {
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

  const sp = await searchParams;
  const requestedFolder = sp.folder && VALID_FOLDER_KEYS.has(sp.folder) ? sp.folder : null;
  const requestedPage = Math.max(1, parseInt(sp.page ?? "1", 10) || 1);

  const sql = getSql();

  // Folder membership is derived from a materialized suggestion
  // (clusters.suggested_cluster_id -> app/clustering/suggestions.py on the backend)
  // via a query-time join, not recomputed here - a cluster's folder is "the OG of
  // its suggested match", or Others if deferred/unsuggested/an unknown OG. Using an
  // FK (not denormalized name/og text) means a later rename or merge/discard of the
  // suggested cluster is reflected immediately, never stale.
  if (!requestedFolder) {
    // knownPersons (search/OG-tab picker data) isn't needed on this screen at all -
    // only the folder-detail screen below renders ReviewClusterGrid/Card, which is
    // the only consumer of it.
    const folderCounts = await (sql`
      SELECT
        CASE WHEN c.deferred_to_others THEN 'OTHERS'
             WHEN s.og = ANY(${ALL_OGS}::text[]) THEN s.og
             ELSE 'OTHERS' END AS folder,
        COUNT(*)::int AS cnt
      FROM clusters c
      LEFT JOIN clusters s ON s.id = c.suggested_cluster_id AND s.status = 'labeled'
      WHERE c.status = 'unlabeled'
      GROUP BY 1
    ` as unknown as Promise<FolderCountRow[]>);

    const countByFolder = new Map(folderCounts.map((r) => [r.folder, r.cnt]));
    const totalUnlabeled = folderCounts.reduce((sum, r) => sum + r.cnt, 0);

    return (
      <div className="max-w-6xl mx-auto p-6">
        <h1 className="text-xl font-semibold mb-1">Review faces</h1>
        <p className="text-sm text-gray-500 mb-4">
          Unlabeled clusters the pipeline couldn&apos;t confidently match to a
          known person, grouped by their suggested OG. {totalUnlabeled} total.
        </p>
        {totalUnlabeled === 0 ? (
          <p className="text-sm text-gray-500">Nothing to review right now.</p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-4">
            {[...VALID_FOLDER_KEYS].map((key) => (
              <Link
                key={key}
                href={buildReviewHref(key, 1)}
                className="border border-gray-200 rounded-lg p-4 flex flex-col items-center gap-1 bg-white hover:bg-gray-50"
              >
                <span className="text-3xl">&#128193;</span>
                <span className="font-medium text-sm">{folderLabel(key)}</span>
                <span className="text-xs text-gray-500">{countByFolder.get(key) ?? 0} to review</span>
              </Link>
            ))}
          </div>
        )}
      </div>
    );
  }

  // sql`...` (the tagged-template form used everywhere else on this page) executes
  // immediately and isn't a composable fragment - it can't be built once and reused
  // across the count/rows queries below. Use sql.query(text, params) instead (the
  // same parameterized-dynamic-SQL pattern gallery/page.tsx already establishes),
  // with the shared CTE text as a plain string and every value - including the
  // validated `requestedFolder` - still passed positionally, never interpolated
  // into the query text itself.
  const bucketedCte = `
    WITH bucketed AS (
      SELECT c.id, c.face_count, c.r2_thumbnail_key, c.suggested_similarity,
             s.person_name AS suggested_person_name, s.og AS suggested_og,
             CASE WHEN c.deferred_to_others THEN 'OTHERS'
                  WHEN s.og = ANY($1::text[]) THEN s.og
                  ELSE 'OTHERS' END AS folder
      FROM clusters c
      LEFT JOIN clusters s ON s.id = c.suggested_cluster_id AND s.status = 'labeled'
      WHERE c.status = 'unlabeled'
    )
  `;

  // Count first, then clamp the requested page before computing the offset for the
  // rows query below - two sequential round trips (not parallelizable, the second
  // depends on the first), but both are indexed/CTE-scoped and sub-10ms; the thing
  // being replaced was a multi-second in-memory brute-force scan, so this is still a
  // large net win.
  const [countRows, knownPersons] = await Promise.all([
    sql.query(`${bucketedCte} SELECT COUNT(*)::int AS cnt FROM bucketed WHERE folder = $2`, [
      ALL_OGS,
      requestedFolder,
    ]) as unknown as Promise<BucketedCountRow[]>,
    sql`
      SELECT person_name, MAX(og) AS og
      FROM clusters
      WHERE status = 'labeled' AND person_name IS NOT NULL
      GROUP BY person_name
      ORDER BY person_name
    ` as unknown as Promise<KnownPerson[]>,
  ]);

  const total = countRows[0]?.cnt ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const page = Math.min(requestedPage, totalPages);
  const offset = (page - 1) * PAGE_SIZE;

  const bucketedRows =
    total === 0
      ? []
      : ((await sql.query(
          `${bucketedCte}
           SELECT id, face_count, r2_thumbnail_key, suggested_person_name, suggested_og, suggested_similarity
           FROM bucketed
           WHERE folder = $2
           ORDER BY face_count DESC, id ASC
           LIMIT $3 OFFSET $4`,
          [ALL_OGS, requestedFolder, PAGE_SIZE, offset]
        )) as unknown as BucketedRow[]);

  const pageIds = bucketedRows.map((r) => r.id);

  const clusterFaceRows =
    pageIds.length === 0
      ? []
      : ((await sql`
          SELECT cluster_id, r2_thumbnail_key FROM (
            SELECT cluster_id, r2_thumbnail_key,
                   ROW_NUMBER() OVER (PARTITION BY cluster_id ORDER BY det_score DESC) AS rn
            FROM faces
            WHERE cluster_id = ANY(${pageIds}::int[]) AND r2_thumbnail_key IS NOT NULL
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
  const fallbackKeys = bucketedRows
    .filter((c) => !facesByCluster.has(c.id) && c.r2_thumbnail_key)
    .map((c) => c.r2_thumbnail_key!);
  const fallbackUrls = await presignGetUrls(fallbackKeys);
  const fallbackUrlByKey = new Map(fallbackKeys.map((key, i) => [key, fallbackUrls[i]]));

  const pageClusters: ReviewClusterViewModel[] = bucketedRows.map((c) => {
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
      // Others is a catch-all (deferred, no suggestion, or a suggestion whose OG
      // isn't one of the known 8) - don't show a "suggested match" for any of those.
      recommendation:
        requestedFolder !== OTHERS_KEY && c.suggested_person_name && c.suggested_similarity !== null
          ? { person_name: c.suggested_person_name, og: c.suggested_og, similarity: c.suggested_similarity }
          : null,
    };
  });

  return (
    <div className="max-w-6xl mx-auto p-6">
      <Link href="/review" className="text-sm text-indigo-600 hover:underline mb-3 inline-block">
        &larr; Back to folders
      </Link>
      <h2 className="text-lg font-semibold mb-3">
        {folderLabel(requestedFolder)} <span className="text-sm font-normal text-gray-500">({total})</span>
      </h2>

      {pageClusters.length === 0 ? (
        <p className="text-sm text-gray-500">Nothing left to review in this folder.</p>
      ) : (
        <ReviewClusterGrid
          key={`${requestedFolder}-${page}`}
          clusters={pageClusters}
          knownPersons={knownPersons}
          // OTHERS is a catch-all bucket, not an OG - there's no folder-implied
          // group to preselect there, so leave the picker on "No OG".
          defaultOg={requestedFolder === OTHERS_KEY ? null : requestedFolder}
        />
      )}

      {totalPages > 1 && (
        <div className="flex items-center gap-3 mt-6 text-sm">
          {page > 1 && (
            <Link
              href={buildReviewHref(requestedFolder, page - 1)}
              className="px-3 py-1 rounded border border-gray-300 hover:bg-gray-50"
            >
              Previous
            </Link>
          )}
          <span className="text-gray-500">
            Page {page} of {totalPages}
          </span>
          {page < totalPages && (
            <Link
              href={buildReviewHref(requestedFolder, page + 1)}
              className="px-3 py-1 rounded border border-gray-300 hover:bg-gray-50"
            >
              Next
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
