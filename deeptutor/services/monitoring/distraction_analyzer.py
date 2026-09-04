"""
AI Guru Distraction Analyzer with False-Positive Whitelist Filter.
==================================================================

Detects study distractions while strictly whitelisting valid study behaviors:
- Whitelisted (NO alert, Focus = 100%):
  * Reading downwards in textbook
  * Writing and taking notes
  * Turning book pages
  * Drinking water / beverage
  * Normal posture shifts and stretches
- Flagged Distractions:
  * Prolonged looking away (> 10s)
  * Smartphone / device interaction (> 3-5s)
  * Leaving desk (AWAY state)
  * Face identity mismatch
  * Drowsiness / sleeping (eyes closed > 4s)

Guarantees 100% local execution.
"""

from __future__ import annotations

from dataclasses import dataclass
import enum
import logging
from typing import Dict, Optional

from deeptutor.services.monitoring.liveness_detector import LivenessResult
from deeptutor.services.monitoring.pose_gaze import GazeResult, HeadPoseResult
from deeptutor.services.monitoring.presence_state_machine import PresenceState

logger = logging.getLogger(__name__)


class DistractionType(str, enum.Enum):
    NONE = "NONE"
    LOOKING_AWAY = "LOOKING_AWAY"
    PHONE_DETECTED = "PHONE_DETECTED"
    STUDENT_AWAY = "STUDENT_AWAY"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    DROWSINESS = "DROWSINESS"


class WhitelistedAction(str, enum.Enum):
    READING_DOWNWARDS = "READING_DOWNWARDS"
    WRITING_NOTES = "WRITING_NOTES"
    TURNING_PAGES = "TURNING_PAGES"
    DRINKING_WATER = "DRINKING_WATER"
    POSTURE_SHIFT = "POSTURE_SHIFT"


@dataclass
class DistractionAnalysisResult:
    """Detailed distraction analysis and false-positive evaluation result."""
    is_distracted: bool
    distraction_type: DistractionType
    focus_score: float                # 0.0 to 100.0
    confidence: float                 # 0.0 to 1.0
    duration_seconds: float
    whitelisted_action: Optional[WhitelistedAction] = None
    reason: str = ""
    # A distraction still BUILDING below its alert threshold (e.g. looking
    # away for 4s). Lets the nudge tier act early without flipping
    # ``is_distracted`` (whose contract many consumers depend on).
    pending_distraction_type: Optional[DistractionType] = None


class DistractionAnalyzer:
    """
    Distraction detection engine with rigorous false-positive study gesture filter.
    """

    # Time thresholds for flagging distractions (seconds)
    LOOKING_AWAY_THRESHOLD: float = 10.0
    PHONE_DETECTED_THRESHOLD: float = 4.0
    IDENTITY_MISMATCH_THRESHOLD: float = 15.0
    DROWSINESS_THRESHOLD: float = 4.0

    # Whitelist duration tolerances
    MAX_DRINKING_DURATION: float = 6.0
    MAX_PAGE_TURN_DURATION: float = 4.0
    MAX_POSTURE_SHIFT_DURATION: float = 4.0

    # Continuous (quadratic) focus normalization angles — focus degrades
    # smoothly as the head drifts instead of dropping off a binary cliff.
    # Inside the neutral band (natural seated micro-movement) focus stays 100.
    YAW_FULL_RANGE: float = 45.0
    PITCH_FULL_RANGE: float = 35.0
    YAW_NEUTRAL_BAND: float = 12.0
    PITCH_NEUTRAL_BAND: float = 10.0
    MIN_GAZE_FACTOR: float = 0.35

    def __init__(self) -> None:
        self._timers: Dict[str, Optional[float]] = {
            "looking_away": None,
            "phone": None,
            "mismatch": None,
            "drowsiness": None,
            "drinking": None,
            "page_turn": None,
            "posture_shift": None,
            "away": None,
        }

    # Backward-compat shims (pre-refactor attribute names).
    @property
    def _looking_away_start(self) -> Optional[float]:
        return self._timers["looking_away"]

    @_looking_away_start.setter
    def _looking_away_start(self, v: Optional[float]) -> None:
        self._timers["looking_away"] = v

    @property
    def _phone_start(self) -> Optional[float]:
        return self._timers["phone"]

    @_phone_start.setter
    def _phone_start(self, v: Optional[float]) -> None:
        self._timers["phone"] = v

    @property
    def _mismatch_start(self) -> Optional[float]:
        return self._timers["mismatch"]

    @_mismatch_start.setter
    def _mismatch_start(self, v: Optional[float]) -> None:
        self._timers["mismatch"] = v

    @property
    def _drowsiness_start(self) -> Optional[float]:
        return self._timers["drowsiness"]

    @_drowsiness_start.setter
    def _drowsiness_start(self, v: Optional[float]) -> None:
        self._timers["drowsiness"] = v

    @property
    def _drinking_start(self) -> Optional[float]:
        return self._timers["drinking"]

    @_drinking_start.setter
    def _drinking_start(self, v: Optional[float]) -> None:
        self._timers["drinking"] = v

    @property
    def _page_turn_start(self) -> Optional[float]:
        return self._timers["page_turn"]

    @_page_turn_start.setter
    def _page_turn_start(self, v: Optional[float]) -> None:
        self._timers["page_turn"] = v

    @property
    def _posture_shift_start(self) -> Optional[float]:
        return self._timers["posture_shift"]

    @_posture_shift_start.setter
    def _posture_shift_start(self, v: Optional[float]) -> None:
        self._timers["posture_shift"] = v

    @property
    def _away_start(self) -> Optional[float]:
        return self._timers["away"]

    @_away_start.setter
    def _away_start(self, v: Optional[float]) -> None:
        self._timers["away"] = v

    def _since(self, key: str, timestamp: float) -> float:
        """Start timer on first sight, return elapsed seconds."""
        started = self._timers.get(key)
        if started is None:
            self._timers[key] = timestamp
            return 0.0
        return max(0.0, timestamp - started)

    def _clear(self, key: str) -> None:
        self._timers[key] = None

    def reset(self) -> None:
        """Reset all tracking timers."""
        for key in self._timers:
            self._timers[key] = None

    def check_whitelist(
        self,
        timestamp: float,
        pose: HeadPoseResult,
        writing_gesture: bool,
        hand_to_mouth_gesture: bool,
        page_turn_gesture: bool,
    ) -> Optional[DistractionAnalysisResult]:
        """Return whitelisted-study result when matched, else None."""
        from deeptutor.services.monitoring.pose_gaze import PostureCategory as _Posture

        if pose.is_reading_writing_pose or writing_gesture or pose.posture == _Posture.LOOKING_DOWN:
            action = WhitelistedAction.WRITING_NOTES if writing_gesture else WhitelistedAction.READING_DOWNWARDS
            self._clear("looking_away")
            return DistractionAnalysisResult(
                is_distracted=False,
                distraction_type=DistractionType.NONE,
                focus_score=100.0,
                confidence=0.95,
                duration_seconds=0.0,
                whitelisted_action=action,
                reason=f"Valid study behavior: {action.value.replace('_', ' ').title()}",
            )
        if hand_to_mouth_gesture:
            drink_dur = self._since("drinking", timestamp)
            if drink_dur <= self.MAX_DRINKING_DURATION:
                return DistractionAnalysisResult(
                    is_distracted=False,
                    distraction_type=DistractionType.NONE,
                    focus_score=100.0,
                    confidence=0.90,
                    duration_seconds=drink_dur,
                    whitelisted_action=WhitelistedAction.DRINKING_WATER,
                    reason="Student taking a sip of water (Whitelisted)",
                )
        else:
            self._clear("drinking")
        if page_turn_gesture:
            pt_dur = self._since("page_turn", timestamp)
            if pt_dur <= self.MAX_PAGE_TURN_DURATION:
                return DistractionAnalysisResult(
                    is_distracted=False,
                    distraction_type=DistractionType.NONE,
                    focus_score=100.0,
                    confidence=0.90,
                    duration_seconds=pt_dur,
                    whitelisted_action=WhitelistedAction.TURNING_PAGES,
                    reason="Turning textbook page (Whitelisted)",
                )
        else:
            self._clear("page_turn")
        if pose.posture == _Posture.HEAD_TILT or abs(pose.roll) > 20.0:
            shift_dur = self._since("posture_shift", timestamp)
            if shift_dur <= self.MAX_POSTURE_SHIFT_DURATION:
                return DistractionAnalysisResult(
                    is_distracted=False,
                    distraction_type=DistractionType.NONE,
                    focus_score=95.0,
                    confidence=0.85,
                    duration_seconds=shift_dur,
                    whitelisted_action=WhitelistedAction.POSTURE_SHIFT,
                    reason="Normal posture shift / stretch (Whitelisted)",
                )
        else:
            self._clear("posture_shift")
        return None

    def analyze(
        self,
        timestamp: float,
        presence_state: PresenceState,
        pose: HeadPoseResult,
        liveness: LivenessResult,
        identity_match: bool,
        phone_object_detected: bool = False,
        hand_to_mouth_gesture: bool = False,
        page_turn_gesture: bool = False,
        writing_gesture: bool = False,
        gaze: Optional[GazeResult] = None,
    ) -> DistractionAnalysisResult:
        """
        Analyze current frame and state for distractions, applying the false-positive whitelist.
        ``gaze`` is optional; when provided it modulates the continuous focus score.
        """
        # 1. State: AWAY -> Flagged (duration grows for the whole absence so
        # warnings and reports can tell a 20s bathroom trip from a 10-min walkaway)
        if presence_state == PresenceState.AWAY:
            away_dur = self._since("away", timestamp)
            return DistractionAnalysisResult(
                is_distracted=True,
                distraction_type=DistractionType.STUDENT_AWAY,
                focus_score=0.0,
                confidence=0.98,
                duration_seconds=round(away_dur, 1),
                whitelisted_action=None,
                reason="Student is away from study desk",
            )
        self._clear("away")

        # 2. Check Whitelisted Study Gestures FIRST (Priority 1)
        whitelisted = self.check_whitelist(
            timestamp, pose, writing_gesture, hand_to_mouth_gesture, page_turn_gesture
        )
        if whitelisted is not None:
            return whitelisted

        # 3. Evaluate Flagged Distractions

        # Continuous quadratic focus: Focus = 100·(1−(|yaw|/45)²)·(1−(|pitch|/35)²)·GazeFactor.
        # Sub-threshold head drift degrades the score smoothly instead of
        # sitting at a flat 100 until a binary threshold trips.
        gaze_factor = self._gaze_factor(gaze)
        yaw_term = self._quadratic_term(pose.yaw, self.YAW_NEUTRAL_BAND, self.YAW_FULL_RANGE)
        pitch_term = self._quadratic_term(pose.pitch, self.PITCH_NEUTRAL_BAND, self.PITCH_FULL_RANGE)
        continuous_focus = round(max(0.0, min(100.0, 100.0 * yaw_term * pitch_term * gaze_factor)), 1)

        # A: Smartphone Interaction (> 4s)
        if phone_object_detected:
            phone_dur = self._since("phone", timestamp)
            if phone_dur >= self.PHONE_DETECTED_THRESHOLD:
                return DistractionAnalysisResult(
                    is_distracted=True,
                    distraction_type=DistractionType.PHONE_DETECTED,
                    focus_score=20.0,
                    confidence=0.92,
                    duration_seconds=round(phone_dur, 1),
                    whitelisted_action=None,
                    reason=f"Smartphone detected for {phone_dur:.1f}s",
                )
            return DistractionAnalysisResult(
                is_distracted=False,
                distraction_type=DistractionType.NONE,
                focus_score=continuous_focus,
                confidence=0.80,
                duration_seconds=round(phone_dur, 1),
                whitelisted_action=None,
                reason=f"Phone visible ({phone_dur:.1f}s / {self.PHONE_DETECTED_THRESHOLD}s threshold)",
                pending_distraction_type=DistractionType.PHONE_DETECTED,
            )
        else:
            self._clear("phone")

        # B: Identity Mismatch (> 15s)
        if not identity_match:
            mismatch_dur = self._since("mismatch", timestamp)
            if mismatch_dur >= self.IDENTITY_MISMATCH_THRESHOLD:
                return DistractionAnalysisResult(
                    is_distracted=True,
                    distraction_type=DistractionType.IDENTITY_MISMATCH,
                    focus_score=10.0,
                    confidence=0.95,
                    duration_seconds=round(mismatch_dur, 1),
                    whitelisted_action=None,
                    reason=f"Face identity does not match enrolled student ({mismatch_dur:.1f}s)",
                )
        else:
            self._clear("mismatch")

        # C: Drowsiness / Eyes Closed (> 4s)
        if liveness.ear > 0.0 and liveness.ear < 0.18:
            drowsy_dur = self._since("drowsiness", timestamp)
            if drowsy_dur >= self.DROWSINESS_THRESHOLD:
                return DistractionAnalysisResult(
                    is_distracted=True,
                    distraction_type=DistractionType.DROWSINESS,
                    focus_score=15.0,
                    confidence=0.90,
                    duration_seconds=round(drowsy_dur, 1),
                    whitelisted_action=None,
                    reason=f"Student eyes closed for {drowsy_dur:.1f}s (drowsiness)",
                )
            return DistractionAnalysisResult(
                is_distracted=False,
                distraction_type=DistractionType.NONE,
                focus_score=continuous_focus,
                confidence=0.80,
                duration_seconds=round(drowsy_dur, 1),
                whitelisted_action=None,
                reason=f"Eyes closing ({drowsy_dur:.1f}s / {self.DROWSINESS_THRESHOLD}s threshold)",
                pending_distraction_type=DistractionType.DROWSINESS,
            )
        else:
            self._clear("drowsiness")

        # D: Looking Away / Daydreaming (> 10s)
        is_looking_away = (abs(pose.yaw) > 35.0) or (pose.pitch < -20.0)
        if is_looking_away:
            away_dur = self._since("looking_away", timestamp)
            if away_dur >= self.LOOKING_AWAY_THRESHOLD:
                return DistractionAnalysisResult(
                    is_distracted=True,
                    distraction_type=DistractionType.LOOKING_AWAY,
                    focus_score=max(10.0, min(float(continuous_focus), 100.0 - away_dur * 5.0)),
                    confidence=0.88,
                    duration_seconds=round(away_dur, 1),
                    whitelisted_action=None,
                    reason=f"Looking away from study area for {away_dur:.1f}s",
                )
            else:
                # Still within threshold: smooth quadratic degradation, no alert yet
                return DistractionAnalysisResult(
                    is_distracted=False,
                    distraction_type=DistractionType.NONE,
                    focus_score=max(30.0, continuous_focus),
                    confidence=0.80,
                    duration_seconds=round(away_dur, 1),
                    whitelisted_action=None,
                    reason=f"Looking away ({away_dur:.1f}s / {self.LOOKING_AWAY_THRESHOLD}s threshold)",
                    pending_distraction_type=DistractionType.LOOKING_AWAY,
                )
        else:
            self._clear("looking_away")

        # 4. Default: Focused on study (continuous score reflects micro-drift)
        return DistractionAnalysisResult(
            is_distracted=False,
            distraction_type=DistractionType.NONE,
            focus_score=continuous_focus,
            confidence=0.95,
            duration_seconds=0.0,
            whitelisted_action=None,
            reason="Focused on study",
        )

    @classmethod
    def _gaze_factor(cls, gaze: Optional[GazeResult]) -> float:
        """Gaze modulation of the continuous score (1.0 when no gaze signal)."""
        if gaze is None:
            return 1.0
        if gaze.is_focused:
            return 1.0
        deviation = max(abs(gaze.gaze_x), abs(gaze.gaze_y))
        return max(cls.MIN_GAZE_FACTOR, 1.0 - deviation)

    @staticmethod
    def _quadratic_term(angle: float, neutral_band: float, full_range: float) -> float:
        """Smooth dead-banded quadratic falloff for one axis.

        1.0 inside the neutral band, decaying quadratically to 0.0 at
        ``full_range`` — continuous at the band edge.
        """
        magnitude = abs(angle)
        if magnitude <= neutral_band:
            return 1.0
        if magnitude >= full_range:
            return 0.0
        effective = (magnitude - neutral_band) / (full_range - neutral_band)
        return 1.0 - effective * effective
