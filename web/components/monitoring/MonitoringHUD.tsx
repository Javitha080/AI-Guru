"use client";

import React from "react";
import {
  Activity,
  AlertCircle,
  BookOpen,
  CheckCircle,
  Compass,
  Cpu,
  Eye,
  Lock,
  Shield,
  Smile,
  Timer,
  Zap,
} from "lucide-react";
import { TelemetryState } from "./CameraPreview";

interface MonitoringHUDProps {
  telemetry?: TelemetryState;
  yaw?: number;
  pitch?: number;
  roll?: number;
  ear?: number;
  blinkCount?: number;
  livenessConfidence?: number;
  cpuPercent?: number;
  ramPercent?: number;
  className?: string;
}

export default function MonitoringHUD({
  telemetry = {
    presence: "PRESENT",
    focusScore: 98,
    engagementScore: 92,
    posture: "LOOKING_DOWN",
    isDistracted: false,
    whitelistedAction: "WRITING_NOTES",
    fps: 9.2,
  },
  yaw = 2.4,
  pitch = 28.5,
  roll = -1.2,
  ear = 0.28,
  blinkCount = 14,
  livenessConfidence = 0.96,
  cpuPercent = 14.2,
  ramPercent = 42.8,
  className = "",
}: MonitoringHUDProps) {
  return (
    <div
      className={`rounded-2xl border border-white/10 bg-slate-950/90 p-5 shadow-2xl backdrop-blur-2xl text-slate-200 ${className}`}
    >
      {/* Top Header: Platform Identity & Zero-Egress Invariant */}
      <div className="flex items-center justify-between border-b border-white/10 pb-3">
        <div className="flex items-center gap-2">
          <Shield className="h-5 w-5 text-indigo-400" />
          <h3 className="font-display font-semibold text-sm tracking-wide text-white">
            AI Guru Monitoring Engine
          </h3>
        </div>
        <div className="flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-medium text-emerald-400">
          <Lock size={12} />
          <span>Local CV Only</span>
        </div>
      </div>

      {/* Primary Key Metric Tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 my-4">
        {/* Presence State */}
        <div className="rounded-xl border border-white/5 bg-slate-900/60 p-3 flex flex-col justify-between">
          <span className="text-[11px] font-medium uppercase tracking-wider text-slate-400 flex items-center gap-1">
            <Timer size={13} className="text-slate-400" /> Presence
          </span>
          <div className="mt-1 flex items-baseline gap-1.5">
            <span
              className={`text-sm font-bold ${
                telemetry.presence === "PRESENT"
                  ? "text-emerald-400"
                  : telemetry.presence === "TEMPORARILY_NOT_VISIBLE"
                  ? "text-amber-400"
                  : "text-rose-400"
              }`}
            >
              {telemetry.presence.replace(/_/g, " ")}
            </span>
          </div>
        </div>

        {/* Focus Score */}
        <div className="rounded-xl border border-white/5 bg-slate-900/60 p-3 flex flex-col justify-between">
          <span className="text-[11px] font-medium uppercase tracking-wider text-slate-400 flex items-center gap-1">
            <Zap size={13} className="text-indigo-400" /> Focus Score
          </span>
          <div className="mt-1 flex items-baseline gap-1">
            <span className="text-lg font-bold text-white">
              {telemetry.focusScore}
            </span>
            <span className="text-xs text-slate-400">%</span>
          </div>
        </div>

        {/* Engagement Meter */}
        <div className="rounded-xl border border-white/5 bg-slate-900/60 p-3 flex flex-col justify-between">
          <span className="text-[11px] font-medium uppercase tracking-wider text-slate-400 flex items-center gap-1">
            <Activity size={13} className="text-cyan-400" /> Engagement
          </span>
          <div className="mt-1 flex items-baseline gap-1">
            <span className="text-lg font-bold text-cyan-300">
              {telemetry.engagementScore}
            </span>
            <span className="text-xs text-slate-400">/ 100</span>
          </div>
        </div>

        {/* Sampling Rate */}
        <div className="rounded-xl border border-white/5 bg-slate-900/60 p-3 flex flex-col justify-between">
          <span className="text-[11px] font-medium uppercase tracking-wider text-slate-400 flex items-center gap-1">
            <Cpu size={13} className="text-violet-400" /> Analysis Rate
          </span>
          <div className="mt-1 flex items-baseline gap-1">
            <span className="text-lg font-bold text-violet-300">
              {telemetry.fps}
            </span>
            <span className="text-xs text-slate-400">FPS</span>
          </div>
        </div>
      </div>

      {/* Head Pose & Biometric Analysis */}
      <div className="rounded-xl border border-white/5 bg-slate-900/40 p-3.5 space-y-2.5">
        <div className="flex items-center justify-between text-xs font-semibold text-slate-300">
          <span className="flex items-center gap-1.5">
            <Compass size={14} className="text-slate-400" /> Head Pose & Ergonomics
          </span>
          <span className="font-mono text-[11px] text-indigo-300">
            {telemetry.posture.replace(/_/g, " ")}
          </span>
        </div>

        <div className="grid grid-cols-3 gap-2 text-center text-xs font-mono">
          <div className="rounded-lg bg-slate-950/60 p-2 border border-white/5">
            <span className="text-[10px] text-slate-400 block">Yaw (L/R)</span>
            <span className="font-semibold text-slate-200">{yaw > 0 ? `+${yaw}°` : `${yaw}°`}</span>
          </div>
          <div className="rounded-lg bg-slate-950/60 p-2 border border-white/5">
            <span className="text-[10px] text-slate-400 block">Pitch (Desk)</span>
            <span className="font-semibold text-indigo-300">{pitch > 0 ? `+${pitch}°` : `${pitch}°`}</span>
          </div>
          <div className="rounded-lg bg-slate-950/60 p-2 border border-white/5">
            <span className="text-[10px] text-slate-400 block">Roll (Tilt)</span>
            <span className="font-semibold text-slate-200">{roll > 0 ? `+${roll}°` : `${roll}°`}</span>
          </div>
        </div>

        {/* Liveness & Eye Aspect Ratio */}
        <div className="flex items-center justify-between pt-2 border-t border-white/5 text-xs text-slate-400">
          <div className="flex items-center gap-2">
            <Eye size={13} className="text-emerald-400" />
            <span>EAR: <strong className="text-white font-mono">{ear}</strong></span>
            <span>Blinks: <strong className="text-white font-mono">{blinkCount}</strong></span>
          </div>
          <div className="flex items-center gap-1 text-emerald-400 font-medium text-[11px]">
            <CheckCircle size={12} />
            <span>Live Face ({(livenessConfidence * 100).toFixed(0)}%)</span>
          </div>
        </div>
      </div>

      {/* Whitelist / Distraction Status Banner */}
      {telemetry.whitelistedAction && (
        <div className="mt-3 flex items-center justify-between rounded-xl bg-indigo-500/10 border border-indigo-500/20 px-3.5 py-2 text-xs text-indigo-300">
          <div className="flex items-center gap-2">
            <BookOpen size={14} className="text-indigo-400" />
            <span>
              Study Activity Whitelisted:{" "}
              <strong className="text-white font-medium">
                {telemetry.whitelistedAction.replace(/_/g, " ").toLowerCase()}
              </strong>
            </span>
          </div>
          <span className="text-[10px] text-indigo-400 font-medium">
            Focus Preserved (100%)
          </span>
        </div>
      )}

      {/* Resource Governor Bar */}
      <div className="mt-3 flex items-center justify-between text-[11px] text-slate-400 font-mono">
        <span>CPU: {cpuPercent}% | RAM: {ramPercent}%</span>
        <span className="text-emerald-400 font-sans text-[10px]">
          Governor Healthy
        </span>
      </div>
    </div>
  );
}
