"use client";

/**
 * Parent portal API helper.
 *
 * The parent 'Ask Pass' gate is enforced SERVER-SIDE: every /api/v1/parent/*
 * route (except the bootstrap auth trio) requires a Bearer access token
 * issued by verify-pin. Tokens live in sessionStorage so closing the tab
 * locks the portal again.
 */

const ACCESS_KEY = "aiguru.parent.access";
const REFRESH_KEY = "aiguru.parent.refresh";

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

async function tryRefresh(): Promise<boolean> {
  const refresh = getParentRefreshToken();
  if (!refresh) return false;
  try {
    const res = await fetch("/api/v1/parent/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    if (data?.access_token) {
      storeParentTokens(data.access_token);
      return true;
    }
    return false;
  } catch {
    return false;
  }
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
  if (res.status === 401 && !_retried) {
    let detail = "";
    try {
      detail = (await res.clone().json())?.detail ?? "";
    } catch {
      /* ignore body parse issues */
    }
    if (detail === "parent_auth_required" || detail === "invalid_refresh_token" || !detail) {
      const ok = await tryRefresh();
      if (ok) return pFetch(input, init, true);
      clearParentTokens();
      throw new ParentAuthError();
    }
  }
  return res;
}
