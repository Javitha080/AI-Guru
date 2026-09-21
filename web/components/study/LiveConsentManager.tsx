"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { monitoringApi } from "@/lib/monitoring/monitoringApi";
import { apiFetch } from "@/lib/api";

interface UseLiveConsentOptions {
  sessionId: string | null;
  onNotice?: (notice: { kind: "error" | "warn"; text: string } | null) => void;
}

/**
 * Parent Live View consent — ON by default, student opts out any time.
 *
 * Sync readiness comes from the backend itself: consent requires an active
 * monitoring session server-side, so a 409 means "no channel yet" and the
 * hook retries when the room reports the channel up (markChannelUp) instead
 * of needing a canSync prop (which would prop-cycle with telemetry).
 * Turning OFF always sticks locally first — the switch never traps ON.
 */
export function useLiveConsent({ sessionId, onNotice }: UseLiveConsentOptions) {
  const [liveViewEnabled, setLiveViewEnabled] = useState(true);
  const [pending, setPending] = useState(false);
  const syncedSessionRef = useRef<string | null>(null);
  const stateRef = useRef({ liveViewEnabled: true, sessionId: null as string | null });
  stateRef.current = { liveViewEnabled, sessionId };

  const postConsent = useCallback(async (sid: string, enabled: boolean) => {
    const res = await apiFetch(monitoringApi.liveConsent(sid), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    if (!res.ok) {
      const err = new Error(String(res.status)) as Error & { status?: number };
      err.status = res.status;
      throw err;
    }
  }, []);

  const trySyncOn = useCallback(
    async (sid: string) => {
      if (syncedSessionRef.current === sid) return true;
      try {
        await postConsent(sid, true);
        syncedSessionRef.current = sid;
        return true;
      } catch {
        return false; // 409 (no channel yet) or network — caller decides
      }
    },
    [postConsent]
  );

  // Auto-sync the default-ON consent for a fresh session. A 409 just means
  // the monitoring socket isn't up yet — markChannelUp retries then.
  useEffect(() => {
    if (!liveViewEnabled || !sessionId) return;
    if (syncedSessionRef.current === sessionId) return;
    let cancelled = false;
    (async () => {
      const ok = await trySyncOn(sessionId);
      if (!ok && !cancelled) {
        /* pending until the channel reports up; switch stays truthfully ON */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [liveViewEnabled, sessionId, trySyncOn]);

  // Consent is per-session: a new session starts opted-in again.
  useEffect(() => {
    syncedSessionRef.current = null;
    setLiveViewEnabled(true);
    setPending(false);
  }, [sessionId]);

  /** Room calls this when the monitoring WS connects — flush pending ON sync. */
  const markChannelUp = useCallback(() => {
    const { liveViewEnabled: on, sessionId: sid } = stateRef.current;
    if (on && sid) void trySyncOn(sid);
  }, [trySyncOn]);

  const toggleLiveView = useCallback(
    async (next: boolean) => {
      if (pending) return;
      const { sessionId: sid } = stateRef.current;
      if (!sid) {
        setLiveViewEnabled(next);
        return;
      }
      const prev = stateRef.current.liveViewEnabled;
      setLiveViewEnabled(next);
      if (!next) {
        // Opt-out always wins locally; converge server-side best-effort.
        // Socket close purges server consent anyway — never trap the student ON.
        if (syncedSessionRef.current === sid) syncedSessionRef.current = null;
        setPending(true);
        try {
          await postConsent(sid, false);
        } catch {
          /* local OFF stands; backend converges on close/retry */
        } finally {
          setPending(false);
        }
        return;
      }
      setPending(true);
      try {
        await postConsent(sid, true);
        syncedSessionRef.current = sid;
      } catch (e) {
        // ON failed to register — revert so the switch never lies.
        setLiveViewEnabled(prev);
        const status = (e as Error & { status?: number })?.status;
        onNotice?.({
          kind: "warn",
          text:
            status === 409
              ? "Parent Live View needs camera monitoring — unavailable while unmonitored."
              : "Could not sync Parent Live View consent with the backend — snapshots won't upload.",
        });
      } finally {
        setPending(false);
      }
    },
    [postConsent, onNotice, pending]
  );

  return {
    liveViewEnabled,
    setLiveViewEnabled,
    toggleLiveView,
    markChannelUp,
    pending,
  };
}
