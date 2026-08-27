"use client";

/**
 * Parent Live Supervision — High-Speed Live Video Stream.
 *
 * Supports high-throughput binary WebSocket stream (~5 FPS, CDN-like speed)
 * with transparent HTTP snapshot fallback. Parent-initiated start/stop
 * controls operate both from here and via Telegram (/live stream, /live stop).
 *
 * Fully failure-isolated: automatically recovers from transient network drops,
 * handles pairing permissions honestly, and provides manual reconnect controls.
 * Zero-cloud storage: frames exist strictly in memory during active transmission.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Activity, AlertTriangle, Radio, RefreshCw, ShieldAlert, StopCircle, Video, XCircle } from "lucide-react";
import {
  getParentLiveWsUrl,
  pFetch,
  startParentLiveStream,
  stopParentLiveStream,
} from "@/lib/parent/parent-api";

interface LiveVideoViewProps {
  studentName?: string;
  /** Explicit monitoring session id; omit for "any active session". */
  sessionId?: string | null;
  onClose: () => void;
}

type LivePhase = "connecting" | "live" | "waiting" | "denied" | "ended" | "error";

export default function LiveVideoView({ studentName, sessionId, onClose }: LiveVideoViewProps) {
  const [phase, setPhase] = useState<LivePhase>("connecting");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [frameAge, setFrameAge] = useState<number>(0);
  const [fps, setFps] = useState<number>(0);
  const [isWsMode, setIsWsMode] = useState<boolean>(false);
  const [stopping, setStopping] = useState<boolean>(false);
  const [retryCount, setRetryCount] = useState<number>(0);

  const wsRef = useRef<WebSocket | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const hiddenRef = useRef(false);
  const frameCountRef = useRef(0);
  const fpsTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const connectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastFrameTimeRef = useRef(Date.now());

  const targetSessionId = sessionId || "current";

  const stopHttpPoll = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const cleanupWs = useCallback(() => {
    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch {
        /* ignore close err */
      }
      wsRef.current = null;
    }
    setIsWsMode(false);
  }, []);

  const handleNewFrameBlob = useCallback((blob: Blob, tsHeader?: string | null) => {
    const url = URL.createObjectURL(blob);
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = url;
    setFrameUrl(url);

    frameCountRef.current += 1;
    lastFrameTimeRef.current = Date.now();

    if (tsHeader) {
      setFrameAge(Math.max(0, Math.round(Date.now() / 1000 - Number(tsHeader))));
    } else {
      setFrameAge(0);
    }
    setPhase("live");
    setErrorMessage(null);
  }, []);

  // Fallback HTTP snapshot poll
  const pollSnapshot = useCallback(async () => {
    if (hiddenRef.current) return;
    try {
      const res = await pFetch(
        `/api/v1/parent/live/snapshot?session_id=${encodeURIComponent(targetSessionId)}`
      );
      if (res.ok) {
        const blob = await res.blob();
        handleNewFrameBlob(blob, res.headers.get("X-Frame-Timestamp"));
      } else if (res.status === 404) {
        setPhase((p) => (p === "live" ? "waiting" : "connecting"));
      } else if (res.status === 403) {
        setPhase("denied");
        setErrorMessage("Live view is restricted by pairing permissions for this student.");
        stopHttpPoll();
      } else if (res.status === 401) {
        // Refresh handled by pFetch
      } else {
        setPhase("error");
        setErrorMessage(`Server returned HTTP ${res.status}`);
      }
    } catch (err) {
      setPhase((p) => (p === "live" ? p : "error"));
      setErrorMessage(err instanceof Error ? err.message : "Connection dropped");
    }
  }, [targetSessionId, handleNewFrameBlob, stopHttpPoll]);

  // Connect WebSocket stream
  const connectWs = useCallback(() => {
    cleanupWs();
    const wsUrl = getParentLiveWsUrl(targetSessionId);
    if (!wsUrl) {
      // No token yet or SSR — fall back to polling
      pollTimerRef.current = setInterval(() => void pollSnapshot(), 400);
      return;
    }

    try {
      const ws = new WebSocket(wsUrl);
      ws.binaryType = "blob";
      wsRef.current = ws;

      ws.onopen = () => {
        setIsWsMode(true);
        stopHttpPoll();
        setErrorMessage(null);
      };

      ws.onmessage = (event) => {
        if (event.data instanceof Blob) {
          handleNewFrameBlob(event.data);
        } else if (typeof event.data === "string") {
          try {
            const data = JSON.parse(event.data);
            if (data.type === "ended") {
              setPhase("ended");
              cleanupWs();
            } else if (data.type === "waiting") {
              setPhase((p) => (p === "live" ? "waiting" : "connecting"));
            } else if (data.type === "error") {
              setPhase("error");
              setErrorMessage(data.message || "Monitoring feed error");
            }
          } catch {
            /* ignore parse err */
          }
        }
      };

      ws.onerror = () => {
        // Fallback to HTTP polling if WebSocket gets blocked or closed
        setIsWsMode(false);
        if (!pollTimerRef.current) {
          pollTimerRef.current = setInterval(() => void pollSnapshot(), 400);
        }
      };

      ws.onclose = (ev) => {
        setIsWsMode(false);
        if (ev.code === 4001) {
          setPhase("denied");
          setErrorMessage("Parent authentication failed. Re-enter your PIN.");
        }
      };
    } catch (err) {
      setIsWsMode(false);
      setErrorMessage(err instanceof Error ? err.message : "Could not open stream");
      pollTimerRef.current = setInterval(() => void pollSnapshot(), 400);
    }
  }, [targetSessionId, handleNewFrameBlob, pollSnapshot, stopHttpPoll, cleanupWs]);

  const startStreamPipeline = useCallback(() => {
    setPhase("connecting");
    setErrorMessage(null);

    // Timeout guard: if still connecting after 14s, surface actionable state
    if (connectTimeoutRef.current) clearTimeout(connectTimeoutRef.current);
    connectTimeoutRef.current = setTimeout(() => {
      setPhase((prev) => {
        if (prev === "connecting") {
          setErrorMessage("Stream connection is taking longer than expected. Check if the study session is active.");
          return "error";
        }
        return prev;
      });
    }, 14000);

    // Auto-start parent live stream on backend (overrides student toggle, starts tunnel)
    void startParentLiveStream(targetSessionId)
      .then((res) => {
        if (res.ok) {
          connectWs();
        } else {
          // If 404, student isn't studying
          if (res.status === 404) {
            setPhase("ended");
            setErrorMessage("No active study session found. The student is not currently studying.");
          } else {
            // Fallback to direct poll
            void pollSnapshot();
            pollTimerRef.current = setInterval(() => void pollSnapshot(), 500);
          }
        }
      })
      .catch((err) => {
        setPhase("error");
        setErrorMessage(err instanceof Error ? err.message : "Failed to initiate stream");
        void pollSnapshot();
        pollTimerRef.current = setInterval(() => void pollSnapshot(), 600);
      });
  }, [targetSessionId, connectWs, pollSnapshot]);

  // Main lifecycle
  useEffect(() => {
    startStreamPipeline();

    // FPS measurement timer (evaluates every 1 second)
    fpsTimerRef.current = setInterval(() => {
      setFps(frameCountRef.current);
      frameCountRef.current = 0;

      // Check if frames stalled (> 4 seconds since last frame)
      if (Date.now() - lastFrameTimeRef.current > 4000 && phase === "live") {
        setPhase("waiting");
      }
    }, 1000);

    const onVisibility = () => {
      hiddenRef.current = document.hidden;
      if (!document.hidden && !isWsMode && phase === "live") {
        void pollSnapshot();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      stopHttpPoll();
      cleanupWs();
      if (fpsTimerRef.current) clearInterval(fpsTimerRef.current);
      if (connectTimeoutRef.current) clearTimeout(connectTimeoutRef.current);
      document.removeEventListener("visibilitychange", onVisibility);
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
    };
  }, [startStreamPipeline, retryCount, stopHttpPoll, cleanupWs, isWsMode, phase, pollSnapshot]);

  const handleRetry = () => {
    stopHttpPoll();
    cleanupWs();
    setRetryCount((c) => c + 1);
  };

  const handleStopStream = async () => {
    setStopping(true);
    try {
      await stopParentLiveStream(targetSessionId);
    } catch {
      /* best-effort */
    } finally {
      setStopping(false);
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 z-[999] flex items-center justify-center p-4 animate-overlay-in"
      style={{ background: "var(--overlay)", backdropFilter: "blur(10px)", WebkitBackdropFilter: "blur(10px)" }}
    >
      <div className="w-full max-w-3xl bento-cell liquid-sheen !rounded-2xl overflow-hidden animate-pop-in shadow-[0_20px_60px_rgba(0,0,0,0.6)]">
        {/* Header */}
        <div className="relative z-[2] px-5 py-3.5 bg-gradient-to-r from-[var(--primary)] to-[#E8895F] text-white flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="p-1.5 bg-white/20 rounded-lg backdrop-blur-sm">
              <Video size={18} />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-display font-bold text-sm">Live Student Video Feed</h3>
                {phase === "live" && (
                  <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-white/20 text-[10px] font-mono font-bold tracking-wider">
                    <Radio size={10} className="text-white animate-pulse" />
                    LIVE
                  </span>
                )}
              </div>
              <p className="text-[10px] text-white/85 flex items-center gap-1.5 mt-0.5">
                {studentName ? `${studentName} · ` : ""}
                {phase === "live"
                  ? `${fps > 0 ? `${fps} FPS` : "High-Speed"} · ${isWsMode ? "WebSocket Stream" : "Turbo Relay"} · updated ${frameAge}s ago`
                  : phase === "connecting"
                    ? "Establishing encrypted video link…"
                    : phase === "waiting"
                      ? "Standby · awaiting next video frame…"
                      : phase === "ended"
                        ? "Session Completed"
                        : "Stream Interrupted"}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {(phase === "error" || phase === "waiting") && (
              <button
                onClick={handleRetry}
                className="glow-ring flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-white/20 hover:bg-white/30 text-white text-xs font-semibold transition-colors"
                title="Retry stream connection"
              >
                <RefreshCw size={13} />
                <span>Retry</span>
              </button>
            )}
            <button
              onClick={handleStopStream}
              disabled={stopping}
              className="glow-ring flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-black/30 hover:bg-black/40 text-white text-xs font-semibold transition-colors"
              title="Stop live stream"
            >
              <StopCircle size={14} className={stopping ? "animate-spin" : "text-red-400"} />
              <span>{stopping ? "Stopping…" : "Stop Live"}</span>
            </button>
            <button
              onClick={onClose}
              className="p-1.5 hover:bg-white/20 rounded-lg transition-colors"
              aria-label="Close live supervision"
            >
              <XCircle size={20} />
            </button>
          </div>
        </div>

        {/* Video Canvas / Display */}
        <div className="aspect-video bg-black flex items-center justify-center relative z-[2]">
          {phase === "live" && frameUrl && (
            <>
              <img
                src={frameUrl}
                alt="Live student camera feed"
                className="w-full h-full object-contain select-none"
              />
              <div className="scanline-bar !h-[14%]" style={{ opacity: 0.35 }} aria-hidden />

              {/* Stream Telemetry Overlay */}
              <div className="absolute top-3 left-3 z-10 flex items-center gap-2 px-2.5 py-1 rounded-full bg-black/70 backdrop-blur-md text-[10px] text-[var(--amber)] font-mono border border-white/10">
                <span className="w-2 h-2 rounded-full bg-[var(--primary)] ember-dot" />
                <span>{isWsMode ? "CDN STREAM" : "LOCAL RELAY"}</span>
                <span className="text-white/40">·</span>
                <span className="text-white font-bold">{fps} FPS</span>
              </div>
            </>
          )}

          {phase !== "live" && (
            <div className="text-center space-y-3.5 px-6 max-w-md">
              {phase === "connecting" || phase === "waiting" ? (
                <>
                  <div className="mx-auto w-12 h-12 rounded-full border-4 border-[var(--primary)] border-t-transparent animate-spin" />
                  <p className="text-white/90 text-sm font-semibold">
                    {phase === "connecting"
                      ? "Connecting high-speed stream…"
                      : "Awaiting next video frame…"}
                  </p>
                  <p className="text-white/45 text-xs leading-relaxed">
                    Connecting to the student&apos;s active study session camera. Encrypted tunnel
                    and local relays are negotiating.
                  </p>
                </>
              ) : phase === "ended" ? (
                <>
                  <Activity size={36} className="mx-auto text-amber-400" />
                  <p className="text-white/90 text-sm font-semibold">Study Session Completed</p>
                  <p className="text-white/50 text-xs leading-relaxed">
                    {errorMessage || "The student has finished their study session. The live camera feed has stopped."}
                  </p>
                </>
              ) : phase === "denied" ? (
                <>
                  <ShieldAlert size={36} className="mx-auto text-red-400" />
                  <p className="text-white/80 text-sm font-medium">
                    Access Denied
                  </p>
                  <p className="text-white/50 text-xs">
                    {errorMessage || "Live view is not permitted for this student pairing."}
                  </p>
                </>
              ) : (
                <>
                  <AlertTriangle size={36} className="mx-auto text-amber-400" />
                  <p className="text-white/90 text-sm font-medium">
                    Feed Unavailable
                  </p>
                  <p className="text-white/50 text-xs leading-relaxed">
                    {errorMessage || "Could not connect to the live stream. Ensure a study session is active."}
                  </p>
                  <button
                    onClick={handleRetry}
                    className="mt-2 inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-[var(--primary)] to-[#E8895F] text-white text-xs font-semibold shadow-[0_4px_14px_var(--glow-primary)] hover:brightness-110 active:scale-95 transition-all"
                  >
                    <RefreshCw size={13} />
                    <span>Try Again</span>
                  </button>
                </>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="relative z-[2] px-5 py-2.5 border-t border-[var(--glass-border)] bg-[var(--glass-0)] text-[11px] text-[var(--muted-foreground)] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Radio size={13} className="shrink-0 text-[var(--primary)]" />
            <span>
              Real-time on-device feed. Auto-terminates when the session ends or when &quot;Stop Live&quot; is pressed.
            </span>
          </div>
          <span className="text-[10px] font-mono text-white/40 shrink-0 hidden sm:inline">
            Zero Cloud Storage
          </span>
        </div>
      </div>
    </div>
  );
}


