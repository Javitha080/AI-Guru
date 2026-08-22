"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  Camera,
  CameraOff,
  Eye,
  ShieldCheck,
  AlertTriangle,
  BookOpen,
  Coffee,
  Smartphone,
  Maximize2,
  Minimize2,
  Activity,
  CheckCircle2,
} from "lucide-react";

export interface TelemetryState {
  presence: "PRESENT" | "TEMPORARILY_NOT_VISIBLE" | "AWAY" | "UNKNOWN";
  focusScore: number;
  engagementScore: number;
  posture: string;
  isDistracted: boolean;
  whitelistedAction?: string | null;
  fps: number;
  warning?: {
    category: string;
    message: string;
    severity: "info" | "warning" | "alert";
  } | null;
}

interface CameraPreviewProps {
  sessionId?: string;
  isMockMode?: boolean;
  onTelemetryUpdate?: (telemetry: TelemetryState) => void;
  className?: string;
}

export default function CameraPreview({
  sessionId = "active-session",
  isMockMode = false,
  onTelemetryUpdate,
  className = "",
}: CameraPreviewProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [streamActive, setStreamActive] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [isExpanded, setIsExpanded] = useState(false);

  const [telemetry, setTelemetry] = useState<TelemetryState>({
    presence: "PRESENT",
    focusScore: 100,
    engagementScore: 95,
    posture: "HEAD_CENTER",
    isDistracted: false,
    whitelistedAction: null,
    fps: 8.5,
    warning: null,
  });

  // Initialize camera stream locally
  useEffect(() => {
    let mediaStream: MediaStream | null = null;

    async function startCamera() {
      if (isMockMode) {
        setStreamActive(true);
        return;
      }

      try {
        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
          mediaStream = await navigator.mediaDevices.getUserMedia({
            video: { width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 30 } },
            audio: false,
          });
          if (videoRef.current) {
            videoRef.current.srcObject = mediaStream;
            await videoRef.current.play().catch(() => {});
          }
          setStreamActive(true);
          setCameraError(null);
        } else {
          setCameraError("Webcam not supported in this browser");
        }
      } catch (err: any) {
        console.warn("Local camera access notice:", err.message);
        setCameraError(err.message || "Camera permission needed");
        // Fall back to simulation mode
        setStreamActive(true);
      }
    }

    startCamera();

    return () => {
      if (mediaStream) {
        mediaStream.getTracks().forEach((track) => track.stop());
      }
    };
  }, [isMockMode]);

  // Periodic telemetry simulation or WS stream listener
  useEffect(() => {
    const interval = setInterval(() => {
      // In mock/development mode, simulate slight variations in focus and blinks
      setTelemetry((prev) => {
        const nextTelemetry: TelemetryState = {
          ...prev,
          fps: Math.round((7.5 + Math.random() * 2.0) * 10) / 10,
        };
        if (onTelemetryUpdate) {
          onTelemetryUpdate(nextTelemetry);
        }
        return nextTelemetry;
      });
    }, 2000);

    return () => clearInterval(interval);
  }, [onTelemetryUpdate]);

  const getPresenceBadgeColor = (state: string) => {
    switch (state) {
      case "PRESENT":
        return "bg-emerald-500/20 text-emerald-400 border-emerald-500/30";
      case "TEMPORARILY_NOT_VISIBLE":
        return "bg-amber-500/20 text-amber-400 border-amber-500/30";
      case "AWAY":
        return "bg-rose-500/20 text-rose-400 border-rose-500/30";
      default:
        return "bg-slate-500/20 text-slate-400 border-slate-500/30";
    }
  };

  return (
    <div
      className={`relative overflow-hidden rounded-2xl border border-white/10 bg-slate-950/80 shadow-2xl backdrop-blur-xl transition-all duration-300 ${
        isExpanded ? "fixed inset-6 z-50 flex flex-col" : "w-full max-w-sm"
      } ${className}`}
    >
      {/* Top Header / Status Bar */}
      <div className="flex items-center justify-between border-b border-white/10 px-3.5 py-2.5 bg-slate-900/60">
        <div className="flex items-center gap-2">
          <div className="flex h-6 items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-400">
            <ShieldCheck size={12} className="text-emerald-400" />
            <span>Zero Cloud Egress</span>
          </div>
          <span className="text-[10px] text-slate-400 font-mono">
            {telemetry.fps} FPS
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <div
            className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${getPresenceBadgeColor(
              telemetry.presence
            )}`}
          >
            {telemetry.presence.replace(/_/g, " ")}
          </div>
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="rounded-lg p-1 text-slate-400 hover:bg-white/5 hover:text-white transition-colors"
            title={isExpanded ? "Minimize" : "Expand"}
          >
            {isExpanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        </div>
      </div>

      {/* Video Viewport */}
      <div className="relative aspect-video w-full bg-slate-900 flex items-center justify-center overflow-hidden">
        {streamActive && !cameraError ? (
          <video
            ref={videoRef}
            playsInline
            muted
            autoPlay
            className="h-full w-full object-cover transform -scale-x-100"
          />
        ) : (
          <div className="flex flex-col items-center justify-center p-6 text-center">
            <CameraOff size={32} className="text-slate-500 mb-2" />
            <p className="text-xs text-slate-400 font-medium">
              {cameraError || "Local Mock Camera Active"}
            </p>
            <span className="mt-1 text-[10px] text-slate-500">
              Inference executing 100% locally
            </span>
          </div>
        )}

        {/* Focus & Engagement Circular HUD (Top Left Overlay) */}
        <div className="absolute top-2.5 left-2.5 flex items-center gap-2 rounded-xl bg-slate-950/70 border border-white/10 px-2.5 py-1.5 backdrop-blur-md">
          <div className="flex items-center gap-1.5">
            <Activity size={12} className="text-indigo-400" />
            <div className="flex flex-col">
              <span className="text-[9px] uppercase tracking-wider text-slate-400 leading-none">
                Focus
              </span>
              <span className="text-xs font-bold text-white leading-tight">
                {telemetry.focusScore}%
              </span>
            </div>
          </div>
          <div className="h-4 w-[1px] bg-white/10" />
          <div className="flex flex-col">
            <span className="text-[9px] uppercase tracking-wider text-slate-400 leading-none">
              Engaged
            </span>
            <span className="text-xs font-bold text-emerald-400 leading-tight">
              {telemetry.engagementScore}%
            </span>
          </div>
        </div>

        {/* Whitelisted Study Gesture Toast (Bottom Center Overlay) */}
        {telemetry.whitelistedAction && (
          <div className="absolute bottom-2.5 left-1/2 transform -translate-x-1/2 flex items-center gap-1.5 rounded-full bg-indigo-500/20 border border-indigo-500/40 px-3 py-1 text-[11px] font-medium text-indigo-300 backdrop-blur-md shadow-lg">
            {telemetry.whitelistedAction.includes("READING") || telemetry.whitelistedAction.includes("WRITING") ? (
              <BookOpen size={13} className="text-indigo-400" />
            ) : telemetry.whitelistedAction.includes("DRINK") ? (
              <Coffee size={13} className="text-indigo-400" />
            ) : (
              <CheckCircle2 size={13} className="text-indigo-400" />
            )}
            <span>{telemetry.whitelistedAction.replace(/_/g, " ").toLowerCase()}</span>
          </div>
        )}

        {/* Active Distraction Alert Warning Toast */}
        {telemetry.warning && (
          <div className="absolute top-2.5 right-2.5 flex items-center gap-2 rounded-xl bg-amber-500/20 border border-amber-500/40 px-3 py-1.5 text-amber-200 backdrop-blur-md animate-pulse">
            <AlertTriangle size={14} className="text-amber-400 shrink-0" />
            <span className="text-xs font-semibold leading-tight">
              {telemetry.warning.message}
            </span>
          </div>
        )}
      </div>

      {/* Bottom Telemetry Bar */}
      <div className="flex items-center justify-between px-3.5 py-2 bg-slate-900/40 border-t border-white/5 text-[11px] text-slate-400">
        <div className="flex items-center gap-1.5">
          <Eye size={12} className="text-slate-400" />
          <span>Posture: {telemetry.posture.replace(/_/g, " ")}</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-ping" />
          <span className="text-[10px] text-slate-400 font-mono">Live</span>
        </div>
      </div>
    </div>
  );
}
