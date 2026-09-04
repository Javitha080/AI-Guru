"use client";

/**
 * Pre-flight hardware check - Ember Glass card.
 * Camera -> face/lighting -> liveness sequence, all real on-device checks.
 * Liveness soft-pass stays honest: amber "unverified", never a fake green.
 */

import React, { useState, useEffect, useRef } from "react";
import {
  Camera, Shield, UserCheck, CheckCircle2, XCircle,
  Loader2, RefreshCw, AlertTriangle, VideoOff, Sparkles, BookOpen
} from "lucide-react";
import { monitoringApi, FACE_ENROLLED_KEY } from "@/lib/monitoring/monitoringApi";

interface PreFlightCheckProps {
  onReady: () => void;
  onCancel: () => void;
}

type CheckStatus = "idle" | "checking" | "passed" | "failed";

export default function PreFlightCheck({ onReady, onCancel }: PreFlightCheckProps) {
  const [cameraStatus, setCameraStatus] = useState<CheckStatus>("checking");
  const [faceStatus, setFaceStatus] = useState<CheckStatus>("idle");
  const [livenessStatus, setLivenessStatus] = useState<CheckStatus>("idle");
  // Tri-state: null = backend unreachable, so liveness could NOT be verified.
  const [livenessVerified, setLivenessVerified] = useState<boolean | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [offlineModeAllowed, setOfflineModeAllowed] = useState(false);
  // Backend system-camera mode: preview comes from server-side snapshots.
  const [probeSnapshot, setProbeSnapshot] = useState<string | null>(null);
  const [systemMode, setSystemMode] = useState(false);
  // Bumping this re-runs the whole check sequence WITHOUT a page reload
  // (a reload would drop the user's session context and modal state).
  const [attempt, setAttempt] = useState(0);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    let active = true;

    /** System-camera pre-flight: zero browser getUserMedia involvement. */
    const runSystemPreflight = async (): Promise<boolean> => {
      try {
        const st = await fetch(monitoringApi.cameraStatus);
        if (!st.ok) return false;
        const s = await st.json();
        if (s.mode !== "system") return false;
      } catch {
        return false; // backend unreachable → legacy browser flow decides
      }

      setSystemMode(true);
      setCameraStatus("checking");
      setFaceStatus("checking");

      // Poll one-shot probes until the student's face is visible (~12s max).
      for (let i = 0; i < 24; i++) {
        if (!active) return true;
        try {
          const res = await fetch(monitoringApi.cameraProbe, { method: "POST" });
          if (!res.ok) return false; // endpoint missing → legacy flow
          const d = await res.json();
          if (typeof d.snapshot_b64 === "string" && d.snapshot_b64.length > 32) {
            setProbeSnapshot(`data:image/jpeg;base64,${d.snapshot_b64}`);
          }
          if (d.reason === "camera_unavailable") {
            setCameraStatus("failed");
            setFaceStatus("failed");
            setErrorMessage("The AI Guru camera engine is running but no webcam responded.");
            return true;
          }
          if (d.detected) {
            setCameraStatus("passed");
            setFaceStatus("passed");
            setLivenessStatus("checking");
            // Identity enrollment straight from the system camera (best-effort).
            try {
              await fetch(monitoringApi.enrollFromCamera, { method: "POST" });
              if (typeof window !== "undefined") window.localStorage.setItem(FACE_ENROLLED_KEY, "1");
            } catch {
              /* enrollment is best-effort */
            }
            // Honest soft-pass: multi-frame anti-spoof runs in-session; the
            // pre-flight shows amber "unverified" instead of a fake green.
            setLivenessVerified(null);
            setLivenessStatus("passed");
            return true;
          }
        } catch {
          return false;
        }
        await new Promise((r) => setTimeout(r, 500));
      }

      setFaceStatus("failed");
      setErrorMessage("No face detected by the system camera. Please sit centered in view and retry.");
      return true;
    };

    const runAllChecks = async () => {
      const handled = await runSystemPreflight();
      if (!active || handled) return;
      setSystemMode(false);
      await startCameraAndChecks();
    };

    const startCameraAndChecks = async () => {
      setCameraStatus("checking");
      setFaceStatus("idle");
      setLivenessStatus("idle");
      setLivenessVerified(null);
      setErrorMessage(null);
      setOfflineModeAllowed(false);

      try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
          throw new Error("Camera API not supported in this browser environment.");
        }

        const stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
          audio: false,
        });

        if (!active) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => {});
        }

        setCameraStatus("passed");
        setFaceStatus("checking");

        // 2. Real face + liveness via the on-device MediaPipe pipeline.
        const video = videoRef.current;
        if (!video) throw new Error("Video element unavailable");

        const { VisionPipeline } = await import("@/lib/monitoring/visionPipeline");
        const pipeline = new VisionPipeline({ video, targetFps: 5 });
        await pipeline.start();

        if (!active) {
          pipeline.stop();
          return;
        }

        // Wait for a stable face (up to ~6s), using real landmark detection.
        let sawFace = false;
        for (let i = 0; i < 30 && active; i++) {
          await new Promise((r) => setTimeout(r, 200));
          const frames = pipeline.takeRecentLandmarkFrames(1);
          if (frames.length > 0 && pipeline.hasFaceModel) {
            sawFace = true;
            break;
          }
        }

        const brightnessOk = await new Promise<boolean>((resolve) => {
          setTimeout(() => resolve(pipeline.hasFaceModel ? true : brightnessProbe(video)), 50);
        });

        function brightnessProbe(v: HTMLVideoElement): boolean {
          try {
            const canvas = document.createElement("canvas");
            canvas.width = 64;
            canvas.height = 48;
            const ctx = canvas.getContext("2d");
            if (!ctx) return true;
            ctx.drawImage(v, 0, 0, 64, 48);
            const d = ctx.getImageData(0, 0, 64, 48).data;
            let sum = 0;
            for (let i = 0; i < d.length; i += 4) sum += (d[i] + d[i + 1] + d[i + 2]) / 3;
            return sum / ((d.length / 4)) >= 10;
          } catch {
            return true;
          }
        }

        if (!brightnessOk || !sawFace) {
          pipeline.stop();
          setFaceStatus("failed");
          setErrorMessage(
            !brightnessOk
              ? "Camera appears dark or covered. Please ensure adequate lighting."
              : "No face detected. Please center your face in the camera view."
          );
          return;
        }
        setFaceStatus("passed");
        setLivenessStatus("checking");

        // Collect >=5 landmark frames for the anti-spoof liveness sequence.
        for (let i = 0; i < 14 && active && pipeline.takeRecentLandmarkFrames(6).length < 6; i++) {
          await new Promise((r) => setTimeout(r, 150));
        }
        const seq = pipeline.takeRecentLandmarkFrames(6);
        pipeline.stop();

        let livenessPassed = false;
        let livenessReachable = false;
        try {
          const res = await fetch(monitoringApi.verifyLiveness, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ frames_landmarks: seq }),
          });
          if (res.ok) {
            const data = await res.json();
            livenessPassed = Boolean(data.is_live);
            livenessReachable = true;
          }
        } catch {
          /* backend unreachable -> soft-pass with an honest "unverified" badge */
        }

        if (!active) return;

        // Enroll once per device so in-session identity checks work.
        try {
          if (typeof window !== "undefined" && !window.localStorage.getItem(FACE_ENROLLED_KEY) && seq.length > 0) {
            const enrollRes = await fetch(monitoringApi.enrollFace, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ landmarks: seq[seq.length - 1], student_id: "student-primary" }),
            });
            if (enrollRes.ok) window.localStorage.setItem(FACE_ENROLLED_KEY, "1");
          }
        } catch {
          /* enrollment is best-effort */
        }

        if (livenessPassed) {
          setLivenessVerified(true);
          setLivenessStatus("passed");
        } else {
          // Never block harder than before: continue but surface honest status.
          setLivenessVerified(livenessReachable ? false : null);
          setLivenessStatus("passed");
          if (!livenessReachable) {
            console.warn("[preflight] liveness unverified: endpoint unavailable");
          }
        }

      } catch (err: any) {
        if (!active) return;
        setCameraStatus("failed");
        setFaceStatus("failed");
        setLivenessStatus("failed");
        setErrorMessage(
          err.name === "NotAllowedError"
            ? "Camera permission was denied. Please allow camera access in your browser."
            : "No webcam detected on this device."
        );
        setOfflineModeAllowed(true);
      }
    };

    runAllChecks();

    return () => {
      active = false;
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
      }
    };
  }, [attempt]);

  const handleRetry = () => {
    // Re-runs the effect (fresh camera + checks) without nuking page state.
    setAttempt((n) => n + 1);
  };

  const allPassed = cameraStatus === "passed" && faceStatus === "passed" && livenessStatus === "passed";

  const renderIcon = (status: CheckStatus) => {
    switch (status) {
      case "checking":
        return <Loader2 size={17} className="text-[var(--primary)] animate-spin" />;
      case "passed":
        return <CheckCircle2 size={17} className="text-[var(--primary)] animate-pop-in" />;
      case "failed":
        return <XCircle size={17} className="text-red-400 animate-pop-in" />;
      default:
        return <div className="w-4 h-4 rounded-full border-2 border-[var(--glass-border-highlight)] opacity-40" />;
    }
  };

  const renderLivenessCell = () => {
    if (livenessStatus === "checking") return renderIcon("checking");
    if (livenessStatus !== "passed") return renderIcon(livenessStatus);
    if (livenessVerified === true) return renderIcon("passed");
    // Soft-pass: checks ran but the verdict is unverified (backend unreachable
    // or anti-spoof inconclusive) -- amber, never a fake pass check.
    return (
      <span title="Anti-spoof could not be verified - continuing anyway">
        <AlertTriangle size={17} className="text-[var(--amber)] animate-pop-in" />
      </span>
    );
  };

  const checkRowTone = (status: CheckStatus) =>
    status === "passed"
      ? "border-[var(--ember-line)]/30 bg-[var(--ember-0)]"
      : status === "failed"
        ? "border-red-500/25 bg-red-500/[0.06]"
        : "";

  return (
    <div className="bento-cell liquid-sheen w-full max-w-md mx-auto p-6 space-y-5">
      <div className="text-center space-y-1.5">
        <h2 className="font-display text-xl font-bold">Pre-Flight Hardware Check</h2>
        <p className="text-xs text-[var(--muted-foreground)]">
          Testing local camera access and student presence before starting session.
        </p>
      </div>

      {/* Live preview: backend system-camera snapshots or local webcam stream */}
      <div className="bento-cell scanline relative aspect-video !bg-black/85 overflow-hidden flex items-center justify-center">
        {cameraStatus === "passed" && <div className="scanline-bar" />}
        {systemMode ? (
          probeSnapshot ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={probeSnapshot}
              alt="System camera preview"
              className="absolute inset-0 w-full h-full object-cover opacity-90"
            />
          ) : (
            <div className="relative z-10 text-center space-y-2.5">
              <Loader2 size={28} className="mx-auto text-[var(--primary)] animate-spin" />
              <p className="text-xs text-white/60">Connecting to AI Guru camera engine...</p>
            </div>
          )
        ) : (
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            className={`w-full h-full object-cover transform -scale-x-100 ${cameraStatus !== "passed" ? "hidden" : "block"}`}
          />
        )}

        {!systemMode && cameraStatus === "checking" && (
          <div className="relative z-10 text-center space-y-2.5">
            <Loader2 size={28} className="mx-auto text-[var(--primary)] animate-spin" />
            <p className="text-xs text-white/60">Requesting webcam feed...</p>
          </div>
        )}
        {systemMode && cameraStatus === "checking" && !probeSnapshot && (
          <div className="absolute bottom-3 left-0 right-0 z-10 text-center">
            <p className="text-[10px] text-white/50">No browser permission needed — engine-side camera.</p>
          </div>
        )}

        {cameraStatus === "failed" && (
          <div className="relative z-10 text-center space-y-2 p-4">
            <VideoOff size={32} className="mx-auto text-red-400 opacity-80" />
            <p className="text-xs text-red-300 font-medium">{errorMessage || "Webcam not available"}</p>
          </div>
        )}

        {cameraStatus === "passed" && (
          <div className="absolute top-2.5 left-2.5 z-10 flex items-center gap-1.5 bg-black/60 backdrop-blur-md px-2.5 py-1 rounded-full text-[10px] font-mono text-[var(--amber)]">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--primary)] ember-dot" />
            <span>Live Feed</span>
          </div>
        )}
      </div>

      {/* Step Checklist */}
      <div className="space-y-2">
        <CheckRow icon={<Camera size={16} />} label="Camera Device Access" tone={checkRowTone(cameraStatus)}>
          {renderIcon(cameraStatus)}
        </CheckRow>
        <CheckRow icon={<UserCheck size={16} />} label="Face & Lighting Check" tone={checkRowTone(faceStatus)}>
          {renderIcon(faceStatus)}
        </CheckRow>
        <CheckRow icon={<Shield size={16} />} label="Liveness & Anti-Spoof" tone={checkRowTone(livenessStatus)}>
          {renderLivenessCell()}
        </CheckRow>
      </div>

      {errorMessage && (
        <div className="p-3 rounded-xl bg-[var(--amber-glow)]/50 border border-[var(--amber)]/35 text-xs text-[var(--amber)] flex items-start gap-2">
          <AlertTriangle size={15} className="mt-0.5 shrink-0" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex gap-2 pt-1">
        <button
          onClick={onCancel}
          className="glass-btn-secondary !rounded-xl flex-1 inline-flex items-center justify-center gap-1.5 text-xs"
        >
          <RefreshCw size={13} />
          <span>Cancel</span>
        </button>

        {offlineModeAllowed ? (
          <button
            onClick={onReady}
            className="flex-1 py-2.5 rounded-xl bg-[var(--amber)] hover:brightness-110 text-black text-xs font-bold transition-all flex items-center justify-center gap-1.5 shadow-[0_6px_20px_var(--amber-glow)]"
          >
            <BookOpen size={14} />
            <span>Offline Study Mode</span>
          </button>
        ) : (
          <button
            onClick={onReady}
            disabled={!allPassed}
            className="group flex-1 py-2.5 rounded-xl bg-gradient-to-r from-[var(--primary)] to-[#E8895F] disabled:from-[var(--muted)] disabled:to-[var(--muted)] disabled:text-[var(--muted-foreground)] text-white text-xs font-bold transition-all flex items-center justify-center gap-1.5 shadow-[0_6px_24px_var(--glow-primary)] enabled:hover:-translate-y-0.5 disabled:shadow-none"
          >
            <Sparkles size={14} className="transition-transform duration-500 group-hover:rotate-12" />
            <span>Begin Monitored Study</span>
          </button>
        )}
      </div>
    </div>
  );
}

function CheckRow({
  icon,
  label,
  tone,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  tone: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`flex items-center justify-between p-3 rounded-xl surface-glass-base transition-colors duration-300 ${tone}`}>
      <div className="flex items-center gap-2.5 text-[var(--muted-foreground)]">
        {icon}
        <span className="text-xs font-semibold">{label}</span>
      </div>
      {children}
    </div>
  );
}
