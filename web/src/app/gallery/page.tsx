import Link from "next/link";
import { getSql } from "@/lib/db";
import { presignGetUrls } from "@/lib/r2";
import GalleryFilters from "./GalleryFilters";
import PhotoGrid from "./PhotoGrid";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 48;

const ALL_DAYS = [1, 2, 3];
const ALL_OGS = Array.from({ length: 8 }, (_, i) => `OG${i + 1}`);

interface PhotoRow {
  id: number;
  filename: string;
  taken_at: string | null;
  day: number | null;
  r2_thumbnail_key: string | null;
  r2_key: string | null;
}

function toArray(v: string | string[] | undefined): string[] {
  if (v === undefined) return [];
  return Array.isArray(v) ? v : [v];
}

function buildHref(day: number[], og: string[], face: string | null, page: number): string {
  const usp = new URLSearchParams();
  day.forEach((d) => usp.append("day", String(d)));
  og.forEach((o) => usp.append("og", o));
  if (face) usp.set("face", face);
  if (page > 1) usp.set("page", String(page));
  const qs = usp.toString();
  return `/gallery${qs ? `?${qs}` : ""}`;
}

export default async function GalleryPage({
  searchParams,
}: {
  searchParams: Promise<{
    day?: string | string[];
    og?: string | string[];
    face?: string;
    page?: string;
  }>;
}) {
  const sp = await searchParams;
  const days = toArray(sp.day)
    .map((d) => parseInt(d, 10))
    .filter((d) => Number.isFinite(d));
  const ogs = toArray(sp.og);
  const face = sp.face && sp.face.trim() ? sp.face.trim() : null;
  const page = Math.max(1, parseInt(sp.page ?? "1", 10) || 1);
  const offset = (page - 1) * PAGE_SIZE;

  const sql = getSql();

  // Filter combination (day multi-select AND og multi-select AND at most one
  // face) isn't expressible with the fixed-shape tagged-template `sql` form used
  // elsewhere in this app, so this builds a parameterized WHERE clause and runs
  // it via sql.query(text, params) instead - every user-controlled value still
  // goes through the params array by position ($1, $2, ...), never string-
  // interpolated into the query text itself.
  const conditions: string[] = ["p.status = 'processed'"];
  const params: unknown[] = [];

  if (days.length > 0) {
    params.push(days);
    conditions.push(`p.day = ANY($${params.length}::int[])`);
  }
  if (ogs.length > 0) {
    params.push(ogs);
    conditions.push(
      `p.id IN (SELECT f.photo_id FROM faces f JOIN clusters c ON c.id = f.cluster_id WHERE c.status = 'labeled' AND c.og = ANY($${params.length}::text[]))`
    );
  }
  if (face) {
    params.push(face);
    conditions.push(
      `p.id IN (SELECT f.photo_id FROM faces f JOIN clusters c ON c.id = f.cluster_id WHERE c.status = 'labeled' AND c.person_name = $${params.length})`
    );
  }
  const whereClause = conditions.join(" AND ");

  const countParams = [...params];
  const rowsParams = [...params, PAGE_SIZE, offset];
  const limitIdx = params.length + 1;
  const offsetIdx = params.length + 2;

  const [photoRows, countRows, personRows] = await Promise.all([
    sql.query(
      `SELECT p.id, p.filename, p.taken_at, p.day, p.r2_thumbnail_key, p.r2_key
       FROM photos p
       WHERE ${whereClause}
       ORDER BY p.taken_at DESC NULLS LAST, p.id DESC
       LIMIT $${limitIdx} OFFSET $${offsetIdx}`,
      rowsParams
    ) as unknown as Promise<PhotoRow[]>,
    sql.query(`SELECT COUNT(*)::int AS count FROM photos p WHERE ${whereClause}`, countParams) as unknown as Promise<
      { count: number }[]
    >,
    sql`SELECT DISTINCT person_name FROM clusters WHERE status = 'labeled' AND person_name IS NOT NULL ORDER BY person_name` as unknown as Promise<
      { person_name: string }[]
    >,
  ]);

  const total = countRows[0]?.count ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const thumbnailUrls = await presignGetUrls(photoRows.map((p) => p.r2_thumbnail_key ?? p.r2_key));

  return (
    <div className="max-w-6xl mx-auto p-6">
      <h1 className="text-xl font-semibold mb-1">Gallery</h1>
      <p className="text-sm text-gray-500 mb-4">{total} photo(s)</p>

      <GalleryFilters
        days={ALL_DAYS}
        ogs={ALL_OGS}
        persons={personRows.map((r) => r.person_name)}
        selectedDays={days}
        selectedOgs={ogs}
        selectedFace={face}
      />

      <PhotoGrid
        photos={photoRows.map((p, i) => ({
          id: p.id,
          filename: p.filename,
          day: p.day,
          thumbnailUrl: thumbnailUrls[i],
        }))}
      />

      {totalPages > 1 && (
        <div className="flex items-center gap-3 mt-6 text-sm">
          {page > 1 && (
            <Link
              href={buildHref(days, ogs, face, page - 1)}
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
              href={buildHref(days, ogs, face, page + 1)}
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
