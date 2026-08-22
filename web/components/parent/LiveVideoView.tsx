"use client";

/**
 * Parent Live Supervision — consented snapshot polling.
 *
 * The STUDENT opts in per session (Vision Guard toggle); the parent polls
 * /api/v1/parent/live/snapshot through the tunnel or LAN at ~1 fps.
 * Frames are never stored server-side beyond the in-memory latest slot and
 * auto-expire when the study session ends or consent is revoked.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Video, XCircle, ShieldAlert } from "lucide-react";
import { pFetch } from "@/lib/parent/parent-api";

interface LiveVideoViewProps {
  studentName?: string;
  onClose: () => void;
}

type LivePhase = "connecting" | "live" | "waiting" | "denied" | "error";

export default function LiveVideoView({ studentName, onClose }: LiveVideoViewProps) {
  const [phase, setPhase] = useState<LivePhase>("connecting");
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [frameAge, setFrameAge] = useState<number>(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const objectUrlRef = useRef<string | null>(null);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const poll = useCallback(async () => {
    try {
      const res = await pFetch("/api/v1/parent/live/snapshot?session_id=current");
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
  }, [stopTimer]);

  useEffect(() => {
    void poll();
    timerRef.current = setInterval(() => void poll(), 1000);
    return () => {
      stopTimer();
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    };
  }, [poll, stopTimer]);

  return (
    <div className="fixed inset-0 z-[999] flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl overflow-hidden">
        {/* Header */}
        <div className="px-5 py-4 bg-gradient-to-r from-purple-600 to-indigo-600 text-white flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Video size={18} />
            <div>
              <h3 className="font-bold text-sm">Live Supervision</h3>
              <p className="text-[10px] text-purple-100">
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
        <div className="aspect-video bg-black flex items-center justify-center relative">
          {phase === "live" && frameUrl && (
            <img
              src={frameUrl}
              alt="Live student camera snapshot"
              className="w-full h-full object-contain"
            />
          )}
          {phase !== "live" && (
            <div className="text-center space-y-3 px-6">
              {phase === "connecting" || phase === "waiting" ? (
                <>
                  <div className="mx-auto w-10 h-10 rounded-full border-4 border-purple-500 border-t-transparent animate-spin" />
                  <p className="text-white/70 text-sm font-medium">
                    {phase === "connecting"
                      ? "Connecting to live view…"
                      : "Waiting for the student's next frame…"}
                  </p>
                  <p className="text-white/40 text-xs max-w-sm mx-auto">
                    Live view only streams when the student enables “Parent Live View”
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
                    Could not reach the live view. Ensure you're connected via the tunnel or LAN.
                  </p>
                </>
              )}
            </div>
          )}

          {phase === "live" && (
            <div className="absolute top-3 left-3 flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-black/60 text-[10px] text-green-400 font-mono">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
              LIVE · CONSENTED
            </div>
          )}
        </div>

        {/* Footer note */}
        <div className="px-5 py-3 bg-gray-50 dark:bg-gray-800 text-[11px] text-gray-500 dark:text-gray-400 flex items-center gap-2">
          <ShieldAlert size={13} className="shrink-0 text-amber-500" />
          <span>
            Student-controlled: frames stream only while their toggle is ON and the session is active.
            Auto-terminates at session end — no recording.
          </span>
        </div>
      </div>
    </div>
  );
}
