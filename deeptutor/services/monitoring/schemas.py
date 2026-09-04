"""Canonical telemetry schemas for the monitoring engine.

One serializer for the ``telemetry_update`` WS shape previously built in
three places (browser_session, system_monitor, monitoring_core), plus
helpers for brightness normalization and pose/gaze payload parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


def canonical_brightness(value: Any, default: float = 0.5) -> float:
    """Normalize brightness to 0-1 canonical scale.

    Accepts 0-1 floats, 0-255 luminance, or garbage (→ default).
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v > 1.0:
        return max(0.0, min(1.0, v / 255.0))
    return max(0.0, min(1.0, v))


def parse_pose_gaze(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Return (pose_dict, gaze_dict) when both are present, else (None, None)."""
    pose = payload.get("pose")
    gaze = payload.get("gaze")
    if isinstance(pose, dict) and isinstance(gaze, dict):
        return pose, gaze
    return None, None


def build_pose_result(raw_p: Dict[str, Any]) -> Any:
    """Build HeadPoseResult from a raw pose dict (never raises on bad posture).

    Fail-closed: missing/invalid flags default to NOT facing / NOT reading so
    garbage payloads can never look focused.
    """
    from deeptutor.services.monitoring.pose_gaze import HeadPoseResult, PostureCategory

    if not isinstance(raw_p, dict):
        raw_p = {}
    posture_raw = raw_p.get("posture", PostureCategory.HEAD_CENTER.value)
    try:
        posture = PostureCategory(posture_raw)
    except ValueError:
        posture = PostureCategory.UNKNOWN
    def _f(key: str, default: float) -> float:
        try:
            v = float(raw_p.get(key, default))
        except (TypeError, ValueError):
            return default
        import math as _math

        return v if _math.isfinite(v) else default

    return HeadPoseResult(
        yaw=_f("yaw", 0.0),
        pitch=_f("pitch", 0.0),
        roll=_f("roll", 0.0),
        posture=posture,
        is_facing_screen=bool(raw_p.get("is_facing_screen", False)),
        is_reading_writing_pose=bool(raw_p.get("is_reading_writing_pose", False)),
    )


def build_gaze_result(raw_g: Dict[str, Any]) -> Any:
    """Build GazeResult from a raw gaze dict (fail-closed: not focused)."""
    from deeptutor.services.monitoring.pose_gaze import GazeResult

    if not isinstance(raw_g, dict):
        raw_g = {}
    def _f(key: str, default: float) -> float:
        try:
            v = float(raw_g.get(key, default))
        except (TypeError, ValueError):
            return default
        import math as _math

        return v if _math.isfinite(v) else default

    return GazeResult(
        gaze_x=_f("gaze_x", 0.0),
        gaze_y=_f("gaze_y", 0.0),
        is_focused=bool(raw_g.get("is_focused", False)),
        confidence=_f("confidence", 0.0),
    )


@dataclass
class TelemetryUpdate:
    """WS ``telemetry_update`` payload shared by both engine paths."""

    session_id: str
    timestamp: float
    presence: str
    focus_score: float
    engagement_score: float
    engagement_trend: str = "STABLE"
    posture: str = "HEAD_CENTER"
    is_distracted: bool = False
    whitelisted_action: Optional[str] = None
    fps: float = 0.0
    ear: Optional[float] = None
    warning: Optional[Dict[str, Any]] = field(default=None)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "type": "telemetry_update",
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "presence": self.presence,
            "focus_score": self.focus_score,
            "engagement_score": self.engagement_score,
            "engagement_trend": self.engagement_trend,
            "posture": self.posture,
            "is_distracted": self.is_distracted,
            "whitelisted_action": self.whitelisted_action,
            "fps": self.fps,
        }
        if self.ear is not None:
            data["ear"] = self.ear
        if self.warning is not None:
            data["warning"] = self.warning
        return data


__all__ = [
    "canonical_brightness",
    "parse_pose_gaze",
    "build_pose_result",
    "build_gaze_result",
    "TelemetryUpdate",
]
