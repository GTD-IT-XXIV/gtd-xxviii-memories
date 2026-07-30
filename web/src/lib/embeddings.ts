/**
 * Decoding/comparing the 512 x float32, L2-normalized embeddings the Python
 * pipeline writes into `faces.embedding` / `clusters.centroid` (BYTEA, raw
 * little-endian float32 bytes -- see the schema contract).
 */

export const EMBEDDING_DIM = 512;
export const EMBEDDING_BYTE_LENGTH = EMBEDDING_DIM * 4; // 2048

/**
 * Decodes a Postgres BYTEA column (delivered to Node as a Buffer) into a
 * Float32Array.
 *
 * A `Buffer` returned by a Postgres driver is frequently a *view* into a
 * larger shared allocation pool -- its `byteOffset` is not guaranteed to be
 * a multiple of 4. Constructing `new Float32Array(buf.buffer, buf.byteOffset, ...)`
 * directly on such a view can silently misalign every float read, producing
 * wrong-but-plausible-looking similarity scores instead of a crash.
 *
 * `Uint8Array.from(buffer)` copies the bytes into a brand-new, tightly
 * packed ArrayBuffer (offset 0), so the Float32Array view built on top of
 * it is always correctly aligned.
 */
export function decodeEmbedding(buffer: Buffer | Uint8Array): Float32Array {
  const bytes = Uint8Array.from(buffer);
  if (bytes.byteLength !== EMBEDDING_BYTE_LENGTH) {
    throw new Error(
      `Expected a ${EMBEDDING_BYTE_LENGTH}-byte embedding (512 x float32), got ${bytes.byteLength} bytes`
    );
  }
  return new Float32Array(bytes.buffer);
}

/**
 * Cosine similarity between two embeddings. Since both `faces.embedding`
 * and `clusters.centroid` are already L2-normalized by the Python pipeline,
 * cosine similarity reduces to a plain dot product.
 */
export function dotProduct(a: Float32Array, b: Float32Array): number {
  if (a.length !== b.length) {
    throw new Error(`Vector length mismatch: ${a.length} vs ${b.length}`);
  }
  let sum = 0;
  for (let i = 0; i < a.length; i++) {
    sum += a[i] * b[i];
  }
  return sum;
}
