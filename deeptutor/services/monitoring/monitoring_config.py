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
    # Above MediaPipe landmark jitter on a printed photo (measured jitter
    # variance ~2e-6; old value 0.0003 was near it and could only flag
    # synthetic input). 0.001 stays ~450x above photo jitter while keeping a
    # genuinely live, still-reading student (EAR oscillation variance
    # ~1.2e-3) firmly on the live side.
    min_ear_variance: float = 0.001
    min_motion_variance: float = 0.0004
    texture_flat: float = 30.0
    texture_moire: float = 800.0
    # A blink within the last N seconds counts as liveness evidence —
    # concentrated readers drop to ~4 blinks/min, and an un-decayed
    # "ever blinked" flag made the static-photo branch dead after minute one.
    blink_recency_seconds: float = 30.0
    # Minimum observation seconds before the static-image (spoof) branch may
    # fire, so a brief still moment can never be judged a photograph.
    static_spoof_min_history_seconds: float = 10.0

    # Drowsiness (PERCLOS — percentage of eyelid closure over a window)
    perclos_window_seconds: float = 60.0
    perclos_threshold: float = 0.15
    eye_closure_closed_level: float = 0.6
    drowsiness_sustained_closed_seconds: float = 2.5
    yawn_open_level: float = 0.5
    yawn_sustained_seconds: float = 2.0
    personal_ear_baseline_seconds: float = 5.0
    personal_ear_closed_ratio: float = 0.6

    # Warnings
    warn_cooldown_seconds: float = 60.0
    warn_min_confidence: float = 0.80
    warn_max_per_window: int = 5
    warn_window_seconds: float = 600.0
    nudge_cooldown_seconds: float = 40.0
    nudge_min_seconds: float = 3.0
    nudge_max_seconds: float = 6.0
    # Nudges carry their own (lower) confidence gate: pending distractions
    # are emitted at confidence 0.80, so a strictness profile with
    # min_confidence 0.85 ("gentle") must not silently disable every nudge.
    nudge_min_confidence: float = 0.75

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
