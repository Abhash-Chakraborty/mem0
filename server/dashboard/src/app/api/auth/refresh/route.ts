import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { AUTH_ENDPOINTS } from "@/utils/api-endpoints";
import { getServerApiUrl } from "@/lib/server-api-url";

const COOKIE_NAME = "mem0_refresh_token";

function shouldUseSecureCookie() {
  const dashboardUrl = process.env.DASHBOARD_URL;
  if (!dashboardUrl) {
    return process.env.NODE_ENV === "production";
  }

  try {
    return new URL(dashboardUrl).protocol === "https:";
  } catch {
    return process.env.NODE_ENV === "production";
  }
}

const COOKIE_OPTIONS = {
  httpOnly: true,
  secure: shouldUseSecureCookie(),
  sameSite: "lax" as const,
  path: "/",
  maxAge: 30 * 24 * 60 * 60, // 30 days
};

export async function POST() {
  const cookieStore = await cookies();
  const refreshToken = cookieStore.get(COOKIE_NAME)?.value;

  if (!refreshToken) {
    return NextResponse.json({ error: "No refresh token" }, { status: 401 });
  }

  let res: Response;
  try {
    res = await fetch(`${getServerApiUrl()}${AUTH_ENDPOINTS.REFRESH}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  } catch {
    // The API is unreachable, which says nothing about whether the token is
    // good. Keeping the cookie lets the session come back on the next attempt
    // instead of turning a restart or a network blip into a forced sign-out.
    return NextResponse.json({ error: "API unreachable" }, { status: 503 });
  }

  if (res.status === 401) {
    // The only answer that means the token itself is spent, expired or revoked.
    cookieStore.delete(COOKIE_NAME);
    return NextResponse.json({ error: "Refresh failed" }, { status: 401 });
  }

  if (!res.ok) {
    // 5xx, a rate-limit 429, a proxy error: transient, so the cookie stays.
    return NextResponse.json({ error: "Refresh failed" }, { status: 503 });
  }

  const data = await res.json();

  cookieStore.set(COOKIE_NAME, data.refresh_token, COOKIE_OPTIONS);

  return NextResponse.json({ access_token: data.access_token });
}

export async function PUT(request: NextRequest) {
  const body = await request.json();
  const cookieStore = await cookies();

  if (!body.refresh_token) {
    return NextResponse.json(
      { error: "Missing refresh_token" },
      { status: 400 },
    );
  }

  cookieStore.set(COOKIE_NAME, body.refresh_token, COOKIE_OPTIONS);
  return NextResponse.json({ ok: true });
}

export async function DELETE() {
  const cookieStore = await cookies();
  cookieStore.delete(COOKIE_NAME);
  return NextResponse.json({ ok: true });
}
