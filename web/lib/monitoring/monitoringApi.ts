/**
 * Central URLs + fetch helpers for the monitoring + study-session API.
 * Replaces hardcoded `/api/v1/monitoring/*` and `/api/v1/study-session/*`
 * strings scattered across hooks and components.
 */

export const monitoringApi = {
  cameraStatus: "/api/v1/monitoring/camera/status",
  cameraProbe: "/api/v1/monitoring/camera/probe",
  enrollFromCamera: (force?: boolean) =>
    `/api/v1/monitoring/enroll-from-camera${force ? "?force=true" : ""}`,
  enrollFace: "/api/v1/monitoring/enroll-face",
  enrollFromPhoto: (force?: boolean) =>
    `/api/v1/monitoring/enroll-from-photo${force ? "?force=true" : ""}`,
  identityStatus: "/api/v1/monitoring/identity-status",
  verifyIdentity: "/api/v1/monitoring/verify-identity",
  clearBaseline: "/api/v1/monitoring/identity-baseline",
  verifyLiveness: "/api/v1/monitoring/verify-liveness",
  sessionWs: (sessionId: string, mode?: "browser") =>
    mode
      ? `/api/v1/monitoring/session/${encodeURIComponent(sessionId)}?mode=${mode}`
      : `/api/v1/monitoring/session/${encodeURIComponent(sessionId)}`,
  liveConsent: (sessionId: string) =>
    `/api/v1/monitoring/live/consent?session_id=${encodeURIComponent(sessionId)}`,
  liveFrame: (sessionId: string) =>
    `/api/v1/monitoring/live/frame?session_id=${encodeURIComponent(sessionId)}`,
  voiceIncoming: (sessionId: string) =>
    `/api/v1/monitoring/voice/incoming?session_id=${encodeURIComponent(sessionId)}`,
  voiceSignal: "/api/v1/monitoring/voice/signal",
  feed: (sessionId: string, retry?: number) =>
    `/api/v1/monitoring/feed/${encodeURIComponent(sessionId)}${retry ? `?retry=${retry}` : ""}`,
} as const;

export const studySessionApi = {
  create: "/api/v1/study-session/create",
  history: (studentId: string, limit = 5, offset = 0) =>
    `/api/v1/study-session/history/${encodeURIComponent(studentId)}?limit=${limit}&offset=${offset}`,
  lifecycle: (sessionId: string, action: "start" | "pause" | "resume" | "stop" | "abandon") =>
    `/api/v1/study-session/${encodeURIComponent(sessionId)}/${action}`,
  report: (sessionId: string) =>
    `/api/v1/study-session/${encodeURIComponent(sessionId)}/report`,
  retarget: (sessionId: string) =>
    `/api/v1/study-session/${encodeURIComponent(sessionId)}/target`,
} as const;

export const VISION_FPS_KEY = "aiguru.vision.fps";
export const FACE_ENROLLED_KEY = "aiguru.face.enrolled";
