"""Parent voice drop-in — in-memory call + signaling state.

Local-first intercom: the backend never touches audio bytes. It only
relays WebRTC SDP/ICE signaling and text announcements between the
parent portal and the student's study-room client, enforcing the
safeguards from ``monitoring_config`` (duration cap, cooldown, rate
limit). Audio itself is peer-to-peer WebRTC between the two browsers.

No DB tables: call state lives in this process (like live frames) and
is purged on disconnect/expiry. Auditing is the caller's duty via the
parent audit logger. Never raises into request paths.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Any, Dict, List, Optional
import uuid

from deeptutor.services.monitoring.monitoring_config import DEFAULT_THRESHOLDS

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

_SIGNAL_TYPES = {"offer", "answer", "ice", "bye", "heartbeat"}
_SIGNAL_MAX_CHARS = 12000


def valid_session_id(session_id: str) -> bool:
    return isinstance(session_id, str) and bool(_SESSION_ID_RE.match(session_id))


@dataclass
class VoiceCall:
    call_id: str
    session_id: str
    parent_id: str
    student_id: str = ""
    mode: str = "voice"
    started_at: float = 0.0
    ends_at: float = 0.0
    ended: bool = False
    end_reason: str = ""


_calls: Dict[str, VoiceCall] = {}
_call_starts: Dict[str, List[float]] = {}
_announce_times: Dict[str, List[float]] = {}
_signals: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
_announcements: Dict[str, List[Dict[str, Any]]] = {}


def _now() -> float:
    return time.time()


def _prune_history(session_id: str, now: float) -> List[float]:
    window = DEFAULT_THRESHOLDS.voice_window_seconds
    kept = [t for t in _call_starts.get(session_id, []) if now - t < window]
    _call_starts[session_id] = kept
    return kept


def _get_call(session_id: str) -> Optional[VoiceCall]:
    call = _calls.get(session_id)
    if call is None:
        return None
    if call.ended or _now() >= call.ends_at:
        if not call.ended:
            call.ended = True
            call.end_reason = call.end_reason or "expired"
        return call if not call.ended else call
    return call


def get_call(session_id: str) -> Optional[VoiceCall]:
    if not valid_session_id(session_id):
        return None
    call = _calls.get(session_id)
    if call is None:
        return None
    if not call.ended and _now() >= call.ends_at:
        call.ended = True
        call.end_reason = call.end_reason or "expired"
    return call


def is_call_active(session_id: str) -> bool:
    call = get_call(session_id)
    return bool(call and not call.ended)


def check_rate_limit(session_id: str) -> tuple[bool, str]:
    now = _now()
    call = _calls.get(session_id)
    if call and not call.ended and now < call.ends_at:
        return False, "call_active"
    hist = _prune_history(session_id, now)
    if hist:
        last = hist[-1]
        if now - last < DEFAULT_THRESHOLDS.voice_cooldown_seconds:
            wait = int(DEFAULT_THRESHOLDS.voice_cooldown_seconds - (now - last))
            return False, f"cooldown_{wait}s"
    if len(hist) >= DEFAULT_THRESHOLDS.voice_max_per_window:
        return False, "rate_limited"
    return True, ""


def check_announce_rate_limit(session_id: str) -> tuple[bool, str]:
    now = _now()
    window = float(DEFAULT_THRESHOLDS.voice_announce_window_seconds)
    hist = [t for t in _announce_times.get(session_id, []) if now - t < window]
    _announce_times[session_id] = hist
    if hist:
        gap = float(DEFAULT_THRESHOLDS.voice_announce_cooldown_seconds)
        last = hist[-1]
        if now - last < gap:
            wait = int(gap - (now - last))
            return False, f"announce_cooldown_{wait}s"
    if len(hist) >= int(DEFAULT_THRESHOLDS.voice_announce_max_per_window):
        return False, "announce_rate_limited"
    return True, ""


def start_call(session_id: str, parent_id: str, student_id: str = "", mode: str = "voice") -> VoiceCall:
    now = _now()
    call = VoiceCall(
        call_id=uuid.uuid4().hex[:12],
        session_id=session_id,
        parent_id=parent_id or "default",
        student_id=student_id or "",
        mode=mode if mode in ("voice", "announce") else "voice",
        started_at=now,
        ends_at=now + float(DEFAULT_THRESHOLDS.voice_max_duration_seconds),
    )
    _calls[session_id] = call
    hist = _prune_history(session_id, now)
    hist.append(now)
    _call_starts[session_id] = hist
    _signals.setdefault(session_id, {"parent": [], "student": []})
    _announcements.setdefault(session_id, [])
    return call


def end_call(session_id: str, reason: str = "ended") -> Optional[VoiceCall]:
    call = _calls.get(session_id)
    if call is None:
        return None
    call.ended = True
    call.end_reason = reason[:64]
    return call


def call_to_dict(call: VoiceCall) -> Dict[str, Any]:
    now = _now()
    return {
        "call_id": call.call_id,
        "session_id": call.session_id,
        "parent_id": call.parent_id,
        "student_id": call.student_id,
        "mode": call.mode,
        "started_at": call.started_at,
        "ends_at": call.ends_at,
        "seconds_left": max(0, int(call.ends_at - now)),
        "active": bool(not call.ended and now < call.ends_at),
        "end_reason": call.end_reason,
    }


def push_signal(session_id: str, from_role: str, sig_type: str, payload: Any) -> bool:
    if not valid_session_id(session_id):
        return False
    if from_role not in ("parent", "student"):
        return False
    if sig_type not in _SIGNAL_TYPES:
        return False
    try:
        text = payload if isinstance(payload, str) else __import__("json").dumps(payload)
    except Exception:
        return False
    if not isinstance(text, str) or len(text) > _SIGNAL_MAX_CHARS:
        return False
    if sig_type == "bye":
        end_call(session_id, "peer_bye")
    box = _signals.setdefault(session_id, {"parent": [], "student": []})
    to_role = "student" if from_role == "parent" else "parent"
    box[to_role].append({"type": sig_type, "payload": text, "ts": _now()})
    if len(box[to_role]) > 50:
        del box[to_role][:-50]
    return True


def drain_signals(session_id: str, for_role: str) -> List[Dict[str, Any]]:
    if not valid_session_id(session_id) or for_role not in ("parent", "student"):
        return []
    box = _signals.setdefault(session_id, {"parent": [], "student": []})
    items = box.get(for_role, [])
    box[for_role] = []
    now = _now()
    return [m for m in items if now - float(m.get("ts", 0)) < 60.0]


def push_announcement(session_id: str, parent_id: str, text: str) -> Optional[Dict[str, Any]]:
    if not valid_session_id(session_id):
        return None
    clean = (text or "").strip()
    if not clean:
        return None
    max_chars = int(DEFAULT_THRESHOLDS.voice_max_text_chars)
    clean = clean[:max_chars]
    item = {"text": clean, "parent_id": parent_id or "default", "ts": _now()}
    box = _announcements.setdefault(session_id, [])
    box.append(item)
    if len(box) > 10:
        del box[:-10]
    hist = _announce_times.setdefault(session_id, [])
    hist.append(item["ts"])
    window = float(DEFAULT_THRESHOLDS.voice_announce_window_seconds)
    _announce_times[session_id] = [t for t in hist if item["ts"] - t < window]
    return item


def drain_announcements(session_id: str) -> List[Dict[str, Any]]:
    if not valid_session_id(session_id):
        return []
    box = _announcements.setdefault(session_id, [])
    items = list(box)
    box.clear()
    now = _now()
    return [m for m in items if now - float(m.get("ts", 0)) < 120.0]


def cleanup_expired() -> int:
    now = _now()
    removed = 0
    for sid, call in list(_calls.items()):
        if call.ended and now - call.ends_at > 300:
            _calls.pop(sid, None)
            _signals.pop(sid, None)
            _announcements.pop(sid, None)
            removed += 1
        elif not call.ended and now >= call.ends_at:
            call.ended = True
            call.end_reason = call.end_reason or "expired"
    return removed


def reset_for_tests() -> None:
    _calls.clear()
    _call_starts.clear()
    _announce_times.clear()
    _signals.clear()
    _announcements.clear()


__all__ = [
    "VoiceCall",
    "valid_session_id",
    "get_call",
    "is_call_active",
    "check_rate_limit",
    "check_announce_rate_limit",
    "start_call",
    "end_call",
    "call_to_dict",
    "push_signal",
    "drain_signals",
    "push_announcement",
    "drain_announcements",
    "cleanup_expired",
    "reset_for_tests",
]
