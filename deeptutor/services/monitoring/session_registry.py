"""Accessor API for monitoring session state (replaces direct global mutation).

Canonical state still lives in ``monitoring_session`` (single source of truth).
Parent portal + Telegram listener should call these helpers instead of
importing ``_active_monitoring_sessions/_live_consent/_live_frames`` directly.
Lazy imports avoid router↔service cycles.
"""

from __future__ import annotations

from typing import Any, List, Optional


def _mod():
    from deeptutor.api.routers import monitoring_session as _m

    return _m


def register_session(session_id: str, ws: Any) -> None:
    _mod()._active_monitoring_sessions[session_id] = ws


def unregister_session(session_id: str) -> None:
    _mod()._active_monitoring_sessions.pop(session_id, None)
    _mod()._frame_rings.pop(session_id, None)
    _mod()._purge_session_state(session_id)


def is_session_active(session_id: str) -> bool:
    return session_id in _mod()._active_monitoring_sessions


def list_active_sessions() -> List[str]:
    return list(_mod()._active_monitoring_sessions.keys())


def grant_consent(session_id: str) -> None:
    _mod()._live_consent.add(session_id)


def revoke_consent(session_id: str) -> None:
    _mod()._live_consent.discard(session_id)
    _mod()._live_frames.pop(session_id, None)


def has_consent(session_id: str) -> bool:
    return session_id in _mod()._live_consent


def list_consented_active() -> List[str]:
    m = _mod()
    return [sid for sid in m._live_consent if sid in m._active_monitoring_sessions]


def store_live_frame(session_id: str, jpeg_b64: str, ts: float) -> None:
    _mod()._live_frames[session_id] = (jpeg_b64, ts)


def get_live_frame(session_id: str) -> Optional[tuple[str, float]]:
    return _mod()._live_frames.get(session_id)


def purge_stale_frames() -> None:
    _mod()._purge_stale_frames()


def clear_all_live() -> None:
    m = _mod()
    m._live_consent.clear()
    m._live_frames.clear()


def get_frame_ring(session_id: str) -> List[str]:
    ring = _mod()._frame_rings.get(session_id, ())
    return list(ring)


__all__ = [
    "register_session",
    "unregister_session",
    "is_session_active",
    "list_active_sessions",
    "grant_consent",
    "revoke_consent",
    "has_consent",
    "list_consented_active",
    "store_live_frame",
    "get_live_frame",
    "purge_stale_frames",
    "clear_all_live",
    "get_frame_ring",
]
