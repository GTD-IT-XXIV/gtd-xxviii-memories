import { NextRequest, NextResponse } from "next/server";
import { verifyTelegramLogin } from "@/lib/telegram-auth";
import { resolveAllowedReviewer } from "@/lib/allowlist";
import {
  COOKIE_NAME,
  SESSION_MAX_AGE_SECONDS,
  createSessionToken,
} from "@/lib/session";

/**
 * Telegram's Login Widget redirects the browser here (GET, with the
 * signed user payload as query params) after a successful widget login.
 * This must be a Route Handler, not proxy.ts / middleware -- signature
 * verification needs Node's `crypto` module.
 */
export async function GET(request: NextRequest) {
  const botToken = process.env.TELEGRAM_BOT_TOKEN;
  if (!botToken) {
    console.error(
      "TELEGRAM_BOT_TOKEN is not set; cannot verify Telegram login callback."
    );
    return NextResponse.redirect(
      new URL("/login?error=server_misconfigured", request.url)
    );
  }

  const result = verifyTelegramLogin(request.nextUrl.searchParams, botToken);

  if (!result.ok) {
    // Don't leak *why* verification failed to the client (could help an
    // attacker iterate on a forged payload) -- log server-side only. A
    // mismatched hash means this request did not actually come from
    // Telegram.
    console.error(`Telegram login verification failed: ${result.reason}`);
    return NextResponse.redirect(
      new URL("/login?error=verification_failed", request.url)
    );
  }

  const { user } = result;
  const username = user.username ? user.username.toLowerCase() : null;

  let allowed;
  try {
    allowed = await resolveAllowedReviewer(user.id, username);
  } catch (err) {
    console.error("Allowlist lookup failed during Telegram login:", err);
    return NextResponse.redirect(
      new URL("/login?error=server_misconfigured", request.url)
    );
  }

  if (!allowed) {
    console.warn(
      `Telegram login rejected (not on allowlist): id=${user.id} username=${
        username ?? "(none)"
      }`
    );
    return NextResponse.redirect(
      new URL("/login?error=not_authorized", request.url)
    );
  }

  const token = await createSessionToken({ telegram_user_id: user.id });

  const response = NextResponse.redirect(new URL("/review", request.url));
  response.cookies.set(COOKIE_NAME, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
  return response;
}
