"use client";

/**
 * Parent portal API helper.
 *
 * The parent 'Ask Pass' gate is enforced SERVER-SIDE: every /api/v1/parent/*
 * route (except the bootstrap auth trio) requires a Bearer access token
 * issued by verify-pin. Tokens live in sessionStorage so closing the tab
 * locks the portal again.
 *
 * Refresh handling:
 * - Access tokens last 15 min; refresh tokens rotate server-side (the old
 *   refresh token is revoked on each exchange).
 * - Concurrent callers share ONE in-flight refresh (single-flight) so a burst
 *   of 401s can never thrash the rotation or log a valid session out.
 * - When recovery is impossible we clear tokens, broadcast
 *   `aiguru:parent-auth-lost`, and throw ParentAuthError so pages re-lock.
 */

const ACCESS_KEY = "aiguru.parent.access";
const REFRESH_KEY = "aiguru.parent.refresh";

export const PARENT_AUTH_LOST_EVENT = "aiguru:parent-auth-lost";

export class ParentAuthError extends Error {
  constructor() {
    super("Parent authentication required");
    this.name = "ParentAuthError";
  }
}

export function getParentAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(ACCESS_KEY);
}

export function getParentRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(REFRESH_KEY);
}

export function storeParentTokens(access: string, refresh?: string): void {
  window.sessionStorage.setItem(ACCESS_KEY, access);
  if (refresh) window.sessionStorage.setItem(REFRESH_KEY, refresh);
}

export function clearParentTokens(): void {
  window.sessionStorage.removeItem(ACCESS_KEY);
  window.sessionStorage.removeItem(REFRESH_KEY);
}

function notifyAuthLost(): void {
  try {
    window.dispatchEvent(new Event(PARENT_AUTH_LOST_EVENT));
  } catch {
    /* non-browser or listener-less environments */
  }
}

async function doRefresh(refresh: string): Promise<boolean> {
  try {
    const res = await fetch("/api/v1/parent/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    if (data?.access_token) {
      // Server rotates refresh tokens; persist the new pair atomically-ish.
      storeParentTokens(data.access_token, data.refresh_token ?? undefined);
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

let refreshInFlight: Promise<boolean> | null = null;

/** Single-flight: concurrent 401s share one refresh request. */
function tryRefresh(): Promise<boolean> {
  const refresh = getParentRefreshToken();
  if (!refresh) return Promise.resolve(false);
  if (!refreshInFlight) {
    refreshInFlight = doRefresh(refresh).finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

/** fetch wrapper: attaches Bearer, auto-refreshes once on parent-auth 401s. */
export async function pFetch(
  input: string,
  init?: RequestInit,
  _retried = false
): Promise<Response> {
  const token = getParentAccessToken();
  const headers = new Headers(init?.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(input, { ...init, headers });
  const isParentRoute = input.includes("/api/v1/parent/");
  if (res.status === 401 && !_retried && isParentRoute) {
    // Refresh on ANY 401 from a parent route: the backend phrases expiry
    // differently across endpoints ("parent_auth_required", "Token
    // superseded by a PIN change", raw JWT errors) — all mean "try the
    // refresh token once, then fall back to the PIN gate".
    let detail = "";
    try {
      detail = (await res.clone().json())?.detail ?? "";
    } catch {
      /* ignore body parse issues */
    }
    if (detail !== "invalid_refresh_token") {
      const ok = await tryRefresh();
      if (ok) return pFetch(input, init, true);
      clearParentTokens();
      notifyAuthLost();
      throw new ParentAuthError();
    }
  }
  return res;
}

/** POST JSON helper returning parsed body + ok flag (throws ParentAuthError upstream). */
export async function pJson<T = unknown>(
  input: string,
  init?: RequestInit
): Promise<{ ok: boolean; status: number; data: T | null }> {
  const headers = new Headers(init?.headers || {});
  if (!headers.has("Content-Type") && init?.body) {
    headers.set("Content-Type", "application/json");
  }
  const res = await pFetch(input, { ...init, headers });
  let data: T | null = null;
  try {
    data = (await res.json()) as T;
  } catch {
    /* empty body */
  }
  return { ok: res.ok, status: res.status, data };
}

export interface LiveStreamStartResult {
  session_id?: string;
  enabled?: boolean;
  tunnel_url?: string | null;
  lan_url?: string | null;
}

export async function startParentLiveStream(
  sessionId = "current"
): Promise<{ ok: boolean; status: number; data: LiveStreamStartResult | null }> {
  return pJson<LiveStreamStartResult>(
    `/api/v1/parent/live/start?session_id=${encodeURIComponent(sessionId)}`,
    { method: "POST" }
  );
}

export async function stopParentLiveStream(
  sessionId = "current"
): Promise<{ ok: boolean; status: number; data: { stopped?: boolean } | null }> {
  return pJson<{ stopped?: boolean }>(
    `/api/v1/parent/live/stop?session_id=${encodeURIComponent(sessionId)}`,
    { method: "POST" }
  );
}

export function getParentLiveWsUrl(sessionId = "current"): string | null {
  if (typeof window === "undefined") return null;
  const token = getParentAccessToken();
  if (!token) return null;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/v1/parent/live/stream?session_id=${encodeURIComponent(sessionId)}&token=${encodeURIComponent(token)}`;
}
