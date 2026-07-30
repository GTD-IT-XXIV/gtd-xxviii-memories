import Link from "next/link";
import { getSql } from "@/lib/db";
import { presignGetUrls } from "@/lib/r2";
import {
  decodeLabeledClusters,
  findBestMatch,
  type LabeledClusterRow,
} from "@/lib/recommend";
import type { KnownPerson, ReviewClusterViewModel } from "@/lib/types";
import ReviewClusterCard from "./ReviewClusterCard";

// This page hits Postgres/R2 on every request and must never be prerendered
// at build time (no DATABASE_URL / R2 credentials exist during `next build`).
export const dynamic = "force-dynamic";

const PAGE_SIZE = 24;

interface UnlabeledClusterRow {
  id: number;
  face_count: number;
  r2_thumbnail_key: string | null;
  centroid: Buffer;
}

export default async function ReviewPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string }>;
}) {
  const params = await searchParams;
  const page = Math.max(1, parseInt(params.page ?? "1", 10) || 1);
  const offset = (page - 1) * PAGE_SIZE;

  const sql = getSql();

  const [unlabeledRows, labeledRows, countRows, knownPersons] =
    await Promise.all([
      sql`
        SELECT id, face_count, r2_thumbnail_key, centroid
        FROM clusters
        WHERE status = 'unlabeled'
        ORDER BY face_count DESC, id ASC
        LIMIT ${PAGE_SIZE} OFFSET ${offset}
      ` as unknown as Promise<UnlabeledClusterRow[]>,
      sql`
        SELECT id, person_name, og, centroid
        FROM clusters
        WHERE status = 'labeled' AND person_name IS NOT NULL
      ` as unknown as Promise<LabeledClusterRow[]>,
      sql`
        SELECT COUNT(*)::int AS count FROM clusters WHERE status = 'unlabeled'
      ` as unknown as Promise<{ count: number }[]>,
      sql`
        SELECT person_name, MAX(og) AS og
        FROM clusters
        WHERE status = 'labeled' AND person_name IS NOT NULL
        GROUP BY person_name
        ORDER BY person_name
      ` as unknown as Promise<KnownPerson[]>,
    ]);

  const totalUnlabeled = countRows[0]?.count ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalUnlabeled / PAGE_SIZE));

  const decodedLabeled = decodeLabeledClusters(labeledRows);

  const thumbnailUrls = await presignGetUrls(
    unlabeledRows.map((c) => c.r2_thumbnail_key)
  );

  const clusters: ReviewClusterViewModel[] = unlabeledRows.map((c, i) => {
    const match = findBestMatch(c.centroid, decodedLabeled);
    return {
      id: c.id,
      face_count: c.face_count,
      thumbnail_url: thumbnailUrls[i],
      recommendation: match
        ? {
            person_name: match.person_name,
            og: match.og,
            similarity: match.similarity,
          }
        : null,
    };
  });

  return (
    <div className="max-w-6xl mx-auto p-6">
      <h1 className="text-xl font-semibold mb-1">Review faces</h1>
      <p className="text-sm text-gray-500 mb-4">
        Unlabeled clusters the pipeline couldn&apos;t confidently match to a
        known person, sorted by how many faces they contain.{" "}
        {totalUnlabeled} remaining.
      </p>

      {clusters.length === 0 ? (
        <p className="text-sm text-gray-500">Nothing to review right now.</p>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
          {clusters.map((cluster) => (
            <ReviewClusterCard
              key={cluster.id}
              cluster={cluster}
              knownPersons={knownPersons}
            />
          ))}
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center gap-3 mt-6 text-sm">
          {page > 1 && (
            <Link
              href={`/review?page=${page - 1}`}
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
              href={`/review?page=${page + 1}`}
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
