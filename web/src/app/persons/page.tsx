import Link from "next/link";
import { getSql } from "@/lib/db";
import { presignGetUrls } from "@/lib/r2";

export const dynamic = "force-dynamic";

interface PersonRow {
  person_name: string;
  og: string | null;
  r2_thumbnail_key: string | null;
  photo_count: number;
}

export default async function PersonsPage() {
  const sql = getSql();

  // One row per person_name: pick a representative cluster (preferring one
  // with a thumbnail) for the og/thumbnail, and sum distinct photo counts
  // across all of that person's labeled clusters.
  const rows = (await sql`
    WITH labeled AS (
      SELECT
        id,
        person_name,
        og,
        r2_thumbnail_key,
        ROW_NUMBER() OVER (
          PARTITION BY person_name
          ORDER BY (r2_thumbnail_key IS NULL), id
        ) AS rn
      FROM clusters
      WHERE status = 'labeled' AND person_name IS NOT NULL
    ),
    counts AS (
      SELECT c.person_name, COUNT(DISTINCT f.photo_id) AS photo_count
      FROM clusters c
      JOIN faces f ON f.cluster_id = c.id
      WHERE c.status = 'labeled' AND c.person_name IS NOT NULL
      GROUP BY c.person_name
    )
    SELECT
      l.person_name,
      l.og,
      l.r2_thumbnail_key,
      COALESCE(counts.photo_count, 0)::int AS photo_count
    FROM labeled l
    LEFT JOIN counts ON counts.person_name = l.person_name
    WHERE l.rn = 1
    ORDER BY l.person_name
  `) as PersonRow[];

  const thumbnailUrls = await presignGetUrls(
    rows.map((r) => r.r2_thumbnail_key)
  );

  return (
    <div className="max-w-6xl mx-auto p-6">
      <h1 className="text-xl font-semibold mb-1">Persons</h1>
      <p className="text-sm text-gray-500 mb-4">
        {rows.length} labeled {rows.length === 1 ? "person" : "people"}.
      </p>

      {rows.length === 0 ? (
        <p className="text-sm text-gray-500">No labeled persons yet.</p>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {rows.map((r, i) => (
            <Link
              key={r.person_name}
              href={`/persons/${encodeURIComponent(r.person_name)}`}
              className="border border-gray-200 rounded-lg bg-white p-3 flex flex-col gap-2 hover:shadow-sm transition-shadow"
            >
              <div className="aspect-square bg-gray-100 rounded-md overflow-hidden flex items-center justify-center">
                {thumbnailUrls[i] ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={thumbnailUrls[i]!}
                    alt={r.person_name}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <span className="text-gray-400 text-xs">No thumbnail</span>
                )}
              </div>
              <p className="text-sm font-medium text-gray-900 truncate">
                {r.person_name}
              </p>
              <p className="text-xs text-gray-500">
                {r.og ? `${r.og} · ` : ""}
                {r.photo_count} photo(s)
              </p>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
