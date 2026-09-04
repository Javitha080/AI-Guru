"""Central thresholds for the student-monitoring engine.

Single source of truth for every magic number previously scattered across
presence/distraction/warning/pose/liveness/outbox modules. Values are
frozen to current production behavior — this module only moves them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class MonitoringThresholds:
    # Presence FSM
    temp_absent_seconds: float = 5.0
    away_seconds: float = 20.0
    min_luminance: float = 20.0  # 0-255 scale (0.08 on 0-1 scale)

    # Distraction durations
    looking_away_seconds: float = 10.0
    phone_seconds: float = 4.0
    identity_mismatch_seconds: float = 15.0
    drowsiness_seconds: float = 4.0

    # Whitelist tolerances
    max_drinking_seconds: float = 6.0
    max_page_turn_seconds: float = 4.0
    max_posture_shift_seconds: float = 4.0

    # Continuous focus geometry
    yaw_full_range: float = 45.0
    pitch_full_range: float = 35.0
    yaw_neutral_band: float = 12.0
    pitch_neutral_band: float = 10.0
    min_gaze_factor: float = 0.35
    yaw_away_deg: float = 35.0
    pitch_up_deg: float = -20.0

    # Pose classification
    yaw_screen_deg: float = 25.0
    pitch_reading_min: float = 18.0
    pitch_reading_max: float = 55.0

    # Liveness
    ear_closed: float = 0.18
    ear_open: float = 0.25
    min_ear_variance: float = 0.0003
    min_motion_variance: float = 0.00005
    texture_flat: float = 30.0
    texture_moire: float = 800.0

    # Warnings
    warn_cooldown_seconds: float = 60.0
    warn_min_confidence: float = 0.80
    warn_max_per_window: int = 5
    warn_window_seconds: float = 600.0
    nudge_cooldown_seconds: float = 40.0
    nudge_min_seconds: float = 3.0
    nudge_max_seconds: float = 6.0

    # Evidence / outbox
    ring_size: int = 30
    ring_min_interval: float = 0.5
    frame_timestamp_max_lag: float = 300.0
    frame_timestamp_max_ahead: float = 5.0
    outbox_max_retries: int = 8
    outbox_base_backoff: float = 30.0
    outbox_max_backoff: float = 600.0
    outbox_stale_after: float = 3600.0


DEFAULT_THRESHOLDS = MonitoringThresholds()

# Parent strictness profiles: (cooldown_seconds, min_confidence).
STRICTNESS_PROFILES: Dict[str, Tuple[float, float]] = {
    "gentle": (90.0, 0.85),
    "balanced": (60.0, 0.80),
    "strict": (30.0, 0.75),
}


def strictness_for(name: str) -> Tuple[float, float]:
    """Return (cooldown, confidence) for a strictness profile name."""
    return STRICTNESS_PROFILES.get(name, STRICTNESS_PROFILES["balanced"])


__all__ = ["MonitoringThresholds", "DEFAULT_THRESHOLDS", "STRICTNESS_PROFILES", "strictness_for"]
