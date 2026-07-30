import { createHash, createHmac, timingSafeEqual } from "crypto";

/**
 * Replay-attack protection window recommended by Telegram's own docs for
 * the Login Widget: https://core.telegram.org/widgets/login#checking-authorization
 */
const AUTH_MAX_AGE_SECONDS = 24 * 60 * 60;

export interface TelegramAuthUser {
  id: number;
  first_name?: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
  auth_date: number;
}

export type TelegramVerifyResult =
  | { ok: true; user: TelegramAuthUser }
  | { ok: false; reason: "missing_fields" | "bad_hash" | "stale" };

/**
 * Verifies the query-string payload Telegram's Login Widget appends when it
 * redirects back to `data-auth-url`, per Telegram's documented algorithm:
 *
 *   1. data-check-string = every received field except `hash`, sorted
 *      alphabetically by key, formatted `key=value`, joined by `\n`.
 *   2. secret_key = SHA256(bot_token) (raw bytes).
 *   3. expected_hash = HMAC-SHA256(data-check-string, secret_key), hex.
 *   4. Compare expected_hash to the received `hash` in constant time.
 *   5. Reject stale payloads (replay-attack protection).
 *
 * This must run on the Node.js runtime (uses Node's `crypto` module), which
 * is why it lives behind a Route Handler and not `proxy.ts`.
 */
export function verifyTelegramLogin(
  params: URLSearchParams,
  botToken: string
): TelegramVerifyResult {
  const hash = params.get("hash");
  const id = params.get("id");
  const authDateRaw = params.get("auth_date");
  if (!hash || !id || !authDateRaw) {
    return { ok: false, reason: "missing_fields" };
  }

  const dataCheckString = [...params.entries()]
    .filter(([key]) => key !== "hash")
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([key, value]) => `${key}=${value}`)
    .join("\n");

  const secretKey = createHash("sha256").update(botToken).digest();
  const expectedHash = createHmac("sha256", secretKey)
    .update(dataCheckString)
    .digest("hex");

  const expectedBuf = Buffer.from(expectedHash, "utf8");
  const receivedBuf = Buffer.from(hash, "utf8");
  const hashesMatch =
    expectedBuf.length === receivedBuf.length &&
    timingSafeEqual(expectedBuf, receivedBuf);

  if (!hashesMatch) {
    return { ok: false, reason: "bad_hash" };
  }

  const authDate = Number(authDateRaw);
  const nowSeconds = Math.floor(Date.now() / 1000);
  if (
    !Number.isFinite(authDate) ||
    nowSeconds - authDate > AUTH_MAX_AGE_SECONDS
  ) {
    return { ok: false, reason: "stale" };
  }

  const telegramId = Number(id);
  if (!Number.isInteger(telegramId)) {
    return { ok: false, reason: "missing_fields" };
  }

  return {
    ok: true,
    user: {
      id: telegramId,
      first_name: params.get("first_name") ?? undefined,
      last_name: params.get("last_name") ?? undefined,
      username: params.get("username") ?? undefined,
      photo_url: params.get("photo_url") ?? undefined,
      auth_date: authDate,
    },
  };
}
