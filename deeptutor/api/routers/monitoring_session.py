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
from deeptutor.api.routers.ownership import require_session_owner
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
    from deeptutor.api.routers.ownership import check_session_owner_ws

    user_token = await ws_require_auth(websocket)
    if user_token is ws_auth_failed:
        return  # socket already rejected/closed by the auth helper

    if not await check_session_owner_ws(session_id):
        await websocket.close(code=4003)
        return

    await websocket.accept()
    _active_monitoring_sessions[session_id] = websocket
    # Per-connection pipeline: never share/reset the process-global singleton
    # across concurrent sessions. Inherit the enrolled baseline (if any),
    # else restore the persisted (encrypted) one.
    pipeline = LocalCVPipeline()
    try:
        from deeptutor.services.monitoring.cv_pipeline import hydrate_identity_baseline

        await hydrate_identity_baseline(pipeline)
    except Exception:  # noqa: BLE001 - inheritance best-effort
        pass
    pipeline.reset_session()

    mode_param = websocket.query_params.get("mode")
    try:
        camera_cfg = await load_camera_config()
    except Exception as exc:  # noqa: BLE001 - config is optional
        logger.debug("Camera config load failed for %s: %s", session_id, exc)
        camera_cfg = {"enabled": False}
    monitor = None
    if mode_param != "browser" and camera_cfg.get("enabled", True):
        try:
            monitor = await start_system_monitor(session_id, camera_cfg, pipeline=pipeline)
        except Exception as exc:  # noqa: BLE001 - fall back to browser mode
            logger.warning("System monitor start failed for %s: %s", session_id, exc)
            monitor = None

    if monitor is not None:
        listener = monitor.register(websocket)
        try:
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
            except Exception as exc:  # noqa: BLE001 - dead socket on init
                logger.debug("session_init send failed for %s: %s", session_id, exc)
                return
            while True:
                try:
                    raw_text = await websocket.receive_text()
                except WebSocketDisconnect:
                    raise
                except Exception as exc:  # noqa: BLE001 - transport hiccup
                    logger.debug("WS receive failed for %s: %s", session_id, exc)
                    break
                try:
                    msg = json.loads(raw_text)
                except Exception:
                    try:
                        await websocket.send_json({"type": "error", "message": "Invalid frame."})
                    except Exception:
                        pass
                    continue
                if not isinstance(msg, dict):
                    continue
                msg_type = msg.get("type", "")
                try:
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
                    elif msg_type:
                        await websocket.send_json(
                            {"type": "error", "message": f"Unknown type: {msg_type}"}
                        )
                except WebSocketDisconnect:
                    raise
                except Exception as exc:  # noqa: BLE001 - one bad control msg never kills session
                    logger.debug("Control-msg send failed for %s: %s", session_id, exc)
                    break
        except WebSocketDisconnect:
            logger.info("Monitoring WebSocket disconnected for session: %s", session_id)
        except Exception as e:
            logger.warning("Monitoring WS error for session %s: %s", session_id, e)
            try:
                await websocket.send_json({"type": "error", "message": "Stream error. Reconnect."})
            except Exception:
                pass
        finally:
            try:
                monitor.unregister(listener)
            except Exception:  # noqa: BLE001 - teardown best-effort
                pass
            try:
                if monitor.listener_count == 0:
                    await stop_system_monitor(session_id)
            except Exception:  # noqa: BLE001
                pass
            _active_monitoring_sessions.pop(session_id, None)
            _frame_rings.pop(session_id, None)
            _purge_session_state(session_id)
            # Bank the open study stretch so a dropped socket never leaves an
            # 'in_progress' row accruing phantom minutes (parent dashboard
            # sums live durations). Best-effort: never raises into WS teardown.
            try:
                from deeptutor.services.background import spawn_bg
                from deeptutor.services.study.session_manager import StudySessionManager

                spawn_bg(
                    StudySessionManager().pause_on_disconnect(session_id),
                    name=f"monitoring-disconnect-pause-{session_id}",
                )
            except Exception:  # noqa: BLE001
                pass
        return

    _apply_supervision_strictness_bg(pipeline, session_id=session_id)

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


def _apply_supervision_strictness_bg(pipeline: Any, session_id: Optional[str] = None) -> None:
    """Schedule strictness application on the running loop (legacy WS path)."""
    from deeptutor.services.background import spawn_bg

    spawn_bg(
        apply_supervision_strictness(pipeline, session_id=session_id),
        name="monitoring-strictness",
    )


# --- Live supervision endpoints ----------------------------------------------


@router.post("/live/consent")
async def set_live_consent(
    req: LiveConsentRequest,
    session_id: str,
    _owner: str = Depends(require_session_owner),
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
    _owner: str = Depends(require_session_owner),
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
    _owner: str = Depends(require_session_owner),
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


# --- Parent voice drop-in (student side) --------------------------------------


class VoiceStudentSignalRequest(BaseModel):
    session_id: str
    type: str = Field(..., pattern="^(offer|answer|ice|bye|heartbeat)$")
    payload: str = Field(default="", max_length=12000)


@router.get("/voice/incoming")
async def voice_incoming(
    session_id: str,
    _owner: str = Depends(require_session_owner),
    _user: Any = Depends(require_auth),
) -> Dict[str, Any]:
    """Student poll: active parent call + pending signals + announcements."""
    import time as _time

    from deeptutor.services.monitoring import voice_intercom as _voice

    if not _voice.valid_session_id(session_id):
        return {"session_id": session_id, "call": None, "signals": [], "announcements": []}
    call = _voice.get_call(session_id)
    return {
        "session_id": session_id,
        "call": _voice.call_to_dict(call) if call else None,
        "signals": _voice.drain_signals(session_id, "student"),
        "announcements": _voice.drain_announcements(session_id),
        "ts": _time.time(),
    }


@router.post("/voice/signal")
async def voice_student_signal(
    req: VoiceStudentSignalRequest,
    _user: Any = Depends(require_auth),
) -> Dict[str, Any]:
    """Student posts WebRTC answer/ICE (or bye) for the parent to collect."""
    from deeptutor.services.monitoring import voice_intercom as _voice

    await require_session_owner(req.session_id, _user)

    if not _voice.valid_session_id(req.session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    if not _voice.push_signal(req.session_id, "student", req.type, req.payload):
        raise HTTPException(status_code=400, detail="Invalid signal")
    return {"accepted": True}
