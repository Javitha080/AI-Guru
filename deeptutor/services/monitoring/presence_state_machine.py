"""
AI Guru Hysteresis Presence State Machine.
==========================================

Manages student presence detection using 4 discrete states with temporal hysteresis:
- PRESENT: Student is seated at desk and visible.
- TEMPORARILY_NOT_VISIBLE: Student briefly out of frame (3-5s < t < 20s, e.g. picking up a pen).
- AWAY: Student has left study area (t >= 20s).
- UNKNOWN: Camera occluded or room too dark (mean luminance < 25).

Guarantees instant recovery to PRESENT upon face re-detection.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


class PresenceState(str, enum.Enum):
    PRESENT = "PRESENT"
    TEMPORARILY_NOT_VISIBLE = "TEMPORARILY_NOT_VISIBLE"
    AWAY = "AWAY"
    UNKNOWN = "UNKNOWN"


@dataclass
class PresenceTransitionEvent:
    """Record of a presence state transition."""
    from_state: PresenceState
    to_state: PresenceState
    timestamp: float
    duration_in_prev_state: float
    reason: str


@dataclass
class PresenceStateResult:
    """Current presence state snapshot."""
    state: PresenceState
    state_duration_seconds: float
    unobserved_duration_seconds: float
    is_present: bool
    state_changed: bool
    transition: Optional[PresenceTransitionEvent] = None


class PresenceStateMachine:
    """
    Temporal hysteresis state machine for student presence tracking.
    """

    DEFAULT_TEMP_ABSENT_THRESHOLD: float = 5.0   # Seconds absent before TEMPORARILY_NOT_VISIBLE
    DEFAULT_AWAY_THRESHOLD: float = 20.0          # Seconds absent before AWAY
    MIN_LUMINANCE_THRESHOLD: float = 20.0        # Luminance (0-255 scale) or 0.08 (0-1) below which is UNKNOWN

    def __init__(
        self,
        temp_absent_seconds: float = DEFAULT_TEMP_ABSENT_THRESHOLD,
        away_seconds: float = DEFAULT_AWAY_THRESHOLD,
        min_luminance: float = MIN_LUMINANCE_THRESHOLD,
    ) -> None:
        self.temp_absent_seconds = temp_absent_seconds
        self.away_seconds = away_seconds
        self.min_luminance = min_luminance

        self._current_state: PresenceState = PresenceState.UNKNOWN
        self._last_seen_timestamp: float = 0.0
        self._last_transition_timestamp: float = 0.0
        self._initialized: bool = False
        self._history: List[PresenceTransitionEvent] = []

    def reset(self, initial_timestamp: float = 0.0) -> None:
        """Reset state machine for a new session."""
        self._current_state = PresenceState.UNKNOWN
        self._last_seen_timestamp = initial_timestamp
        self._last_transition_timestamp = initial_timestamp
        self._initialized = False
        self._history.clear()

    @property
    def current_state(self) -> PresenceState:
        return self._current_state

    @property
    def history(self) -> List[PresenceTransitionEvent]:
        return list(self._history)

    def update(
        self,
        face_detected: bool,
        confidence: float = 1.0,
        timestamp: float = 0.0,
        brightness: float = 100.0,  # 0-255 scale or 0-1
    ) -> PresenceStateResult:
        """
        Evaluate new frame observation and transition presence state with hysteresis.
        """
        if not self._initialized:
            self._initialized = True
            self._last_transition_timestamp = timestamp
            self._last_seen_timestamp = timestamp if face_detected else (timestamp - 1.0)
            self._current_state = PresenceState.PRESENT if (face_detected and confidence >= 0.5) else PresenceState.UNKNOWN

        # Normalize brightness to 0-255 scale
        lum = brightness if brightness > 1.0 else (brightness * 255.0)

        prev_state = self._current_state
        state_changed = False
        transition_event: Optional[PresenceTransitionEvent] = None

        if lum < self.min_luminance and not face_detected:
            target_state = PresenceState.UNKNOWN
            reason = f"Room lighting too dark (luminance={lum:.1f})"
        elif face_detected and confidence >= 0.5:
            # Face re-detected: INSTANT transition to PRESENT
            self._last_seen_timestamp = timestamp
            target_state = PresenceState.PRESENT
            reason = "Face detected with valid confidence"
        else:
            # Face not observed: evaluate temporal hysteresis
            unobserved_sec = max(0.0, timestamp - self._last_seen_timestamp)
            if unobserved_sec >= self.away_seconds:
                target_state = PresenceState.AWAY
                reason = f"Student absent for {unobserved_sec:.1f}s (>= {self.away_seconds}s)"
            elif unobserved_sec >= self.temp_absent_seconds:
                target_state = PresenceState.TEMPORARILY_NOT_VISIBLE
                reason = f"Student temporarily unobserved for {unobserved_sec:.1f}s (>= {self.temp_absent_seconds}s)"
            else:
                # Still within grace window: keep prior state (or PRESENT)
                target_state = prev_state if prev_state != PresenceState.UNKNOWN else PresenceState.TEMPORARILY_NOT_VISIBLE
                reason = f"Within grace period ({unobserved_sec:.1f}s unobserved)"

        if target_state != prev_state:
            duration_in_prev = max(0.0, timestamp - self._last_transition_timestamp)
            transition_event = PresenceTransitionEvent(
                from_state=prev_state,
                to_state=target_state,
                timestamp=timestamp,
                duration_in_prev_state=round(duration_in_prev, 2),
                reason=reason,
            )
            self._history.append(transition_event)
            self._current_state = target_state
            self._last_transition_timestamp = timestamp
            state_changed = True
            logger.info("Presence transition: %s -> %s (%s)", prev_state.value, target_state.value, reason)

        state_duration = max(0.0, timestamp - self._last_transition_timestamp)
        unobserved_duration = 0.0 if face_detected else max(0.0, timestamp - self._last_seen_timestamp)

        return PresenceStateResult(
            state=self._current_state,
            state_duration_seconds=round(state_duration, 2),
            unobserved_duration_seconds=round(unobserved_duration, 2),
            is_present=(self._current_state == PresenceState.PRESENT),
            state_changed=state_changed,
            transition=transition_event,
        )
