import { createHash, randomBytes } from "crypto";
import { createRemoteJWKSet, jwtVerify } from "jose";

/**
 * Telegram's OpenID Connect provider: https://core.telegram.org/widgets/login
 * (the "Login with Telegram" library / Web Login flow, distinct from the
 * legacy telegram-widget.js iframe this app used previously).
 */
const OIDC_ISSUER = "https://oauth.telegram.org";
const AUTHORIZATION_ENDPOINT = `${OIDC_ISSUER}/auth`;
const TOKEN_ENDPOINT = `${OIDC_ISSUER}/token`;

const jwks = createRemoteJWKSet(
  new URL(`${OIDC_ISSUER}/.well-known/jwks.json`)
);

export interface PkcePair {
  verifier: string;
  challenge: string;
}

/** PKCE (RFC 7636) code_verifier/code_challenge pair, S256 method. */
export function generatePkce(): PkcePair {
  const verifier = randomBytes(32).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  return { verifier, challenge };
}

/** Opaque anti-CSRF token echoed back by Telegram on the callback. */
export function generateState(): string {
  return randomBytes(16).toString("base64url");
}

export function buildAuthorizationUrl(params: {
  clientId: string;
  redirectUri: string;
  state: string;
  codeChallenge: string;
}): string {
  const url = new URL(AUTHORIZATION_ENDPOINT);
  url.searchParams.set("client_id", params.clientId);
  url.searchParams.set("redirect_uri", params.redirectUri);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", "openid profile");
  url.searchParams.set("state", params.state);
  url.searchParams.set("code_challenge", params.codeChallenge);
  url.searchParams.set("code_challenge_method", "S256");
  return url.toString();
}

export interface TelegramOidcUser {
  id: number;
  username?: string;
}

export type TelegramOidcResult =
  | { ok: true; user: TelegramOidcUser }
  | {
      ok: false;
      reason: "token_endpoint_error" | "missing_id_token" | "bad_id_token" | "missing_id";
    };

/**
 * Exchanges an authorization `code` for an id_token at Telegram's token
 * endpoint, then verifies the id_token's signature against Telegram's JWKS
 * (checking `iss`/`aud`/`exp`) before trusting any claims in it -- per
 * https://core.telegram.org/widgets/login#validating-id-tokens.
 */
export async function exchangeCodeForUser(params: {
  code: string;
  redirectUri: string;
  codeVerifier: string;
  clientId: string;
  clientSecret: string;
}): Promise<TelegramOidcResult> {
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    code: params.code,
    redirect_uri: params.redirectUri,
    client_id: params.clientId,
    code_verifier: params.codeVerifier,
  });

  const basicAuth = Buffer.from(
    `${params.clientId}:${params.clientSecret}`
  ).toString("base64");

  const tokenResponse = await fetch(TOKEN_ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Authorization: `Basic ${basicAuth}`,
    },
    body: body.toString(),
  });

  if (!tokenResponse.ok) {
    return { ok: false, reason: "token_endpoint_error" };
  }

  const tokenJson = (await tokenResponse.json()) as { id_token?: string };
  if (!tokenJson.id_token) {
    return { ok: false, reason: "missing_id_token" };
  }

  let payload;
  try {
    ({ payload } = await jwtVerify(tokenJson.id_token, jwks, {
      issuer: OIDC_ISSUER,
      audience: params.clientId,
    }));
  } catch {
    return { ok: false, reason: "bad_id_token" };
  }

  // Telegram's id_token carries the numeric Telegram user id as `id`
  // (matching the legacy widget's field of the same name -- what
  // allowed_reviewers.telegram_user_id is keyed on), separate from the
  // OIDC-mandated opaque `sub`.
  const telegramId = Number(payload.id);
  if (!Number.isInteger(telegramId)) {
    return { ok: false, reason: "missing_id" };
  }

  const preferredUsername = payload.preferred_username;

  return {
    ok: true,
    user: {
      id: telegramId,
      username:
        typeof preferredUsername === "string" ? preferredUsername : undefined,
    },
  };
}
