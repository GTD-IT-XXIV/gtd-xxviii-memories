import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

const PRESIGN_EXPIRY_SECONDS = 60 * 60; // 1 hour

let cachedClient: S3Client | null = null;
let cachedBucket: string | null = null;

/**
 * Lazily creates (and caches) the R2 (S3-compatible) client. Lazy for the
 * same reason as lib/db.ts: no credentials exist at `next build` time.
 */
function getR2Client(): S3Client {
  if (!cachedClient) {
    const accountId = process.env.R2_ACCOUNT_ID;
    const accessKeyId = process.env.R2_ACCESS_KEY_ID;
    const secretAccessKey = process.env.R2_SECRET_ACCESS_KEY;
    if (!accountId || !accessKeyId || !secretAccessKey) {
      throw new Error(
        "R2 credentials are not set (R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY). See .env.example."
      );
    }
    cachedClient = new S3Client({
      region: "auto",
      endpoint: `https://${accountId}.r2.cloudflarestorage.com`,
      credentials: { accessKeyId, secretAccessKey },
    });
  }
  return cachedClient;
}

function getBucket(): string {
  if (!cachedBucket) {
    const bucket = process.env.R2_BUCKET_NAME;
    if (!bucket) {
      throw new Error("R2_BUCKET_NAME is not set. See .env.example.");
    }
    cachedBucket = bucket;
  }
  return cachedBucket;
}

/** RFC 5987 encoding for a filename in a Content-Disposition header: percent-encodes
 * everything outside a conservative safe set, so non-ASCII and quotes/semicolons in a
 * photo's filename can't break (or inject into) the header. */
function encodeFilename(filename: string): string {
  return encodeURIComponent(filename).replace(/['()*]/g, (c) => "%" + c.charCodeAt(0).toString(16).toUpperCase());
}

/**
 * Presigns a single R2 object key for a short-lived GET, or returns null for a
 * null/empty key.
 *
 * Pass `downloadFilename` to make the browser SAVE the object instead of displaying
 * it. This is not cosmetic: an <a download> attribute is silently ignored for
 * cross-origin URLs, so without this a presigned image URL just navigates the tab to
 * the JPEG and renders it. `ResponseContentDisposition` is signed into the URL and
 * makes R2 itself return `Content-Disposition: attachment`, which does force a
 * download - and carries the filename, which the ignored `download` attribute could
 * not.
 */
export async function presignGetUrl(
  key: string | null | undefined,
  downloadFilename?: string
): Promise<string | null> {
  if (!key) return null;
  const client = getR2Client();
  const command = new GetObjectCommand({
    Bucket: getBucket(),
    Key: key,
    ...(downloadFilename
      ? {
          // Both forms: `filename` for older clients, `filename*` for correct
          // handling of non-ASCII names (which Indonesian filenames may contain).
          ResponseContentDisposition:
            `attachment; filename="${downloadFilename.replace(/["\\]/g, "")}"; ` +
            `filename*=UTF-8''${encodeFilename(downloadFilename)}`,
        }
      : {}),
  });
  return getSignedUrl(client, command, { expiresIn: PRESIGN_EXPIRY_SECONDS });
}

/**
 * Presigns a batch of R2 object keys in one call. Signing is a local SigV4
 * computation (no network round trip), so fanning this out with
 * Promise.all is cheap even for a full page of thumbnails.
 */
export async function presignGetUrls(
  keys: Array<string | null | undefined>
): Promise<Array<string | null>> {
  return Promise.all(keys.map((key) => presignGetUrl(key)));
}

// NOTE: a getObjectStream() helper used to live here, for streaming originals
// through the server into a zip. It was removed along with that download path -
// proxying image bytes through the server made them count as origin transfer.
// Everything client-facing goes through presigned URLs above so the browser
// fetches from R2 directly (R2 egress to the internet is free).
