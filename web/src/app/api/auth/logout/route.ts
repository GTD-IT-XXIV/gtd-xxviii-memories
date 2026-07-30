import { NextRequest, NextResponse } from "next/server";
import { COOKIE_NAME } from "@/lib/session";

/** Clears the session cookie and sends the browser back to /login. */
export async function POST(request: NextRequest) {
  // 303 forces the browser to follow up with a GET, since the nav "Log
  // out" button submits this as a POST and /login only handles GET.
  const response = NextResponse.redirect(new URL("/login", request.url), 303);
  response.cookies.delete(COOKIE_NAME);
  return response;
}
