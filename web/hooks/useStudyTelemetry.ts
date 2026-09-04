"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import type { VisionPipeline } from "@/lib/monitoring/visionPipeline";
import type { TelemetrySocket } from "@/lib/monitoring/telemetrySocket";
import { monitoringApi, VISION_FPS_KEY } from "@/lib/monitoring/monitoringApi";
import { useMonitorMode, type MonitorMode } from "./useMonitorMode";
import { useWarningFeed, type LiveWarning } from "./useWarningFeed";

export type { MonitorMode, LiveWarning };

/** Whitelisted-study-behavior chips (mirrors backend WhitelistedAction enum). */
export const WHITELIST_LABELS: Record<string, string> = {
  READING_DOWNWARDS: "📖 Reading Book",
  WRITING_NOTES: "✍️ Writing Notes",
  TURNING_PAGES: "📄 Turning Pages",
  DRINKING_WATER: "💧 Drinking Water",
  POSTURE_SHIFT: "🧘 Posture Shift",
};

interface UseStudyTelemetryOptions {
  sessionId: string | null;
  isActive: boolean;
  liveViewEnabled: boolean;
  onNotice?: (notice: { kind: "error" | "warn"; text: string } | null) => void;
}

export function useStudyTelemetry({
  sessionId,
  isActive,
  liveViewEnabled,
  onNotice,
}: UseStudyTelemetryOptions) {
  const [focusScore, setFocusScore] = useState<number | null>(null);
  const [engagementScore, setEngagementScore] = useState<number | null>(null);
  // Backend sends `engagement_trend`; kept as focusTrend for HUD compat.
  const [focusTrend, setFocusTrend] = useState<string>("STABLE");
  const [whitelistedAction, setWhitelistedAction] = useState<string | null>(null);
  const [presenceState, setPresenceState] = useState<string>("unknown");
  const [postureLabel, setPostureLabel] = useState<string>("—");
  const [wsConnected, setWsConnected] = useState(false);
  const [feedAttempt, setFeedAttempt] = useState(0);

  const { monitorMode, setMonitorMode } = useMonitorMode(isActive, sessionId);
  const {
    liveWarnings,
    pushWarning,
    reset: resetWarnings,
    setTelegramBadgeAt,
    telegramBadgeVisible,
  } = useWarningFeed();

  const pipelineRef = useRef<VisionPipeline | null>(null);
  const socketRef = useRef<TelemetrySocket | null>(null);
  const feedRetryRef = useRef(0);
  const streamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const liveViewRef = useRef(liveViewEnabled);
  liveViewRef.current = liveViewEnabled;

  // Shared telemetry message handler for both system and browser paths
  const applyRemote = useCallback(
    (msg: Record<string, unknown>) => {
      if (typeof msg.engagement_score === "number")
        setEngagementScore(Math.round(msg.engagement_score));
      if (typeof msg.focus_score === "number")
        setFocusScore(Math.round(msg.focus_score));
      if (typeof msg.engagement_trend === "string")
        setFocusTrend(String(msg.engagement_trend));
      if (typeof msg.presence === "string")
        setPresenceState(String(msg.presence));
      if (typeof msg.posture === "string") {
        setPostureLabel(String(msg.posture).replace(/_/g, " ").toLowerCase());
      }
      setWhitelistedAction(
        typeof msg.whitelisted_action === "string"
          ? String(msg.whitelisted_action)
          : null
      );

      pushWarning(
        msg.warning as
          | {
              warning_id?: string;
              category?: string;
              message?: string;
              severity?: string;
            }
          | undefined
      );
    },
    [pushWarning]
  );

  // 2a. System mode: backend webcam + MJPEG feed + WS telemetry
  useEffect(() => {
    if (!isActive || monitorMode !== "system" || !sessionId) return;
    let cancelled = false;
    feedRetryRef.current = 0;
    setFeedAttempt(0);

    (async () => {
      const { TelemetrySocket } = await import(
        "@/lib/monitoring/telemetrySocket"
      );
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
  }, [isActive, monitorMode, sessionId, applyRemote]);

  // 2b. Browser mode fallback: MediaPipe WASM + local webcam
  useEffect(() => {
    if (!isActive || monitorMode !== "browser") return;
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

        const { VisionPipeline } = await import(
          "@/lib/monitoring/visionPipeline"
        );
        let lastLiveUpload = 0;
        const pipeline = new VisionPipeline({
          video,
          sessionId: sessionId ?? undefined,
          targetFps: Number(
            window.localStorage.getItem(VISION_FPS_KEY) || 5
          ),
          onState: (s) => setWsConnected(s === "ready"),
          onTelemetry: (frame, remote) => {
            if (remote) {
              applyRemote(remote);
            }
            if (
              liveViewRef.current &&
              frame.jpeg_b64 &&
              Date.now() - lastLiveUpload > 1500 &&
              sessionId
            ) {
              lastLiveUpload = Date.now();
              void fetch(monitoringApi.liveFrame(sessionId), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ jpeg_b64: frame.jpeg_b64 }),
              }).catch(() => {});
            }
          },
        });
        pipelineRefLocal.current = pipeline;
        pipelineRef.current = pipeline;
        await pipeline.start();
      } catch (err) {
        console.warn("Monitoring unavailable:", err);
        setWsConnected(false);
        onNotice?.({
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
  }, [isActive, monitorMode, sessionId, applyRemote, onNotice]);

  const handleFeedError = useCallback(() => {
    if (feedRetryRef.current < 3) {
      feedRetryRef.current += 1;
      setFeedAttempt(feedRetryRef.current);
    } else {
      setMonitorMode("browser");
    }
  }, [setMonitorMode]);

  const resetTelemetry = useCallback(() => {
    setFocusScore(null);
    setEngagementScore(null);
    setFocusTrend("STABLE");
    setWhitelistedAction(null);
    setPresenceState("unknown");
    setPostureLabel("—");
    resetWarnings();
    setWsConnected(false);
    setMonitorMode(null);
    setFeedAttempt(0);
    setTelegramBadgeAt(null);
  }, [resetWarnings, setMonitorMode, setTelegramBadgeAt]);

  return {
    focusScore,
    engagementScore,
    focusTrend,
    /** Alias: backend trend is engagement-based. */
    engagementTrend: focusTrend,
    whitelistedAction,
    presenceState,
    postureLabel,
    liveWarnings,
    wsConnected,
    monitorMode,
    setMonitorMode,
    feedAttempt,
    handleFeedError,
    telegramBadgeVisible,
    videoRef,
    resetTelemetry,
  };
}
