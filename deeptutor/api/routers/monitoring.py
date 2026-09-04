"""
AI Guru Study Monitoring API Router — Aggregation Shim.
=======================================================

This module is the backward-compatible entry point for the monitoring router.
It was refactored from a 930-line monolith into three focused sub-routers:

- ``monitoring_core``    — enroll-face, verify-liveness, analyze-frame, status
- ``monitoring_camera``  — camera status/config, snapshot, MJPEG feed, probe
- ``monitoring_session`` — WebSocket session, live consent/frame, events

The combined ``router`` object aggregates all three so that ``api/main.py``
continues to mount a single ``monitoring.router`` with no changes.

**Re-exports** for backward compatibility:
- ``parent.py`` (6 lazy import sites) and ``telegram_command_listener.py``
  (5 lazy import sites) import shared state globals from this module.
- ``test_monitoring_feed_e2e.py`` imports endpoint functions directly.
All re-exports reference the *same Python objects* so mutations propagate.
"""

from __future__ import annotations

from fastapi import APIRouter

from deeptutor.api.routers.monitoring_camera import router as _camera_router
from deeptutor.api.routers.monitoring_core import router as _core_router
from deeptutor.api.routers.monitoring_session import router as _session_router

# Combined router — mounted by api/main.py as monitoring.router
router = APIRouter(tags=["monitoring"])
router.include_router(_core_router)
router.include_router(_camera_router)
router.include_router(_session_router)

# ═══════════════════════════════════════════════════════════════════════════════
# BACKWARD-COMPATIBLE RE-EXPORTS
# These symbols are imported by parent.py, telegram_command_listener.py,
# and test files via ``from deeptutor.api.routers.monitoring import ...``.
# They must resolve to the canonical instances owned by monitoring_session.py.
# ═══════════════════════════════════════════════════════════════════════════════

# Endpoint functions for test_monitoring_feed_e2e.py
from deeptutor.api.routers.monitoring_camera import (  # noqa: F401, E402
    get_camera_snapshot,
    monitoring_feed,
)

# Shared state for parent.py & telegram_command_listener.py
# (Deprecated: prefer deeptutor.services.monitoring.session_registry accessors.
# Kept so existing imports keep resolving to the canonical objects.)
from deeptutor.api.routers.monitoring_session import (  # noqa: F401, E402
    _active_monitoring_sessions,
    _extract_frame,
    _frame_rings,
    _live_consent,
    _live_frames,
    _purge_session_state,
    _purge_stale_frames,
)

# Preferred accessor API (new code should import from session_registry).
from deeptutor.services.monitoring.session_registry import (  # noqa: F401, E402
    clear_all_live,
    get_live_frame,
    grant_consent,
    has_consent,
    is_session_active,
    list_active_sessions,
    list_consented_active,
    revoke_consent,
)
