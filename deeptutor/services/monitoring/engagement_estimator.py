"""
AI Guru Real-Time Engagement Estimator.
=======================================

Computes a continuous 0-100 student engagement score from:
- Visual gaze alignment and desk/screen attention
- Head pose stability and micro-dynamics
- Ergonomic study posture
- Presence state machine status

Uses Exponential Moving Average (EMA) smoothing for stability.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
import logging
from typing import Deque, Tuple

from deeptutor.services.monitoring.pose_gaze import HeadPoseResult, PostureCategory
from deeptutor.services.monitoring.presence_state_machine import PresenceState

logger = logging.getLogger(__name__)


@dataclass
class EngagementSnapshot:
    """Engagement metrics snapshot."""

    score: float  # 0.0 to 100.0 smoothed engagement score
    instantaneous_score: float  # Unsmoothed frame score
    gaze_factor: float  # 0.0 to 1.0
    posture_factor: float  # 0.0 to 1.0
    stability_factor: float  # 0.0 to 1.0
    trend: str  # "STABLE", "RISING", "FALLING"


class EngagementEstimator:
    """
    Continuous student engagement estimator with dual-rate EMA smoothing:
    attention drops are reacted to fast (α=0.25), recovery is gradual (α=0.10).
    """

    EMA_ALPHA: float = 0.15  # Neutral smoothing (~2-3s response)
    FAST_DECAY_ALPHA: float = 0.25  # Focus dropping — react quickly
    SLOW_RECOVERY_ALPHA: float = 0.10  # Focus returning — gradual rebuild

    def __init__(self, ema_alpha: float = EMA_ALPHA) -> None:
        self.ema_alpha = ema_alpha
        self._smoothed_score: float = 100.0
        self._pose_history: Deque[Tuple[float, float, float]] = collections.deque(maxlen=20)
        self._score_history: Deque[float] = collections.deque(maxlen=10)

    def reset(self) -> None:
        """Reset engagement state to baseline 100.0."""
        self._smoothed_score = 100.0
        self._pose_history.clear()
        self._score_history.clear()

    def update(
        self,
        presence_state: PresenceState,
        pose: HeadPoseResult,
        gaze_focused: bool,
        is_distracted: bool = False,
    ) -> EngagementSnapshot:
        """
        Calculate and return updated engagement metrics for the current frame.
        """
        if presence_state == PresenceState.AWAY:
            instant_score = 0.0
            gaze_factor = 0.0
            posture_factor = 0.0
            stability_factor = 0.0
        elif presence_state == PresenceState.TEMPORARILY_NOT_VISIBLE:
            instant_score = 60.0
            gaze_factor = 0.5
            posture_factor = 0.6
            stability_factor = 0.7
        elif presence_state == PresenceState.UNKNOWN:
            instant_score = 50.0
            gaze_factor = 0.5
            posture_factor = 0.5
            stability_factor = 0.5
        else:
            # 1. Gaze Factor (0.0 to 1.0)
            if gaze_focused or pose.is_reading_writing_pose or pose.is_facing_screen:
                gaze_factor = 1.0
            elif abs(pose.yaw) < 30.0 and pose.pitch > -10.0:
                gaze_factor = 0.8
            else:
                gaze_factor = max(0.2, 1.0 - (abs(pose.yaw) / 90.0))

            # 2. Posture Factor (0.0 to 1.0)
            if pose.posture in (PostureCategory.HEAD_CENTER, PostureCategory.LOOKING_DOWN):
                posture_factor = 1.0
            elif pose.posture == PostureCategory.HEAD_TILT:
                posture_factor = 0.85
            elif pose.posture == PostureCategory.SLOUCHING:
                posture_factor = 0.60
            elif pose.posture in (PostureCategory.LOOKING_LEFT, PostureCategory.LOOKING_RIGHT):
                posture_factor = 0.40
            else:
                posture_factor = 0.70

            # 3. Stability Factor (0.0 to 1.0)
            self._pose_history.append((pose.yaw, pose.pitch, pose.roll))
            stability_factor = self._compute_stability()

            # Base instantaneous score
            # Weights: Gaze (45%), Posture (35%), Stability (20%)
            instant_score = gaze_factor * 45.0 + posture_factor * 35.0 + stability_factor * 20.0

            if is_distracted:
                instant_score = max(0.0, instant_score - 40.0)

        # Dual-rate EMA smoothing: fast decay on drops, gradual recovery.
        alpha = self.ema_alpha
        if instant_score < self._smoothed_score - 5.0:
            alpha = self.FAST_DECAY_ALPHA
        elif instant_score > self._smoothed_score + 2.0:
            alpha = self.SLOW_RECOVERY_ALPHA
        self._smoothed_score = alpha * instant_score + (1.0 - alpha) * self._smoothed_score
        self._smoothed_score = max(0.0, min(100.0, self._smoothed_score))

        # Determine trend
        self._score_history.append(self._smoothed_score)
        trend = "STABLE"
        if len(self._score_history) >= 5:
            delta = self._score_history[-1] - self._score_history[0]
            if delta > 3.0:
                trend = "RISING"
            elif delta < -3.0:
                trend = "FALLING"

        return EngagementSnapshot(
            score=round(self._smoothed_score, 1),
            instantaneous_score=round(instant_score, 1),
            gaze_factor=round(gaze_factor, 3),
            posture_factor=round(posture_factor, 3),
            stability_factor=round(stability_factor, 3),
            trend=trend,
        )

    def _compute_stability(self) -> float:
        """Compute head pose stability factor from recent history (all axes)."""
        if len(self._pose_history) < 3:
            return 1.0

        h = list(self._pose_history)
        # Combined RMS of yaw + pitch + roll inter-frame deltas so vertical
        # head-bobbing and lateral fidgeting are properly penalised.
        yaw_deltas = [abs(h[i][0] - h[i - 1][0]) for i in range(1, len(h))]
        pitch_deltas = [abs(h[i][1] - h[i - 1][1]) for i in range(1, len(h))]
        roll_deltas = [abs(h[i][2] - h[i - 1][2]) for i in range(1, len(h))]
        combined = [(y + p + r) / 3.0 for y, p, r in zip(yaw_deltas, pitch_deltas, roll_deltas)]
        avg_motion = sum(combined) / len(combined)

        # Steady study micro-movements: < 2.5 degrees/frame = high stability (1.0)
        # Erratic fast turning (> 10 deg/frame) = lower stability
        if avg_motion < 2.5:
            return 1.0
        elif avg_motion < 8.0:
            return max(0.5, 1.0 - (avg_motion - 2.5) / 10.0)
        else:
            return 0.3
