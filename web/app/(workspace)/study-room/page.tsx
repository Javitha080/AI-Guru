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
import { useLiveConsent } from "@/components/study/LiveConsentManager";
import { studySessionApi } from "@/lib/monitoring/monitoringApi";
import { notify } from "@/lib/notifications";

export interface SessionStats {
  durationMinutes: number | null;
  focusScore: number | null;
  engagementScore: number | null;
  distractionCount: number | null;
  warningCount: number | null;
  xpEarned: number | null;
  badgesUnlocked: string[];
  summary: string | null;
}

function toSessionStats(raw: Record<string, unknown> | null): SessionStats | null {
  if (!raw) return null;
  const metrics = (raw.metrics as Record<string, unknown> | undefined) ?? raw;
  const num = (v: unknown): number | null =>
    typeof v === "number" && Number.isFinite(v) ? v : null;
  const actualSecs =
    num(metrics.actual_duration_seconds) ?? num(raw.actual_duration_seconds);
  return {
    durationMinutes: actualSecs !== null ? Math.round(actualSecs / 60) : null,
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

  // Unified session clock
  const [timeLeft, setTimeLeft] = useState<number | null>(null);
  const [isPaused, setIsPaused] = useState(false);
  const [stopping, setStopping] = useState(false);

  // Scratchpad & workspace navigation
  const [studyNotes, setStudyNotes] = useState<string>("");
  const [activeTab, setActiveTab] = useState<"workspace" | "notes">("workspace");

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

  // Live supervision consent
  const { liveViewEnabled, toggleLiveView } = useLiveConsent({
    sessionId,
    onNotice: setApiNotice,
  });

  // Real-time telemetry hook
  const {
    focusScore,
    engagementScore,
    focusTrend,
    whitelistedAction,
    presenceState,
    postureLabel,
    liveWarnings,
    wsConnected,
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
    onNotice: setApiNotice,
  });

  // Scratchpad auto-persistence
  useEffect(() => {
    if (!sessionId) return;
    const key = `aiguru.study_notes.${sessionId}`;
    const saved = window.localStorage.getItem(key);
    if (saved) setStudyNotes(saved);
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId || !studyNotes) return;
    const key = `aiguru.study_notes.${sessionId}`;
    window.localStorage.setItem(key, studyNotes);
  }, [sessionId, studyNotes]);

  // Unified session clock: countdown tick
  const handleCompleteRef = useRef<() => Promise<void>>(async () => {});

  useEffect(() => {
    if (state !== "active" || isPaused) return;
    const interval = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev === null) return null;
        if (prev <= 1) {
          clearInterval(interval);
          void handleCompleteRef.current();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [state, isPaused]);

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
    setSessionData({
      title,
      subject,
      duration,
      paperId: paperMeta?.paperId,
      bankPaperId: paperMeta?.bankPaperId,
      grade: paperMeta?.grade,
      isCustomExam: paperMeta?.isCustomExam,
    });
    setState("pre-flight");
  };

  const handleResumeSession = (row: PastSessionRow) => {
    const elapsed = row.actual_duration_seconds || 0;
    const remaining = Math.max(0, row.target_duration_seconds - elapsed);
    setSessionId(row.id);
    setSessionData({
      title: row.title,
      subject: row.subject,
      duration: Math.round(row.target_duration_seconds / 60),
    });
    setTimeLeft(remaining);
    setIsPaused(row.status === "paused");
    setState("active");
  };

  const handlePreFlightReady = async () => {
    if (!sessionData) return;
    setApiNotice(null);
    try {
      const res = await fetch(studySessionApi.create, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          student_id: STUDENT_ID,
          title: sessionData.title,
          subject: sessionData.subject,
          target_duration_seconds: sessionData.duration * 60,
          monitoring_enabled: true,
          paper_id: sessionData.paperId,
          bank_paper_id: sessionData.bankPaperId,
          grade: sessionData.grade,
          is_custom_exam: sessionData.isCustomExam,
        }),
      });
      if (!res.ok) throw new Error(String(res.status));
      const json = await res.json();
      const realId = json.session_id || json.id;
      if (!realId) throw new Error("No session_id in create response");
      setSessionId(realId);
      setTimeLeft(sessionData.duration * 60);
      setIsPaused(false);
      setState("active");
    } catch {
      setApiNotice({
        kind: "warn",
        text: "Could not create session in backend database — running session locally without score persistence.",
      });
      setSessionId(null);
      setTimeLeft(sessionData.duration * 60);
      setIsPaused(false);
      setState("active");
    }
  };

  const handlePauseToggle = async () => {
    const next = !isPaused;
    setIsPaused(next);
    if (!sessionId) return;
    try {
      const ep = next ? "pause" : "resume";
      await fetch(studySessionApi.lifecycle(sessionId, ep), { method: "POST" });
    } catch {
      /* pause state remains local if offline */
    }
  };

  const handleComplete = useCallback(async () => {
    setStopping(true);
    setReportError(null);
    let summary: Record<string, unknown> | null = null;
    if (sessionId) {
      try {
        const res = await fetch(studySessionApi.lifecycle(sessionId, "stop"), {
          method: "POST",
        });
        if (res.ok) summary = await res.json();
      } catch {
        /* proceed to fetch report */
      }
      try {
        const repRes = await fetch(studySessionApi.report(sessionId));
        if (repRes.ok) {
          const reportJson = await repRes.json();
          summary = { ...summary, ...reportJson };
        }
      } catch {
        setReportError("Could not load full analytics report.");
      }
    }
    setReportStats(toSessionStats(summary));
    setState("completed");
    setStopping(false);
    notify("Study session completed! Great focus.", { tone: "success" });
  }, [sessionId]);

  handleCompleteRef.current = handleComplete;

  const resetToIdle = () => {
    resetTelemetry();
    setSessionData(null);
    setSessionId(null);
    setTimeLeft(null);
    setIsPaused(false);
    setStopping(false);
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
          {/* Top Session HUD Bar */}
          <ActiveSessionHUD
            sessionData={sessionData}
            sessionId={sessionId}
            wsConnected={wsConnected}
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
            liveViewEnabled={liveViewEnabled}
            telegramBadgeVisible={telegramBadgeVisible}
            feedAttempt={feedAttempt}
            videoRef={videoRef}
            onPauseToggle={() => void handlePauseToggle()}
            onFinish={() => {
              if (stopping) return;
              if (window.confirm("Finish this study session now?")) {
                void handleComplete();
              }
            }}
            onToggleLiveView={(next) => void toggleLiveView(next)}
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
              liveViewEnabled={liveViewEnabled}
              telegramBadgeVisible={telegramBadgeVisible}
              feedAttempt={feedAttempt}
              videoRef={videoRef}
              onPauseToggle={() => void handlePauseToggle()}
              onToggleLiveView={(next) => void toggleLiveView(next)}
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
            focusScore={focusScore}
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
    </div>
  );
}
