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

/**
 * Explicit re-lock: wipe the session and tell every listener to show the
 * PIN gate. Used after a passcode change (the PIN epoch invalidates all
 * outstanding tokens by design) and anywhere else that needs an
 * explained logout rather than a silent 401.
 */
export function lockParentPortal(): void {
  clearParentTokens();
  notifyAuthLost();
}

async function doRefresh(refresh: string): Promise<boolean> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 10_000);
  try {
    const res = await fetch("/api/v1/parent/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
      signal: ctrl.signal,
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
  } finally {
    clearTimeout(timer);
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

/**
 * Auth-bootstrap routes that must NEVER trigger a token refresh:
 * - verify-pin: a 401 here means "wrong PIN / locked out" and the detail
 *   string (remaining tries, lockout seconds) must reach the UI verbatim.
 *   Refreshing would also wipe the (absent) session and throw
 *   ParentAuthError, masking the real message as "Connection error".
 * - refresh: refreshing the refresh endpoint recurses pointlessly.
 * - has-pin / set-pin(first-time): ungated bootstrap, no session to save.
 * Authenticated auth routes (change-pin, logout) are NOT exempt: their
 * 401s mean expiry and should refresh like any other parent route.
 */
const NO_REFRESH_SUFFIXES = [
  "/api/v1/parent/auth/verify-pin",
  "/api/v1/parent/auth/refresh",
  "/api/v1/parent/auth/has-pin",
  "/api/v1/parent/auth/set-pin",
];

function isRefreshExempt(input: string): boolean {
  const path = input.split("?")[0];
  return NO_REFRESH_SUFFIXES.some((s) => path.endsWith(s));
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
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 20_000);
  let res: Response;
  try {
    res = await fetch(input, { ...init, headers, signal: init?.signal ?? ctrl.signal });
  } catch (err) {
    // Network/offline/timeout: honest typed error so pages render a retry
    // banner instead of an unhandled rejection.
    throw new Error("Parent portal unreachable. Check connection and try again.", {
      cause: err,
    });
  } finally {
    clearTimeout(timer);
  }
  const isParentRoute = input.includes("/api/v1/parent/");
  if (res.status === 401 && !_retried && isParentRoute && !isRefreshExempt(input)) {
    // Any 401 from a gated parent route means "try the refresh token once,
    // then fall back to the PIN gate". Backend phrases expiry differently
    // across endpoints ("parent_auth_required", "Token superseded by a PIN
    // change", raw JWT errors) — all recoverable via rotation.
    const ok = await tryRefresh();
    if (ok) return pFetch(input, init, true);
    clearParentTokens();
    notifyAuthLost();
    throw new ParentAuthError();
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
  mode?: "tunnel" | "lan" | string;
  reachable_remotely?: boolean;
  message?: string | null;
}

export async function startParentLiveStream(
  sessionId = "current",
  studentId?: string | null
): Promise<{ ok: boolean; status: number; data: LiveStreamStartResult | null }> {
  const q =
    `session_id=${encodeURIComponent(sessionId)}` +
    (studentId ? `&student_id=${encodeURIComponent(studentId)}` : "");
  return pJson<LiveStreamStartResult>(
    `/api/v1/parent/live/start?${q}`,
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

function liveStreamQuery(sessionId: string, studentId?: string | null): string {
  return (
    `session_id=${encodeURIComponent(sessionId)}` +
    (studentId ? `&student_id=${encodeURIComponent(studentId)}` : "")
  );
}

export function getParentLiveWsUrl(
  sessionId = "current",
  studentId?: string | null
): string | null {
  if (typeof window === "undefined") return null;
  // Same-origin WS through the Next /api rewrite. Note: Next rewrites proxy
  // HTTP but NOT WebSocket upgrades, so the live view treats this transport
  // as opportunistic — LiveVideoView always runs the HTTP snapshot poll in
  // parallel and falls back to it when the socket fails.
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/v1/parent/live/stream?${liveStreamQuery(sessionId, studentId)}`;
}

/**
 * Subprotocol tokens for the live WS: `Sec-WebSocket-Protocol: parent.<jwt>`.
 * Keeps the parent JWT out of URLs (proxy logs, history). The backend still
 * accepts `?token=` for older clients.
 */
export function getParentLiveWsProtocols(): string[] {
  const token = getParentAccessToken();
  return token ? [`parent.${token}`] : [];
}

export function getParentLiveSnapshotUrl(
  sessionId = "current",
  studentId?: string | null
): string {
  return `/api/v1/parent/live/snapshot?${liveStreamQuery(sessionId, studentId)}`;
}

export interface ParentVoiceCall {
  call_id?: string;
  session_id?: string;
  parent_id?: string;
  student_id?: string;
  mode?: string;
  started_at?: number;
  ends_at?: number;
  seconds_left?: number;
  active?: boolean;
  end_reason?: string;
}

export interface VoiceSignalItem {
  type: string;
  payload: string;
  ts: number;
}

export async function startParentVoiceCall(
  sessionId = "current",
  studentId?: string | null
): Promise<{ ok: boolean; status: number; data: { call?: ParentVoiceCall } | null }> {
  const q =
    `session_id=${encodeURIComponent(sessionId)}` +
    (studentId ? `&student_id=${encodeURIComponent(studentId)}` : "");
  return pJson<{ call?: ParentVoiceCall }>(`/api/v1/parent/voice/call?${q}`, { method: "POST" });
}

export async function endParentVoiceCall(
  sessionId = "current"
): Promise<{ ok: boolean; status: number; data: unknown }> {
  return pJson(`/api/v1/parent/voice/end?session_id=${encodeURIComponent(sessionId)}`, {
    method: "POST",
  });
}

export async function getParentVoiceStatus(
  sessionId = "current",
  studentId?: string | null
): Promise<{ ok: boolean; status: number; data: { active?: boolean; call?: ParentVoiceCall; session_id?: string } | null }> {
  const q =
    `session_id=${encodeURIComponent(sessionId)}` +
    (studentId ? `&student_id=${encodeURIComponent(studentId)}` : "");
  return pJson(`/api/v1/parent/voice/status?${q}`);
}

export async function postParentVoiceSignal(
  sessionId: string,
  type: string,
  payload: string
): Promise<{ ok: boolean; status: number }> {
  const { ok, status } = await pJson("/api/v1/parent/voice/signal", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, type, payload }),
  });
  return { ok, status };
}

export async function pollParentVoiceSignal(
  sessionId = "current"
): Promise<{ ok: boolean; data: { signals?: VoiceSignalItem[]; call?: ParentVoiceCall | null } | null }> {
  const { ok, data } = await pJson<{ signals?: VoiceSignalItem[]; call?: ParentVoiceCall | null }>(
    `/api/v1/parent/voice/signal?session_id=${encodeURIComponent(sessionId)}`
  );
  return { ok, data };
}

export async function sendParentVoiceAnnouncement(
  sessionId: string,
  text: string,
  studentId?: string | null
): Promise<{ ok: boolean; status: number; data: unknown }> {
  return pJson("/api/v1/parent/voice/announce", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, student_id: studentId ?? null, text }),
  });
}
