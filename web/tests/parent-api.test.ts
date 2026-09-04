/**
 * Node tests for the parent portal transport (lib/parent/parent-api.ts).
 *
 * Covers the auth-recovery contract:
 * - Bearer attach
 * - one transparent refresh+retry on parent-gate 401s
 * - single-flight refresh under concurrent 401 bursts (rotation-safe)
 * - hard-fail path: clear tokens, dispatch aiguru:parent-auth-lost, throw
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  PARENT_AUTH_LOST_EVENT,
  ParentAuthError,
  clearParentTokens,
  getParentAccessToken,
  getParentLiveSnapshotUrl,
  getParentLiveWsProtocols,
  getParentLiveWsUrl,
  getParentRefreshToken,
  lockParentPortal,
  pFetch,
  storeParentTokens,
} from "../lib/parent/parent-api";
import {
  STRICTNESS_LABEL,
  toBackendStrictness,
  toUiStrictness,
} from "../lib/parent/strictness";

// ----------------------------------------------------------------- harness

interface RecordedRequest {
  url: string;
  init: RequestInit | undefined;
}

type FetchResponder = (url: string, init: RequestInit | undefined) => Response | Promise<Response>;

interface Harness {
  requests: RecordedRequest[];
  events: Event[];
  setResponder: (fn: FetchResponder) => void;
  teardown: () => void;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function installHarness(): Harness {
  const requests: RecordedRequest[] = [];
  const events: Event[] = [];
  let responder: FetchResponder = () => jsonResponse({});

  const store = new Map<string, string>();
  const fakeWindow = {
    location: { protocol: "https:", host: "portal.test" },
    sessionStorage: {
      getItem: (key: string) => (store.has(key) ? (store.get(key) as string) : null),
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
      clear: () => store.clear(),
    },
    dispatchEvent: (event: Event) => {
      events.push(event);
      return true;
    },
    addEventListener: () => {},
    removeEventListener: () => {},
  };

  const globalAny = globalThis as unknown as Record<string, unknown>;
  const originalFetch = globalAny.fetch;
  const originalWindow = globalAny.window;

  globalAny.fetch = async (url: unknown, init?: RequestInit) => {
    const urlText = typeof url === "string" ? url : String((url as { url?: string })?.url ?? url);
    requests.push({ url: urlText, init });
    return responder(urlText, init);
  };
  globalAny.window = fakeWindow;

  return {
    requests,
    events,
    setResponder(fn: FetchResponder) {
      responder = fn;
    },
    teardown() {
      globalAny.fetch = originalFetch;
      if (originalWindow === undefined) delete globalAny.window;
      else globalAny.window = originalWindow;
    },
  };
}

// ------------------------------------------------------------------- tests

test("pFetch attaches the stored Bearer token", async () => {
  const h = installHarness();
  try {
    storeParentTokens("access-1", "refresh-1");
    h.setResponder(() => jsonResponse({ ok: true }));

    const res = await pFetch("/api/v1/parent/dashboard/default");

    assert.equal(res.status, 200);
    const auth = new Headers(h.requests[0].init?.headers).get("authorization");
    assert.equal(auth, "Bearer access-1");
  } finally {
    clearParentTokens();
    h.teardown();
  }
});

test("401 parent gate triggers ONE refresh then retries with the new access token", async () => {
  const h = installHarness();
  try {
    storeParentTokens("stale-access", "valid-refresh");

    h.setResponder((url, init) => {
      if (url.endsWith("/auth/refresh")) {
        return jsonResponse({
          access_token: "fresh-access",
          refresh_token: "rotated-refresh",
        });
      }
      const token = new Headers(init?.headers).get("authorization");
      if (token === "Bearer stale-access") {
        return jsonResponse({ detail: "parent_auth_required" }, 401);
      }
      return jsonResponse([{ student_id: "student-primary" }]);
    });

    const res = await pFetch("/api/v1/parent/dashboard/default");

    assert.equal(res.status, 200);
    // First call + refresh + retried call.
    assert.deepEqual(
      h.requests.map((r) => r.url),
      [
        "/api/v1/parent/dashboard/default",
        "/api/v1/parent/auth/refresh",
        "/api/v1/parent/dashboard/default",
      ]
    );
    assert.equal(getParentAccessToken(), "fresh-access");
    assert.equal(getParentRefreshToken(), "rotated-refresh"); // rotation persisted
  } finally {
    clearParentTokens();
    h.teardown();
  }
});

test("concurrent 401s share a single in-flight refresh (rotation-safe)", async () => {
  const h = installHarness();
  try {
    storeParentTokens("stale-access", "valid-refresh");

    h.setResponder((url, init) => {
      if (url.endsWith("/auth/refresh")) {
        return jsonResponse({
          access_token: "fresh-access",
          refresh_token: "rotated-refresh",
        });
      }
      const token = new Headers(init?.headers).get("authorization");
      if (token !== "Bearer fresh-access") {
        return jsonResponse({ detail: "parent_auth_required" }, 401);
      }
      return jsonResponse({ ok: true });
    });

    const [a, b, c] = await Promise.all([
      pFetch("/api/v1/parent/tunnel/status"),
      pFetch("/api/v1/parent/telegram/config?parent_id=default"),
      pFetch("/api/v1/parent/vault/snapshots"),
    ]);

    assert.ok(a.ok && b.ok && c.ok);
    const refreshCalls = h.requests.filter((r) => r.url.endsWith("/auth/refresh")).length;
    assert.equal(refreshCalls, 1); // rotation never thrashed
  } finally {
    clearParentTokens();
    h.teardown();
  }
});

test("verify-pin 401 surfaces verbatim: no refresh, no logout, no auth-lost", async () => {
  const h = installHarness();
  try {
    // No session yet (lock screen) — a wrong PIN must not look like expiry.
    h.setResponder((url) => {
      if (url.endsWith("/auth/verify-pin")) {
        return jsonResponse({ detail: "Invalid PIN. 4 attempts remaining." }, 401);
      }
      return jsonResponse({}, 500);
    });

    const res = await pFetch("/api/v1/parent/auth/verify-pin", {
      method: "POST",
      body: JSON.stringify({ pin: "9999", parent_id: "default" }),
    });

    assert.equal(res.status, 401);
    assert.equal((await res.json()).detail, "Invalid PIN. 4 attempts remaining.");
    assert.equal(
      h.requests.some((r) => r.url.endsWith("/auth/refresh")),
      false
    );
    assert.equal(h.events.some((e) => e.type === PARENT_AUTH_LOST_EVENT), false);
  } finally {
    clearParentTokens();
    h.teardown();
  }
});

test("refresh-endpoint 401 never re-triggers a refresh", async () => {
  const h = installHarness();
  try {
    storeParentTokens("stale-access", "dead-refresh");
    h.setResponder((url) => jsonResponse({ detail: "invalid_refresh_token" }, 401));

    const res = await pFetch("/api/v1/parent/auth/refresh", {
      method: "POST",
      body: JSON.stringify({ refresh_token: "dead-refresh" }),
    });

    assert.equal(res.status, 401);
    const refreshCalls = h.requests.filter((r) =>
      r.url.endsWith("/auth/refresh")
    ).length;
    assert.equal(refreshCalls, 1); // the call itself — no retry loop
  } finally {
    clearParentTokens();
    h.teardown();
  }
});

test("live WS URL carries no token; token travels via subprotocol", async () => {
  const h = installHarness();
  try {
    storeParentTokens("access-abc", "refresh-abc");
    const url = getParentLiveWsUrl("current", "student-primary");
    assert.ok(url && !url.includes("access-abc") && !url.includes("token="));
    assert.ok(url.includes("student_id=student-primary"));
    assert.deepEqual(getParentLiveWsProtocols(), ["parent.access-abc"]);
    assert.ok(
      getParentLiveSnapshotUrl("current", "student-primary").includes(
        "student_id=student-primary"
      )
    );
  } finally {
    clearParentTokens();
    h.teardown();
  }
});

test("lockParentPortal wipes the session and fires auth-lost", async () => {
  const h = installHarness();
  try {
    storeParentTokens("access-1", "refresh-1");
    lockParentPortal();
    assert.equal(getParentAccessToken(), null);
    assert.equal(getParentRefreshToken(), null);
    assert.equal(h.events.some((e) => e.type === PARENT_AUTH_LOST_EVENT), true);
  } finally {
    h.teardown();
  }
});

test("strictness vocabulary round-trips with safe fallbacks", () => {
  assert.equal(toBackendStrictness("lenient"), "gentle");
  assert.equal(toBackendStrictness("normal"), "balanced");
  assert.equal(toBackendStrictness("strict"), "strict");
  assert.equal(toUiStrictness("gentle"), "lenient");
  assert.equal(toUiStrictness("balanced"), "normal");
  assert.equal(toUiStrictness("strict"), "strict");
  assert.equal(toUiStrictness("bogus"), "normal");
  assert.equal(toUiStrictness(undefined), "normal");
  assert.equal(STRICTNESS_LABEL.lenient, "Gentle");
});

test("unrecoverable session clears tokens, fires auth-lost, and throws ParentAuthError", async () => {
  const h = installHarness();
  try {
    storeParentTokens("dead-access", "dead-refresh");

    h.setResponder((url) => {
      if (url.endsWith("/auth/refresh")) {
        return jsonResponse({ detail: "invalid_refresh_token" }, 401);
      }
      return jsonResponse({ detail: "parent_auth_required" }, 401);
    });

    await assert.rejects(
      pFetch("/api/v1/parent/dashboard/default"),
      (err: unknown) => err instanceof ParentAuthError
    );

    assert.equal(getParentAccessToken(), null);
    assert.equal(getParentRefreshToken(), null);
    assert.equal(h.events.some((e) => e.type === PARENT_AUTH_LOST_EVENT), true);
  } finally {
    clearParentTokens();
    h.teardown();
  }
});
