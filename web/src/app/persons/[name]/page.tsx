import Link from "next/link";
import { notFound } from "next/navigation";
import { getSql } from "@/lib/db";
import { presignGetUrls } from "@/lib/r2";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 40;

interface PhotoRow {
  id: number;
  filename: string;
  taken_at: string | null;
  r2_thumbnail_key: string | null;
  r2_key: string | null;
}

export default async function PersonGalleryPage({
  params,
  searchParams,
}: {
  params: Promise<{ name: string }>;
  searchParams: Promise<{ page?: string }>;
}) {
  const { name } = await params;
  const personName = decodeURIComponent(name);
  const { page: pageParam } = await searchParams;
  const page = Math.max(1, parseInt(pageParam ?? "1", 10) || 1);
  const offset = (page - 1) * PAGE_SIZE;

  const sql = getSql();

  const clusterRows = (await sql`
    SELECT id FROM clusters
    WHERE person_name = ${personName} AND status = 'labeled'
  `) as { id: number }[];

  if (clusterRows.length === 0) {
    notFound();
  }
  const clusterIds = clusterRows.map((c) => c.id);

  const [photoRows, countRows] = await Promise.all([
    sql`
      SELECT p.id, p.filename, p.taken_at, p.r2_thumbnail_key, p.r2_key
      FROM photos p
      WHERE p.id IN (
        SELECT DISTINCT f.photo_id FROM faces f
        WHERE f.cluster_id = ANY(${clusterIds})
      )
      AND p.status = 'processed'
      ORDER BY p.taken_at DESC NULLS LAST, p.id DESC
      LIMIT ${PAGE_SIZE} OFFSET ${offset}
    ` as unknown as Promise<PhotoRow[]>,
    sql`
      SELECT COUNT(DISTINCT f.photo_id)::int AS count
      FROM faces f
      JOIN photos p ON p.id = f.photo_id
      WHERE f.cluster_id = ANY(${clusterIds}) AND p.status = 'processed'
    ` as unknown as Promise<{ count: number }[]>,
  ]);

  const total = countRows[0]?.count ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const thumbnailUrls = await presignGetUrls(
    photoRows.map((p) => p.r2_thumbnail_key ?? p.r2_key)
  );

  return (
    <div className="max-w-6xl mx-auto p-6">
      <Link href="/persons" className="text-sm text-indigo-600 hover:underline">
        &larr; All persons
      </Link>
      <h1 className="text-xl font-semibold mt-2 mb-1">{personName}</h1>
      <p className="text-sm text-gray-500 mb-4">{total} photo(s)</p>

      {photoRows.length === 0 ? (
        <p className="text-sm text-gray-500">No photos found.</p>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {photoRows.map((p, i) => (
            <div
              key={p.id}
              className="aspect-square bg-gray-100 rounded-md overflow-hidden flex items-center justify-center"
            >
              {thumbnailUrls[i] ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={thumbnailUrls[i]!}
                  alt={p.filename}
                  className="w-full h-full object-cover"
                />
              ) : (
                <span className="text-gray-400 text-xs">No image</span>
              )}
            </div>
          ))}
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center gap-3 mt-6 text-sm">
          {page > 1 && (
            <Link
              href={`/persons/${encodeURIComponent(personName)}?page=${page - 1}`}
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
              href={`/persons/${encodeURIComponent(personName)}?page=${page + 1}`}
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
