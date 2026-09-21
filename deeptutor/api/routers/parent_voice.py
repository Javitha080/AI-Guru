"""Parent voice drop-in — parent-gated signaling endpoints.

Mounted in ``api/main.py`` under ``/api/v1/parent/voice`` with the same
``parent_context`` workspace dependency as ``parent.py``. Every route
requires the parent PIN-JWT via ``require_parent``.

The backend only relays signaling (SDP/ICE) and text announcements;
audio itself is peer-to-peer WebRTC between the parent and student
browsers. Safeguards (duration cap, cooldown, rate limit) live in
``services/monitoring/voice_intercom.py``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deeptutor.api.routers.parent import require_parent
from deeptutor.services.monitoring import voice_intercom as voice

logger = logging.getLogger(__name__)

router = APIRouter(tags=["parent-voice"])


def _audit(action: str, actor: str = "default", details: Optional[Dict[str, Any]] = None) -> None:
    async def _run() -> None:
        try:
            from deeptutor.services.remote.audit_logger import AuditLogger

            await AuditLogger.log_event(actor, "parent", action, "voice_call", "", details or {})
        except Exception as exc:  # noqa: BLE001
            logger.debug("voice audit skipped for %s: %s", action, exc)

    try:
        from deeptutor.services.background import spawn_bg

        spawn_bg(_run(), name=f"voice-audit-{action}")
    except Exception:  # noqa: BLE001
        pass


async def _resolve_session(session_id: Optional[str], student_id: Optional[str]) -> Optional[str]:
    if student_id:
        try:
            from deeptutor.services.study.session_manager import StudySessionManager

            rows = await StudySessionManager().list_sessions(student_id, limit=10)
            items = rows.get("items", rows) if isinstance(rows, dict) else rows
            for s in items or []:
                if isinstance(s, dict) and s.get("status") == "in_progress" and s.get("id"):
                    return str(s.get("id"))
            return None
        except Exception as exc:  # noqa: BLE001
            logger.debug("voice student resolve failed: %s", exc)
            return None
    if not session_id or session_id == "current":
        try:
            from deeptutor.services.monitoring.session_registry import list_consented_active

            candidates = list_consented_active()
            if candidates:
                return candidates[0]
        except Exception:  # noqa: BLE001
            pass
        try:
            from deeptutor.services.monitoring.session_registry import list_active_sessions

            active = list_active_sessions()
            return active[0] if active else None
        except Exception:  # noqa: BLE001
            return None
    return session_id


async def _require_voice_permission(parent_id: str, session_id: str) -> str:
    try:
        from deeptutor.api.routers.parent import _require_live_permission

        await _require_live_permission(parent_id, session_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.debug("voice permission lookup skipped: %s", exc)
    try:
        from deeptutor.services.remote.pairing import PairingService

        links = await PairingService.get_linked_students(parent_id)
    except Exception:  # noqa: BLE001
        return ""
    if not links:
        return ""
    student_id = ""
    try:
        from deeptutor.services.study.session_manager import StudySessionManager

        sess = await StudySessionManager().get_session(session_id)
        student_id = str((sess or {}).get("student_id") or "")
    except Exception:  # noqa: BLE001
        student_id = ""
    if not student_id:
        return ""
    for link in links:
        if str(link.get("student_id")) == student_id:
            perms = link.get("permissions", {}) or {}
            if "can_voice_interrupt" in perms and not perms.get("can_voice_interrupt", True):
                _audit("voice.denied_no_permission", actor=parent_id, details={"session_id": session_id})
                raise HTTPException(status_code=403, detail="can_voice_interrupt not granted")
            return student_id
    _audit("voice.denied_not_linked", actor=parent_id, details={"session_id": session_id})
    raise HTTPException(status_code=403, detail="student_not_linked_to_parent")


def _notify_student_ws(session_id: str, payload: Dict[str, Any]) -> None:
    try:
        from deeptutor.api.routers import monitoring_session as _m

        ws = _m._active_monitoring_sessions.get(session_id)
        if ws is None:
            return

        async def _send() -> None:
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                pass

        try:
            from deeptutor.services.background import spawn_bg

            spawn_bg(_send(), name=f"voice-notify-{session_id}")
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass


class VoiceSignalRequest(BaseModel):
    session_id: str = "current"
    type: str = Field(..., pattern="^(offer|answer|ice|bye|heartbeat)$")
    payload: str = Field(default="", max_length=12000)


class VoiceAnnounceRequest(BaseModel):
    session_id: str = "current"
    student_id: Optional[str] = None
    text: str = Field(..., min_length=1, max_length=280)


@router.post("/call")
async def start_voice_call(
    session_id: str = "current",
    student_id: Optional[str] = None,
    _parent: Dict[str, Any] = Depends(require_parent),
) -> Dict[str, Any]:
    parent_id = str(_parent.get("sub", "default"))
    resolved = await _resolve_session(session_id, student_id)
    if not resolved or not voice.valid_session_id(resolved):
        raise HTTPException(status_code=404, detail="No active study session")
    try:
        from deeptutor.services.monitoring.session_registry import is_session_active

        if not is_session_active(resolved):
            raise HTTPException(status_code=404, detail="Session not found or not active")
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        pass
    student_resolved = await _require_voice_permission(parent_id, resolved)
    ok, reason = voice.check_rate_limit(resolved)
    if not ok:
        _audit("voice.rate_limited", actor=parent_id, details={"session_id": resolved, "reason": reason})
        raise HTTPException(status_code=429, detail=reason)
    voice.cleanup_expired()
    call = voice.start_call(resolved, parent_id, student_resolved)
    _audit("voice.call_started", actor=parent_id, details={"session_id": resolved, "call_id": call.call_id})
    _notify_student_ws(resolved, {"type": "voice-incoming", "call": voice.call_to_dict(call)})
    return {"call": voice.call_to_dict(call)}


@router.post("/end")
async def end_voice_call(
    session_id: str = "current",
    _parent: Dict[str, Any] = Depends(require_parent),
) -> Dict[str, Any]:
    parent_id = str(_parent.get("sub", "default"))
    resolved = await _resolve_session(session_id, None)
    target = resolved or session_id
    if not voice.valid_session_id(target):
        return {"stopped": True}
    voice.push_signal(target, "parent", "bye", "ended")
    voice.end_call(target, "parent_ended")
    _audit("voice.call_ended", actor=parent_id, details={"session_id": target})
    _notify_student_ws(target, {"type": "voice-ended", "session_id": target})
    return {"stopped": True, "session_id": target}


@router.get("/status")
async def voice_status(
    session_id: str = "current",
    student_id: Optional[str] = None,
    _parent: Dict[str, Any] = Depends(require_parent),
) -> Dict[str, Any]:
    resolved = await _resolve_session(session_id, student_id)
    if not resolved or not voice.valid_session_id(resolved):
        return {"active": False, "session_id": None}
    call = voice.get_call(resolved)
    if call is None:
        return {"active": False, "session_id": resolved}
    data = voice.call_to_dict(call)
    return {"active": data["active"], "session_id": resolved, "call": data}


@router.post("/signal")
async def post_voice_signal(
    req: VoiceSignalRequest,
    _parent: Dict[str, Any] = Depends(require_parent),
) -> Dict[str, Any]:
    resolved = await _resolve_session(req.session_id, None)
    target = resolved or req.session_id
    if not voice.valid_session_id(target):
        raise HTTPException(status_code=404, detail="No active study session")
    if not voice.push_signal(target, "parent", req.type, req.payload):
        raise HTTPException(status_code=400, detail="Invalid signal")
    if req.type in ("offer", "bye"):
        _notify_student_ws(
            target,
            {"type": "voice-signal", "signal_type": req.type, "session_id": target},
        )
    return {"accepted": True}


@router.get("/signal")
async def poll_voice_signal(
    session_id: str = "current",
    _parent: Dict[str, Any] = Depends(require_parent),
) -> Dict[str, Any]:
    resolved = await _resolve_session(session_id, None)
    target = resolved or session_id
    if not voice.valid_session_id(target):
        return {"session_id": target, "signals": [], "call": None}
    call = voice.get_call(target)
    return {
        "session_id": target,
        "signals": voice.drain_signals(target, "parent"),
        "call": voice.call_to_dict(call) if call else None,
        "ts": time.time(),
    }


@router.post("/announce")
async def post_voice_announcement(
    req: VoiceAnnounceRequest,
    _parent: Dict[str, Any] = Depends(require_parent),
) -> Dict[str, Any]:
    parent_id = str(_parent.get("sub", "default"))
    resolved = await _resolve_session(req.session_id, req.student_id)
    if not resolved or not voice.valid_session_id(resolved):
        raise HTTPException(status_code=404, detail="No active study session")
    await _require_voice_permission(parent_id, resolved)
    ok, reason = voice.check_announce_rate_limit(resolved)
    if not ok:
        raise HTTPException(status_code=429, detail=reason)
    item = voice.push_announcement(resolved, parent_id, req.text)
    if not item:
        raise HTTPException(status_code=400, detail="Empty announcement")
    _audit(
        "voice.announced",
        actor=parent_id,
        details={"session_id": resolved, "chars": len(item["text"])},
    )
    _notify_student_ws(resolved, {"type": "voice-announce", "text": item["text"], "session_id": resolved})
    return {"success": True, "session_id": resolved, "chars": len(item["text"])}
