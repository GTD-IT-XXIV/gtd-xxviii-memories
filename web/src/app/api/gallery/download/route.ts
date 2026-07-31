import { Readable } from "node:stream";
import { ZipArchive } from "archiver";
import { getSql } from "@/lib/db";
import { getObjectStream } from "@/lib/r2";

const MAX_PHOTOS = 500;

interface PhotoRow {
  id: number;
  filename: string;
  r2_key: string | null;
}

/** Dedupes filenames within one zip (two originals can share a filename when
 * scanned from different source folders/machines) by suffixing " (n)". */
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

  const archive = new ZipArchive({ zlib: { level: 6 } });
  const nameFor = uniqueNamer();

  // Appends run in the background as the response stream is consumed by the
  // client; archiver pulls from each object stream in turn and finalizes once
  // every entry has been added.
  (async () => {
    for (const row of rows) {
      try {
        const stream = await getObjectStream(row.r2_key!);
        archive.append(stream, { name: nameFor(row.filename) });
      } catch (err) {
        console.error(`gallery download: failed to fetch r2_key=${row.r2_key} for photo ${row.id}`, err);
      }
    }
    archive.finalize();
  })();

  const timestamp = new Date().toISOString().slice(0, 10);
  return new Response(Readable.toWeb(archive) as unknown as ReadableStream, {
    headers: {
      "Content-Type": "application/zip",
      "Content-Disposition": `attachment; filename="gtd-photos-${timestamp}.zip"`,
    },
  });
}
