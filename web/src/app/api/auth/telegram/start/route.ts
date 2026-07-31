import { NextRequest, NextResponse } from "next/server";
import {
  buildAuthorizationUrl,
  generatePkce,
  generateState,
} from "@/lib/telegram-oidc";

export const STATE_COOKIE = "tg_oidc_state";
export const VERIFIER_COOKIE = "tg_oidc_verifier";
/** Just needs to outlive the round trip to Telegram and back. */
export const FLOW_MAX_AGE_SECONDS = 10 * 60;

/**
 * Entry point for "Log in with Telegram": stashes a PKCE verifier + CSRF
 * state in short-lived cookies, then redirects to Telegram's OIDC
 * authorization endpoint. The callback route reads these cookies back.
 */
export async function GET(request: NextRequest) {
  const clientId = process.env.TELEGRAM_OIDC_CLIENT_ID;
  if (!clientId) {
    console.error(
      "TELEGRAM_OIDC_CLIENT_ID is not set; cannot start Telegram login."
    );
    return NextResponse.redirect(
      new URL("/login?error=server_misconfigured", request.url)
    );
  }

  const { verifier, challenge } = generatePkce();
  const state = generateState();
  const redirectUri = new URL(
    "/api/auth/telegram/callback",
    request.url
  ).toString();

  const authorizationUrl = buildAuthorizationUrl({
    clientId,
    redirectUri,
    state,
    codeChallenge: challenge,
  });

  const response = NextResponse.redirect(authorizationUrl);
  const cookieOptions = {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/api/auth/telegram",
    maxAge: FLOW_MAX_AGE_SECONDS,
  };
  response.cookies.set(STATE_COOKIE, state, cookieOptions);
  response.cookies.set(VERIFIER_COOKIE, verifier, cookieOptions);
  return response;
}
