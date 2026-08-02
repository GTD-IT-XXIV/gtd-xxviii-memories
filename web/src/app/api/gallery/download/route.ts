import { getSql } from "@/lib/db";
import { presignGetUrl } from "@/lib/r2";

const MAX_PHOTOS = 500;

interface PhotoRow {
  id: number;
  filename: string;
  r2_key: string | null;
}

/** Dedupes filenames within one download batch (two originals can share a
 * filename when scanned from different source folders/machines) by
 * suffixing " (n)". */
function uniqueNamer() {
  const seen = new Map<string, number>();
  return (filename: string): string => {
    const count = seen.get(filename) ?? 0;
    seen.set(filename, count + 1);
    if (count === 0) return filename;
    const dot = filename.lastIndexOf(".");
    return dot === -1 ? `${filename} (${count})` : `${filename.slice(0, dot)} (${count})${filename.slice(dot)}`;
  };
}

/**
 * Returns short-lived presigned R2 URLs for the requested photos so the browser
 * downloads each original DIRECTLY from R2.
 *
 * This route used to stream the originals through the server into a zip
 * (r2 -> server -> browser). That made every downloaded byte count as Vercel
 * origin transfer, and originals here are 8-15MB each: a single 500-photo
 * download moved several GB and burned the whole monthly allowance in one go.
 * R2's egress to the internet is free, so handing out presigned URLs and
 * letting the client fetch them takes this route's transfer to ~zero - the
 * response is now a few KB of JSON regardless of how many photos are selected.
 *
 * The tradeoff is deliberate: the user gets N separate files instead of one
 * zip. Zipping without proxying the bytes would have to happen client-side
 * (browser memory) or in a Cloudflare Worker (free egress) - see the gallery
 * download notes in README.md.
 *
 * Access control is unchanged: proxy.ts gates every non-auth route behind a
 * valid session, so only logged-in users can reach this and obtain URLs. The
 * URLs themselves expire in an hour (lib/r2.ts PRESIGN_EXPIRY_SECONDS).
 */
export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const photoIds = Array.isArray(body?.photoIds)
    ? body.photoIds.filter((v: unknown): v is number => typeof v === "number" && Number.isFinite(v))
    : [];

  if (photoIds.length === 0) {
    return Response.json({ error: "photoIds is required" }, { status: 400 });
  }
  if (photoIds.length > MAX_PHOTOS) {
    return Response.json({ error: `Cannot download more than ${MAX_PHOTOS} photos at once` }, { status: 400 });
  }

  const sql = getSql();
  const rows = (await sql`
    SELECT id, filename, r2_key
    FROM photos
    WHERE id = ANY(${photoIds}::int[]) AND status = 'processed' AND r2_key IS NOT NULL
  `) as unknown as PhotoRow[];

  if (rows.length === 0) {
    return Response.json({ error: "No matching photos found" }, { status: 404 });
  }

  const nameFor = uniqueNamer();
  // Signing is a local SigV4 computation with no network round trip, so doing
  // 500 of them in one request is cheap (same reasoning as presignGetUrls).
  const files = await Promise.all(
    rows.map(async (row) => ({
      id: row.id,
      filename: nameFor(row.filename),
      url: await presignGetUrl(row.r2_key),
    }))
  );

  return Response.json({ files: files.filter((f) => f.url !== null) });
}
