"use client";

/**
 * Parent Live Supervision — consented snapshot polling.
 *
 * The STUDENT opts in per session (Vision Guard toggle); the parent polls
 * /api/v1/parent/live/snapshot through the tunnel or LAN at ~1 fps.
 * Frames are never stored server-side beyond the in-memory latest slot and
 * auto-expire when the study session ends or consent is revoked.
 *
 * Polling pauses while the browser tab is hidden to save bandwidth/battery.
 * Ember Glass viewer with scanline sweep while live.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { ShieldAlert, Video, XCircle } from "lucide-react";
import { pFetch } from "@/lib/parent/parent-api";

interface LiveVideoViewProps {
  studentName?: string;
  /** Explicit monitoring session id; omit for "any consented session". */
  sessionId?: string | null;
  onClose: () => void;
}

type LivePhase = "connecting" | "live" | "waiting" | "denied" | "error";

export default function LiveVideoView({ studentName, sessionId, onClose }: LiveVideoViewProps) {
  const [phase, setPhase] = useState<LivePhase>("connecting");
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [frameAge, setFrameAge] = useState<number>(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const hiddenRef = useRef(false);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const poll = useCallback(async () => {
    if (hiddenRef.current) return;
    try {
      const qs = sessionId ? `session_id=${encodeURIComponent(sessionId)}` : "session_id=current";
      const res = await pFetch(`/api/v1/parent/live/snapshot?${qs}`);
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = url;
        setFrameUrl(url);
        const tsHeader = res.headers.get("X-Frame-Timestamp");
        setFrameAge(tsHeader ? Math.max(0, Math.round(Date.now() / 1000 - Number(tsHeader))) : 0);
        setPhase("live");
      } else if (res.status === 404) {
        setPhase((p) => (p === "live" ? "waiting" : "connecting"));
      } else if (res.status === 403) {
        setPhase("denied");
        stopTimer();
      } else if (res.status === 401) {
        // pFetch already attempted refresh; give up quietly this tick.
      } else {
        setPhase("error");
      }
    } catch {
      setPhase((p) => (p === "live" ? p : "error"));
    }
  }, [sessionId, stopTimer]);

  useEffect(() => {
    // Initial poll fires synchronously by design; subsequent ticks are interval-driven.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void poll();
    timerRef.current = setInterval(() => void poll(), 1000);

    const onVisibility = () => {
      hiddenRef.current = document.hidden;
      if (!document.hidden) void poll();
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      stopTimer();
      document.removeEventListener("visibilitychange", onVisibility);
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
    };
  }, [poll, stopTimer]);

  return (
    <div
      className="fixed inset-0 z-[999] flex items-center justify-center p-4 animate-overlay-in"
      style={{ background: "var(--overlay)", backdropFilter: "blur(10px)", WebkitBackdropFilter: "blur(10px)" }}
    >
      <div className="w-full max-w-2xl bento-cell liquid-sheen !rounded-2xl overflow-hidden animate-pop-in">
        {/* Header */}
        <div className="relative z-[2] px-5 py-4 bg-gradient-to-r from-[var(--primary)] to-[#E8895F] text-white flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="p-1.5 bg-white/20 rounded-lg backdrop-blur-sm">
              <Video size={17} />
            </span>
            <div>
              <h3 className="font-display font-bold text-sm">Live Supervision</h3>
              <p className="text-[10px] text-white/85">
                {studentName ? `${studentName} · ` : ""}
                {phase === "live" ? `Live snapshot · updated ${frameAge}s ago` : "Snapshot polling"}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 hover:bg-white/20 rounded-lg transition-colors"
            aria-label="Close live supervision"
          >
            <XCircle size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="aspect-video bg-black flex items-center justify-center relative z-[2]">
          {phase === "live" && frameUrl && (
            <>
              <img
                src={frameUrl}
                alt="Live student camera snapshot"
                className="w-full h-full object-contain"
              />
              <div className="scanline-bar !h-[14%]" style={{ opacity: 0.5 }} aria-hidden />
            </>
          )}
          {phase !== "live" && (
            <div className="text-center space-y-3 px-6">
              {phase === "connecting" || phase === "waiting" ? (
                <>
                  <div className="mx-auto w-10 h-10 rounded-full border-4 border-[var(--primary)] border-t-transparent animate-spin" />
                  <p className="text-white/75 text-sm font-medium">
                    {phase === "connecting"
                      ? "Connecting to live view…"
                      : "Waiting for the student's next frame…"}
                  </p>
                  <p className="text-white/40 text-xs max-w-sm mx-auto">
                    Live view only streams when the student enables &quot;Parent Live View&quot;
                    during an active session. Nothing is recorded.
                  </p>
                </>
              ) : phase === "denied" ? (
                <>
                  <ShieldAlert size={32} className="mx-auto text-red-400" />
                  <p className="text-white/80 text-sm font-medium">
                    Live view is not permitted for this student pairing.
                  </p>
                </>
              ) : (
                <>
                  <Video size={32} className="mx-auto text-white/30" />
                  <p className="text-white/60 text-sm">
                    Could not reach the live view. Ensure you&apos;re connected via the tunnel or LAN.
                  </p>
                </>
              )}
            </div>
          )}

          {phase === "live" && (
            <div className="absolute top-3 left-3 z-10 flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-black/60 backdrop-blur-sm text-[10px] text-[var(--amber)] font-mono">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--primary)] ember-dot" />
              LIVE · CONSENTED
            </div>
          )}
        </div>

        {/* Footer note */}
        <div className="relative z-[2] px-5 py-3 border-t border-[var(--glass-border)] bg-[var(--glass-0)] text-[11px] text-[var(--muted-foreground)] flex items-center gap-2">
          <ShieldAlert size={13} className="shrink-0 text-[var(--amber)]" />
          <span>
            Student-controlled: frames stream only while their toggle is ON and the session is active.
            Auto-terminates at session end — no recording.
          </span>
        </div>
      </div>
    </div>
  );
}
