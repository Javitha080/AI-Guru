"use client";

import React from "react";
import {
  BookOpen,
  Pause,
  Play,
  StopCircle,
  Eye,
  Video,
  AlertTriangle,
} from "lucide-react";
import StudyTimer from "@/components/study/StudyTimer";
import { monitoringApi } from "@/lib/monitoring/monitoringApi";
import {
  WHITELIST_LABELS,
  type LiveWarning,
  type MonitorMode,
} from "@/hooks/useStudyTelemetry";

export function TelemetryRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex justify-between items-center text-[var(--muted-foreground)]">
      <span>{label}</span>
      {children}
    </div>
  );
}

export interface ActiveSessionHUDProps {
  sessionData: {
    title: string;
    subject: string;
    duration: number;
  } | null;
  sessionId: string | null;
  wsConnected: boolean;
  monitorMode: MonitorMode | null;
  timeLeft: number | null;
  isPaused: boolean;
  stopping: boolean;
  focusScore: number | null;
  engagementScore: number | null;
  focusTrend: string;
  presenceState: string;
  postureLabel: string;
  whitelistedAction: string | null;
  liveWarnings: LiveWarning[];
  liveViewEnabled: boolean;
  telegramBadgeVisible: boolean;
  feedAttempt: number;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  onPauseToggle: () => void;
  onFinish: () => void;
  onToggleLiveView: (next: boolean) => void;
  onFeedError: () => void;
}

export default function ActiveSessionHUD({
  sessionData,
  sessionId,
  wsConnected,
  monitorMode,
  timeLeft,
  isPaused,
  stopping,
  focusScore,
  engagementScore,
  focusTrend,
  presenceState,
  postureLabel,
  whitelistedAction,
  liveWarnings,
  liveViewEnabled,
  telegramBadgeVisible,
  feedAttempt,
  videoRef,
  onPauseToggle,
  onFinish,
  onToggleLiveView,
  onFeedError,
}: ActiveSessionHUDProps) {
  return (
    <>
      {/* Top Session HUD Bar — floating frosted glass */}
      <div className="surface-glass-base mx-3 mt-3 rounded-2xl px-5 py-3 flex items-center justify-between gap-4 shrink-0 relative z-30">
        <div className="flex items-center gap-3.5 min-w-0">
          <div className="w-10 h-10 rounded-xl bg-[var(--ember-0)] border border-[var(--glass-border)] flex items-center justify-center text-[var(--primary)] shrink-0">
            <BookOpen size={19} />
          </div>
          <div className="min-w-0">
            <h2 className="font-display font-bold text-sm leading-tight flex items-center gap-2 truncate">
              <span className="truncate">
                {sessionData?.title || "Active Study Session"}
              </span>
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
                  wsConnected
                    ? "text-[var(--primary)]"
                    : "text-[var(--muted-foreground)]"
                }`}
                title={
                  wsConnected
                    ? "On-device computer vision is streaming telemetry locally"
                    : "Monitoring engine standby"
                }
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    wsConnected
                      ? "bg-[var(--primary)] ember-dot"
                      : "bg-[var(--muted-foreground)]/50"
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

        {/* Live Controls */}
        <div className="flex items-center gap-2.5 shrink-0">
          <button
            onClick={onPauseToggle}
            className="glow-ring px-3.5 py-2 rounded-xl surface-glass-base text-xs font-bold flex items-center gap-1.5 hover:text-[var(--primary)]"
            title={isPaused ? "Resume session" : "Pause session"}
          >
            {isPaused ? <Play size={14} /> : <Pause size={14} />}
            <span>{isPaused ? "Resume" : "Pause"}</span>
          </button>

          <button
            onClick={onFinish}
            disabled={stopping}
            className="px-4 py-2 rounded-xl bg-red-500/10 hover:bg-red-500/20 disabled:opacity-50 text-red-400 border border-red-500/30 text-xs font-bold transition-colors flex items-center gap-1.5 glow-ring"
          >
            <StopCircle size={15} className={stopping ? "animate-pulse" : ""} />
            <span>{stopping ? "Finishing…" : "Finish Session"}</span>
          </button>
        </div>
      </div>
    </>
  );
}

export function MonitoringSidebar({
  sessionData,
  sessionId,
  wsConnected,
  monitorMode,
  timeLeft,
  isPaused,
  focusScore,
  engagementScore,
  focusTrend,
  presenceState,
  postureLabel,
  whitelistedAction,
  liveWarnings,
  liveViewEnabled,
  telegramBadgeVisible,
  feedAttempt,
  videoRef,
  onPauseToggle,
  onToggleLiveView,
  onFeedError,
}: Omit<ActiveSessionHUDProps, "stopping" | "onFinish">) {
  return (
    <aside className="w-full lg:w-[340px] shrink-0 flex flex-col gap-4 p-4 pt-2 lg:pl-1 pb-28 overflow-y-auto max-h-[48vh] lg:max-h-none border-t border-[var(--glass-border)] lg:border-t-0 lg:border-l">
      {/* Timer Clock */}
      <div className="bento-cell p-5 pt-7 flex flex-col items-center shrink-0 liquid-sheen">
        <StudyTimer
          timeLeft={timeLeft}
          totalSeconds={Math.max(60, sessionData?.duration || 25) * 60}
          isPaused={isPaused}
          onTogglePause={onPauseToggle}
        />
      </div>

      {/* Local CV Monitor Status Card */}
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
                presenceState.toUpperCase() === "PRESENT"
                  ? "text-[var(--primary)]"
                  : presenceState.toUpperCase() === "AWAY"
                  ? "text-red-400"
                  : "text-[var(--foreground)]"
              }`}
            >
              {presenceState.replace(/_/g, " ").toLowerCase()}
            </span>
          </TelemetryRow>
          <TelemetryRow label="Posture">
            <span className="font-semibold capitalize">{postureLabel}</span>
          </TelemetryRow>
          {whitelistedAction && (
            <TelemetryRow label="Recognized">
              <span className="font-semibold text-[var(--primary)]">
                {WHITELIST_LABELS[whitelistedAction] ||
                  whitelistedAction.replace(/_/g, " ").toLowerCase()}
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
                title={
                  focusTrend === "RISING"
                    ? "Engagement rising"
                    : focusTrend === "FALLING"
                    ? "Engagement falling"
                    : "Steady"
                }
                className={
                  focusTrend === "FALLING"
                    ? "text-red-400"
                    : focusTrend === "RISING"
                    ? "text-[var(--primary)]"
                    : "text-[var(--muted-foreground)]"
                }
              >
                {focusTrend === "RISING"
                  ? "↑"
                  : focusTrend === "FALLING"
                  ? "↓"
                  : "→"}
              </span>
              {engagementScore === null ? "—" : `${engagementScore}%`}
            </span>
          </TelemetryRow>
          <TelemetryRow label="Data Privacy">
            <span
              className={`font-semibold ${
                wsConnected
                  ? "text-[var(--amber)]"
                  : "text-[var(--muted-foreground)]"
              }`}
            >
              {wsConnected
                ? monitorMode === "system"
                  ? "On-device · photos only on alerts"
                  : "0 Bytes (Local)"
                : "—"}
            </span>
          </TelemetryRow>
          <div className="flex justify-between items-center pt-1.5 border-t border-[var(--glass-border)]">
            <span className="text-[var(--muted-foreground)]">
              Parent Live View
            </span>
            <button
              onClick={() => onToggleLiveView(!liveViewEnabled)}
              disabled={!wsConnected}
              aria-label="Toggle parent live view"
              className={`relative w-9 h-5 rounded-full transition-colors duration-300 ${
                liveViewEnabled
                  ? "bg-[var(--primary)] shadow-[0_0_12px_var(--glow-primary)]"
                  : "bg-[var(--muted)] border border-[var(--glass-border)]"
              } ${!wsConnected ? "opacity-40 cursor-not-allowed" : ""}`}
              title={
                liveViewEnabled
                  ? "Parent can view live snapshots"
                  : "Allow parent to view this session"
              }
            >
              <span
                className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all duration-300 ${
                  liveViewEnabled ? "left-[18px]" : "left-0.5"
                }`}
              />
            </button>
          </div>
        </div>

        {/* Live warnings — 3-tier: nudge / warning / alert */}
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

      {/* Camera feed */}
      <div className="bento-cell scanline relative aspect-video overflow-hidden flex items-center justify-center !bg-black/80">
        {wsConnected && <div className="scanline-bar" />}
        {monitorMode === "system" && sessionId && wsConnected ? (
          <img
            key={sessionId}
            src={monitoringApi.feed(sessionId, feedAttempt || undefined)}
            alt="Live AI Guru monitoring feed with face mesh overlay"
            className="absolute inset-0 h-full w-full object-cover opacity-95"
            onError={onFeedError}
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
            <p className="text-[10px] text-white/50 font-medium">
              Monitoring standby
            </p>
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
  );
}
