"""
AI Guru Study Monitoring — Core CV Analysis Endpoints.
======================================================

Split from the monolithic monitoring.py router. Contains:
- Student baseline face enrollment (POST /enroll-face)
- Pre-flight anti-spoof liveness verification (POST /verify-liveness)
- Single frame / telemetry analysis (POST /analyze-frame)
- Monitoring engine diagnostics (GET /status)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_auth
from deeptutor.services.governor import get_resource_governor
from deeptutor.services.monitoring import (
    FaceLandmarks,
    FrameAnalysisResult,
    LivenessDetector,
    get_cv_pipeline,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitoring"])


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
    frames_landmarks: List[Dict[str, Any]] = Field(
        ..., description="Sequence of landmark frames from client"
    )
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
async def enroll_face(
    req: EnrollFaceRequest, _user: Any = Depends(require_auth)
) -> EnrollFaceResponse:
    """
    Enroll student baseline for local identity verification.

    Accepts either a pre-computed ``face_embedding`` or raw ``landmarks`` —
    when landmarks are given the embedding is derived server-side via the
    exact same geometric pipeline used during identity verification, so
    enrollment and verification vectors can never drift.
    """
    pipeline = get_cv_pipeline()
    embedding: Optional[List[float]] = req.face_embedding
    identity_mode = "geometric"

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

    pipeline.enroll_student_baseline(embedding, identity_mode=identity_mode)
    persisted = await _persist_baseline(pipeline, embedding, identity_mode)

    logger.info(
        "Enrolled student face baseline (dim=%d, mode=%s, persisted=%s)",
        len(embedding),
        identity_mode,
        persisted,
    )
    return EnrollFaceResponse(
        success=True,
        dimension=len(embedding),
        message="Student facial baseline enrolled successfully"
        + (" (persisted)" if persisted else " in local memory."),
    )


async def _persist_baseline(pipeline: Any, embedding: List[float], identity_mode: str) -> bool:
    """Best-effort encrypted persistence of the enrolled baseline."""
    try:
        from deeptutor.services.monitoring.identity_store import save_baseline
        from deeptutor.services.path_service import get_path_service

        db_path = str(get_path_service().user_dir / "chat_history.db")
        return await save_baseline(db_path, embedding, identity_mode)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Baseline persistence skipped: %s", exc)
        return False


@router.post("/verify-liveness", response_model=VerifyLivenessResponse)
async def verify_liveness(
    req: VerifyLivenessRequest, _user: Any = Depends(require_auth)
) -> VerifyLivenessResponse:
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
async def analyze_frame(
    req: AnalyzeFrameRequest, _user: Any = Depends(require_auth)
) -> Dict[str, Any]:
    """
    Analyze a single frame / telemetry payload and return comprehensive study monitoring metrics.

    DIAGNOSTIC ONLY: this runs on the process-global singleton pipeline, so
    calls MUTATE its presence FSM, distraction timers and liveness history —
    they are shared with (and can perturb) whatever the pre-flight endpoints
    last touched. Real sessions always use a per-session LocalCVPipeline.
    """
    pipeline = get_cv_pipeline()
    payload = req.model_dump()
    result: FrameAnalysisResult = pipeline.process_telemetry_payload(
        payload, current_time=req.timestamp
    )

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
            "whitelisted_action": result.distraction.whitelisted_action.value
            if result.distraction.whitelisted_action
            else None,
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
        }
        if result.dispatched_warning
        else None,
        "cloud_egress_bytes": result.cloud_egress_bytes,
    }
    return resp


@router.get("/status", response_model=MonitoringStatusResponse)
async def get_monitoring_status(_user: Any = Depends(require_auth)) -> MonitoringStatusResponse:
    """
    Return local monitoring engine diagnostics and real-time FPS metrics.
    """
    # Import here to avoid circular dependency at module level — the session
    # module owns the canonical _active_monitoring_sessions dict.
    from deeptutor.api.routers.monitoring_session import _active_monitoring_sessions

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
