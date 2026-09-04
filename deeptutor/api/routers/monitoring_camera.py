"""
AI Guru Study Monitoring — System Camera Endpoints.
====================================================

Split from the monolithic monitoring.py router. Contains:
- Camera capability probe (GET /camera/status)
- Camera configuration (POST /camera/config)
- Raw JPEG snapshot (GET /snapshot/{session_id})
- MJPEG live stream feed (GET /feed/{session_id})
- Server-side face enrollment (POST /enroll-from-camera)
- One-shot presence probe (POST /camera/probe)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_auth
from deeptutor.services.monitoring import get_cv_pipeline
from deeptutor.services.monitoring.system_monitor import (
    get_system_monitor,
    load_camera_config,
    save_camera_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitoring"])


class CameraConfigRequest(BaseModel):
    enabled: Optional[bool] = Field(default=None)
    camera_index: Optional[int] = Field(default=None, ge=0, le=8)
    target_fps: Optional[int] = Field(default=None, ge=1, le=30)


# --- Helpers ---


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
        # Transient grabber: stop our own capture. Only release the shared
        # registry when no session is actively monitoring — otherwise we
        # would pop the device an active SystemMonitorSession owns.
        camera.stop()
        if not active_system_monitors():
            release_system_camera(int(cfg.get("camera_index", 0)))


def _snapshot_payload_b64(frame: Any) -> Optional[str]:
    import base64

    try:
        import cv2

        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        return base64.b64encode(buf.tobytes()).decode("ascii") if ok else None
    except Exception:  # noqa: BLE001
        return None


# --- Endpoints ---


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
async def set_camera_config(
    req: CameraConfigRequest, _user: Any = Depends(require_auth)
) -> Dict[str, Any]:
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    saved = await save_camera_config(updates)
    return {"saved": True, "config": saved}


@router.get("/snapshot/{session_id}")
async def get_camera_snapshot(session_id: str, _user: Any = Depends(require_auth)) -> Any:
    """Latest raw camera JPEG for one session (parent live view / diagnostics)."""
    from fastapi import Response

    monitor = get_system_monitor(session_id)
    if monitor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No active system monitor"
        )
    jpeg = monitor.get_snapshot_jpeg()
    if jpeg is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Camera warming up"
        )
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No active system camera feed"
        )

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
async def enroll_from_camera(
    force: bool = False, _user: Any = Depends(require_auth)
) -> Dict[str, Any]:
    """Enroll the identity baseline straight from the system camera.

    Lets the pre-flight check register the student without ANY browser camera
    involvement. Hardened on two axes:

    - **Already-enrolled gate**: without ``force=true`` the endpoint is a
      no-op when a baseline exists. The old behavior re-enrolled WHOEVER was
      sitting in front of the camera on every system-mode pre-flight — the
      sibling who pressed start became the "enrolled student".
    - **SFace neural enrollment**: when the SFace model is present, the
      template is the per-dimension MEDIAN of ~10 frontal grabs over ~3s
      (a single frame is a pose/expression snapshot); the geometric vector
      is the clearly-labelled fallback.
    """
    pipeline = get_cv_pipeline()

    # --- already-enrolled gate (in-memory OR persisted) -------------------
    if not force and pipeline.face_engine.get_enrolled_face() is not None:
        return {
            "enrolled": False,
            "already_enrolled": True,
            "reason": "identity_baseline_exists",
            "identity_mode": pipeline.enrolled_identity_mode,
        }

    loop = asyncio.get_running_loop()
    pose_info = None
    sface_samples: list = []
    geo_embedding = None

    # Burst of frontal grabs over ~3.5s for a stable median template.
    deadline = time.time() + 3.5
    grabs = 0
    while grabs < 12 and time.time() < deadline:
        probe = await _probe_camera_frame()
        if probe is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="System camera unavailable",
            )
        result = probe["result"]
        if not result.detected or result.landmarks is None:
            await asyncio.sleep(0.25)
            continue
        angles = getattr(result, "head_angles_raw", None)
        frontal = angles is None or (abs(angles[0]) <= 25.0 and abs(angles[1]) <= 25.0)
        if not frontal:
            await asyncio.sleep(0.25)
            continue
        grabs += 1
        if pose_info is None and result.pose is not None:
            pose_info = {
                "yaw": result.pose.yaw,
                "pitch": result.pose.pitch,
                "roll": result.pose.roll,
                "posture": result.pose.posture.value,
            }
        frame = probe["frame"]
        if pipeline.sface_available and result.raw_landmarks:
            emb = await loop.run_in_executor(
                None, pipeline.sface_enroll_vector, frame, result.raw_landmarks
            )
            if emb is not None:
                sface_samples.append(emb)
        if geo_embedding is None:
            geo_embedding = pipeline.face_engine.generate_geometric_embedding(result.landmarks)
        await asyncio.sleep(0.2)

    if grabs == 0 or geo_embedding is None:
        return {"enrolled": False, "reason": "no_face_detected"}

    identity_mode = "geometric"
    embedding = geo_embedding
    if len(sface_samples) >= 5:
        try:
            from deeptutor.services.monitoring.face_identity import enroll_sface_from_engine

            sface_engine = getattr(pipeline, "_sface", None)
            vector = (
                enroll_sface_from_engine(sface_engine, sface_samples) if sface_engine else None
            )
            if vector is not None:
                embedding = vector
                identity_mode = "sface"
        except Exception as exc:  # noqa: BLE001 - geometric fallback stays
            logger.warning("SFace enrollment fell back to geometric: %s", exc)

    pipeline.enroll_student_baseline(embedding, identity_mode=identity_mode)

    # --- encrypted persistence so restarts stay enrolled -------------------
    persisted = False
    try:
        from deeptutor.services.monitoring.identity_store import save_baseline
        from deeptutor.services.path_service import get_path_service

        db_path = str(get_path_service().user_dir / "chat_history.db")
        persisted = await save_baseline(db_path, embedding, identity_mode)
    except Exception as exc:  # noqa: BLE001 - persistence best-effort
        logger.debug("Baseline persistence skipped: %s", exc)

    return {
        "enrolled": True,
        "dimension": len(embedding),
        "identity_mode": identity_mode,
        "persisted": persisted,
        "samples": len(sface_samples) if identity_mode == "sface" else grabs,
        "pose": pose_info,
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
        }
        if result.pose
        else None,
        "snapshot_b64": _snapshot_payload_b64(probe["frame"]),
    }
