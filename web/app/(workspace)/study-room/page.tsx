"use client";

/**
 * AI Guru Study Room — Ember Glass edition.
 * Bento lobby, frosted HUD workspace, animated ember ring timer.
 * Refactored orchestrator composing modular study hooks and components.
 */

import React, { useState, useEffect, useRef, useCallback } from "react";
import { BookOpen, ShieldCheck } from "lucide-react";
import CreateSessionModal from "@/components/study/CreateSessionModal";
import PreFlightCheck from "@/components/study/PreFlightCheck";
import SessionReportView from "@/components/study/SessionReportView";
import FloatingStudyBar from "@/components/study/FloatingStudyBar";
import IdleLobby, { type PastSessionRow } from "@/components/study/IdleLobby";
import PastPaperPanel from "@/components/study/PastPaperPanel";
import ActiveSessionHUD, {
  MonitoringSidebar,
} from "@/components/study/ActiveSessionHUD";
import { useStudyTelemetry } from "@/hooks/useStudyTelemetry";
import { useVoiceDropIn } from "@/hooks/useVoiceDropIn";
import VoiceDropInBanner from "@/components/study/VoiceDropInBanner";
import { useSessionClock, computeResumeRemaining } from "@/hooks/useSessionClock";
import { useLiveConsent } from "@/components/study/LiveConsentManager";
import { studySessionApi } from "@/lib/monitoring/monitoringApi";
import { papersApi } from "@/lib/papers/paper-api";
import { apiFetch } from "@/lib/api";
import { notify } from "@/lib/notifications";
import { STUDY_ACTIVE_EVENT } from "@/components/layout/AppShell";

export interface SessionStats {
  durationMinutes: number | null;
  focusScore: number | null;
  engagementScore: number | null;
  distractionCount: number | null;
  warningCount: number | null;
  xpEarned: number | null;
  badgesUnlocked: string[];
  summary: string | null;
  reportReason?: string;
}

async function readDetail(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { detail?: unknown };
    if (typeof data?.detail === "string" && data.detail.trim()) return data.detail;
    if (Array.isArray((data as { detail?: unknown[] })?.detail)) {
      const msgs = ((data as { detail?: unknown[] }).detail ?? [])
        .map((d) => (typeof d === "string" ? d : (d as { msg?: unknown })?.msg))
        .filter((m): m is string => typeof m === "string" && m.length > 0);
      if (msgs.length > 0) return msgs.join("; ");
    }
  } catch {
    /* non-JSON error body */
  }
  return `Request failed (${res.status})`;
}

function toSessionStats(raw: Record<string, unknown> | null): SessionStats | null {
  if (!raw) return null;
  const metrics = (raw.metrics as Record<string, unknown> | undefined) ?? raw;
  const num = (v: unknown): number | null =>
    typeof v === "number" && Number.isFinite(v) ? v : null;
  const actualSecs =
    num(metrics.actual_duration_seconds) ?? num(raw.actual_duration_seconds);
  return {
    durationMinutes:
      actualSecs !== null && actualSecs > 0 ? Math.round(actualSecs / 60) : null,
    focusScore: num(metrics.focus_score) ?? num(raw.focus_score),
    engagementScore: num(metrics.engagement_score) ?? num(raw.engagement_score),
    distractionCount: num(metrics.distraction_count) ?? num(raw.distraction_count),
    warningCount: num(metrics.warning_count) ?? num(raw.warning_count),
    xpEarned: num(raw.xp_earned) ?? num(raw.xpEarned),
    badgesUnlocked: Array.isArray(raw.badgesUnlocked)
      ? (raw.badgesUnlocked as string[])
      : Array.isArray((raw as Record<string, unknown>).badges_unlocked)
        ? ((raw as Record<string, unknown>).badges_unlocked as string[])
        : [],
    summary:
      typeof raw.summary === "string"
        ? (raw.summary as string)
        : typeof raw.ai_summary === "string"
          ? (raw.ai_summary as string)
          : null,
    reportReason: typeof raw.reason === "string" ? (raw.reason as string) : undefined,
  };
}

type SessionState = "idle" | "creating" | "pre-flight" | "active" | "completed";

const STUDENT_ID = "student-primary";
const cssVars = (o: Record<string, string>) => o as unknown as React.CSSProperties;

export default function StudyRoomPage() {
  const [state, setState] = useState<SessionState>("idle");
  const [sessionData, setSessionData] = useState<{
    title: string;
    subject: string;
    duration: number;
    paperId?: string;
    bankPaperId?: string;
    grade?: number;
    isCustomExam?: boolean;
  } | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  const [isPaused, setIsPaused] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [confirmFinish, setConfirmFinish] = useState(false);
  // True when pre-flight continued without a camera: honest unmonitored
  // session — no vision engines start, Vision Guard stays blank.
  const [isOfflineSession, setIsOfflineSession] = useState(false);

  // Scratchpad & workspace navigation
  const [studyNotes, setStudyNotes] = useState<string>("");
  const [activeTab, setActiveTab] = useState<"workspace" | "notes">("workspace");

  // Deep-link from the Paper Bank ("Timed Exam"): the target paper id is
  // consumed once on mount and auto-started inside the new session.
  const [timedPaperId, setTimedPaperId] = useState<string | null>(null);
  const deepLinkConsumed = useRef(false);

  // API failure surfacing
  const [apiNotice, setApiNotice] = useState<{
    kind: "error" | "warn";
    text: string;
  } | null>(null);

  // Completed session reporting
  const [reportStats, setReportStats] = useState<SessionStats | null>(
    null
  );
  const [reportError, setReportError] = useState<string | null>(null);

  // Server-reconciled clock: deadline-based, pause-aware, tab-throttle safe.
  const targetSeconds = sessionData ? Math.max(60, Math.round(sessionData.duration * 60)) : null;
  const { timeLeft, start: startClock, reset: resetClock, reconcile } = useSessionClock({
    isActive: state === "active",
    isPaused,
    targetSeconds,
    sessionId,
  });

  // Live supervision consent (default ON, student opts out; the hook
  // retries backend sync once the monitoring channel reports up)
  const { liveViewEnabled, setLiveViewEnabled, markChannelUp } =
    useLiveConsent({
      sessionId,
      onNotice: setApiNotice,
    });

  // Parent voice drop-in: auto-answer intercom, default ON like Live View.
  // The student keeps volume + own-mic control; the banner never hides
  // mid-call. Audio unlock comes from the Pre-Flight continue gesture.
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const {
    call: voiceCall,
    micMuted: voiceMicMuted,
    setMicMuted: setVoiceMicMuted,
    volume: voiceVolume,
    setVolume: setVoiceVolume,
    announcement: voiceAnnouncement,
  } = useVoiceDropIn({
    sessionId: state === "active" ? sessionId : null,
    enabled: state === "active" && voiceEnabled && !isOfflineSession,
    onNotice: setApiNotice,
  });

  // Real-time telemetry hook (engines stay off for offline sessions)
  const {
    focusScore,
    engagementScore,
    focusTrend,
    whitelistedAction,
    presenceState,
    postureLabel,
    liveWarnings,
    wsConnected,
    hasTelemetry,
    monitorMode,
    feedAttempt,
    handleFeedError,
    telegramBadgeVisible,
    videoRef,
    resetTelemetry,
  } = useStudyTelemetry({
    sessionId,
    isActive: state === "active",
    liveViewEnabled,
    isPaused,
    monitoringEnabled: !isOfflineSession,
    onNotice: setApiNotice,
  });

  // Flush pending Live View consent once the monitoring socket is up.
  useEffect(() => {
    if (state === "active" && wsConnected) markChannelUp();
  }, [state, wsConnected, markChannelUp]);

  // Tell AppShell when a timed session is running so it can hide the
  // FloatingDock for focus mode (visible again in lobby/report states).
  useEffect(() => {
    window.dispatchEvent(
      new CustomEvent(STUDY_ACTIVE_EVENT, {
        detail: { active: state === "active" },
      }),
    );
  }, [state]);

  // Safety reset if the route unmounts mid-session.
  useEffect(() => {
    return () => {
      window.dispatchEvent(
        new CustomEvent(STUDY_ACTIVE_EVENT, { detail: { active: false } }),
      );
    };
  }, []);

  // Scratchpad auto-persistence (debounced, quota-safe)
  useEffect(() => {
    if (!sessionId) return;
    const key = `aiguru.study_notes.${sessionId}`;
    try {
      const saved = window.localStorage.getItem(key);
      if (saved) setStudyNotes(saved);
    } catch {
      /* storage unavailable */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    const key = `aiguru.study_notes.${sessionId}`;
    const id = setTimeout(() => {
      try {
        if (studyNotes) window.localStorage.setItem(key, studyNotes);
        else window.localStorage.removeItem(key);
      } catch {
        /* quota exceeded — notes stay in memory */
      }
    }, 400);
    return () => clearTimeout(id);
  }, [sessionId, studyNotes]);

  // Deep-link entry: /study-room?bankPaperId=<id>&mode=timed from the
  // Paper Bank hub. Pre-fills a real session (pre-flight → monitoring) and
  // lets the workspace auto-start the timed sitting once loaded.
  useEffect(() => {
    if (deepLinkConsumed.current) return;
    deepLinkConsumed.current = true;
    let params: URLSearchParams;
    try {
      params = new URLSearchParams(window.location.search);
    } catch {
      return;
    }
    const bankPaperId = (params.get("bankPaperId") || "").trim();
    if (!bankPaperId) return;
    const mode = params.get("mode");
    try {
      const url = new URL(window.location.href);
      url.searchParams.delete("bankPaperId");
      url.searchParams.delete("mode");
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    } catch {
      /* keep the URL — the param was still consumed */
    }
    if (mode === "timed") setTimedPaperId(bankPaperId);
    setApiNotice({ kind: "warn", text: "Opening paper from the Paper Bank — setting up your session…" });
    void papersApi
      .getPaper(bankPaperId)
      .then((detail) => {
        const mins = Math.max(1, Math.round((detail.default_duration_seconds || 3600) / 60));
        const subject = /^ict/i.test(detail.subject || "") ? "ICT" : detail.subject || "General";
        handleStartSession(detail.paper.title, subject, mins, {
          bankPaperId,
          grade: detail.grade,
        });
      })
      .catch(() => {
        setTimedPaperId(null);
        setApiNotice({
          kind: "error",
          text: "Could not open that paper — it may have been removed. Start a session manually.",
        });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Unified session clock: auto-finish at zero (deadline-based, no drift)
  const handleCompleteRef = useRef<() => Promise<void>>(async () => {});

  useEffect(() => {
    if (state !== "active" || isPaused) return;
    if (timeLeft === 0) void handleCompleteRef.current();
  }, [state, isPaused, timeLeft]);

  // Best-effort pause beacon: closing/refreshing mid-session banks the
  // open stretch server-side instead of leaking an 'in_progress' row that
  // inflates parent-dashboard minutes forever.
  useEffect(() => {
    if (state !== "active" || !sessionId) return;
    const onUnload = () => {
      try {
        navigator.sendBeacon(
          studySessionApi.lifecycle(sessionId, "pause"),
          new Blob([], { type: "text/plain" })
        );
      } catch {
        /* unload path — nothing to surface */
      }
    };
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, [state, sessionId]);

  // Session state handlers
  const handleStartSession = (
    title: string,
    subject: string,
    duration: number,
    paperMeta?: {
      paperId?: string;
      bankPaperId?: string;
      grade?: number;
      isCustomExam?: boolean;
    }
  ) => {
    const cleanTitle = title.trim().slice(0, 120) || `${subject} Study Session`.slice(0, 120);
    const cleanSubject = subject.trim().slice(0, 60) || "General";
    const cleanDuration = Number.isFinite(duration)
      ? Math.min(480, Math.max(1, Math.round(duration)))
      : 25;
    setSessionData({
      title: cleanTitle,
      subject: cleanSubject,
      duration: cleanDuration,
      paperId: paperMeta?.paperId,
      bankPaperId: paperMeta?.bankPaperId,
      grade: paperMeta?.grade,
      isCustomExam: paperMeta?.isCustomExam,
    });
    setApiNotice(null);
    setState("pre-flight");
  };

  const handleResumeSession = (row: PastSessionRow) => {
    // Only open sessions are resumable. Completed/abandoned rows are
    // terminal server-side (409) — refusing here avoids a confusing round
    // trip and a possible history rewrite.
    if (row.status !== "in_progress" && row.status !== "paused") {
      setApiNotice({
        kind: "warn",
        text: `That session is ${row.status.replace(/_/g, " ")} and can't be resumed. Start a new session instead.`,
      });
      return;
    }
    // Honest remaining: worked_seconds + open stretch, not actual_duration
    // (which is only written on stop).
    const remaining = computeResumeRemaining(row as unknown as Parameters<typeof computeResumeRemaining>[0]);
    setSessionId(row.id);
    setSessionData({
      title: row.title,
      subject: row.subject,
      duration: Math.max(1, Math.round(row.target_duration_seconds / 60)),
    });
    startClock(remaining);
    setIsPaused(row.status === "paused");
    setApiNotice(null);
    setState("active");
  };

  const handlePreFlightReady = async (result: { offline: boolean }) => {
    if (!sessionData) return;
    setApiNotice(null);
    // Unlock the AudioContext on this explicit gesture so a later parent
    // voice drop-in can autoplay without being blocked. Best-effort only.
    try {
      const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (Ctx) {
        const ctx = new Ctx();
        await ctx.resume().catch(() => {});
        void ctx.close().catch(() => {});
      }
    } catch {
      /* autoplay unlock is opportunistic */
    }
    const offline = result.offline === true;
    try {
      const res = await apiFetch(studySessionApi.create, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          student_id: STUDENT_ID,
          title: sessionData.title,
          subject: sessionData.subject,
          target_duration_seconds: Math.max(60, sessionData.duration * 60),
          monitoring_enabled: !offline,
          paper_id: sessionData.paperId,
          bank_paper_id: sessionData.bankPaperId,
          grade: sessionData.grade,
          is_custom_exam: sessionData.isCustomExam,
        }),
      });
      if (!res.ok) throw new Error(await readDetail(res));
      const json = (await res.json()) as { session_id?: string; id?: string };
      const realId = json.session_id || json.id;
      if (!realId) throw new Error("No session_id in create response");
      // Open the first active stretch: without /start the backend keeps
      // last_resume_time=NULL and banks zero minutes.
      const startRes = await apiFetch(studySessionApi.lifecycle(realId, "start"), {
        method: "POST",
      });
      if (!startRes.ok && startRes.status !== 409) throw new Error(await readDetail(startRes));
      setSessionId(realId);
      setIsOfflineSession(offline);
      if (offline) {
        // No monitoring channel can ever exist: keep Live View honestly OFF
        // instead of a default-ON switch that uploads nowhere.
        setLiveViewEnabled(false);
        setApiNotice({
          kind: "warn",
          text: "Unmonitored session — no camera. Vision Guard stays blank and the report records no focus scores.",
        });
      }
      startClock(Math.max(60, sessionData.duration * 60));
      setIsPaused(false);
      setState("active");
    } catch (e) {
      // No silent local-only session: without a backend row there is no
      // persistence, no report, and nothing for the parent dashboard.
      setApiNotice({
        kind: "error",
        text:
          e instanceof Error && e.message && !e.message.startsWith("Request failed")
            ? e.message
            : `Could not create session: ${e instanceof Error ? e.message : "backend unreachable"}. The session was not started.`,
      });
      return;
    }
  };

  const handlePaperStart = useCallback(
    async (info: { durationSeconds: number; title: string }) => {
      if (!sessionId) return;
      const secs = Math.max(60, Math.round(info.durationSeconds));
      try {
        const res = await apiFetch(studySessionApi.retarget(sessionId), {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target_duration_seconds: secs }),
        });
        if (!res.ok) throw new Error(await readDetail(res));
        const mins = Math.max(1, Math.round(secs / 60));
        setSessionData((prev) => (prev ? { ...prev, duration: mins } : prev));
        // Reconcile (not restart): elapsed study time stays banked, the new
        // paper duration becomes the target the clock counts down from.
        await reconcile();
        setApiNotice({
          kind: "warn",
          text: `Timer follows the paper: ${mins} min for “${info.title.slice(0, 60)}”.`,
        });
      } catch (e) {
        setApiNotice({
          kind: "error",
          text: `Could not adopt the paper duration: ${
            e instanceof Error ? e.message : "backend unreachable"
          }. The session clock is unchanged.`,
        });
      }
    },
    [sessionId, reconcile]
  );

  const handlePauseToggle = async () => {
    if (!sessionId) {
      setIsPaused((p) => !p);
      return;
    }
    const next = !isPaused;
    const prev = isPaused;
    setIsPaused(next);
    try {
      const ep = next ? "pause" : "resume";
      const res = await apiFetch(studySessionApi.lifecycle(sessionId, ep), { method: "POST" });
      if (!res.ok) {
        setIsPaused(prev);
        const detail = await readDetail(res);
        setApiNotice({
          kind: res.status === 409 ? "warn" : "error",
          text:
            res.status === 409
              ? "Session state changed on the server. Refreshed to match."
              : `Could not ${next ? "pause" : "resume"}: ${detail}`,
        });
      }
    } catch {
      setIsPaused(prev);
      setApiNotice({ kind: "error", text: "Connection lost. Pause was not saved. Try again." });
    }
  };

  const handleComplete = useCallback(async () => {
    if (stopping) return;
    if (!sessionId) {
      setReportError("No backend session exists for this run. Nothing was recorded. Start a new session.");
      setReportStats(null);
      setState("completed");
      return;
    }
    setStopping(true);
    setConfirmFinish(false);
    setReportError(null);
    let reportJson: Record<string, unknown> | null = null;
    let stopFailed = false;
    try {
      const res = await apiFetch(studySessionApi.lifecycle(sessionId, "stop"), {
        method: "POST",
      });
      if (!res.ok) {
        stopFailed = true;
        if (res.status === 409) {
          setReportError("This session was already closed. Showing its saved report.");
        } else {
          setReportError(`Could not close session: ${await readDetail(res)}`);
        }
      }
    } catch {
      stopFailed = true;
    }
    try {
      const repRes = await apiFetch(studySessionApi.report(sessionId));
      if (repRes.ok) {
        reportJson = (await repRes.json()) as Record<string, unknown>;
      } else {
        throw new Error(await readDetail(repRes));
      }
    } catch (e) {
      setReportError((prev) =>
        prev ??
        (stopFailed
          ? "Could not close the session or load its report. The session may still be open. Check Recent Sessions."
          : `Could not load full analytics report: ${e instanceof Error ? e.message : "unknown error"}`)
      );
    }
    const stats = toSessionStats(reportJson);
    if (stats && !stats.summary) {
      const reason = stats.reportReason;
      if (reason === "abandoned") stats.summary = "Session was abandoned. No summary generated.";
      else if (reason === "in_progress") stats.summary = "Session still open. Close it to generate the full report.";
    }
    setReportStats(stats);
    setState("completed");
    setStopping(false);
    notify("Study session completed! Great focus.", { tone: "success" });
  }, [sessionId, stopping]);

  handleCompleteRef.current = handleComplete;

  const resetToIdle = () => {
    resetTelemetry();
    resetClock();
    setVoiceEnabled(true);
    setTimedPaperId(null);
    setSessionData(null);
    setSessionId(null);
    setIsOfflineSession(false);
    setIsPaused(false);
    setStopping(false);
    setConfirmFinish(false);
    setStudyNotes("");
    setReportStats(null);
    setReportError(null);
    setApiNotice(null);
    setState("idle");
  };

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-[var(--background)] text-[var(--foreground)] relative font-sans">
      {/* Drifting aurora background */}
      <div className="aurora-stage">
        <div
          className="aurora-blob"
          style={cssVars({ "--x": "12%", "--y": "-10%", "--size": "560px", "--drift-dur": "34s" })}
        />
        <div
          className="aurora-blob"
          style={cssVars({
            "--x": "88%",
            "--y": "104%",
            "--size": "480px",
            "--blob-color": "var(--amber-glow)",
            "--blob-opacity": "0.45",
            "--drift-dur": "38s",
            "--drift-delay": "-8s",
          })}
        />
      </div>

      {/* API Notice Banner */}
      {apiNotice && (
        <div
          role="status"
          className={`px-4 py-2 text-xs flex items-center justify-between z-40 border-b ${
            apiNotice.kind === "error"
              ? "bg-red-500/15 border-red-500/30 text-red-300"
              : "bg-amber-500/15 border-amber-500/30 text-amber-200"
          }`}
        >
          <span>{apiNotice.text}</span>
          <button
            onClick={() => setApiNotice(null)}
            className="text-[10px] font-bold underline ml-3 opacity-75 hover:opacity-100"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* 1. IDLE STATE: BENTO LOBBY */}
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
        <div className="flex-1 min-h-0 overflow-y-auto p-4 py-6 relative z-10">
          <div className="m-auto w-full max-w-md">
            <PreFlightCheck
              onReady={(result) => void handlePreFlightReady(result)}
              onCancel={() => setState("idle")}
            />
          </div>
        </div>
      )}

      {/* 4. ACTIVE STUDY SESSION WORKSPACE */}
      {state === "active" && (
        <div className="flex-1 flex flex-col h-full overflow-hidden">
          {/* Parent voice drop-in banner (auto-answer, no hangup by design) */}
          {(voiceCall?.active || voiceAnnouncement) && (
            <VoiceDropInBanner
              secondsLeft={voiceCall?.seconds_left ?? 0}
              micMuted={voiceMicMuted}
              volume={voiceVolume}
              announcement={voiceAnnouncement}
              onToggleMute={(m) => setVoiceMicMuted(m)}
              onVolume={(v) => setVoiceVolume(v)}
            />
          )}
          {/* Top Session HUD Bar */}
          <ActiveSessionHUD
            sessionData={sessionData}
            sessionId={sessionId}
            wsConnected={wsConnected}
            hasTelemetry={hasTelemetry}
            monitorMode={monitorMode}
            timeLeft={timeLeft}
            isPaused={isPaused}
            stopping={stopping}
            focusScore={focusScore}
            engagementScore={engagementScore}
            focusTrend={focusTrend}
            presenceState={presenceState}
            postureLabel={postureLabel}
            whitelistedAction={whitelistedAction}
            liveWarnings={liveWarnings}
            telegramBadgeVisible={telegramBadgeVisible}
            feedAttempt={feedAttempt}
            videoRef={videoRef}
            onPauseToggle={() => void handlePauseToggle()}
            onFinish={() => {
              if (stopping) return;
              setConfirmFinish(true);
            }}
            voiceEnabled={voiceEnabled}
            onToggleVoice={(next) => setVoiceEnabled(next)}
            onFeedError={handleFeedError}
          />

          {/* Main Dual-Pane Workspace */}
          <div className="flex-1 flex flex-col lg:flex-row overflow-hidden">
            {/* Left Pane: Interactive Document & Past Paper Study Zone */}
            <div className="flex-1 flex flex-col overflow-hidden">
              <div className="px-5 pt-4 flex items-center justify-between gap-3">
                <div className="relative grid grid-cols-2 p-1 rounded-full surface-glass-base w-full max-w-sm">
                  {/* Sliding capsule thumb */}
                  <span
                    aria-hidden
                    className="absolute top-1 bottom-1 left-1 w-[calc(50%-4px)] rounded-full bg-[var(--primary)] shadow-[0_0_18px_var(--glow-primary)] transition-transform duration-300 ease-out"
                    style={{
                      transform:
                        activeTab === "notes"
                          ? "translateX(100%)"
                          : "translateX(0)",
                    }}
                  />
                  <button
                    onClick={() => setActiveTab("workspace")}
                    className={`relative z-10 px-3 py-1.5 rounded-full text-xs font-bold transition-colors duration-200 ${
                      activeTab === "workspace"
                        ? "text-white"
                        : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    }`}
                  >
                    Past Paper Problem Space
                  </button>
                  <button
                    onClick={() => setActiveTab("notes")}
                    className={`relative z-10 px-3 py-1.5 rounded-full text-xs font-bold transition-colors duration-200 ${
                      activeTab === "notes"
                        ? "text-white"
                        : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
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
                <PastPaperPanel
                  subject={sessionData?.subject || "General"}
                  initialPaperId={
                    sessionData?.bankPaperId || sessionData?.paperId
                  }
                  initialGrade={sessionData?.grade}
                  autoStartPaperId={timedPaperId}
                  onPaperStart={(info) => void handlePaperStart(info)}
                />
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

            {/* Right Pane: Monitoring Sidebar */}
            <MonitoringSidebar
              sessionData={sessionData}
              sessionId={sessionId}
              wsConnected={wsConnected}
              hasTelemetry={hasTelemetry}
              monitorMode={monitorMode}
              timeLeft={timeLeft}
              isPaused={isPaused}
              focusScore={focusScore}
              engagementScore={engagementScore}
              focusTrend={focusTrend}
              presenceState={presenceState}
              postureLabel={postureLabel}
              whitelistedAction={whitelistedAction}
              liveWarnings={liveWarnings}
              telegramBadgeVisible={telegramBadgeVisible}
              feedAttempt={feedAttempt}
              videoRef={videoRef}
              onPauseToggle={() => void handlePauseToggle()}
              voiceEnabled={voiceEnabled}
              onToggleVoice={(next) => setVoiceEnabled(next)}
              onFeedError={handleFeedError}
            />
          </div>

          {/* Floating Study Bar */}
          <FloatingStudyBar
            sessionTitle={sessionData?.title || "Study Session"}
            subject={sessionData?.subject || "General"}
            timeLeft={timeLeft}
            isPaused={isPaused}
            onTogglePause={() => void handlePauseToggle()}
            focusScore={wsConnected && hasTelemetry ? focusScore : null}
          />
        </div>
      )}

      {/* 5. COMPLETED STATE: SESSION REPORT CARD */}
      {state === "completed" && (
        <div className="flex-1 flex overflow-y-auto relative z-10">
          <SessionReportView
            stats={reportStats}
            error={reportError}
            onHome={resetToIdle}
          />
        </div>
      )}

      {/* Finish confirmation — styled modal, not window.confirm */}
      {confirmFinish && state === "active" && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(8px)" }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setConfirmFinish(false);
          }}
          role="dialog"
          aria-modal="true"
          aria-label="Finish study session"
        >
          <div className="bento-cell p-6 w-full max-w-sm space-y-4 animate-pop-in">
            <h2 className="font-display font-bold text-base">Finish this study session now?</h2>
            <p className="text-xs text-[var(--muted-foreground)] leading-relaxed">
              Your progress will be saved and the completion report generated. This cannot be undone.
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setConfirmFinish(false)}
                className="glass-btn-secondary !rounded-xl px-4 py-2 text-xs"
              >
                Keep studying
              </button>
              <button
                onClick={() => void handleComplete()}
                disabled={stopping}
                className="glass-btn-primary !rounded-xl px-4 py-2 text-xs disabled:opacity-50"
              >
                {stopping ? "Finishing…" : "Finish session"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
