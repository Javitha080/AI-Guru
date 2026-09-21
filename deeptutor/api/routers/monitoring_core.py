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

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
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
        ..., min_length=3, max_length=30, description="Sequence of landmark frames from client"
    )
    timestamps: Optional[List[float]] = Field(default=None, max_length=30, description="Sequence timestamps")


class VerifyLivenessResponse(BaseModel):
    is_live: bool
    confidence: float
    details: str
    timestamp: float = Field(default_factory=time.time)


class PhotoEnrollResponse(BaseModel):
    enrolled: bool
    already_enrolled: bool = False
    identity_mode: str = "unenrolled"
    dimension: int = 0
    persisted: bool = False
    brightness: float = 0.0
    pose: Optional[Dict[str, float]] = None
    reason: str = ""
    message: str = ""


class IdentityStatusResponse(BaseModel):
    enrolled: bool
    identity_mode: str = "unenrolled"
    dimension: int = 0
    sface_available: bool = False
    persisted: bool = False


class VerifyIdentityRequest(BaseModel):
    face_embedding: Optional[List[float]] = Field(
        default=None, description="Pre-computed vector in the SAME space as the baseline."
    )
    landmarks: Optional[Dict[str, Any]] = Field(default=None)
    jpeg_b64: Optional[str] = Field(default=None, description="Base64 JPEG to analyze server-side.")


class VerifyIdentityResponse(BaseModel):
    enrolled: bool
    match: Optional[bool] = None
    similarity: float = 0.0
    identity_mode: str = "unenrolled"
    threshold: float = 0.65
    reason: str = ""


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
        try:
            detection = pipeline.face_engine.extract_landmarks_from_telemetry(
                {"detected": True, "confidence": 0.95, "brightness": 0.5, "landmarks": req.landmarks}
            )
            embedding = detection.embedding
        except Exception as exc:  # noqa: BLE001 - malformed landmarks
            logger.debug("Face enroll landmark parse failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Could not read landmarks from this frame. Try again.",
            )

    if not embedding or len(embedding) < 16:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either face_embedding (>=16 dims) or landmarks to derive it.",
        )

    try:
        pipeline.enroll_student_baseline(embedding, identity_mode=identity_mode)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Face enroll failed: %s", exc)
        raise HTTPException(status_code=500, detail="Could not enroll face. Try again.")
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


# Photo-upload identity enrollment -------------------------------------------
# A student photo (upload or camera-preview snapshot) is analyzed server-side:
# face detection + frontal/brightness gates, then an SFace neural embedding
# when the model is present, geometric fallback otherwise. Only the embedding
# is ever stored (encrypted) — the photo bytes are discarded.

_PHOTO_MAX_BYTES = 5_000_000
_PHOTO_MIN_BYTES = 4_096
_PHOTO_MIN_DIM = 160
_PHOTO_MIN_BRIGHTNESS = 0.08


def _decode_upload(photo_bytes: bytes) -> Any:
    """Decode JPEG/PNG bytes to a BGR frame; raises 422/503 on bad input."""
    try:
        import cv2  # noqa: PLC0415 - guarded optional dependency
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Photo enrollment needs the server vision engine (opencv).",
        )
    if not photo_bytes or len(photo_bytes) < _PHOTO_MIN_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File is too small to be a photo.",
        )
    if len(photo_bytes) > _PHOTO_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Photo exceeds the 5 MB limit.",
        )
    try:
        import numpy as _np

        buf = _np.frombuffer(photo_bytes, dtype=_np.uint8)
        frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:  # noqa: BLE001
        frame = None
    if frame is None or frame.shape[0] < _PHOTO_MIN_DIM or frame.shape[1] < _PHOTO_MIN_DIM:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not read this image (need a clear photo, at least 160px).",
        )
    return frame


async def _analyze_upload_frame(frame: Any) -> Any:
    """Run the shared face processor over an uploaded frame (executor thread)."""
    from deeptutor.services.monitoring.python_face_processor import (  # noqa: PLC0415
        get_python_face_processor,
    )

    processor = get_python_face_processor()
    if not processor.available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Face analysis unavailable on the server right now.",
        )
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, processor.process_frame, frame)
    if not result.detected or result.landmarks is None or not result.raw_landmarks:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No face found — use a clear, front-facing photo with nothing covering the face.",
        )
    angles = result.head_angles_raw or (0.0, 0.0, 0.0)
    try:
        from deeptutor.services.monitoring.cv_pipeline import (  # noqa: PLC0415
            SFACE_FRONTAL_GATE_DEG,
        )
    except Exception:  # noqa: BLE001
        SFACE_FRONTAL_GATE_DEG = 25.0
    if abs(angles[0]) > SFACE_FRONTAL_GATE_DEG or abs(angles[1]) > SFACE_FRONTAL_GATE_DEG:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Face is turned away (yaw {angles[0]:.0f}, pitch {angles[1]:.0f}) — look straight at the camera.",
        )
    if float(result.brightness) < _PHOTO_MIN_BRIGHTNESS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Photo is too dark — retake it in better light.",
        )
    return result


async def _baseline_state() -> Dict[str, Any]:
    """In-memory baseline if present, else the persisted one (read-only)."""
    from deeptutor.services.monitoring.cv_pipeline import get_cv_pipeline  # noqa: PLC0415

    pipeline = get_cv_pipeline()
    embedding = pipeline.face_engine.get_enrolled_face()
    if embedding is not None:
        return {
            "embedding": list(embedding),
            "mode": pipeline.enrolled_identity_mode,
            "persisted": True,
        }
    try:
        from deeptutor.services.monitoring.identity_store import load_baseline  # noqa: PLC0415
        from deeptutor.services.path_service import get_path_service  # noqa: PLC0415

        db_path = str(get_path_service().user_dir / "chat_history.db")
        stored = await load_baseline(db_path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Baseline lookup skipped: %s", exc)
        stored = None
    if stored is None:
        return {"embedding": None, "mode": "unenrolled", "persisted": False}
    vec, mode = stored
    return {"embedding": list(vec), "mode": str(mode), "persisted": True}


@router.post("/enroll-from-photo", response_model=PhotoEnrollResponse)
async def enroll_from_photo(
    photo: UploadFile = File(...),
    force: bool = False,
    _user: Any = Depends(require_auth),
) -> PhotoEnrollResponse:
    """Enroll the student baseline from an uploaded photo.

    The photo is analyzed and discarded — only the embedding is stored
    (encrypted, same as camera enrollment). Without ``force=true`` this is a
    no-op when a baseline already exists, so a stray upload can never silently
    replace the enrolled student. A fresh upload still needs a live
    pre-flight match (``POST /verify-identity``) before it is trusted.
    """
    from deeptutor.services.monitoring.cv_pipeline import get_cv_pipeline  # noqa: PLC0415

    pipeline = get_cv_pipeline()
    if not force:
        existing = await _baseline_state()
        if existing["embedding"] is not None:
            return PhotoEnrollResponse(
                enrolled=False,
                already_enrolled=True,
                identity_mode=existing["mode"],
                dimension=len(existing["embedding"]),
                persisted=existing["persisted"],
                reason="identity_baseline_exists",
                message="A face is already enrolled. Use Replace to enroll a new photo.",
            )

    photo_bytes = await photo.read()
    frame = _decode_upload(photo_bytes)
    result = await _analyze_upload_frame(frame)

    identity_mode = "geometric"
    embedding: Optional[List[float]] = None
    if pipeline.sface_available and result.raw_landmarks:
        loop = asyncio.get_running_loop()
        try:
            embedding = await loop.run_in_executor(
                None, pipeline.sface_enroll_vector, frame, result.raw_landmarks
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("SFace photo embed failed, geometric fallback: %s", exc)
            embedding = None
        if embedding is not None:
            identity_mode = "sface"
    if embedding is None:
        try:
            embedding = pipeline.face_engine.generate_geometric_embedding(result.landmarks)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Geometric photo embed failed: %s", exc)
            raise HTTPException(status_code=500, detail="Could not read this photo. Try another.")

    try:
        pipeline.enroll_student_baseline(embedding, identity_mode=identity_mode)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Photo enroll failed: %s", exc)
        raise HTTPException(status_code=500, detail="Could not enroll this photo. Try again.")
    persisted = await _persist_baseline(pipeline, embedding, identity_mode)
    pose = result.pose
    logger.info(
        "Enrolled student baseline from photo (mode=%s, dim=%d, persisted=%s)",
        identity_mode,
        len(embedding),
        persisted,
    )
    return PhotoEnrollResponse(
        enrolled=True,
        identity_mode=identity_mode,
        dimension=len(embedding),
        persisted=persisted,
        brightness=round(float(result.brightness), 3),
        pose=(
            {"yaw": pose.yaw, "pitch": pose.pitch, "roll": pose.roll}
            if pose is not None
            else None
        ),
        message=(
            "Face enrolled from photo (neural recognition)."
            if identity_mode == "sface"
            else "Face enrolled from photo (basic mode — neural model inactive)."
        ),
    )


@router.get("/identity-status", response_model=IdentityStatusResponse)
async def identity_status(_user: Any = Depends(require_auth)) -> IdentityStatusResponse:
    """Enrollment state for the identity UI (read-only, never enrolls)."""
    from deeptutor.services.monitoring.cv_pipeline import get_cv_pipeline  # noqa: PLC0415

    pipeline = get_cv_pipeline()
    state = await _baseline_state()
    return IdentityStatusResponse(
        enrolled=state["embedding"] is not None,
        identity_mode=state["mode"],
        dimension=len(state["embedding"]) if state["embedding"] is not None else 0,
        sface_available=bool(pipeline.sface_available),
        persisted=state["persisted"],
    )


@router.post("/verify-identity", response_model=VerifyIdentityResponse)
async def verify_identity(
    req: VerifyIdentityRequest, _user: Any = Depends(require_auth)
) -> VerifyIdentityResponse:
    """One-shot identity check against the enrolled baseline (never enrolls).

    Send live landmarks, a same-space ``face_embedding``, or a ``jpeg_b64``
    snapshot. Cross-mode comparisons (neural vs geometric live in different
    spaces) are reported as not-judgeable instead of a false mismatch.
    """
    import base64 as _b64

    from deeptutor.services.monitoring.cv_pipeline import get_cv_pipeline  # noqa: PLC0415
    from deeptutor.services.monitoring.face_identity import (  # noqa: PLC0415
        SFACE_COSINE_THRESHOLD,
    )

    pipeline = get_cv_pipeline()
    state = await _baseline_state()
    if state["embedding"] is None:
        return VerifyIdentityResponse(enrolled=False, reason="no_baseline_enrolled")
    baseline = state["embedding"]
    baseline_mode = state["mode"]
    threshold = (
        SFACE_COSINE_THRESHOLD if baseline_mode == "sface" else pipeline.face_engine.match_threshold
    )

    embedding: Optional[List[float]] = None
    derived_mode = baseline_mode
    geo_landmarks = None
    if req.face_embedding and len(req.face_embedding) >= 16:
        try:
            embedding = [float(v) for v in req.face_embedding]
        except (TypeError, ValueError):
            embedding = None
    elif req.landmarks:
        try:
            detection = pipeline.face_engine.extract_landmarks_from_telemetry(
                {"detected": True, "confidence": 0.95, "brightness": 0.5, "landmarks": req.landmarks}
            )
            embedding = detection.embedding
            geo_landmarks = detection.landmarks
        except Exception as exc:  # noqa: BLE001
            logger.debug("Verify-identity landmark parse failed: %s", exc)
        derived_mode = "geometric"
    elif req.jpeg_b64:
        try:
            raw = _b64.b64decode(req.jpeg_b64, validate=True)
        except Exception:  # noqa: BLE001
            raw = b""
        if raw:
            try:
                frame = _decode_upload(raw)
                fres = await _analyze_upload_frame(frame)
            except HTTPException as exc:
                return VerifyIdentityResponse(
                    enrolled=True, identity_mode=baseline_mode, threshold=threshold,
                    reason=str(exc.detail),
                )
            geo_landmarks = fres.landmarks
            if pipeline.sface_available and fres.raw_landmarks:
                loop = asyncio.get_running_loop()
                try:
                    embedding = await loop.run_in_executor(
                        None, pipeline.sface_enroll_vector, frame, fres.raw_landmarks
                    )
                except Exception:  # noqa: BLE001
                    embedding = None
                if embedding is not None:
                    derived_mode = "sface"
            if embedding is None:
                try:
                    embedding = pipeline.face_engine.generate_geometric_embedding(fres.landmarks)
                except Exception:  # noqa: BLE001
                    embedding = None
                derived_mode = "geometric"
    if embedding is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide face_embedding (>=16 dims), landmarks, or jpeg_b64.",
        )

    if derived_mode != baseline_mode:
        if baseline_mode == "geometric" and geo_landmarks is not None:
            # Legacy baseline: judge with the geometric vector (same space).
            embedding = pipeline.face_engine.generate_geometric_embedding(geo_landmarks)
            derived_mode = "geometric"
        else:
            return VerifyIdentityResponse(
                enrolled=True, identity_mode=baseline_mode, threshold=threshold,
                reason="cross_mode_cannot_judge",
            )
    is_match, sim = pipeline.face_engine.verify_identity(
        embedding, baseline, threshold=threshold
    )
    return VerifyIdentityResponse(
        enrolled=True, match=is_match, similarity=sim,
        identity_mode=baseline_mode, threshold=threshold,
        reason="match" if is_match else "mismatch",
    )


@router.delete("/identity-baseline")
async def clear_identity_baseline(_user: Any = Depends(require_auth)) -> Dict[str, Any]:
    """Drop the enrolled baseline (memory + encrypted store). Active study
    sessions keep their in-memory copy until their socket reconnects."""
    from deeptutor.services.monitoring.cv_pipeline import get_cv_pipeline  # noqa: PLC0415

    pipeline = get_cv_pipeline()
    try:
        pipeline.clear_identity_baseline()
    except Exception as exc:  # noqa: BLE001
        logger.debug("In-memory baseline clear skipped: %s", exc)
    try:
        from deeptutor.services.monitoring.identity_store import clear_baseline  # noqa: PLC0415
        from deeptutor.services.path_service import get_path_service  # noqa: PLC0415

        await clear_baseline(str(get_path_service().user_dir / "chat_history.db"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Persisted baseline clear skipped: %s", exc)
    return {"cleared": True}


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
        try:
            parsed = pipeline.face_engine.extract_landmarks_from_telemetry(f)
        except Exception as exc:  # noqa: BLE001 - one corrupt frame skips
            logger.debug("Liveness frame parse skipped: %s", exc)
            continue
        if parsed.landmarks:
            landmarks_list.append(parsed.landmarks)

    try:
        is_live, conf, details = detector.verify_preflight_sequence(
            landmarks_list,
            timestamps=req.timestamps,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Liveness verification failed: %s", exc)
        raise HTTPException(status_code=500, detail="Could not verify liveness. Try again.")

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
    try:
        pipeline = get_cv_pipeline()
        payload = req.model_dump()
        result: FrameAnalysisResult = pipeline.process_telemetry_payload(
            payload, current_time=req.timestamp
        )
    except Exception as exc:  # noqa: BLE001 - CV must never 500 diagnostics
        logger.warning("Frame analysis failed: %s", exc)
        raise HTTPException(status_code=422, detail="Could not analyze this frame. Try again.")

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
