"""
AI Guru Study Monitoring API Router.
====================================

Provides endpoints for:
- Student baseline face enrollment (`POST /api/v1/monitoring/enroll-face`)
- Pre-flight anti-spoof liveness verification (`POST /api/v1/monitoring/verify-liveness`)
- Single frame / telemetry analysis (`POST /api/v1/monitoring/analyze-frame`)
- Real-time bidirectional WebSocket telemetry streaming (`WS /api/v1/monitoring/session/{session_id}`)
- Monitoring engine diagnostics and FPS telemetry (`GET /api/v1/monitoring/status`)
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import time
from typing import Any, Deque, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_auth
from deeptutor.services.governor import get_resource_governor
from deeptutor.services.monitoring import (
    FaceLandmarks,
    FrameAnalysisResult,
    LivenessDetector,
    get_cv_pipeline,
)
from deeptutor.services.monitoring.dispatch import handle_warning

logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitoring"])

# Active session tracking for WebSocket connections
_active_monitoring_sessions: Dict[str, WebSocket] = {}
# Per-session rolling window of recent JPEG frames (base64) for vault evidence.
_frame_rings: Dict[str, Deque[str]] = {}
_RING_SIZE = 30

# --- Live supervision (parent-controlled snapshot polling) -------------------
# The STUDENT opts in per session via /live/consent; the PARENT polls
# /parent/live/snapshot through the tunnel or LAN. Frames live only in this
# process's memory, are overwritten each upload, and are purged when the
# monitoring socket closes — nothing is ever written to disk.
_live_consent: set[str] = set()
_live_frames: Dict[str, tuple[str, float]] = {}
_LIVE_FRAME_TTL = 60.0


class LiveConsentRequest(BaseModel):
    enabled: bool


class LiveFrameRequest(BaseModel):
    jpeg_b64: str = Field(..., min_length=32)


def _purge_stale_frames() -> None:
    now = time.time()
    stale = [sid for sid, (_, ts) in _live_frames.items() if now - ts > _LIVE_FRAME_TTL]
    for sid in stale:
        _live_frames.pop(sid, None)


def _purge_session_state(session_id: str) -> None:
    """Called when a monitoring WS disconnects."""
    _live_consent.discard(session_id)
    _live_frames.pop(session_id, None)

_FRAME_KEYS = ("jpeg_b64", "jpeg", "frame_b64", "frame", "image_b64", "image")


def _extract_frame(payload: Dict[str, Any]) -> Optional[str]:
    for key in _FRAME_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and len(value) > 32:
            return value
    return None


_STRICTNESS_PROFILES = {
    # strictness -> (per-category cooldown s, min confidence)
    "gentle": (90.0, 0.85),
    "balanced": (60.0, 0.80),
    "strict": (30.0, 0.75),
}


def _apply_supervision_strictness(pipeline: Any) -> None:
    """Map persisted wizard strictness onto the warning gates for this session."""
    try:
        asyncio.get_running_loop().create_task(_apply_async(pipeline))
    except RuntimeError:
        pass


async def _apply_async(pipeline: Any) -> None:
    try:
        import json as _json

        import aiosqlite

        from deeptutor.services.path_service import get_path_service

        db = get_path_service().user_dir / "chat_history.db"
        async with aiosqlite.connect(db) as conn:
            from deeptutor.services.remote.kv_settings import ensure_kv_settings

            await ensure_kv_settings(conn)
            cur = await conn.execute("SELECT value FROM settings WHERE key = 'supervision_rules_default'")
            row = await cur.fetchone()
        if not row or not row[0]:
            return
        rules = _json.loads(row[0])
        cooldown, conf = _STRICTNESS_PROFILES.get(rules.get("alert_strictness", "balanced"), (60.0, 0.80))
        wm = getattr(pipeline, "warning_manager", None)
        if wm is not None:
            wm.cooldown_seconds = float(cooldown)
            wm.min_confidence = float(conf)
            logger.info("Supervision strictness applied: %s", rules.get("alert_strictness"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Strictness application skipped: %s", exc)


# --- Request & Response Models ---

class EnrollFaceRequest(BaseModel):
    student_id: Optional[str] = Field(default=None, description="Optional student identifier")
    face_embedding: Optional[List[float]] = Field(
        default=None,
        description="Pre-computed facial feature vector (>=16 dims). Omit when sending landmarks.",
    )
    landmarks: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "MediaPipe landmark groups (left_eye/right_eye/mouth/all_points + "
            "nose_tip/chin/forehead/cheeks). The embedding is derived server-side "
            "with the SAME geometric math used at verify time."
        ),
    )
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class EnrollFaceResponse(BaseModel):
    success: bool
    dimension: int
    message: str
    enrolled_at: float = Field(default_factory=time.time)


class VerifyLivenessRequest(BaseModel):
    frames_landmarks: List[Dict[str, Any]] = Field(..., description="Sequence of landmark frames from client")
    timestamps: Optional[List[float]] = Field(default=None, description="Sequence timestamps")


class VerifyLivenessResponse(BaseModel):
    is_live: bool
    confidence: float
    details: str
    timestamp: float = Field(default_factory=time.time)


class AnalyzeFrameRequest(BaseModel):
    detected: bool = Field(default=True)
    confidence: float = Field(default=0.95)
    brightness: float = Field(default=128.0)
    texture_laplacian_var: Optional[float] = Field(default=None)
    landmarks: Optional[Dict[str, Any]] = Field(default=None)
    embedding: Optional[List[float]] = Field(default=None)
    pose: Optional[Dict[str, Any]] = Field(default=None)
    gaze: Optional[Dict[str, Any]] = Field(default=None)
    phone_detected: bool = Field(default=False)
    hand_to_mouth_gesture: bool = Field(default=False)
    page_turn_gesture: bool = Field(default=False)
    writing_gesture: bool = Field(default=False)
    timestamp: Optional[float] = Field(default=None)


class MonitoringStatusResponse(BaseModel):
    status: str
    target_fps: int
    actual_fps: float
    system_cpu_percent: float
    system_ram_percent: float
    is_resource_overloaded: bool
    active_sessions_count: int
    zero_cloud_egress: bool = True


# --- Endpoints ---

@router.post("/enroll-face", response_model=EnrollFaceResponse)
async def enroll_face(req: EnrollFaceRequest) -> EnrollFaceResponse:
    """
    Enroll student baseline for local identity verification.

    Accepts either a pre-computed ``face_embedding`` or raw ``landmarks`` —
    when landmarks are given the embedding is derived server-side via the
    exact same geometric pipeline used during identity verification, so
    enrollment and verification vectors can never drift.
    """
    pipeline = get_cv_pipeline()
    embedding: Optional[List[float]] = req.face_embedding

    if not embedding and req.landmarks:
        detection = pipeline.face_engine.extract_landmarks_from_telemetry(
            {"detected": True, "confidence": 0.95, "brightness": 0.5, "landmarks": req.landmarks}
        )
        embedding = detection.embedding

    if not embedding or len(embedding) < 16:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either face_embedding (>=16 dims) or landmarks to derive it.",
        )

    pipeline.enroll_student_baseline(embedding)

    logger.info("Enrolled student face baseline (dim=%d) locally", len(embedding))
    return EnrollFaceResponse(
        success=True,
        dimension=len(embedding),
        message="Student facial baseline enrolled successfully in local memory.",
    )


@router.post("/verify-liveness", response_model=VerifyLivenessResponse)
async def verify_liveness(req: VerifyLivenessRequest) -> VerifyLivenessResponse:
    """
    Evaluate multi-frame landmark sequence for pre-flight anti-spoof liveness check.
    """
    if not req.frames_landmarks or len(req.frames_landmarks) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least 3 consecutive frames are required for liveness verification.",
        )

    pipeline = get_cv_pipeline()
    detector = LivenessDetector()

    landmarks_list: List[FaceLandmarks] = []
    for f in req.frames_landmarks:
        parsed = pipeline.face_engine.extract_landmarks_from_telemetry(f)
        if parsed.landmarks:
            landmarks_list.append(parsed.landmarks)

    is_live, conf, details = detector.verify_preflight_sequence(
        landmarks_list,
        timestamps=req.timestamps,
    )

    return VerifyLivenessResponse(
        is_live=is_live,
        confidence=conf,
        details=details,
    )


@router.post("/analyze-frame")
async def analyze_frame(req: AnalyzeFrameRequest) -> Dict[str, Any]:
    """
    Analyze a single frame / telemetry payload and return comprehensive study monitoring metrics.
    """
    pipeline = get_cv_pipeline()
    payload = req.model_dump()
    result: FrameAnalysisResult = pipeline.process_telemetry_payload(payload, current_time=req.timestamp)

    # Format structured response
    resp = {
        "timestamp": result.timestamp,
        "fps": result.fps,
        "face_detected": result.face_detected,
        "presence": {
            "state": result.presence.state.value,
            "state_duration_seconds": result.presence.state_duration_seconds,
            "unobserved_duration_seconds": result.presence.unobserved_duration_seconds,
            "is_present": result.presence.is_present,
            "state_changed": result.presence.state_changed,
        },
        "pose": {
            "yaw": result.pose.yaw,
            "pitch": result.pose.pitch,
            "roll": result.pose.roll,
            "posture": result.pose.posture.value,
            "is_facing_screen": result.pose.is_facing_screen,
            "is_reading_writing_pose": result.pose.is_reading_writing_pose,
        },
        "gaze": {
            "gaze_x": result.gaze.gaze_x,
            "gaze_y": result.gaze.gaze_y,
            "is_focused": result.gaze.is_focused,
            "confidence": result.gaze.confidence,
        },
        "liveness": {
            "is_live": result.liveness.is_live,
            "confidence": result.liveness.confidence,
            "blink_detected": result.liveness.blink_detected,
            "ear": result.liveness.ear,
            "reason": result.liveness.reason,
        },
        "engagement": {
            "score": result.engagement.score,
            "instantaneous_score": result.engagement.instantaneous_score,
            "trend": result.engagement.trend,
        },
        "distraction": {
            "is_distracted": result.distraction.is_distracted,
            "distraction_type": result.distraction.distraction_type.value,
            "focus_score": result.distraction.focus_score,
            "confidence": result.distraction.confidence,
            "duration_seconds": result.distraction.duration_seconds,
            "whitelisted_action": result.distraction.whitelisted_action.value if result.distraction.whitelisted_action else None,
            "reason": result.distraction.reason,
        },
        "identity": {
            "matched": result.identity_matched,
            "similarity": result.identity_similarity,
        },
        "warning": {
            "warning_id": result.dispatched_warning.warning_id,
            "category": result.dispatched_warning.category,
            "message": result.dispatched_warning.message,
            "severity": result.dispatched_warning.severity,
        } if result.dispatched_warning else None,
        "cloud_egress_bytes": result.cloud_egress_bytes,
    }
    return resp


@router.get("/status", response_model=MonitoringStatusResponse)
async def get_monitoring_status() -> MonitoringStatusResponse:
    """
    Return local monitoring engine diagnostics and real-time FPS metrics.
    """
    pipeline = get_cv_pipeline()
    governor = get_resource_governor()
    metrics = governor.get_metrics()

    return MonitoringStatusResponse(
        status="active",
        target_fps=pipeline.get_current_target_fps(),
        actual_fps=round(pipeline._actual_fps, 1),
        system_cpu_percent=metrics["cpu_percent"],
        system_ram_percent=metrics["ram_percent"],
        is_resource_overloaded=metrics["is_overloaded"],
        active_sessions_count=len(_active_monitoring_sessions),
        zero_cloud_egress=True,
    )


@router.websocket("/session/{session_id}")
async def monitoring_session_websocket(websocket: WebSocket, session_id: str) -> None:
    """
    Bidirectional WebSocket for live telemetry streaming, alerts, and state synchronization.
    """
    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth

    user_token = await ws_require_auth(websocket)
    if user_token is ws_auth_failed:
        return  # socket already rejected/closed by the auth helper

    await websocket.accept()
    _active_monitoring_sessions[session_id] = websocket
    pipeline = get_cv_pipeline()
    pipeline.reset_session()
    _apply_supervision_strictness(pipeline)

    logger.info("Monitoring WebSocket connected for session: %s", session_id)

    try:
        # Initial greeting with target FPS
        await websocket.send_json({
            "type": "session_init",
            "session_id": session_id,
            "target_fps": pipeline.get_current_target_fps(),
            "zero_cloud_egress": True,
            "message": "AI Guru Local Study Monitoring Stream Active",
        })

        while True:
            # Receive telemetry payload from client
            raw_text = await websocket.receive_text()
            try:
                msg = json.loads(raw_text)
            except Exception:
                continue

            msg_type = msg.get("type", "telemetry")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "timestamp": time.time()})
                continue

            payload = msg.get("data", msg)
            frame_b64 = _extract_frame(payload)
            if frame_b64 is not None:
                ring = _frame_rings.setdefault(session_id, collections.deque(maxlen=_RING_SIZE))
                ring.append(frame_b64)

            analysis = pipeline.process_telemetry_payload(payload)

            # Send back real-time metrics
            response_data = {
                "type": "telemetry_update",
                "session_id": session_id,
                "timestamp": analysis.timestamp,
                "presence": analysis.presence.state.value,
                "focus_score": analysis.distraction.focus_score,
                "engagement_score": analysis.engagement.score,
                "posture": analysis.pose.posture.value,
                "is_distracted": analysis.distraction.is_distracted,
                "whitelisted_action": analysis.distraction.whitelisted_action.value if analysis.distraction.whitelisted_action else None,
                "fps": analysis.fps,
            }

            if analysis.dispatched_warning:
                response_data["warning"] = {
                    "warning_id": analysis.dispatched_warning.warning_id,
                    "category": analysis.dispatched_warning.category,
                    "message": analysis.dispatched_warning.message,
                    "severity": analysis.dispatched_warning.severity,
                }
                warning_dict = {
                    **response_data["warning"],
                    "confidence": analysis.distraction.confidence,
                    "duration_seconds": analysis.distraction.duration_seconds,
                }
                asyncio.get_running_loop().create_task(
                    handle_warning(
                        session_id=session_id,
                        warning=warning_dict,
                        current_frame_b64=frame_b64,
                        ring_frames_b64=list(_frame_rings.get(session_id, ())),
                    )
                )

            await websocket.send_json(response_data)

    except WebSocketDisconnect:
        logger.info("Monitoring WebSocket disconnected for session: %s", session_id)
    except Exception as e:
        logger.warning("Monitoring WebSocket error for session %s: %s", session_id, e)
    finally:
        _active_monitoring_sessions.pop(session_id, None)
        _frame_rings.pop(session_id, None)
        _purge_session_state(session_id)


# --- Live supervision endpoints ----------------------------------------------


@router.post("/live/consent")
async def set_live_consent(
    req: LiveConsentRequest,
    session_id: str,
    _user: Any = Depends(require_auth),
) -> Dict[str, Any]:
    """Student-side opt-in/out for the current session's live view."""
    if req.enabled:
        if session_id not in _active_monitoring_sessions:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No active monitoring session")
        _live_consent.add(session_id)
    else:
        _live_consent.discard(session_id)
        _live_frames.pop(session_id, None)
    return {"session_id": session_id, "enabled": session_id in _live_consent}


@router.post("/live/frame")
async def upload_live_frame(
    req: LiveFrameRequest,
    session_id: str,
    _user: Any = Depends(require_auth),
) -> Dict[str, Any]:
    """Student client uploads its latest frame (~1/s) while consent is on."""
    if session_id not in _live_consent:
        return {"accepted": False, "reason": "consent_off"}
    if session_id not in _active_monitoring_sessions:
        return {"accepted": False, "reason": "no_active_session"}
    _purge_stale_frames()
    _live_frames[session_id] = (req.jpeg_b64, time.time())
    return {"accepted": True}


@router.get("/events/{session_id}")
async def get_session_monitoring_events(
    session_id: str,
    limit: int = 100,
    _user: Any = Depends(require_auth),
) -> Dict[str, Any]:
    """
    Student-safe own-summary of monitoring events for a session.
    Returns sanitized metadata only — never raw frames or images.
    Gated by the standard auth dependency (no-op when auth is disabled).
    """
    from deeptutor.services.study.telemetry_logger import TelemetryLogger

    try:
        events = await TelemetryLogger().get_session_events(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Event fetch failed for %s: %s", session_id, exc)
        events = []

    sanitized = [
        {
            "id": e.get("id"),
            "event_type": e.get("event_type"),
            "severity": e.get("severity"),
            "confidence": e.get("confidence"),
            "duration_seconds": e.get("duration_seconds"),
            "timestamp": e.get("timestamp"),
            "message": ((e.get("metadata") or {}).get("message") if isinstance(e.get("metadata"), dict) else None),
        }
        for e in (events or [])
    ]
    return {"session_id": session_id, "items": sanitized[: max(0, min(limit, 500))], "total": len(sanitized)}
