import { SignJWT, jwtVerify } from "jose";

/** Name of the cookie holding the signed session JWT. */
export const COOKIE_NAME = "gtd_session";

/** Session lifetime, expressed both ways `jose` and `cookies().set()` want it. */
const SESSION_DURATION = "7d";
export const SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60;

export interface SessionPayload {
  telegram_user_id: number;
}

let cachedSecret: Uint8Array | null = null;

/**
 * Lazily encodes (and caches) the session-signing secret. Lazy for the same
 * reason as lib/db.ts / lib/r2.ts: this module is imported by Route
 * Handlers, `proxy.ts`, and a Server Component (layout), all of which get
 * evaluated by `next build` without real secrets present. Reading
 * `process.env.SESSION_SECRET` only inside this function (at request time)
 * keeps the build from failing.
 */
function getSecretKey(): Uint8Array {
  if (!cachedSecret) {
    const secret = process.env.SESSION_SECRET;
    if (!secret) {
      throw new Error(
        "SESSION_SECRET is not set. Generate one with `openssl rand -base64 32` " +
          "and add it to your environment (see .env.example)."
      );
    }
    cachedSecret = new TextEncoder().encode(secret);
  }
  return cachedSecret;
}

/** Signs a short-lived session JWT for an already-authorized Telegram user. */
export async function createSessionToken(
  payload: SessionPayload
): Promise<string> {
  return new SignJWT({ telegram_user_id: payload.telegram_user_id })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(SESSION_DURATION)
    .sign(getSecretKey());
}

/**
 * Verifies a session JWT (signature + expiry). Returns `null` on any
 * failure (missing, malformed, expired, wrong signature) rather than
 * throwing, since every caller just wants a yes/no "is this a valid
 * session" answer.
 */
export async function verifySessionToken(
  token: string
): Promise<SessionPayload | null> {
  try {
    const { payload } = await jwtVerify(token, getSecretKey(), {
      algorithms: ["HS256"],
    });
    const telegramUserId = payload.telegram_user_id;
    if (typeof telegramUserId !== "number") {
      return null;
    }
    return { telegram_user_id: telegramUserId };
  } catch {
    return null;
  }
}
