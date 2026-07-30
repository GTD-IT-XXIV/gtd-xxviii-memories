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

/** Presigns a single R2 object key for a short-lived GET, or returns null for a null/empty key. */
export async function presignGetUrl(
  key: string | null | undefined
): Promise<string | null> {
  if (!key) return null;
  const client = getR2Client();
  const command = new GetObjectCommand({ Bucket: getBucket(), Key: key });
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
