"use client";

/**
 * AI Guru Study Room — Ember Glass edition.
 * Bento lobby, frosted HUD workspace, animated ember ring timer.
 * All session logic (create / pre-flight / WS telemetry / stop / report)
 * is unchanged; this file is presentation-only redesign.
 */

import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  Plus, BookOpen, BookOpenCheck, ShieldCheck, Sparkles,
  Pause, Play, StopCircle, FileText, AlertTriangle,
  Eye, Video, RefreshCw, ChevronRight, History,
  Calculator, Atom, Cpu, FlaskConical,
} from "lucide-react";
import CreateSessionModal from "@/components/study/CreateSessionModal";
import PreFlightCheck from "@/components/study/PreFlightCheck";
import StudyTimer from "@/components/study/StudyTimer";
import SessionReportView from "@/components/study/SessionReportView";
import FloatingStudyBar from "@/components/study/FloatingStudyBar";
import { notify } from "@/lib/notifications";
import { motionOK, useRevealStagger, useMagneticTilt } from "@/lib/motion/useGsapReveal";
import type { VisionPipeline } from "@/lib/monitoring/visionPipeline";
import type { TelemetrySocket } from "@/lib/monitoring/telemetrySocket";

type SessionState = "idle" | "creating" | "pre-flight" | "active" | "completed";
type MonitorMode = "system" | "browser";

interface LiveWarning {
  warning_id: string;
  category: string;
  message: string;
  severity: string;
  at: number;
}

interface PastSessionRow {
  id: string;
  title: string;
  subject: string;
  status: string;
  target_duration_seconds: number;
  actual_duration_seconds: number;
  focus_score: number;
  created_at: number;
}

const STUDENT_ID = "student-primary";

/** Whitelisted-study-behavior chips (mirrors backend WhitelistedAction enum). */
const WHITELIST_LABELS: Record<string, string> = {
  READING_DOWNWARDS: "📖 Reading Book",
  WRITING_NOTES: "✍️ Writing Notes",
  TURNING_PAGES: "📄 Turning Pages",
  DRINKING_WATER: "💧 Drinking Water",
  POSTURE_SHIFT: "🧘 Posture Shift",
};

/** Inline CSS custom properties without fighting the CSSProperties type. */
const cssVars = (o: Record<string, string>) => o as unknown as React.CSSProperties;

/** Lightweight Web Audio chime for distraction warnings — no external files. */
const _audioCtx = typeof AudioContext !== "undefined" ? new AudioContext() : null;
function playChime(severity: "nudge" | "warning" | "alert"): void {
  if (!_audioCtx) return;
  try {
    // Resume context on user interaction (Chrome autoplay policy)
    if (_audioCtx.state === "suspended") void _audioCtx.resume();
    const t = _audioCtx.currentTime;
    const osc = _audioCtx.createOscillator();
    const gain = _audioCtx.createGain();
    osc.connect(gain);
    gain.connect(_audioCtx.destination);
    osc.type = severity === "alert" ? "triangle" : "sine";
    // Nudge: gentle rising double-ping; Warning/Alert: descending attention tone
    if (severity === "nudge") {
      osc.frequency.setValueAtTime(523, t);        // C5
      osc.frequency.setValueAtTime(659, t + 0.12); // E5
      gain.gain.setValueAtTime(0.08, t);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.3);
      osc.start(t);
      osc.stop(t + 0.3);
    } else {
      const vol = severity === "alert" ? 0.15 : 0.10;
      osc.frequency.setValueAtTime(880, t);        // A5
      osc.frequency.setValueAtTime(659, t + 0.08); // E5
      osc.frequency.setValueAtTime(523, t + 0.16); // C5
      gain.gain.setValueAtTime(vol, t);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.4);
      osc.start(t);
      osc.stop(t + 0.4);
    }
  } catch { /* audio unavailable — silent fallback */ }
}

export default function StudyRoomPage() {
  const [state, setState] = useState<SessionState>("idle");
  const [sessionData, setSessionData] = useState<{
    title: string;
    subject: string;
    duration: number;
  } | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  // ---- Unified session clock: single source for the ring timer + floating bar ----
  const [timeLeft, setTimeLeft] = useState<number | null>(null);
  const [isPaused, setIsPaused] = useState(false);
  const [stopping, setStopping] = useState(false);

  // ---- Real monitoring telemetry (WS-backed; no simulated values) ----
  const [focusScore, setFocusScore] = useState<number | null>(null); // null = awaiting real data
  const [engagementScore, setEngagementScore] = useState<number | null>(null);
  const [focusTrend, setFocusTrend] = useState<string>("STABLE");
  const [whitelistedAction, setWhitelistedAction] = useState<string | null>(null);
  const [presenceState, setPresenceState] = useState<string>("unknown");
  const [postureLabel, setPostureLabel] = useState<string>("—");
  const [liveWarnings, setLiveWarnings] = useState<LiveWarning[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  // null until /camera/status answers; drives <img> MJPEG vs getUserMedia.
  const [monitorMode, setMonitorMode] = useState<MonitorMode | null>(null);
  const [feedAttempt, setFeedAttempt] = useState(0);
  const [telegramBadgeAt, setTelegramBadgeAt] = useState<number | null>(null);
  const pipelineRef = useRef<VisionPipeline | null>(null);
  const socketRef = useRef<TelemetrySocket | null>(null);
  const feedRetryRef = useRef(0);
  const streamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [studyNotes, setStudyNotes] = useState<string>("");
  const [activeTab, setActiveTab] = useState<"workspace" | "notes">("workspace");
  const [liveViewEnabled, setLiveViewEnabled] = useState(false);
  // The vision-pipeline effect captures values once; the ref lets the running
  // loop read the CURRENT toggle state without re-opening camera + WS.
  const liveViewRef = useRef(liveViewEnabled);
  liveViewRef.current = liveViewEnabled;

  // ---- API failure surfacing: never fail silently ----
  const [apiNotice, setApiNotice] = useState<{ kind: "error" | "warn"; text: string } | null>(null);

  const toggleLiveView = async (next: boolean) => {
    setLiveViewEnabled(next);
    if (!sessionId) return;
    try {
      const res = await fetch(
        `/api/v1/monitoring/live/consent?session_id=${encodeURIComponent(sessionId)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: next }),
        }
      );
      if (!res.ok) throw new Error(String(res.status));
    } catch {
      setApiNotice({
        kind: "warn",
        text: "Could not sync Parent Live View consent with the backend — snapshots won't upload.",
      });
      setLiveViewEnabled(!next);
    }
  };

  // Shared telemetry application for both monitor modes (system + browser).
  const applyRemote = useCallback((msg: Record<string, unknown>) => {
    if (typeof msg.engagement_score === "number") setEngagementScore(Math.round(msg.engagement_score));
    if (typeof msg.focus_score === "number") setFocusScore(Math.round(msg.focus_score));
    if (typeof msg.engagement_trend === "string") setFocusTrend(String(msg.engagement_trend));
    if (typeof msg.presence === "string") setPresenceState(String(msg.presence));
    if (typeof msg.posture === "string") {
      setPostureLabel(String(msg.posture).replace(/_/g, " ").toLowerCase());
    }
    setWhitelistedAction(
      typeof msg.whitelisted_action === "string" ? String(msg.whitelisted_action) : null
    );
    const warn = msg.warning as { warning_id?: string; category?: string; message?: string; severity?: string } | undefined;
    if (warn?.warning_id) {
      setLiveWarnings((prev) =>
        [{ ...warn, at: Date.now() } as LiveWarning, ...prev.filter((w) => w.warning_id !== warn.warning_id)].slice(0, 5)
      );
      if (warn.severity === "alert") {
        // High-priority alerts dispatch a real photo to the parent's Telegram.
        setTelegramBadgeAt(Date.now());
      }
      // Backend pre-throttles warnings (cooldown + episode + rate gates),
      // so toasting every dispatched event stays spam-free. Nudges toast
      // gently (info tone); real warnings escalate the tone instead.
      // Audio chime helps when the student is looking away from the screen.
      const sev = (warn.severity === "alert" || warn.severity === "warning" || warn.severity === "nudge")
        ? warn.severity as "alert" | "warning" | "nudge"
        : "nudge";
      playChime(sev);
      notify(warn.message || "Stay focused!", {
        tone:
          warn.severity === "alert"
            ? "error"
            : warn.severity === "warning"
              ? "warning"
              : "info",
      });
    }
  }, []);

  // 1. Decide the monitoring mode once per active session: system camera
  //    (backend Python CV — no browser permission prompt) or browser WASM CV.
  useEffect(() => {
    if (state !== "active" || monitorMode !== null) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/v1/monitoring/camera/status");
        if (!res.ok) throw new Error(String(res.status));
        const data = await res.json();
        if (!cancelled) setMonitorMode(data.mode === "system" && sessionId ? "system" : "browser");
      } catch {
        if (!cancelled) setMonitorMode("browser");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [state, sessionId, monitorMode]);

  // 2a. SYSTEM MODE: backend owns the webcam and drives analysis ticks; this
  //     page just renders the MJPEG feed and consumes WS telemetry updates.
  useEffect(() => {
    if (state !== "active" || monitorMode !== "system" || !sessionId) return;
    let cancelled = false;
    feedRetryRef.current = 0;
    setFeedAttempt(0);

    (async () => {
      const { TelemetrySocket } = await import("@/lib/monitoring/telemetrySocket");
      if (cancelled) return;
      const socket = new TelemetrySocket({
        sessionId,
        onUpdate: applyRemote,
        onState: setWsConnected,
      });
      socketRef.current = socket;
      socket.start();
    })();

    return () => {
      cancelled = true;
      socketRef.current?.stop();
      socketRef.current = null;
      setWsConnected(false);
    };
  }, [state, monitorMode, sessionId, applyRemote]);

  // 2b. BROWSER MODE fallback: MediaPipe WASM runs on-device; landmarks feed
  //     the backend geometry engine over the monitoring WS.
  useEffect(() => {
    if (state !== "active" || monitorMode !== "browser") return;
    let cancelled = false;
    const pipelineRefLocal: { current: VisionPipeline | null } = { current: null };

    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { width: 640, height: 480, facingMode: "user" },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        const video = videoRef.current;
        if (!video) return;
        video.srcObject = stream;
        await video.play().catch(() => {});

        const { VisionPipeline } = await import("@/lib/monitoring/visionPipeline");
        let lastLiveUpload = 0;
        const pipeline = new VisionPipeline({
          video,
          sessionId: sessionId ?? undefined,
          targetFps: Number(window.localStorage.getItem("aiguru.vision.fps") || 5),
          onState: (s) => setWsConnected(s === "ready"),
          onTelemetry: (frame, remote) => {
            if (remote) {
              applyRemote(remote);
            }
            // Parent live view: throttled frame upload while consented.
            // Reads the ref so toggling mid-session takes effect immediately.
            if (
              liveViewRef.current &&
              frame.jpeg_b64 &&
              Date.now() - lastLiveUpload > 1500 &&
              sessionId
            ) {
              lastLiveUpload = Date.now();
              void fetch(
                `/api/v1/monitoring/live/frame?session_id=${encodeURIComponent(sessionId)}`,
                {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ jpeg_b64: frame.jpeg_b64 }),
                }
              ).catch(() => {});
            }
          },
        });
        pipelineRefLocal.current = pipeline;
        pipelineRef.current = pipeline;
        await pipeline.start();
      } catch (err) {
        console.warn("Monitoring unavailable:", err);
        setWsConnected(false);
        setApiNotice({
          kind: "warn",
          text: "Camera or monitoring engine unavailable — the session continues unmonitored.",
        });
      }
    })();

    return () => {
      cancelled = true;
      pipelineRefLocal.current?.stop();
      pipelineRef.current = null;
      const stream = streamRef.current;
      stream?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      setWsConnected(false);
    };
  }, [state, monitorMode, sessionId, applyRemote]);

  const handleStartSession = (title: string, subject: string, duration: number) => {
    setSessionData({ title, subject, duration });
    setState("pre-flight");
  };

  const handlePreFlightReady = async () => {
    // Create + start the session against the real backend; surface failures
    // honestly instead of continuing silently untracked.
    setApiNotice(null);
    let createdId: string | null = null;
    try {
      const res = await fetch("/api/v1/study-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          student_id: STUDENT_ID,
          title: sessionData?.title || "Study Session",
          subject: sessionData?.subject || "General",
          target_duration_seconds: Math.max(60, (sessionData?.duration || 25) * 60),
        }),
      });
      if (!res.ok) throw new Error(`create failed (${res.status})`);
      const data = await res.json();
      createdId = typeof data.id === "string" ? data.id : null;

      if (createdId) {
        const startRes = await fetch(`/api/v1/study-session/${createdId}/start`, { method: "POST" });
        if (!startRes.ok) throw new Error(`start failed (${startRes.status})`);
      }
    } catch (err) {
      console.warn("Study-session API unreachable; continuing locally", err);
      setApiNotice({
        kind: "warn",
        text: "Backend unreachable — this run is not being tracked (no history, XP, or parent alerts).",
      });
    }

    if (createdId) {
      const draftKey = `aiguru.notes.${createdId}`;
      setStudyNotes(window.localStorage.getItem(draftKey) || "");
    }
    setSessionId(createdId);
    setTimeLeft(Math.max(60, sessionData?.duration || 25) * 60);
    setIsPaused(false);
    setActiveTab("workspace");
    setState("active");
  };

  /** Resume a previously started session found in history (e.g. after refresh). */
  const handleResumeSession = (row: PastSessionRow) => {
    const target = Math.max(60, Math.round(row.target_duration_seconds / 60) || 25);
    setSessionData({ title: row.title, subject: row.subject || "General", duration: target });
    setSessionId(row.id);
    setIsPaused(row.status === "paused");
    setTimeLeft(target * 60); // paused rows carry no elapsed accumulation; restart clock honestly
    setStudyNotes(window.localStorage.getItem(`aiguru.notes.${row.id}`) || "");
    setLiveWarnings([]);
    setFocusScore(null);
    setEngagementScore(null);
    setFocusTrend("STABLE");
    setWhitelistedAction(null);
    setTelegramBadgeAt(null);
    setPresenceState("unknown");
    setPostureLabel("—");
    setMonitorMode(null);
    setState("active");
    void fetch(`/api/v1/study-session/${row.id}/resume`, { method: "POST" }).catch(() => {});
  };

  const completingRef = useRef(false);
  const handleComplete = useCallback(async () => {
    if (completingRef.current || !sessionId) {
      // Untracked local run: jump straight to the completion screen.
      if (!sessionId) setState("completed");
      return;
    }
    completingRef.current = true;
    setStopping(true);
    try {
      const res = await fetch(`/api/v1/study-session/${sessionId}/stop`, { method: "POST" });
      if (!res.ok && res.status !== 404) {
        console.warn("Stop returned", res.status);
      }
    } catch (err) {
      console.warn("Stop failed", err);
      setApiNotice({ kind: "warn", text: "Couldn't reach the backend to finalize the session." });
    }
    setStopping(false);
    setState("completed");
  }, [sessionId]);

  // Tick the unified session clock; pausing stops the interval so the ring,
  // floating bar and PiP stay in sync from this single source of truth.
  useEffect(() => {
    if (state !== "active" || isPaused) return;
    const id = setInterval(() => {
      setTimeLeft((t) => (t === null ? null : Math.max(0, t - 1)));
    }, 1000);
    return () => clearInterval(id);
  }, [state, isPaused]);

  useEffect(() => {
    if (state === "active" && timeLeft === 0 && !completingRef.current) {
      notify("Time is up — study session complete.", { tone: "success" });
      void handleComplete();
    }
    if (state !== "active") completingRef.current = false;
  }, [state, timeLeft, handleComplete]);

  const handlePauseToggle = useCallback(async () => {
    if (state !== "active") return;
    const next = !isPaused;
    setIsPaused(next);
    // System-camera mode: the backend engine pauses its ticks + releases the
    // webcam on this control message (no analysis → no false absence alerts).
    if (next) {
      socketRef.current?.sendPause();
      pipelineRef.current?.setPaused(true);
    } else {
      socketRef.current?.sendResume();
      pipelineRef.current?.setPaused(false);
    }
    if (!sessionId) return;
    try {
      const res = await fetch(`/api/v1/study-session/${sessionId}/${next ? "pause" : "resume"}`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(String(res.status));
    } catch {
      /* backend pause/resume is best-effort */
    }
  }, [state, isPaused, sessionId]);

  // Persist scratch notes per session (survives refresh; nothing leaves device).
  useEffect(() => {
    if (!sessionId || state !== "active") return;
    const key = `aiguru.notes.${sessionId}`;
    const id = setTimeout(() => window.localStorage.setItem(key, studyNotes), 400);
    return () => clearTimeout(id);
  }, [studyNotes, sessionId, state]);

  // ---- Completed-screen report state (all real; null renders as "—") ----
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  const [reportStats, setReportStats] = useState<{
    durationMinutes: number | null;
    focusScore: number | null;
    engagementScore: number | null;
    distractionCount: number | null;
    warningCount: number | null;
    xpEarned: number | null;
    summary: string | null;
    badgesUnlocked: string[];
  } | null>(null);

  const resetToIdle = useCallback(() => {
    setState("idle");
    setSessionId(null);
    setTimeLeft(null);
    setIsPaused(false);
    setStopping(false);
    setReportStats(null);
    setReportError(null);
    setReportLoading(false);
    setFocusScore(null);
    setEngagementScore(null);
    setFocusTrend("STABLE");
    setWhitelistedAction(null);
    setTelegramBadgeAt(null);
    setPresenceState("unknown");
    setPostureLabel("—");
    setLiveWarnings([]);
    setStudyNotes("");
    setLiveViewEnabled(false);
    setMonitorMode(null);
    setSessionData(null);
  }, []);

  useEffect(() => {
    if (state !== "completed") return;
    if (!sessionId) {
      // Untracked local run — show honest empty card.
      setReportStats(null);
      setReportError("This session was not tracked by the backend, so there is no report data.");
      return;
    }
    setReportLoading(true);
    setReportError(null);
    const load = async () => {
      try {
        const res = await fetch(`/api/v1/study-session/${sessionId}/report`);
        if (res.status === 404) {
          setReportStats(null);
          setReportError("The backend has no record of this session.");
          return;
        }
        if (!res.ok) throw new Error(`report failed (${res.status})`);
        const r = await res.json();
        const metrics = r.metrics || {};
        const secs = Number(metrics.actual_duration_seconds ?? metrics.duration_seconds ?? NaN);
        setReportStats({
          durationMinutes: Number.isFinite(secs) ? Math.round(secs / 60) : null,
          focusScore: typeof metrics.focus_score === "number" ? Math.round(metrics.focus_score) : null,
          engagementScore: typeof metrics.engagement_score === "number" ? Math.round(metrics.engagement_score) : null,
          distractionCount: typeof metrics.distraction_count === "number" ? metrics.distraction_count : null,
          warningCount: typeof metrics.warning_count === "number" ? metrics.warning_count : liveWarnings.length,
          xpEarned: typeof r.xp_earned === "number" ? r.xp_earned : null,
          summary: typeof r.summary === "string" && r.summary.trim() ? r.summary : null,
          badgesUnlocked: [],
        });
      } catch {
        setReportStats(null);
        setReportError("Couldn't load the session report. Is the AI Guru backend running?");
      } finally {
        setReportLoading(false);
      }
    };
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, sessionId]);

  // Auto-dismiss transient notices after 8s.
  useEffect(() => {
    if (!apiNotice) return;
    const id = setTimeout(() => setApiNotice(null), 8000);
    return () => clearTimeout(id);
  }, [apiNotice]);

  // Telegram photo-dispatch badge: visible ~15s after an alert-tier warning.
  const [telegramBadgeVisible, setTelegramBadgeVisible] = useState(false);
  useEffect(() => {
    if (!telegramBadgeAt) {
      setTelegramBadgeVisible(false);
      return;
    }
    setTelegramBadgeVisible(true);
    const id = setTimeout(() => setTelegramBadgeVisible(false), 15000);
    return () => clearTimeout(id);
  }, [telegramBadgeAt]);

  return (
    <div className="flex-1 h-full flex flex-col text-[var(--foreground)] relative overflow-hidden">
      {/* Transient API notices (errors never fail silently) */}
      {apiNotice && (
        <div
          className={`surface-glass-elevated absolute top-3 left-1/2 -translate-x-1/2 z-[60] px-4 py-2.5 rounded-xl text-xs font-medium flex items-center gap-2 ${
            apiNotice.kind === "error"
              ? "border-red-500/40 text-red-300 shadow-[0_0_24px_rgba(239,68,68,0.15)]"
              : "border-[var(--amber)]/40 text-[var(--amber)] shadow-[0_0_24px_var(--amber-glow)]"
          }`}
          role="status"
        >
          <AlertTriangle size={14} className="shrink-0" />
          <span>{apiNotice.text}</span>
        </div>
      )}

      {/* 1. IDLE STATE: STUDY ROOM LOBBY */}
      {state === "idle" && (
        <IdleLobby
          onStart={handleStartSession}
          onResume={handleResumeSession}
          onCreate={() => setState("creating")}
        />
      )}

      {/* 2. CREATING SESSION MODAL */}
      {state === "creating" && (
        <CreateSessionModal
          onClose={() => setState("idle")}
          onStart={handleStartSession}
        />
      )}

      {/* 3. PRE-FLIGHT HARDWARE & CAMERA CHECK */}
      {state === "pre-flight" && (
        <div className="flex-1 flex items-center justify-center p-4 relative z-10">
          <PreFlightCheck
            onReady={() => void handlePreFlightReady()}
            onCancel={() => setState("idle")}
          />
        </div>
      )}

      {/* 4. ACTIVE STUDY SESSION WORKSPACE */}
      {state === "active" && (
        <div className="flex-1 flex flex-col h-full overflow-hidden">
          {/* Top Session HUD Bar — floating frosted glass */}
          <div className="surface-glass-base mx-3 mt-3 rounded-2xl px-5 py-3 flex items-center justify-between gap-4 shrink-0 relative z-30">
            <div className="flex items-center gap-3.5 min-w-0">
              <div className="w-10 h-10 rounded-xl bg-[var(--ember-0)] border border-[var(--glass-border)] flex items-center justify-center text-[var(--primary)] shrink-0">
                <BookOpen size={19} />
              </div>
              <div className="min-w-0">
                <h2 className="font-display font-bold text-sm leading-tight flex items-center gap-2 truncate">
                  <span className="truncate">{sessionData?.title || "Active Study Session"}</span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-[var(--ember-0)] text-[var(--primary)] border border-[var(--ember-line)]/30 shrink-0">
                    {sessionData?.subject}
                  </span>
                  {!sessionId && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-[var(--amber-glow)] text-[var(--amber)] border border-[var(--amber)]/30 shrink-0">
                      Untracked
                    </span>
                  )}
                </h2>
                <div className="flex items-center gap-2.5 text-[11px] text-[var(--muted-foreground)] mt-1">
                  <span
                    className={`flex items-center gap-1.5 font-semibold ${
                      wsConnected ? "text-[var(--primary)]" : "text-[var(--muted-foreground)]"
                    }`}
                    title={
                      wsConnected
                        ? "On-device computer vision is streaming telemetry locally"
                        : "Monitoring engine standby"
                    }
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${
                        wsConnected ? "bg-[var(--primary)] ember-dot" : "bg-[var(--muted-foreground)]/50"
                      }`}
                    />
                    {wsConnected
                      ? monitorMode === "system"
                        ? "System Camera AI Active"
                        : "Local AI Active"
                      : "Monitoring Standby"}
                  </span>
                  <span className="opacity-40">·</span>
                  <span>Target: {sessionData?.duration} mins</span>
                </div>
              </div>
            </div>

            {/* Live Focus Meter & Controls */}
            <div className="flex items-center gap-2.5 shrink-0">
              <button
                onClick={() => void handlePauseToggle()}
                className="glow-ring px-3.5 py-2 rounded-xl surface-glass-base text-xs font-bold flex items-center gap-1.5 hover:text-[var(--primary)]"
                title={isPaused ? "Resume session" : "Pause session"}
              >
                {isPaused ? <Play size={14} /> : <Pause size={14} />}
                <span>{isPaused ? "Resume" : "Pause"}</span>
              </button>

              <button
                onClick={() => {
                  if (stopping) return;
                  if (window.confirm("Finish this study session now?")) void handleComplete();
                }}
                disabled={stopping}
                className="px-4 py-2 rounded-xl bg-red-500/10 hover:bg-red-500/20 disabled:opacity-50 text-red-400 border border-red-500/30 text-xs font-bold transition-colors flex items-center gap-1.5 glow-ring"
              >
                <StopCircle size={15} className={stopping ? "animate-pulse" : ""} />
                <span>{stopping ? "Finishing…" : "Finish Session"}</span>
              </button>
            </div>
          </div>

          {/* Main Dual-Pane Workspace — stacks vertically below lg so the clock stays reachable */}
          <div className="flex-1 flex flex-col lg:flex-row overflow-hidden">
            {/* Left Pane: Interactive Document & Past Paper Study Zone */}
            <div className="flex-1 flex flex-col overflow-hidden">
              <div className="px-5 pt-4 flex items-center justify-between gap-3">
                <div className="relative grid grid-cols-2 p-1 rounded-full surface-glass-base w-full max-w-sm">
                  {/* Sliding capsule thumb */}
                  <span
                    aria-hidden
                    className="absolute top-1 bottom-1 left-1 w-[calc(50%-4px)] rounded-full bg-[var(--primary)] shadow-[0_0_18px_var(--glow-primary)] transition-transform duration-300 ease-out"
                    style={{ transform: activeTab === "notes" ? "translateX(100%)" : "translateX(0)" }}
                  />
                  <button
                    onClick={() => setActiveTab("workspace")}
                    className={`relative z-10 px-3 py-1.5 rounded-full text-xs font-bold transition-colors duration-200 ${
                      activeTab === "workspace" ? "text-white" : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    }`}
                  >
                    Past Paper Problem Space
                  </button>
                  <button
                    onClick={() => setActiveTab("notes")}
                    className={`relative z-10 px-3 py-1.5 rounded-full text-xs font-bold transition-colors duration-200 ${
                      activeTab === "notes" ? "text-white" : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    }`}
                  >
                    Scratch Notes
                  </button>
                </div>
                {activeTab === "notes" && (
                  <span className="hidden sm:flex items-center gap-1 text-[10px] text-[var(--muted-foreground)]">
                    <ShieldCheck size={11} /> Auto-saved on this device
                  </span>
                )}
              </div>

              {activeTab === "workspace" ? (
                <PastPaperPanel subject={sessionData?.subject || "General"} />
              ) : (
                <div className="flex-1 p-5 flex flex-col">
                  <textarea
                    value={studyNotes}
                    onChange={(e) => setStudyNotes(e.target.value)}
                    placeholder="Take session notes, formulas, or key concepts..."
                    className="glass-input w-full flex-1 p-4 text-sm font-mono resize-none"
                  />
                </div>
              )}
            </div>

            {/* Right Pane: Timer & Local AI Supervision HUD — vertical bento */}
            <aside className="w-full lg:w-[340px] shrink-0 flex flex-col gap-4 p-4 pt-2 lg:pl-1 pb-28 overflow-y-auto max-h-[48vh] lg:max-h-none border-t border-[var(--glass-border)] lg:border-t-0 lg:border-l">
              {/* Timer Clock */}
              <div className="bento-cell p-5 pt-7 flex flex-col items-center shrink-0 liquid-sheen">
                <StudyTimer
                  timeLeft={timeLeft}
                  totalSeconds={Math.max(60, sessionData?.duration || 25) * 60}
                  isPaused={isPaused}
                  onTogglePause={() => void handlePauseToggle()}
                />
              </div>

              {/* Local CV Monitor Status Card — real WS telemetry only */}
              <div className="bento-cell p-4 space-y-3 shrink-0">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold flex items-center gap-1.5">
                    <Eye size={14} className="text-[var(--primary)]" />
                    <span>Vision Guard</span>
                  </span>
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded-full font-bold tracking-wide ${
                      wsConnected
                        ? "bg-[var(--ember-0)] text-[var(--primary)] border border-[var(--ember-line)]/40"
                        : "bg-[var(--muted)] text-[var(--muted-foreground)] border border-[var(--glass-border)]"
                    }`}
                  >
                    {wsConnected ? "LIVE" : "OFFLINE"}
                  </span>
                </div>

                <div className="space-y-2 text-xs">
                  <TelemetryRow label="Presence">
                    <span
                      className={`font-semibold capitalize ${
                        presenceState === "present"
                          ? "text-[var(--primary)]"
                          : presenceState === "away"
                            ? "text-red-400"
                            : "text-[var(--foreground)]"
                      }`}
                    >
                      {presenceState.replace(/_/g, " ")}
                    </span>
                  </TelemetryRow>
                  <TelemetryRow label="Posture">
                    <span className="font-semibold capitalize">{postureLabel}</span>
                  </TelemetryRow>
                  {whitelistedAction && (
                    <TelemetryRow label="Recognized">
                      <span className="font-semibold text-[var(--primary)]">
                        {WHITELIST_LABELS[whitelistedAction] || whitelistedAction.replace(/_/g, " ").toLowerCase()}
                      </span>
                    </TelemetryRow>
                  )}
                  <TelemetryRow label="Focus">
                    <span className="font-semibold text-[var(--primary)] font-mono">
                      {focusScore === null ? "—" : `${focusScore}%`}
                    </span>
                  </TelemetryRow>
                  <TelemetryRow label="Engagement">
                    <span className="flex items-center gap-1.5 font-semibold text-[var(--primary)] font-mono">
                      <span
                        title={focusTrend === "RISING" ? "Engagement rising" : focusTrend === "FALLING" ? "Engagement falling" : "Steady"}
                        className={
                          focusTrend === "FALLING"
                            ? "text-red-400"
                            : focusTrend === "RISING"
                              ? "text-[var(--primary)]"
                              : "text-[var(--muted-foreground)]"
                        }
                      >
                        {focusTrend === "RISING" ? "↑" : focusTrend === "FALLING" ? "↓" : "→"}
                      </span>
                      {engagementScore === null ? "—" : `${engagementScore}%`}
                    </span>
                  </TelemetryRow>
                  <TelemetryRow label="Data Privacy">
                    <span className={`font-semibold ${wsConnected ? "text-[var(--amber)]" : "text-[var(--muted-foreground)]"}`}>
                      {wsConnected
                        ? monitorMode === "system"
                          ? "On-device · photos only on alerts"
                          : "0 Bytes (Local)"
                        : "—"}
                    </span>
                  </TelemetryRow>
                  <div className="flex justify-between items-center pt-1.5 border-t border-[var(--glass-border)]">
                    <span className="text-[var(--muted-foreground)]">Parent Live View</span>
                    <button
                      onClick={() => void toggleLiveView(!liveViewEnabled)}
                      disabled={!wsConnected}
                      aria-label="Toggle parent live view"
                      className={`relative w-9 h-5 rounded-full transition-colors duration-300 ${
                        liveViewEnabled
                          ? "bg-[var(--primary)] shadow-[0_0_12px_var(--glow-primary)]"
                          : "bg-[var(--muted)] border border-[var(--glass-border)]"
                      } ${!wsConnected ? "opacity-40 cursor-not-allowed" : ""}`}
                      title={liveViewEnabled ? "Parent can view live snapshots" : "Allow parent to view this session"}
                    >
                      <span
                        className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all duration-300 ${
                          liveViewEnabled ? "left-[18px]" : "left-0.5"
                        }`}
                      />
                    </button>
                  </div>
                </div>

                {/* Live warnings — 3-tier: nudge (subtle) / warning / alert */}
                {liveWarnings.length > 0 && (
                  <div className="pt-2 border-t border-[var(--glass-border)] space-y-1.5">
                    {liveWarnings.slice(0, 3).map((w) => (
                      <div
                        key={w.warning_id}
                        className={`p-2 rounded-lg text-[11px] flex items-start gap-1.5 border ${
                          w.severity === "alert"
                            ? "bg-red-500/10 text-red-300 border-red-500/25"
                            : w.severity === "warning"
                              ? "bg-[var(--amber-glow)]/80 text-[var(--amber)] border-[var(--amber)]/35"
                              : w.severity === "nudge"
                                ? "bg-[var(--amber-glow)]/30 text-[var(--amber)]/90 border-[var(--amber)]/15"
                                : "bg-[var(--ember-0)] text-[var(--primary)] border-[var(--ember-line)]/25"
                        }`}
                      >
                        <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                        <span>{w.message}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Camera — system MJPEG feed (no permission prompt) or local preview fallback */}
              <div className="bento-cell scanline relative aspect-video overflow-hidden flex items-center justify-center !bg-black/80">
                {wsConnected && <div className="scanline-bar" />}
                {monitorMode === "system" && sessionId && wsConnected ? (
                  <img
                    key={sessionId}
                    src={`/api/v1/monitoring/feed/${encodeURIComponent(sessionId)}${feedAttempt ? `?retry=${feedAttempt}` : ""}`}
                    alt="Live AI Guru monitoring feed with face mesh overlay"
                    className="absolute inset-0 h-full w-full object-cover opacity-95"
                    onError={() => {
                      // The monitor registers a beat after the WS handshake;
                      // retry a few times before downgrading to browser mode.
                      if (feedRetryRef.current < 3) {
                        feedRetryRef.current += 1;
                        setFeedAttempt(feedRetryRef.current);
                      } else {
                        setMonitorMode("browser");
                      }
                    }}
                  />
                ) : (
                  <video
                    ref={videoRef}
                    muted
                    playsInline
                    autoPlay
                    className="absolute inset-0 h-full w-full object-cover opacity-90 -scale-x-100"
                  />
                )}
                {!wsConnected && (
                  <div className="relative text-center space-y-1 z-10">
                    <Video size={24} className="mx-auto text-white/40" />
                    <p className="text-[10px] text-white/50 font-medium">Monitoring standby</p>
                  </div>
                )}
                {telegramBadgeVisible && (
                  <div className="absolute bottom-2 right-2 z-20 flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-bold bg-red-500/25 text-red-200 border border-red-500/40 backdrop-blur-sm animate-pop-in">
                    📸 Alert sent to parent
                  </div>
                )}
                <div
                  className={`absolute top-2 left-2 z-10 flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono bg-black/60 backdrop-blur-sm ${
                    wsConnected ? "text-[var(--amber)]" : "text-white/40"
                  }`}
                >
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${
                      wsConnected ? "bg-[var(--primary)] ember-dot" : "bg-white/30"
                    }`}
                  />
                  <span>
                    {wsConnected
                      ? monitorMode === "system"
                        ? "LIVE · SYSTEM AI"
                        : "LIVE · ON-DEVICE"
                      : "IDLE"}
                  </span>
                </div>
              </div>
            </aside>
          </div>

          {/* Floating Study Bar & Cluely-style Assistant */}
          <FloatingStudyBar
            sessionTitle={sessionData?.title || "Study Session"}
            subject={sessionData?.subject || "General"}
            timeLeft={timeLeft}
            isPaused={isPaused}
            onTogglePause={() => void handlePauseToggle()}
            focusScore={focusScore}
          />
        </div>
      )}

      {/* 5. COMPLETED STATE: SESSION REPORT CARD */}
      {state === "completed" && (
        <div className="flex-1 flex overflow-y-auto relative z-10">
          <SessionReportView stats={reportStats} error={reportError} onHome={resetToIdle} />
        </div>
      )}
    </div>
  );
}

function TelemetryRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between items-center text-[var(--muted-foreground)]">
      <span>{label}</span>
      {children}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────
   Idle lobby — Ember Glass bento grid.
   ──────────────────────────────────────────────────────────────────────── */

const PRESETS = [
  { title: "Mathematics (Past Papers)", subject: "Math", duration: 45, Icon: Calculator },
  { title: "Physics Mechanics", subject: "Science", duration: 30, Icon: Atom },
  { title: "Computer Science Algorithms", subject: "Programming", duration: 25, Icon: Cpu },
  { title: "Chemistry Revision", subject: "Science", duration: 30, Icon: FlaskConical },
] as const;

function SubjectTile({
  Icon,
  title,
  duration,
  onPick,
}: {
  Icon: React.ComponentType<{ size?: number | string; className?: string }>;
  title: string;
  duration: number;
  onPick: () => void;
}) {
  const tiltRef = useMagneticTilt<HTMLButtonElement>(motionOK() ? 4 : 0);
  return (
    <button
      ref={tiltRef}
      onClick={onPick}
      className="bento-cell bento-cell--hover tilt-glare p-4 text-left group outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
    >
      <span className="w-10 h-10 rounded-xl bg-[var(--ember-0)] border border-[var(--glass-border)] flex items-center justify-center text-[var(--primary)] mb-3 transition-transform duration-300 ease-out group-hover:scale-110 group-hover:-rotate-6">
        <Icon size={19} />
      </span>
      <h4 className="text-xs font-bold leading-snug line-clamp-1 group-hover:text-[var(--primary)] transition-colors">
        {title}
      </h4>
      <p className="text-[10px] text-[var(--muted-foreground)] mt-1">{duration} mins · Monitored</p>
    </button>
  );
}

function IdleLobby({
  onStart,
  onResume,
  onCreate,
}: {
  onStart: (title: string, subject: string, duration: number) => void;
  onResume: (row: PastSessionRow) => void;
  onCreate: () => void;
}) {
  const router = useRouter();
  const [recent, setRecent] = useState<PastSessionRow[] | null>(null);
  const [historyFailed, setHistoryFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(
          `/api/v1/study-session/history/${STUDENT_ID}?limit=5&offset=0`
        );
        if (!res.ok) throw new Error(String(res.status));
        const data = await res.json();
        if (!cancelled) setRecent(Array.isArray(data.items) ? data.items : []);
      } catch {
        if (!cancelled) setHistoryFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const resumeCandidate = recent?.find(
    (r) => r.status === "in_progress" || r.status === "paused"
  );

  // Re-run the staggered entrance once history resolves (banner appears).
  const revealRoot = useRevealStagger<HTMLDivElement>([recent]);

  return (
    <div className="flex-1 overflow-y-auto relative">
      {/* Drifting ember backdrop */}
      <div className="aurora-stage">
        <div
          className="aurora-blob"
          style={cssVars({ "--x": "16%", "--y": "-8%", "--size": "580px", "--drift-dur": "32s" })}
        />
        <div
          className="aurora-blob"
          style={cssVars({
            "--x": "90%",
            "--y": "106%",
            "--size": "470px",
            "--blob-color": "var(--amber-glow)",
            "--blob-opacity": "0.45",
            "--drift-dur": "38s",
            "--drift-delay": "-10s",
          })}
        />
      </div>

      <div ref={revealRoot} className="relative z-10 max-w-5xl mx-auto px-6 py-10 space-y-6">
        {/* Header row */}
        <div className="flex items-end justify-between gap-4" data-reveal>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.22em] text-[var(--muted-foreground)]">
              AI Guru · Privacy-first
            </p>
            <h1 className="font-display text-4xl font-extrabold tracking-tight mt-1.5">
              Study{" "}
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-[var(--primary)] to-[var(--amber)]">
                Room
              </span>
            </h1>
          </div>
          <button onClick={onCreate} className="glass-btn-primary hidden sm:inline-flex items-center gap-2 !rounded-xl">
            <Plus size={17} />
            <span>Custom Session</span>
          </button>
        </div>

        {/* Hero bento */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div
            data-reveal
            className="bento-cell tilt-glare liquid-sheen col-span-2 lg:row-span-2 p-6 lg:p-8 flex flex-col justify-between gap-5 min-h-[290px]"
          >
            <div className="space-y-3.5">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-[var(--primary)]/25 to-[var(--amber)]/15 border border-[var(--ember-line)]/40 flex items-center justify-center text-[var(--primary)] shadow-[0_0_28px_var(--glow-primary)]">
                <BookOpen size={26} />
              </div>
              <p className="text-sm text-[var(--muted-foreground)] leading-relaxed max-w-sm">
                Intelligent, privacy-first study companion — local AI monitoring, PDF past-paper
                workspace, and real-time focus feedback. Nothing leaves your device.
              </p>
            </div>

            <div className="space-y-4">
              {/* Resumable session banner — real in-progress work first */}
              {resumeCandidate && (
                <div
                  className="p-3.5 rounded-xl bg-[var(--amber-glow)]/50 border border-[var(--amber)]/30 flex items-center justify-between gap-3 animate-fade-in"
                  role="status"
                >
                  <div className="text-left min-w-0">
                    <h4 className="text-xs font-bold text-[var(--amber)]">Unfinished session</h4>
                    <p className="text-[11px] text-[var(--muted-foreground)] mt-0.5 truncate">
                      {resumeCandidate.title}
                    </p>
                  </div>
                  <button
                    onClick={() => onResume(resumeCandidate)}
                    className="shrink-0 px-3.5 py-1.5 rounded-lg bg-[var(--amber)] text-black text-xs font-bold transition-transform hover:scale-105 active:scale-95 flex items-center gap-1.5"
                  >
                    <Play size={13} fill="currentColor" />
                    Resume
                  </button>
                </div>
              )}

              <button
                onClick={onCreate}
                className="glass-btn-primary sm:hidden w-full justify-center !rounded-xl"
              >
                <Plus size={17} />
                Custom Study Session
              </button>

              <button
                onClick={onCreate}
                className="group hidden sm:flex items-center gap-3 px-5 py-3.5 rounded-2xl bg-gradient-to-r from-[var(--primary)] to-[#E8895F] text-white font-bold shadow-[0_8px_30px_var(--glow-primary)] transition-all duration-300 hover:shadow-[0_10px_42px_var(--glow-primary)] hover:-translate-y-0.5 active:scale-[0.98] w-fit"
              >
                <Sparkles size={19} className="transition-transform duration-500 group-hover:rotate-12" />
                <span>Custom Study Session</span>
                <ChevronRight size={17} className="transition-transform duration-300 group-hover:translate-x-1 opacity-80" />
              </button>
            </div>
          </div>

          {/* Subject preset tiles */}
          {PRESETS.map(({ title, subject, duration, Icon }) => (
            <div key={title} data-reveal>
              <SubjectTile
                Icon={Icon}
                title={title}
                duration={duration}
                onPick={() => onStart(title, subject, duration)}
              />
            </div>
          ))}

          {/* Recent sessions — real history from study_sessions */}
          <div data-reveal className="bento-cell col-span-2 lg:col-span-4 p-5">
            <h3 className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--muted-foreground)] flex items-center gap-1.5 mb-3">
              <History size={13} /> Recent Sessions
            </h3>

            {recent === null && !historyFailed && (
              <div className="flex items-center gap-2 text-xs text-[var(--muted-foreground)] py-2">
                <RefreshCw size={12} className="animate-spin" /> Loading…
              </div>
            )}

            {historyFailed && (
              <p className="text-xs text-[var(--muted-foreground)] py-2">
                History unavailable — backend offline.
              </p>
            )}

            {recent !== null && recent.length === 0 && !historyFailed && (
              <p className="text-xs text-[var(--muted-foreground)] py-2">
                No past sessions yet — your finished sessions appear here.
              </p>
            )}

            <div className="space-y-1.5">
              {recent?.map((r) => (
                <button
                  key={r.id}
                  onClick={() => router.push("/achievements")}
                  className="w-full text-left p-3 rounded-xl border border-transparent hover:border-[var(--glass-border)] hover:bg-[var(--ember-0)] transition-all duration-200 flex items-center justify-between gap-3 group"
                >
                  <div className="min-w-0 flex items-center gap-3">
                    <span
                      className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                        r.status === "completed"
                          ? "bg-[var(--primary)]"
                          : r.status === "in_progress" || r.status === "paused"
                            ? "bg-[var(--amber)] ember-dot"
                            : "bg-[var(--muted-foreground)]/50"
                      }`}
                    />
                    <div className="min-w-0">
                      <p className="text-xs font-bold truncate group-hover:text-[var(--primary)] transition-colors">
                        {r.title}
                      </p>
                      <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">
                        {new Date(r.created_at * 1000).toLocaleDateString()} ·{" "}
                        {r.status === "completed"
                          ? `${Math.round((r.actual_duration_seconds || 0) / 60)} min focused`
                          : r.status.replace(/_/g, " ")}
                      </p>
                    </div>
                  </div>
                  <ChevronRight
                    size={14}
                    className="shrink-0 text-[var(--muted-foreground)] transition-transform duration-300 group-hover:translate-x-1 group-hover:text-[var(--primary)]"
                  />
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Real past-paper workspace: Paper Bank built-in past papers (English & Sinhala)
 * + uploaded custom exam papers with 1-click start under study telemetry.
 */
function PastPaperPanel({ subject }: { subject: string }) {
  const router = useRouter();
  const [bankGrade, setBankGrade] = useState<11 | 12 | 13>(13);
  const [bankMedium, setBankMedium] = useState<string>("");
  const [bankPapers, setBankPapers] = useState<
    Array<{
      id: string;
      group_key: string;
      paper_no: number;
      grade: number;
      subject: string;
      year: number;
      medium: string;
      title: string;
      question_count: number;
      mcq_count: number;
      essay_count: number;
      total_marks: number;
    }> | null
  >(null);
  const [uploadedPapers, setUploadedPapers] = useState<
    Array<{
      id: string;
      title: string;
      status: string;
      total_marks: number;
      question_count: number;
    }> | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const [bankRes, examRes] = await Promise.all([
        fetch(`/api/v1/paper_bank/catalog?subject=${bankGrade === 11 ? "ict-ol" : "ict"}&grade=${bankGrade}`),
        fetch("/api/v1/exams/list"),
      ]);
      if (bankRes.ok) {
        const bData = await bankRes.json();
        setBankPapers(bData.papers || []);
      }
      if (examRes.ok) {
        const eData = await examRes.json();
        setUploadedPapers(Array.isArray(eData) ? eData : []);
      }
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [bankGrade]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const filteredBank = useMemo(() => {
    if (!bankPapers) return [];
    return bankPapers.filter((p) => !bankMedium || p.medium === bankMedium);
  }, [bankPapers, bankMedium]);

  return (
    <div className="flex-1 p-5 pt-4 overflow-y-auto space-y-4">
      {/* Exam Room hero strip */}
      <div className="bento-cell liquid-sheen p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 overflow-hidden relative">
        <div className="aurora-stage !absolute">
          <div
            className="aurora-blob"
            style={cssVars({ "--x": "85%", "--y": "0%", "--size": "320px", "--blob-opacity": "0.5" })}
          />
        </div>
        <div className="space-y-1.5 relative z-10">
          <h3 className="text-sm font-bold flex items-center gap-2">
            <BookOpenCheck size={15} className="text-[var(--primary)]" />
            Paper Bank — Official A/L &amp; O/L Papers
          </h3>
          <p className="text-[11px] text-[var(--muted-foreground)] leading-relaxed max-w-md">
            Built-in English &amp; Sinhala medium papers with official answer keys: timed Paper 1 (MCQ) and Paper 2 (Structured Essay) with AI grading.
          </p>
        </div>
        <button
          onClick={() => router.push("/papers")}
          className="shrink-0 relative z-10 px-4 py-2 rounded-xl bg-[var(--primary)] text-white text-xs font-bold transition-all hover:brightness-110 hover:-translate-y-0.5 active:scale-95 shadow-[0_6px_20px_var(--glow-primary)]"
        >
          Open Full Paper Bank
        </button>
      </div>

      {/* Floating Guru hint */}
      <div className="bento-cell p-4 flex items-center justify-between gap-3">
        <div>
          <h4 className="text-xs font-bold text-[var(--amber)]">Need a Step Hint?</h4>
          <p className="text-[11px] text-[var(--muted-foreground)] mt-0.5">
            Studying {subject} — ask AI Guru without leaving your workspace.
          </p>
        </div>
        <button
          onClick={() =>
            window.dispatchEvent(
              new CustomEvent("aiguru:open-floating-chat", {
                detail: {
                  context: `I'm in the Study Room working on ${subject} past papers. I need a hint.`,
                },
              })
            )
          }
          className="shrink-0 px-3.5 py-1.5 rounded-lg surface-glass-base glow-ring text-xs font-bold text-[var(--primary)] transition-colors"
        >
          Ask AI Guru
        </button>
      </div>

      {/* Quick Filters */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--muted-foreground)] flex items-center gap-1.5">
            <FileText size={13} /> Built-in Past Papers
          </h4>
          <div className="flex items-center gap-1">
            {[11, 12, 13].map((g) => (
              <button
                key={g}
                onClick={() => setBankGrade(g as 11 | 12 | 13)}
                className={`px-2.5 py-1 rounded-lg text-[11px] font-bold border transition-colors ${
                  bankGrade === g
                    ? "bg-[var(--primary)] text-white border-transparent"
                    : "surface-glass-base border-[var(--glass-border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                G{g} {g === 11 ? "(O/L)" : "(A/L)"}
              </button>
            ))}
            <span className="w-px h-4 bg-[var(--glass-border)] mx-0.5" />
            {["", "english", "sinhala"].map((m) => (
              <button
                key={m || "all"}
                onClick={() => setBankMedium(m)}
                className={`px-2.5 py-1 rounded-lg text-[11px] font-bold border transition-colors ${
                  bankMedium === m
                    ? "bg-[var(--primary)] text-white border-transparent"
                    : "surface-glass-base border-[var(--glass-border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                {m === "" ? "All" : m === "english" ? "EN" : "සිංහල"}
              </button>
            ))}
          </div>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-6 text-[var(--muted-foreground)] text-xs gap-2">
            <RefreshCw size={14} className="animate-spin" />
            Loading papers…
          </div>
        )}

        {!loading && filteredBank.length === 0 && !failed && (
          <div className="p-6 rounded-xl border border-dashed border-[var(--glass-border-highlight)] text-center text-xs text-[var(--muted-foreground)]">
            No built-in papers found for this grade / medium filter.
          </div>
        )}

        {!loading && filteredBank.length > 0 && (
          <div className="grid gap-2 sm:grid-cols-2">
            {filteredBank.slice(0, 8).map((p) => (
              <button
                key={p.id}
                onClick={() => router.push("/papers")}
                className="p-3 rounded-xl surface-glass-base hover:border-[var(--ember-line)]/50 transition-all duration-200 text-left group flex items-center justify-between gap-2"
              >
                <div className="min-w-0">
                  <p className="text-xs font-bold truncate group-hover:text-[var(--primary)] transition-colors">
                    {p.title}
                  </p>
                  <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">
                    {p.question_count}Q · {p.medium === "sinhala" ? "සිංහල" : "English"} · P{p.paper_no}
                  </p>
                </div>
                <ChevronRight
                  size={14}
                  className="shrink-0 text-[var(--muted-foreground)] transition-transform duration-200 group-hover:translate-x-1 group-hover:text-[var(--primary)]"
                />
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Uploaded custom papers */}
      {uploadedPapers && uploadedPapers.length > 0 && (
        <div className="space-y-2 pt-2">
          <h4 className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
            Your Uploaded Papers
          </h4>
          {uploadedPapers.map((p) => (
            <button
              key={p.id}
              onClick={() => router.push(`/exam?exam=${encodeURIComponent(p.id)}`)}
              className="w-full text-left p-3.5 rounded-xl surface-glass-base hover:border-[var(--ember-line)]/50 transition-all duration-200 flex items-center justify-between gap-3 group"
            >
              <div className="min-w-0">
                <p className="text-xs font-bold truncate group-hover:text-[var(--primary)] transition-colors">{p.title}</p>
                <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">
                  {p.question_count} questions · {p.total_marks} marks ·{" "}
                  <span className="capitalize">{String(p.status || "ready").replace(/_/g, " ")}</span>
                </p>
              </div>
              <ChevronRight
                size={15}
                className="shrink-0 text-[var(--muted-foreground)] transition-transform duration-300 group-hover:translate-x-1 group-hover:text-[var(--primary)]"
              />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
