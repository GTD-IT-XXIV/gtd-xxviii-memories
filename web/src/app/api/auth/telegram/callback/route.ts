import { NextRequest, NextResponse } from "next/server";
import { exchangeCodeForUser } from "@/lib/telegram-oidc";
import { STATE_COOKIE, VERIFIER_COOKIE } from "@/app/api/auth/telegram/start/route";
import { resolveAllowedReviewer } from "@/lib/allowlist";
import {
  COOKIE_NAME,
  SESSION_MAX_AGE_SECONDS,
  createSessionToken,
} from "@/lib/session";

const FLOW_COOKIE_PATH = "/api/auth/telegram";

function clearFlowCookies(response: NextResponse) {
  response.cookies.delete({ name: STATE_COOKIE, path: FLOW_COOKIE_PATH });
  response.cookies.delete({ name: VERIFIER_COOKIE, path: FLOW_COOKIE_PATH });
}

function redirectWithError(request: NextRequest, error: string) {
  const response = NextResponse.redirect(
    new URL(`/login?error=${error}`, request.url)
  );
  clearFlowCookies(response);
  return response;
}

/**
 * Telegram's OIDC provider redirects the browser here (GET, with `code` +
 * `state`) after a successful login at oauth.telegram.org. This must be a
 * Route Handler, not proxy.ts / middleware -- the token exchange and
 * id_token verification need Node's `crypto` module and an outbound fetch.
 */
export async function GET(request: NextRequest) {
  const clientId = process.env.TELEGRAM_OIDC_CLIENT_ID;
  const clientSecret = process.env.TELEGRAM_OIDC_CLIENT_SECRET;
  if (!clientId || !clientSecret) {
    console.error(
      "TELEGRAM_OIDC_CLIENT_ID/TELEGRAM_OIDC_CLIENT_SECRET is not set; cannot complete Telegram login."
    );
    return redirectWithError(request, "server_misconfigured");
  }

  const params = request.nextUrl.searchParams;
  const code = params.get("code");
  const state = params.get("state");
  const expectedState = request.cookies.get(STATE_COOKIE)?.value;
  const codeVerifier = request.cookies.get(VERIFIER_COOKIE)?.value;

  // A mismatched/missing state means this callback didn't originate from a
  // login we started (CSRF), or the flow cookies expired -- don't leak
  // which, just bounce back to /login.
  if (!code || !state || !expectedState || !codeVerifier || state !== expectedState) {
    console.error("Telegram OIDC callback failed the state/PKCE check.");
    return redirectWithError(request, "verification_failed");
  }

  const redirectUri = new URL(
    "/api/auth/telegram/callback",
    request.url
  ).toString();

  const result = await exchangeCodeForUser({
    code,
    redirectUri,
    codeVerifier,
    clientId,
    clientSecret,
  });

  if (!result.ok) {
    console.error(`Telegram OIDC login verification failed: ${result.reason}`);
    return redirectWithError(request, "verification_failed");
  }

  const { user } = result;
  const username = user.username ? user.username.toLowerCase() : null;

  let allowed;
  try {
    allowed = await resolveAllowedReviewer(user.id, username);
  } catch (err) {
    console.error("Allowlist lookup failed during Telegram login:", err);
    return redirectWithError(request, "server_misconfigured");
  }

  if (!allowed) {
    console.warn(
      `Telegram login rejected (not on allowlist): id=${user.id} username=${
        username ?? "(none)"
      }`
    );
    return redirectWithError(request, "not_authorized");
  }

  const token = await createSessionToken({ telegram_user_id: user.id });

  const response = NextResponse.redirect(new URL("/gallery", request.url));
  clearFlowCookies(response);
  response.cookies.set(COOKIE_NAME, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
  return response;
}
