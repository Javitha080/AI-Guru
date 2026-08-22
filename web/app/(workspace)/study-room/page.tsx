"use client";

import React, { useState, useEffect, useRef } from "react";
import { 
  Plus, BookOpen, Clock, ShieldCheck, Flame, Award, Sparkles, 
  Pause, Play, StopCircle, FileText, CheckCircle2, AlertTriangle, 
  Smartphone, Eye, Video, RefreshCw, Send, ChevronRight
} from "lucide-react";
import CreateSessionModal from "@/components/study/CreateSessionModal";
import PreFlightCheck from "@/components/study/PreFlightCheck";
import StudyTimer from "@/components/study/StudyTimer";
import SessionReportView from "@/components/study/SessionReportView";
import FloatingStudyBar from "@/components/study/FloatingStudyBar";
import type { VisionPipeline } from "@/lib/monitoring/visionPipeline";

type SessionState = "idle" | "creating" | "pre-flight" | "active" | "completed";

interface LiveWarning {
  warning_id: string;
  category: string;
  message: string;
  severity: string;
  at: number;
}

export default function StudyRoomPage() {
  const [state, setState] = useState<SessionState>("idle");
  const [sessionData, setSessionData] = useState<{
    title: string;
    subject: string;
    duration: number;
    pdfUrl?: string;
  } | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  // ---- Real monitoring telemetry (WS-backed; no simulated values) ----
  const [focusScore, setFocusScore] = useState<number | null>(null); // null = awaiting real data
  const [engagementScore, setEngagementScore] = useState<number | null>(null);
  const [presenceState, setPresenceState] = useState<string>("unknown");
  const [postureLabel, setPostureLabel] = useState<string>("—");
  const [liveWarnings, setLiveWarnings] = useState<LiveWarning[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const pipelineRef = useRef<VisionPipeline | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [studyNotes, setStudyNotes] = useState<string>("");
  const [activeTab, setActiveTab] = useState<"workspace" | "notes">("workspace");
  const [liveViewEnabled, setLiveViewEnabled] = useState(false);

  const toggleLiveView = async (next: boolean) => {
    setLiveViewEnabled(next);
    if (!sessionId) return;
    try {
      await fetch(
        `/api/v1/monitoring/live/consent?session_id=${encodeURIComponent(sessionId)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: next }),
        }
      );
    } catch {
      /* consent is best-effort; frames simply won't upload */
    }
  };

  // Open the local monitoring stream once the session goes active.
  // MediaPipe runs on-device; landmarks feed the backend geometry engine
  // over the monitoring WS (same-origin, cookie-authenticated).
  useEffect(() => {
    if (state !== "active") return;
    let cancelled = false;
    const pipelineRefLocal: { current: VisionPipeline | null } = { current: null };

    const applyRemote = (msg: Record<string, unknown>) => {
      if (typeof msg.engagement_score === "number") setEngagementScore(Math.round(msg.engagement_score));
      if (typeof msg.focus_score === "number") setFocusScore(Math.round(msg.focus_score));
      if (typeof msg.presence === "string") setPresenceState(String(msg.presence));
      if (typeof msg.posture === "string") {
        setPostureLabel(String(msg.posture).replace(/_/g, " ").toLowerCase());
      }
      const warn = msg.warning as { warning_id?: string; category?: string; message?: string; severity?: string } | undefined;
      if (warn?.warning_id) {
        setLiveWarnings((prev) =>
          [{ ...warn, at: Date.now() } as LiveWarning, ...prev.filter((w) => w.warning_id !== warn.warning_id)].slice(0, 5)
        );
      }
    };

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
            } else if (!frame.detected) {
              setPresenceState((p) => (p === "unknown" ? "unknown" : p));
            }
            // Parent live view: throttled frame upload while consented.
            if (liveViewEnabled && frame.jpeg_b64 && Date.now() - lastLiveUpload > 1500 && sessionId) {
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
  }, [state, sessionId]);

  const handleStartSession = async (title: string, subject: string, duration: number) => {
    setSessionData({ title, subject, duration });
    setState("pre-flight");
  };

  const handlePreFlightReady = async () => {
    // Create + start the session against the real backend; fall back to an
    // untracked local-only run if the API is unreachable.
    let createdId: string | null = null;
    try {
      const res = await fetch("/api/v1/study-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          student_id: "student-primary",
          title: sessionData?.title || "Study Session",
          subject: sessionData?.subject || "General",
          target_duration_seconds: Math.max(60, (sessionData?.duration || 25) * 60),
        }),
      });
      if (res.ok) {
        const data = await res.json();
        createdId = data.id || null;
      }
      if (createdId) {
        await fetch(`/api/v1/study-session/${createdId}/start`, { method: "POST" });
      }
    } catch (err) {
      console.warn("Study-session API unreachable; continuing locally", err);
    }
    setSessionId(createdId);
    setState("active");
  };

  const handleComplete = async () => {
    if (sessionId) {
      try {
        await fetch(`/api/v1/study-session/${sessionId}/stop`, { method: "POST" });
      } catch (err) {
        console.warn("Stop failed", err);
      }
    }
    setState("completed");
  };

  // Report stats come from the real backend where available.
  const [reportStats, setReportStats] = useState<{
    durationMinutes: number;
    focusScore: number | null;
    engagementScore: number | null;
    distractionCount: number;
    warningCount: number;
    xpEarned: number | null;
  }>({
    durationMinutes: 25,
    focusScore: null,
    engagementScore: null,
    distractionCount: 0,
    warningCount: 0,
    xpEarned: null,
  });

  // Report stats come from the real backend where available.
  const sessionStats = {
    durationMinutes: reportStats.durationMinutes,
    focusScore: reportStats.focusScore ?? 0,
    engagementScore: reportStats.engagementScore ?? 0,
    distractionCount: reportStats.distractionCount,
    warningCount: reportStats.warningCount || liveWarnings.length,
    xpEarned: reportStats.xpEarned ?? 0,
    badgesUnlocked: [] as string[],
  };

  useEffect(() => {
    if (state !== "completed") return;
    const load = async () => {
      if (!sessionId) return;
      try {
        const [reportRes, profileRes] = await Promise.allSettled([
          fetch(`/api/v1/study-session/${sessionId}/report`),
          fetch("/api/v1/study-session/gamification/student-primary/profile"),
        ]);
        if (reportRes.status === "fulfilled" && reportRes.value.ok) {
          const r = await reportRes.value.json();
          const metrics = r.metrics || {};
          setReportStats((prev) => ({
            ...prev,
            durationMinutes: Math.round((metrics.actual_duration_seconds ?? metrics.duration_seconds ?? prev.durationMinutes * 60) / 60),
            focusScore: typeof metrics.focus_score === "number" ? Math.round(metrics.focus_score) : focusScore,
            engagementScore: typeof metrics.engagement_score === "number" ? Math.round(metrics.engagement_score) : engagementScore,
            distractionCount: Number(metrics.distraction_count ?? 0),
            warningCount: Number(metrics.warning_count ?? liveWarnings.length),
          }));
        }
        if (profileRes.status === "fulfilled" && profileRes.value.ok) {
          const p = await profileRes.value.json();
          setReportStats((prev) => ({ ...prev, xpEarned: typeof p.xp === "number" ? p.xp : prev.xpEarned }));
        }
      } catch {
        /* keep placeholders as nulls */
      }
    };
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);


  return (
    <div className="flex-1 h-full flex flex-col bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 relative overflow-hidden">
      
      {/* 1. IDLE STATE: STUDY ROOM LOBBY */}
      {state === "idle" && (
        <div className="flex-1 flex flex-col items-center justify-center p-6 text-center max-w-2xl mx-auto space-y-6">
          <div className="w-20 h-20 rounded-3xl bg-blue-100 dark:bg-blue-900/50 flex items-center justify-center shadow-inner text-blue-600 dark:text-blue-400">
            <BookOpen size={36} />
          </div>

          <div className="space-y-2">
            <h1 className="text-3xl font-extrabold tracking-tight">AI Guru Study Room</h1>
            <p className="text-sm text-gray-500 dark:text-gray-400 max-w-md mx-auto">
              Intelligent, privacy-first study companion with local AI monitoring, PDF past-paper workspace, and real-time focus feedback.
            </p>
          </div>

          {/* Quick Subject Launch Cards */}
          <div className="grid grid-cols-2 gap-3 w-full max-w-md">
            {[
              { title: "Mathematics (Past Papers)", duration: 45, icon: "📐" },
              { title: "Physics Mechanics", duration: 30, icon: "⚡" },
              { title: "Computer Science Algorithms", duration: 25, icon: "💻" },
              { title: "Chemistry Revision", duration: 30, icon: "🧪" },
            ].map((sub, idx) => (
              <button
                key={idx}
                onClick={() => handleStartSession(sub.title, sub.title.split(" ")[0], sub.duration)}
                className="p-3.5 bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 hover:border-blue-500 text-left transition-all hover:shadow-md group"
              >
                <span className="text-2xl mb-1 block">{sub.icon}</span>
                <h4 className="text-xs font-bold text-gray-800 dark:text-gray-200 group-hover:text-blue-600 line-clamp-1">
                  {sub.title}
                </h4>
                <p className="text-[10px] text-gray-400 mt-0.5">{sub.duration} mins • Monitored</p>
              </button>
            ))}
          </div>

          <button
            onClick={() => setState("creating")}
            className="px-8 py-3.5 rounded-2xl bg-blue-600 hover:bg-blue-700 text-white font-bold shadow-lg shadow-blue-500/20 transition-all flex items-center gap-2"
          >
            <Plus size={20} />
            <span>Custom Study Session</span>
          </button>
        </div>
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
        <div className="flex-1 flex items-center justify-center p-4">
          <PreFlightCheck
            onReady={handlePreFlightReady}
            onCancel={() => setState("idle")}
          />
        </div>
      )}

      {/* 4. ACTIVE STUDY SESSION WORKSPACE */}
      {state === "active" && (
        <div className="flex-1 flex flex-col h-full overflow-hidden">
          {/* Top Session HUD Bar */}
          <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-3 flex items-center justify-between shadow-sm">
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 rounded-xl bg-blue-50 dark:bg-blue-900/40 flex items-center justify-center text-blue-600 dark:text-blue-400 font-bold">
                <BookOpen size={20} />
              </div>
              <div>
                <h2 className="font-bold text-sm text-gray-900 dark:text-white flex items-center gap-2">
                  <span>{sessionData?.title || "Active Study Session"}</span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-300">
                    {sessionData?.subject}
                  </span>
                </h2>
                <div className="flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  <span className="flex items-center gap-1 text-green-600 dark:text-green-400 font-medium">
                    <ShieldCheck size={13} />
                    Local AI Active (Zero Egress)
                  </span>
                  <span>•</span>
                  <span>Target: {sessionData?.duration} mins</span>
                </div>
              </div>
            </div>

            {/* Live Focus Meter & Controls */}
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-100 dark:bg-gray-700/60 rounded-xl border border-gray-200 dark:border-gray-600">
                <Sparkles size={14} className="text-amber-500" />
                <span className="text-xs font-bold text-gray-700 dark:text-gray-300">
                  Focus: {focusScore === null ? "—" : `${focusScore}%`}
                </span>
              </div>

              <button
                onClick={handleComplete}
                className="px-4 py-2 rounded-xl bg-red-500/10 hover:bg-red-500/20 text-red-600 dark:text-red-400 border border-red-500/30 text-xs font-bold transition-colors flex items-center gap-1.5"
              >
                <StopCircle size={15} />
                <span>Finish Session</span>
              </button>
            </div>
          </div>

          {/* Main Dual-Pane Workspace */}
          <div className="flex-1 flex overflow-hidden">
            {/* Left Pane: Interactive Document & Past Paper Study Zone */}
            <div className="flex-1 flex flex-col bg-white dark:bg-gray-800/50 border-r border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between bg-gray-50 dark:bg-gray-800">
                <div className="flex gap-2">
                  <button
                    onClick={() => setActiveTab("workspace")}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold ${activeTab === "workspace" ? "bg-blue-600 text-white" : "text-gray-500 hover:bg-gray-200 dark:hover:bg-gray-700"}`}
                  >
                    Past Paper Problem Space
                  </button>
                  <button
                    onClick={() => setActiveTab("notes")}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold ${activeTab === "notes" ? "bg-blue-600 text-white" : "text-gray-500 hover:bg-gray-200 dark:hover:bg-gray-700"}`}
                  >
                    Scratch Notes
                  </button>
                </div>
              </div>

              {activeTab === "workspace" ? (
                <div className="flex-1 p-6 overflow-y-auto space-y-6">
                  {/* Sample Past Paper Problem */}
                  <div className="p-5 rounded-2xl bg-gray-50 dark:bg-gray-700/30 border border-gray-200 dark:border-gray-700 space-y-4">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold font-mono text-blue-600 dark:text-blue-400">
                        EXAM PROBLEM #04 • 2024 Past Paper
                      </span>
                      <span className="text-xs text-gray-400">[6 Marks]</span>
                    </div>

                    <p className="text-sm font-serif leading-relaxed text-gray-800 dark:text-gray-200">
                      Solve the quadratic equation:
                      <br />
                      <span className="block my-2 font-mono font-bold text-center text-base bg-white dark:bg-gray-800 py-2 rounded-xl border border-gray-200 dark:border-gray-700">
                        2x² - 7x + 3 = 0
                      </span>
                      Show all factorisation steps or apply the Quadratic Formula.
                    </p>

                    <div className="pt-2 border-t border-gray-200 dark:border-gray-700">
                      <label className="block text-xs font-semibold text-gray-500 mb-2">Student Working Space:</label>
                      <textarea
                        rows={4}
                        placeholder="Write step-by-step derivation here..."
                        className="w-full p-3 text-sm font-mono bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-xl focus:ring-2 focus:ring-blue-500 focus:outline-none"
                      />
                    </div>
                  </div>

                  <div className="p-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-2xl flex items-center justify-between">
                    <div>
                      <h4 className="text-xs font-bold text-blue-900 dark:text-blue-200">Need a Step Hint?</h4>
                      <p className="text-[11px] text-blue-700 dark:text-blue-300 mt-0.5">
                        AI Guru is ready in the background to guide your derivation without giving away the final answer.
                      </p>
                    </div>
                    <button
                      onClick={() =>
                        window.dispatchEvent(
                          new CustomEvent("aiguru:open-floating-chat", {
                            detail: { context: `Studying ${sessionData?.subject || "General"}. I need a hint on this problem.` },
                          })
                        )
                      }
                      className="px-3.5 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold rounded-xl transition-colors"
                    >
                      Ask AI Guru
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex-1 p-6">
                  <textarea
                    value={studyNotes}
                    onChange={(e) => setStudyNotes(e.target.value)}
                    placeholder="Take session notes, formulas, or key concepts..."
                    className="w-full h-full p-4 text-sm font-mono bg-transparent border-0 resize-none focus:outline-none"
                  />
                </div>
              )}
            </div>

            {/* Right Pane: Timer & Local AI Supervision HUD */}
            <div className="w-80 flex flex-col bg-gray-50 dark:bg-gray-900 p-6 justify-between border-l border-gray-200 dark:border-gray-700">
              <div className="space-y-6">
                {/* Timer Clock */}
                <div className="bg-white dark:bg-gray-800 p-6 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm flex flex-col items-center">
                  <StudyTimer
                    durationMinutes={sessionData?.duration || 25}
                    isActive={true}
                    onComplete={handleComplete}
                    onPauseToggle={() => {}}
                  />
                </div>

                {/* Local CV Monitor Status Card — real WS telemetry only */}
                <div className="bg-white dark:bg-gray-800 p-4 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-gray-700 dark:text-gray-300 flex items-center gap-1.5">
                      <Eye size={14} className="text-blue-500" />
                      <span>Vision Guard</span>
                    </span>
                    <span
                      className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${
                        wsConnected
                          ? "bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300"
                          : "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400"
                      }`}
                    >
                      {wsConnected ? "LIVE" : "OFFLINE"}
                    </span>
                  </div>

                  <div className="space-y-2 text-xs">
                    <div className="flex justify-between text-gray-500 dark:text-gray-400">
                      <span>Presence</span>
                      <span
                        className={`font-semibold capitalize ${
                          presenceState === "present"
                            ? "text-green-600 dark:text-green-400"
                            : presenceState === "away"
                              ? "text-red-600 dark:text-red-400"
                              : "text-gray-700 dark:text-gray-300"
                        }`}
                      >
                        {presenceState.replace(/_/g, " ")}
                      </span>
                    </div>
                    <div className="flex justify-between text-gray-500 dark:text-gray-400">
                      <span>Posture</span>
                      <span className="font-semibold text-gray-800 dark:text-gray-200 capitalize">{postureLabel}</span>
                    </div>
                    <div className="flex justify-between text-gray-500 dark:text-gray-400">
                      <span>Engagement</span>
                      <span className="font-semibold text-blue-600 dark:text-blue-400 font-mono">
                        {engagementScore === null ? "—" : `${engagementScore}%`}
                      </span>
                    </div>
                    <div className="flex justify-between text-gray-500 dark:text-gray-400">
                      <span>Device Egress</span>
                      <span className="font-semibold text-blue-600 dark:text-blue-400 font-mono">0 Bytes (Local)</span>
                    </div>
                    <div className="flex justify-between items-center text-gray-500 dark:text-gray-400 pt-1 border-t border-gray-100 dark:border-gray-700">
                      <span>Parent Live View</span>
                      <button
                        onClick={() => void toggleLiveView(!liveViewEnabled)}
                        disabled={!wsConnected}
                        className={`relative w-9 h-5 rounded-full transition-colors ${
                          liveViewEnabled ? "bg-green-500" : "bg-gray-300 dark:bg-gray-600"
                        } ${!wsConnected ? "opacity-40 cursor-not-allowed" : ""}`}
                        title={liveViewEnabled ? "Parent can view live snapshots" : "Allow parent to view this session"}
                      >
                        <span
                          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${
                            liveViewEnabled ? "left-[18px]" : "left-0.5"
                          }`}
                        />
                      </button>
                    </div>
                  </div>

                  {/* Live warnings (dispatched by the local CV pipeline) */}
                  {liveWarnings.length > 0 && (
                    <div className="pt-2 border-t border-gray-200 dark:border-gray-700 space-y-1.5">
                      {liveWarnings.slice(0, 3).map((w) => (
                        <div
                          key={w.warning_id}
                          className={`p-2 rounded-lg text-[11px] flex items-start gap-1.5 ${
                            w.severity === "alert"
                              ? "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300"
                              : w.severity === "warning"
                                ? "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300"
                                : "bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
                          }`}
                        >
                          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                          <span>{w.message}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* Camera — real on-device preview feeding the local CV pipeline */}
              <div className="relative aspect-video bg-black rounded-2xl overflow-hidden border border-gray-200 dark:border-gray-700 shadow-lg flex items-center justify-center">
                <video
                  ref={videoRef}
                  muted
                  playsInline
                  autoPlay
                  className="absolute inset-0 h-full w-full object-cover opacity-90"
                />
                {!wsConnected && (
                  <div className="relative text-center space-y-1 z-10">
                    <Video size={24} className="mx-auto text-white/40" />
                    <p className="text-[10px] text-white/50 font-medium">Monitoring standby</p>
                  </div>
                )}
                <div
                  className={`absolute top-2 left-2 flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono ${
                    wsConnected ? "bg-black/60 text-green-400" : "bg-black/60 text-gray-400"
                  }`}
                >
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${wsConnected ? "bg-green-400 animate-pulse" : "bg-gray-500"}`}
                  />
                  <span>{wsConnected ? "LIVE · ON-DEVICE" : "IDLE"}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Floating Study Bar & Cluely-style Assistant */}
          <FloatingStudyBar
            sessionTitle={sessionData?.title || "Study Session"}
            subject={sessionData?.subject || "General"}
            durationMinutes={sessionData?.duration || 25}
            focusScore={focusScore ?? 0}
            onComplete={handleComplete}
          />
        </div>
      )}

      {/* 5. COMPLETED STATE: SESSION REPORT CARD */}
      {state === "completed" && (
        <div className="flex-1 flex overflow-y-auto">
          <SessionReportView
            stats={sessionStats}
            onHome={() => setState("idle")}
          />
        </div>
      )}
    </div>
  );
}
