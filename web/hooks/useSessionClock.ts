"use client";

import { useState, useEffect, useRef, useCallback } from "react";

interface UseSessionClockOptions {
  isActive: boolean;
  isPaused: boolean;
  targetSeconds: number | null;
  sessionId: string | null;
}

function honestRemaining(session: Record<string, unknown>, fallbackSecs: number): number {
  const target = Number(session.target_duration_seconds ?? fallbackSecs);
  const worked = Number(session.worked_seconds ?? 0);
  const lastResume = session.last_resume_time;
  const status = String(session.status ?? "");
  let openStretch = 0;
  if (status === "in_progress" && typeof lastResume === "number" && Number.isFinite(lastResume)) {
    openStretch = Math.max(0, Date.now() / 1000 - lastResume);
  }
  const elapsed = Math.max(0, worked + openStretch);
  const safeTarget = Number.isFinite(target) && target > 0 ? target : fallbackSecs;
  return Math.max(0, Math.round(safeTarget - elapsed));
}

/**
 * Server-reconciled session clock.
 * - deadline-based tick (no drift, survives tab throttle via Date.now diff)
 * - reconciles with backend worked_seconds on pause/resume/visibility
 * - single source of truth for HUD, sidebar, floating bar, PiP
 */
export function useSessionClock({ isActive, isPaused, targetSeconds, sessionId }: UseSessionClockOptions) {
  const [timeLeft, setTimeLeft] = useState<number | null>(null);
  const deadlineRef = useRef<number | null>(null);
  const pausedRemainingRef = useRef<number | null>(null);

  const reconcile = useCallback(async () => {
    if (!sessionId || targetSeconds === null) return;
    try {
      const res = await fetch(`/api/v1/study-session/${encodeURIComponent(sessionId)}`);
      if (!res.ok) return;
      const session = (await res.json()) as Record<string, unknown>;
      const remaining = honestRemaining(session, targetSeconds);
      setTimeLeft(remaining);
      if (isPaused) {
        pausedRemainingRef.current = remaining;
        deadlineRef.current = null;
      } else {
        pausedRemainingRef.current = null;
        deadlineRef.current = Date.now() + remaining * 1000;
      }
    } catch {
      /* keep local clock on offline */
    }
  }, [sessionId, targetSeconds, isPaused]);

  const start = useCallback(
    (secs: number) => {
      const safe = Math.max(0, Math.round(secs));
      setTimeLeft(safe);
      pausedRemainingRef.current = null;
      deadlineRef.current = Date.now() + safe * 1000;
    },
    []
  );

  // Pause: freeze remaining; resume: rebuild deadline from frozen value.
  useEffect(() => {
    if (!isActive) return;
    if (isPaused) {
      if (deadlineRef.current !== null) {
        pausedRemainingRef.current = Math.max(0, Math.round((deadlineRef.current - Date.now()) / 1000));
        setTimeLeft(pausedRemainingRef.current);
      }
      deadlineRef.current = null;
      void reconcile();
    } else {
      const base = pausedRemainingRef.current ?? timeLeft;
      if (base !== null) {
        deadlineRef.current = Date.now() + Math.max(0, base) * 1000;
        pausedRemainingRef.current = null;
      }
      void reconcile();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPaused, isActive]);

  // Tick via deadline diff — monotonic, no cumulative drift.
  useEffect(() => {
    if (!isActive || isPaused) return;
    if (timeLeft === null) return;
    if (deadlineRef.current === null) {
      deadlineRef.current = Date.now() + Math.max(0, timeLeft) * 1000;
    }
    const id = setInterval(() => {
      const dl = deadlineRef.current;
      if (dl === null) return;
      const remaining = Math.max(0, Math.round((dl - Date.now()) / 1000));
      setTimeLeft((prev) => (prev === remaining ? prev : remaining));
    }, 500);
    return () => clearInterval(id);
  }, [isActive, isPaused, timeLeft === null]);

  // Reconcile when tab becomes visible again (throttled timers catch up).
  useEffect(() => {
    if (!isActive) return;
    const onVisible = () => {
      if (document.visibilityState === "visible") void reconcile();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [isActive, reconcile]);

  const reset = useCallback(() => {
    deadlineRef.current = null;
    pausedRemainingRef.current = null;
    setTimeLeft(null);
  }, []);

  return { timeLeft, setTimeLeft, start, reconcile, reset };
}

export function computeResumeRemaining(
  row: {
    target_duration_seconds: number;
    actual_duration_seconds?: number;
    worked_seconds?: number;
    last_resume_time?: number | null;
    start_time?: number;
    status?: string;
  },
  nowSecs = Date.now() / 1000
): number {
  const target = Number(row.target_duration_seconds || 0);
  const worked = Number(row.worked_seconds ?? row.actual_duration_seconds ?? 0);
  let openStretch = 0;
  if (row.status === "in_progress" && typeof row.last_resume_time === "number") {
    openStretch = Math.max(0, nowSecs - row.last_resume_time);
  }
  return Math.max(0, Math.round(target - worked - openStretch));
}
