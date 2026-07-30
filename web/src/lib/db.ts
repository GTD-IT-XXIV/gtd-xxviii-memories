import { neon, type NeonQueryFunction } from "@neondatabase/serverless";

let cached: NeonQueryFunction<false, false> | null = null;

/**
 * Lazily creates (and caches) the Neon HTTP query function.
 *
 * IMPORTANT: this must stay lazy. Route handlers / server components import
 * this module at build time (when Next.js collects page data), and there is
 * no DATABASE_URL available in that context. Reading `process.env` only
 * inside this function, at request time, keeps `next build` from throwing.
 */
export function getSql(): NeonQueryFunction<false, false> {
  if (!cached) {
    const url = process.env.DATABASE_URL;
    if (!url) {
      throw new Error(
        "DATABASE_URL is not set. Add it to your environment (see .env.example)."
      );
    }
    cached = neon(url);
  }
  return cached;
}

/** Current UTC timestamp in the same ISO-8601 text format the Python pipeline writes. */
export function nowIso(): string {
  return new Date().toISOString();
}
