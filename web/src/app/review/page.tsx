import Link from "next/link";
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
import ReviewClusterGrid from "./ReviewClusterGrid";

// This page hits Postgres/R2 on every request and must never be prerendered
// at build time (no DATABASE_URL / R2 credentials exist during `next build`).
export const dynamic = "force-dynamic";

// Folder cards carry an image carousel + correction UI, heavier than a plain
// gallery thumbnail - half of gallery's PAGE_SIZE (48) keeps a page digestible.
const PAGE_SIZE = 24;

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

interface UnlabeledClusterRow {
  id: number;
  face_count: number;
  r2_thumbnail_key: string | null;
  centroid: Buffer;
  deferred_to_others: boolean;
}

interface ClusterFaceRow {
  cluster_id: number;
  r2_thumbnail_key: string;
}

// Lightweight per-cluster data produced by the bucketing pass below - deliberately
// NOT carrying thumbnails yet, so every navigation can afford to re-run this over
// every unlabeled cluster (cheap: a plain O(labeled) dot-product scan per cluster,
// see recommend.ts) without paying for face-thumbnail fetches/R2 presigning until
// we know exactly which page of which folder is actually being rendered.
interface LightCluster {
  id: number;
  face_count: number;
  r2_thumbnail_key: string | null;
  recommendation: ReviewClusterViewModel["recommendation"];
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

  const [unlabeledRows, labeledRows, knownPersons] = await Promise.all([
    // No LIMIT here - folder membership only exists after the bucketing pass
    // below runs in JS (it's not a stored/indexed column), so a SQL-level cap
    // would silently truncate whichever clusters happen to sort last, cutting
    // them out of every folder rather than just paginating one. See the note
    // above LightCluster and below the bucketing loop for how this stays cheap
    // even uncapped, and where that stops being true.
    sql`
      SELECT id, face_count, r2_thumbnail_key, centroid, deferred_to_others
      FROM clusters
      WHERE status = 'unlabeled'
      ORDER BY face_count DESC, id ASC
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

  // Bucketing pass: reruns in full on every navigation (folder switch AND every
  // Prev/Next click), since a cluster's folder isn't stored anywhere - it's
  // recomputed here every time. Measured cheap at low thousands of unlabeled
  // clusters (matches recommend.ts's own note); at roughly 5,000+ unlabeled
  // clusters this starts costing low seconds of synchronous work per request
  // (~labeled-count dot products per unlabeled cluster). If that threshold is
  // ever reached, the fix is a materialized `clusters.suggested_og` column
  // populated by the Python pipeline, or a short-TTL cache - not needed yet.
  const folderMap = new Map<string, LightCluster[]>();
  for (const key of VALID_FOLDER_KEYS) folderMap.set(key, []);

  for (const c of unlabeledRows) {
    // Deferred clusters ("Move to Others" on a prior visit) skip matching
    // entirely - the reviewer already rejected whatever suggestion this would
    // produce, and a null recommendation is what routes it into Others below.
    const match = c.deferred_to_others ? null : findBestMatch(c.centroid, decodedLabeled);
    const recommendation = match
      ? { person_name: match.person_name, og: match.og, similarity: match.similarity }
      : null;
    const bucket = recommendation?.og && folderMap.has(recommendation.og) ? recommendation.og : OTHERS_KEY;
    folderMap.get(bucket)!.push({
      id: c.id,
      face_count: c.face_count,
      r2_thumbnail_key: c.r2_thumbnail_key,
      recommendation,
    });
  }

  const totalUnlabeled = unlabeledRows.length;

  if (!requestedFolder) {
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
                <span className="text-xs text-gray-500">{folderMap.get(key)!.length} to review</span>
              </Link>
            ))}
          </div>
        )}
      </div>
    );
  }

  const folderClusters = folderMap.get(requestedFolder)!;
  const total = folderClusters.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const page = Math.min(requestedPage, totalPages);
  const offset = (page - 1) * PAGE_SIZE;
  const pageSlice = folderClusters.slice(offset, offset + PAGE_SIZE);
  const pageIds = pageSlice.map((c) => c.id);

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
  const fallbackKeys = pageSlice
    .filter((c) => !facesByCluster.has(c.id) && c.r2_thumbnail_key)
    .map((c) => c.r2_thumbnail_key!);
  const fallbackUrls = await presignGetUrls(fallbackKeys);
  const fallbackUrlByKey = new Map(fallbackKeys.map((key, i) => [key, fallbackUrls[i]]));

  const pageClusters: ReviewClusterViewModel[] = pageSlice.map((c) => {
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
      // Others is a catch-all (no recommendation, or a recommendation whose OG
      // isn't one of the known 8) - don't show a "suggested match" for either case.
      recommendation: requestedFolder === OTHERS_KEY ? null : c.recommendation,
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
