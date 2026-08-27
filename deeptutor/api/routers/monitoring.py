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
from fastapi.responses import StreamingResponse
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
from deeptutor.services.monitoring.system_monitor import (
    apply_supervision_strictness,
    get_system_monitor,
    load_camera_config,
    save_camera_config,
    start_system_monitor,
    stop_system_monitor,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitoring"])

# Active session tracking for WebSocket connections
_active_monitoring_sessions: Dict[str, WebSocket] = {}
# Per-session rolling window of recent JPEG frames (base64) for vault evidence.
_frame_rings: Dict[str, Deque[str]] = {}
_RING_SIZE = 30
# Client-frame timestamp acceptance window (seconds). Within it, the client's
# own observation clock drives the presence/distraction hysteresis; outside
# it the frame falls back to server receive time.
_FRAME_TIMESTAMP_MAX_LAG = 300.0
_FRAME_TIMESTAMP_MAX_AHEAD = 5.0

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


class CameraConfigRequest(BaseModel):
    enabled: Optional[bool] = Field(default=None)
    camera_index: Optional[int] = Field(default=None, ge=0, le=8)
    target_fps: Optional[int] = Field(default=None, ge=1, le=30)


# --- Endpoints ---

@router.post("/enroll-face", response_model=EnrollFaceResponse)
async def enroll_face(req: EnrollFaceRequest, _user: Any = Depends(require_auth)) -> EnrollFaceResponse:
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
async def verify_liveness(req: VerifyLivenessRequest, _user: Any = Depends(require_auth)) -> VerifyLivenessResponse:
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
async def analyze_frame(req: AnalyzeFrameRequest, _user: Any = Depends(require_auth)) -> Dict[str, Any]:
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
async def get_monitoring_status(_user: Any = Depends(require_auth)) -> MonitoringStatusResponse:
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


# --- System-level camera engine endpoints ------------------------------------


async def _probe_camera_frame(max_wait: float = 2.5) -> Optional[Dict[str, Any]]:
    """Grab one frame + inference result, preferring an active session monitor.

    Used by pre-flight checks and enrollment before any monitoring WS exists.
    Falls back to a short-lived transient capture (auto-released).
    """
    from deeptutor.services.monitoring.system_monitor import active_system_monitors

    for monitor in active_system_monitors().values():
        frame = monitor.camera.get_latest_frame()
        if frame is not None:
            result = await asyncio.get_running_loop().run_in_executor(
                None, monitor.processor.process_frame, frame
            )
            return {"frame": frame, "result": result}

    from deeptutor.services.monitoring.python_face_processor import get_python_face_processor
    from deeptutor.services.monitoring.system_camera import (
        SystemCameraManager,
        release_system_camera,
    )

    processor = get_python_face_processor()
    if not processor.available:
        return None

    cfg = await load_camera_config()
    camera = SystemCameraManager(camera_index=int(cfg.get("camera_index", 0)))
    try:
        if not camera.start():
            return None
        deadline = time.time() + max_wait
        frame = None
        while time.time() < deadline:
            frame = camera.get_latest_frame()
            if frame is not None:
                break
            await asyncio.sleep(0.1)
        if frame is None:
            return None
        result = await asyncio.get_running_loop().run_in_executor(
            None, processor.process_frame, frame
        )
        return {"frame": frame, "result": result}
    finally:
        # Transient grabber: always release the physical device.
        camera.stop()
        release_system_camera(int(cfg.get("camera_index", 0)))


def _snapshot_payload_b64(frame: Any) -> Optional[str]:
    import base64

    try:
        import cv2

        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        return base64.b64encode(buf.tobytes()).decode("ascii") if ok else None
    except Exception:  # noqa: BLE001
        return None


@router.get("/camera/status")
async def get_camera_status(_user: Any = Depends(require_auth)) -> Dict[str, Any]:
    """Capability probe driving the study room's system-camera vs browser choice."""
    from deeptutor.services.monitoring.python_face_processor import get_python_face_processor
    from deeptutor.services.monitoring.system_monitor import active_system_monitors

    cfg = await load_camera_config()
    processor = get_python_face_processor()
    available = processor.available
    enabled = bool(cfg.get("enabled", True))
    return {
        "available": available,
        "model_available": available,
        "enabled": enabled,
        "mode": "system" if (available and enabled) else "browser",
        "camera_index": int(cfg.get("camera_index", 0)),
        "target_fps": int(cfg.get("target_fps", 10)),
        "active_sessions": sorted(active_system_monitors().keys()),
    }


@router.post("/camera/config")
async def set_camera_config(req: CameraConfigRequest, _user: Any = Depends(require_auth)) -> Dict[str, Any]:
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    saved = await save_camera_config(updates)
    return {"saved": True, "config": saved}


@router.get("/snapshot/{session_id}")
async def get_camera_snapshot(session_id: str, _user: Any = Depends(require_auth)) -> Any:
    """Latest raw camera JPEG for one session (parent live view / diagnostics)."""
    from fastapi import Response

    monitor = get_system_monitor(session_id)
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active system monitor")
    jpeg = monitor.get_snapshot_jpeg()
    if jpeg is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Camera warming up")
    return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


_MJPEG_BOUNDARY = "aiguruframe"
_FEED_MAX_FPS = 12.0
_FEED_IDLE_LIMIT = 300  # ~25s without frames before the stream closes


@router.get("/feed/{session_id}")
async def monitoring_feed(session_id: str, _user: Any = Depends(require_auth)) -> StreamingResponse:
    """Live MJPEG feed of the system camera with face-mesh overlay.

    Consumed directly by an ``<img>`` element — auth rides the session cookie,
    so the browser never touches getUserMedia or asks for camera permission.
    """
    monitor = get_system_monitor(session_id)
    if monitor is None:
        # The monitor registers a beat after the WS handshake starts it; give
        # the engine a short window instead of instantly 404ing the <img>.
        deadline = time.time() + 4.0
        while monitor is None and time.time() < deadline:
            await asyncio.sleep(0.15)
            monitor = get_system_monitor(session_id)
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active system camera feed")

    boundary = _MJPEG_BOUNDARY
    header = f"--{boundary}\r\nContent-Type: image/jpeg\r\nContent-Length: ".encode("ascii")

    async def frame_stream():
        idle = 0
        interval = 1.0 / _FEED_MAX_FPS
        try:
            while True:
                jpeg = monitor.get_annotated_jpeg()
                if jpeg is None:
                    idle += 1
                    if idle > _FEED_IDLE_LIMIT:
                        break
                    await asyncio.sleep(0.08)
                    continue
                idle = 0
                yield b"".join([header, str(len(jpeg)).encode(), b"\r\n\r\n", jpeg, b"\r\n"])
                await asyncio.sleep(interval)
        except (asyncio.CancelledError, GeneratorExit):
            raise

    return StreamingResponse(
        frame_stream(),
        media_type=f"multipart/x-mixed-replace; boundary={boundary}",
        headers={"Cache-Control": "no-store, no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/enroll-from-camera")
async def enroll_from_camera(_user: Any = Depends(require_auth)) -> Dict[str, Any]:
    """Enroll the identity baseline straight from the system camera.

    Lets the pre-flight check register the student without ANY browser camera
    involvement: one server-side grab → geometric embedding → enroll.
    """
    pipeline = get_cv_pipeline()
    probe = await _probe_camera_frame()
    if probe is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="System camera unavailable")
    result = probe["result"]
    if not result.detected or result.landmarks is None:
        return {"enrolled": False, "reason": "no_face_detected"}

    embedding = pipeline.face_engine.generate_geometric_embedding(result.landmarks)
    pipeline.enroll_student_baseline(embedding)
    return {
        "enrolled": True,
        "dimension": len(embedding),
        "pose": {
            "yaw": result.pose.yaw,
            "pitch": result.pose.pitch,
            "roll": result.pose.roll,
            "posture": result.pose.posture.value,
        } if result.pose else None,
    }


@router.post("/camera/probe")
async def probe_camera(_user: Any = Depends(require_auth)) -> Dict[str, Any]:
    """One-shot presence probe used by the system-mode pre-flight check."""
    probe = await _probe_camera_frame()
    if probe is None:
        return {"detected": False, "reason": "camera_unavailable"}
    result = probe["result"]
    return {
        "detected": bool(result.detected),
        "confidence": float(result.confidence),
        "brightness": round(float(result.brightness), 3),
        "ear": round(float(result.ear), 3),
        "phone_detected": bool(result.phone_detected),
        "pose": {
            "yaw": result.pose.yaw,
            "pitch": result.pose.pitch,
            "roll": result.pose.roll,
            "posture": result.pose.posture.value,
        } if result.pose else None,
        "snapshot_b64": _snapshot_payload_b64(probe["frame"]),
    }


@router.websocket("/session/{session_id}")
async def monitoring_session_websocket(websocket: WebSocket, session_id: str) -> None:
    """
    Bidirectional WebSocket for live telemetry streaming, alerts, and state synchronization.

    Two modes:
    - SYSTEM (default when the Python CV engine + webcam are available): the
      backend owns the camera and drives analysis ticks, broadcasting
      ``telemetry_update`` to every registered socket; the client only sends
      control messages (ping / pause / resume).
    - BROWSER (fallback): the client runs WASM MediaPipe and streams telemetry
      frames; the server analyzes on receive (legacy behavior, unchanged).
    """
    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth

    user_token = await ws_require_auth(websocket)
    if user_token is ws_auth_failed:
        return  # socket already rejected/closed by the auth helper

    await websocket.accept()
    _active_monitoring_sessions[session_id] = websocket
    pipeline = get_cv_pipeline()
    pipeline.reset_session()

    mode_param = websocket.query_params.get("mode")
    camera_cfg = await load_camera_config()
    monitor = None
    if mode_param != "browser" and camera_cfg.get("enabled", True):
        monitor = await start_system_monitor(session_id, camera_cfg, pipeline=pipeline)

    if monitor is not None:
        listener = monitor.register(websocket)
        try:
            await websocket.send_json({
                "type": "session_init",
                "session_id": session_id,
                "mode": "system",
                "target_fps": monitor.target_fps,
                "zero_cloud_egress": True,
                "message": "AI Guru System Camera Monitoring Active",
            })
            while True:
                raw_text = await websocket.receive_text()
                try:
                    msg = json.loads(raw_text)
                except Exception:
                    continue
                if not isinstance(msg, dict):
                    continue
                msg_type = msg.get("type", "")
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": time.time()})
                elif msg_type == "pause":
                    monitor.paused = True
                elif msg_type == "resume":
                    monitor.paused = False
                elif msg_type == "telemetry":
                    # Legacy client chatter is harmless here: the engine reads
                    # the camera directly and ignores browser payloads.
                    continue
        except WebSocketDisconnect:
            logger.info("Monitoring WebSocket disconnected for session: %s", session_id)
        except Exception as e:
            logger.warning("Monitoring WS error for session %s: %s", session_id, e)
        finally:
            monitor.unregister(listener)
            if monitor.listener_count == 0:
                await stop_system_monitor(session_id)
            _active_monitoring_sessions.pop(session_id, None)
            _frame_rings.pop(session_id, None)
            _purge_session_state(session_id)
        return

    apply_supervision_strictness_bg(pipeline)
    await _browser_driven_monitoring_loop(websocket, session_id, pipeline)


def apply_supervision_strictness_bg(pipeline: Any) -> None:
    """Schedule strictness application on the running loop (legacy WS path)."""
    from deeptutor.services.background import spawn_bg

    spawn_bg(apply_supervision_strictness(pipeline), name="monitoring-strictness")


async def _browser_driven_monitoring_loop(
    websocket: WebSocket,
    session_id: str,
    pipeline: Any,
) -> None:
    """
    Legacy browser-driven monitoring loop: the client streams landmark
    telemetry (+ optional JPEG snapshots); the server analyzes on receive.
    """

    logger.info("Monitoring WebSocket connected for session: %s", session_id)

    # --- session-persistence bookkeeping ---------------------------------------
    # Live scores are periodically flushed into study_sessions and real
    # distraction/presence episodes land in monitoring_events so the report,
    # parent dashboard, and XP flow read actual data instead of zeros.
    score_persist_interval = 10.0
    last_persist = time.time()
    warning_count = 0
    distraction_count = 0
    active_distractions: set = set()
    last_presence_state: Optional[str] = None
    # Running means over every analyzed frame. Persisting the LAST frame's
    # instantaneous score instead meant a student who was AWAY when the
    # socket closed got their whole session reported as 0/100 focus.
    focus_sum = 0.0
    engagement_sum = 0.0
    score_ticks = 0
    is_paused = False

    async def _persist_scores() -> None:
        try:
            from deeptutor.services.study.session_manager import StudySessionManager

            if score_ticks > 0:
                focus = focus_sum / score_ticks
                engagement = engagement_sum / score_ticks
            else:
                focus = float(analysis.distraction.focus_score or 0)
                engagement = float(analysis.engagement.score or 0)
            await StudySessionManager().update_scores(
                session_id, focus, engagement, distraction_count, warning_count
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Score persistence skipped for %s: %s", session_id, exc)

    async def _log_episode(event_type: str, severity: str, confidence: float,
                           duration_seconds: float, message: str) -> None:
        try:
            from deeptutor.services.study.telemetry_logger import TelemetryLogger

            await TelemetryLogger().log_event(
                session_id=session_id,
                event_type=event_type,
                severity=severity,
                confidence=confidence,
                duration_seconds=duration_seconds,
                metadata={"message": message},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Episode logging skipped for %s/%s: %s", session_id, event_type, exc)

    try:
        # Initial greeting with target FPS
        await websocket.send_json({
            "type": "session_init",
            "session_id": session_id,
            "mode": "browser",
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
            if not isinstance(msg, dict):
                continue

            msg_type = msg.get("type", "telemetry")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "timestamp": time.time()})
                continue
            elif msg_type == "pause":
                is_paused = True
                continue
            elif msg_type == "resume":
                is_paused = False
                continue

            if is_paused:
                continue

            # A literal ``{"data": null}`` must not poison the pipeline: fall
            # back to the envelope itself so the frame is analyzed, and never
            # hand process_telemetry_payload a None payload.
            data = msg.get("data")
            payload = data if isinstance(data, dict) else msg
            frame_b64 = _extract_frame(payload)
            if frame_b64 is not None:
                ring = _frame_rings.setdefault(session_id, collections.deque(maxlen=_RING_SIZE))
                ring.append(frame_b64)

            # Honor the CLIENT observation clock (the frontend stamps every
            # frame). Server receive-time compresses bursted deliveries — GC
            # pauses, network jitter, tab throttling — below the distraction/
            # absence hysteresis thresholds, silently blinding the detector.
            # Bounded acceptance rejects grossly skewed clocks.
            wall_now = time.time()
            frame_ts = payload.get("timestamp")
            if (
                isinstance(frame_ts, (int, float))
                and (wall_now - _FRAME_TIMESTAMP_MAX_LAG) <= float(frame_ts) <= (wall_now + _FRAME_TIMESTAMP_MAX_AHEAD)
            ):
                analysis_ts = float(frame_ts)
            else:
                analysis_ts = wall_now

            analysis = pipeline.process_telemetry_payload(payload, current_time=analysis_ts)

            # Accumulate for the session-mean scores persisted periodically
            # (and once more on disconnect in the finally block).
            focus_sum += float(analysis.distraction.focus_score or 0)
            engagement_sum += float(analysis.engagement.score or 0)
            score_ticks += 1

            # --- edge-triggered telemetry persistence (real episodes) -------
            if analysis.presence.state_changed or analysis.presence.state != last_presence_state:
                if last_presence_state is not None and analysis.presence.state != last_presence_state:
                    await _log_episode(
                        "PRESENCE_CHANGE",
                        "info",
                        float(analysis.gaze.confidence or 0),
                        float(analysis.presence.state_duration_seconds or 0),
                        f"presence -> {analysis.presence.state}",
                    )
                last_presence_state = analysis.presence.state

            if analysis.distraction.is_distracted:
                dtype = analysis.distraction.distraction_type.value
                if dtype not in active_distractions:
                    active_distractions.add(dtype)
                    distraction_count += 1
                    event_type = "PHONE_DETECTED" if "PHONE" in dtype.upper() else "LOOKING_AWAY"
                    await _log_episode(
                        event_type,
                        "warning",
                        float(analysis.distraction.confidence or 0),
                        float(analysis.distraction.duration_seconds or 0),
                        str(analysis.distraction.reason or dtype),
                    )
            else:
                active_distractions.clear()

            if analysis.dispatched_warning:
                # Info-level presence pings (STUDENT_AWAY) and in-app nudges
                # are not actionable warnings; counting them inflated the
                # parent-facing report.
                if analysis.dispatched_warning.severity not in ("info", "nudge"):
                    warning_count += 1

            now_s = time.time()
            if now_s - last_persist >= score_persist_interval:
                last_persist = now_s
                await _persist_scores()

            # Send back real-time metrics
            response_data = {
                "type": "telemetry_update",
                "session_id": session_id,
                "timestamp": analysis.timestamp,
                "presence": analysis.presence.state.value,
                "focus_score": analysis.distraction.focus_score,
                "engagement_score": analysis.engagement.score,
                "engagement_trend": analysis.engagement.trend,
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
                from deeptutor.services.background import spawn_bg

                spawn_bg(
                    handle_warning(
                        session_id=session_id,
                        warning=warning_dict,
                        current_frame_b64=frame_b64,
                        ring_frames_b64=list(_frame_rings.get(session_id, ())),
                        photo_jpeg_b64=frame_b64,
                    ),
                    name=f"warning-dispatch-{session_id}",
                )

            await websocket.send_json(response_data)

    except WebSocketDisconnect:
        logger.info("Monitoring WebSocket disconnected for session: %s", session_id)
    except Exception as e:
        logger.warning("Monitoring WebSocket error for session %s: %s", session_id, e)
    finally:
        try:
            await _persist_scores()
        except Exception:  # noqa: BLE001
            pass
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

    sanitized = []
    for e in (events or []):
        message = None
        raw_meta = e.get("metadata_json")
        if isinstance(raw_meta, str) and raw_meta:
            try:
                parsed = json.loads(raw_meta)
                if isinstance(parsed, dict):
                    message = parsed.get("message")
            except Exception:  # noqa: BLE001
                pass
        sanitized.append(
            {
                "id": e.get("id"),
                "event_type": e.get("event_type"),
                "severity": e.get("severity"),
                "confidence": e.get("confidence"),
                "duration_seconds": e.get("duration_seconds"),
                "timestamp": e.get("timestamp"),
                "message": message,
            }
        )
    return {"session_id": session_id, "items": sanitized[: max(0, min(limit, 500))], "total": len(sanitized)}
