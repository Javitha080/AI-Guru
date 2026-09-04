"""
AI Guru Study Monitoring — Session & Live Supervision Endpoints.
================================================================

Split from the monolithic monitoring.py router. Contains:
- WebSocket session endpoint (WS /session/{session_id})
- Live supervision consent (POST /live/consent)
- Live frame upload (POST /live/frame)
- Session event history (GET /events/{session_id})

**Owns the canonical shared module-level state** that parent.py and
telegram_command_listener.py access via the re-export shim in monitoring.py:
- _active_monitoring_sessions
- _live_consent
- _live_frames
- _frame_rings
- _purge_stale_frames()
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Deque, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_auth
from deeptutor.services.monitoring.cv_pipeline import LocalCVPipeline
from deeptutor.services.monitoring.system_monitor import (
    apply_supervision_strictness,
    load_camera_config,
    start_system_monitor,
    stop_system_monitor,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitoring"])


# ═══════════════════════════════════════════════════════════════════════════════
# CANONICAL SHARED STATE
# These module-level containers are the single source of truth for the
# monitoring system. parent.py and telegram_command_listener.py import them
# via the re-export shim in monitoring.py and read/mutate them directly.
# ═══════════════════════════════════════════════════════════════════════════════

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
# P0 hardening: bound RAM use of the in-memory live view. A single frame is a
# throttled JPEG (~320px/q0.6); anything far larger is a buggy client, and too
# many concurrent sessions means leaked state rather than real supervision.
_MAX_LIVE_FRAME_B64_LEN = 1_500_000
_MAX_LIVE_SESSIONS = 100

_FRAME_KEYS = ("jpeg_b64", "jpeg", "frame_b64", "frame", "image_b64", "image")


# --- Request models ---


class LiveConsentRequest(BaseModel):
    enabled: bool


class LiveFrameRequest(BaseModel):
    jpeg_b64: str = Field(..., min_length=32, max_length=_MAX_LIVE_FRAME_B64_LEN)


# --- Shared helpers ---


def _purge_stale_frames() -> None:
    now = time.time()
    stale = [sid for sid, (_, ts) in _live_frames.items() if now - ts > _LIVE_FRAME_TTL]
    for sid in stale:
        _live_frames.pop(sid, None)


def _purge_session_state(session_id: str) -> None:
    """Called when a monitoring WS disconnects."""
    _live_consent.discard(session_id)
    _live_frames.pop(session_id, None)


def _extract_frame(payload: Dict[str, Any]) -> Optional[str]:
    for key in _FRAME_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and len(value) > 32:
            return value
    return None


# --- WebSocket session endpoint ---


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
    # Per-connection pipeline: never share/reset the process-global singleton
    # across concurrent sessions. Inherit the enrolled baseline (if any).
    pipeline = LocalCVPipeline()
    try:
        from deeptutor.services.monitoring.cv_pipeline import get_cv_pipeline

        baseline = get_cv_pipeline().face_engine.get_enrolled_face()
        if baseline is not None:
            pipeline.enroll_student_baseline(list(baseline))
    except Exception:  # noqa: BLE001 - inheritance best-effort
        pass
    pipeline.reset_session()

    mode_param = websocket.query_params.get("mode")
    camera_cfg = await load_camera_config()
    monitor = None
    if mode_param != "browser" and camera_cfg.get("enabled", True):
        monitor = await start_system_monitor(session_id, camera_cfg, pipeline=pipeline)

    if monitor is not None:
        listener = monitor.register(websocket)
        try:
            await websocket.send_json(
                {
                    "type": "session_init",
                    "session_id": session_id,
                    "mode": "system",
                    "target_fps": monitor.target_fps,
                    "zero_cloud_egress": True,
                    "message": "AI Guru System Camera Monitoring Active",
                }
            )
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

    _apply_supervision_strictness_bg(pipeline)

    # Delegate to the browser-driven monitoring loop service
    from deeptutor.services.monitoring.browser_session import browser_driven_monitoring_loop

    await browser_driven_monitoring_loop(
        websocket=websocket,
        session_id=session_id,
        pipeline=pipeline,
        frame_rings=_frame_rings,
        active_sessions=_active_monitoring_sessions,
        purge_session_state=_purge_session_state,
    )


def _apply_supervision_strictness_bg(pipeline: Any) -> None:
    """Schedule strictness application on the running loop (legacy WS path)."""
    from deeptutor.services.background import spawn_bg

    spawn_bg(apply_supervision_strictness(pipeline), name="monitoring-strictness")


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
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="No active monitoring session"
            )
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
    if len(req.jpeg_b64) > _MAX_LIVE_FRAME_B64_LEN:
        logger.warning(
            "Live frame rejected for %s: %d chars exceeds %d cap",
            session_id,
            len(req.jpeg_b64),
            _MAX_LIVE_FRAME_B64_LEN,
        )
        return {"accepted": False, "reason": "frame_too_large"}
    if session_id not in _live_frames and len(_live_frames) >= _MAX_LIVE_SESSIONS:
        # Evict the oldest entry rather than growing without bound when
        # disconnect purges are missed (leaked WS state).
        oldest = min(_live_frames.items(), key=lambda kv: kv[1][1])[0]
        _live_frames.pop(oldest, None)
        logger.warning("Live-frame table full; evicted oldest session %s", oldest)
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
    for e in events or []:
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
    return {
        "session_id": session_id,
        "items": sanitized[: max(0, min(limit, 500))],
        "total": len(sanitized),
    }
