"""
AI Guru Warning and Alert Throttle Manager.
===========================================

Controls alert dispatching with:
- Strict 60-second cooldown per alert category to prevent warning spam
- Confidence threshold filtering (>= 0.80)
- Rate limiting (max warnings per interval)
- Structured warning event emissions

Guarantees 100% local execution.
"""

from __future__ import annotations

import collections
import logging
import uuid
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

from deeptutor.services.monitoring.distraction_analyzer import DistractionAnalysisResult, DistractionType

logger = logging.getLogger(__name__)


@dataclass
class WarningEvent:
    """Dispatched student warning event."""
    warning_id: str
    category: str
    message: str
    severity: str  # "info", "warning", "alert"
    timestamp: float
    confidence: float
    duration_seconds: float
    metadata: Dict[str, object] = field(default_factory=dict)


class WarningManager:
    """
    Manages alert throttling, confidence gating, and category cooldowns.
    """

    DEFAULT_COOLDOWN_SECONDS: float = 60.0
    MIN_CONFIDENCE_THRESHOLD: float = 0.80
    MAX_ALERTS_PER_WINDOW: int = 5
    WINDOW_SECONDS: float = 600.0  # 10 minutes

    # Friendly student-facing messages
    WARNING_MESSAGES: Dict[DistractionType, str] = {
        DistractionType.LOOKING_AWAY: "Let's bring our focus back to the study material! 📚",
        DistractionType.PHONE_DETECTED: "Please put your phone aside to maintain deep focus! 📱",
        DistractionType.STUDENT_AWAY: "Study timer paused. Welcome back when you're ready! ⏱️",
        DistractionType.IDENTITY_MISMATCH: "Different face detected. Please ensure the enrolled student is in view. 👤",
        DistractionType.DROWSINESS: "Feeling tired? Take a quick stretch or deep breath! ☕",
    }

    SEVERITY_LEVELS: Dict[DistractionType, str] = {
        DistractionType.LOOKING_AWAY: "warning",
        DistractionType.PHONE_DETECTED: "alert",
        DistractionType.STUDENT_AWAY: "info",
        DistractionType.IDENTITY_MISMATCH: "alert",
        DistractionType.DROWSINESS: "warning",
    }

    def __init__(
        self,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        min_confidence: float = MIN_CONFIDENCE_THRESHOLD,
    ) -> None:
        self.cooldown_seconds = cooldown_seconds
        self.min_confidence = min_confidence

        # Maps category/DistractionType string -> last emitted timestamp
        self._last_alert_timestamps: Dict[str, float] = {}
        # Sliding history of timestamps for window rate limiting
        self._alert_history: Deque[float] = collections.deque()
        self._emitted_warnings: List[WarningEvent] = []

    def reset(self) -> None:
        """Reset all cooldowns and warning histories."""
        self._last_alert_timestamps.clear()
        self._alert_history.clear()
        self._emitted_warnings.clear()

    def get_cooldown_remaining(self, category: str, current_time: float) -> float:
        """Return remaining cooldown seconds for a given category (0.0 if ready)."""
        if category not in self._last_alert_timestamps:
            return 0.0
        last_time = self._last_alert_timestamps[category]
        elapsed = current_time - last_time
        if elapsed < self.cooldown_seconds:
            return round(self.cooldown_seconds - elapsed, 1)
        return 0.0

    def evaluate_and_dispatch(
        self,
        timestamp: float,
        distraction: DistractionAnalysisResult,
    ) -> Optional[WarningEvent]:
        """
        Evaluate if a distraction meets confidence and cooldown criteria, and dispatch warning.
        Returns WarningEvent if issued, None if suppressed by cooldown or low confidence.
        """
        if not distraction.is_distracted or distraction.distraction_type == DistractionType.NONE:
            return None

        # 1. Confidence Gate
        if distraction.confidence < self.min_confidence:
            logger.debug(
                "Warning suppressed: confidence %.2f < %.2f threshold",
                distraction.confidence,
                self.min_confidence,
            )
            return None

        category = distraction.distraction_type.value

        # 2. Cooldown Gate
        cooldown_rem = self.get_cooldown_remaining(category, timestamp)
        if cooldown_rem > 0.0:
            logger.debug(
                "Warning '%s' suppressed by cooldown (%.1fs remaining)",
                category,
                cooldown_rem,
            )
            return None

        # 3. Window Rate Limit Gate
        # Prune older alerts outside window
        while self._alert_history and (timestamp - self._alert_history[0] > self.WINDOW_SECONDS):
            self._alert_history.popleft()

        if len(self._alert_history) >= self.MAX_ALERTS_PER_WINDOW:
            logger.info("Warning '%s' suppressed by 10-minute rate limit window", category)
            return None

        # 4. Construct and issue warning
        message = self.WARNING_MESSAGES.get(
            distraction.distraction_type,
            f"Attention needed: {distraction.reason}",
        )
        severity = self.SEVERITY_LEVELS.get(distraction.distraction_type, "warning")

        event = WarningEvent(
            warning_id=f"warn-{uuid.uuid4().hex[:8]}",
            category=category,
            message=message,
            severity=severity,
            timestamp=timestamp,
            confidence=round(distraction.confidence, 3),
            duration_seconds=round(distraction.duration_seconds, 1),
            metadata={
                "reason": distraction.reason,
                "focus_score": distraction.focus_score,
            },
        )

        self._last_alert_timestamps[category] = timestamp
        self._alert_history.append(timestamp)
        self._emitted_warnings.append(event)

        logger.info("Dispatched study warning [%s]: %s (severity=%s)", category, message, severity)
        return event

    def get_all_warnings(self) -> List[WarningEvent]:
        """Return all warnings emitted during session."""
        return list(self._emitted_warnings)
