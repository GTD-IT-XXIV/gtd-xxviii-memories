import { NextRequest, NextResponse } from "next/server";
import { COOKIE_NAME, verifySessionToken } from "@/lib/session";

// NOTE: Next.js 16 renamed the `middleware.ts` file convention to
// `proxy.ts` (function renamed `middleware` -> `proxy`); the old name is
// deprecated. See node_modules/next/dist/docs/01-app/01-getting-started/16-proxy.md.
// Functionally this is what used to be called Middleware: it runs before
// every matched request and can redirect/rewrite. Unlike pre-16 Middleware,
// Proxy always runs on the Node.js runtime (not configurable), which is
// why plain `jose` (Edge + Node compatible) works fine here.

/**
 * Gates the whole app behind a valid session cookie. Optimistic check only
 * (verifies the JWT signature/expiry, does not hit Postgres) -- see
 * app/lib/session.ts. This is intentional per Next's own auth guidance:
 * Proxy runs on every request/prefetch, so it should stay cheap.
 */
export async function proxy(request: NextRequest) {
  const token = request.cookies.get(COOKIE_NAME)?.value;
  const session = token ? await verifySessionToken(token) : null;

  if (!session) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    // Everything except: the login page itself, the auth Route Handlers
    // (which must stay reachable while logged out / logging out), and
    // Next.js's own static/image/favicon assets.
    "/((?!login|api/auth/telegram/start|api/auth/telegram/callback|api/auth/logout|_next/static|_next/image|favicon.ico).*)",
  ],
};
