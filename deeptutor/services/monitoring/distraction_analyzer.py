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
from typing import Optional

from deeptutor.services.monitoring.liveness_detector import LivenessResult
from deeptutor.services.monitoring.pose_gaze import HeadPoseResult, PostureCategory
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

    def __init__(self) -> None:
        self._looking_away_start: Optional[float] = None
        self._phone_start: Optional[float] = None
        self._mismatch_start: Optional[float] = None
        self._drowsiness_start: Optional[float] = None
        self._drinking_start: Optional[float] = None
        self._page_turn_start: Optional[float] = None
        self._posture_shift_start: Optional[float] = None
        self._away_start: Optional[float] = None

    def reset(self) -> None:
        """Reset all tracking timers."""
        self._looking_away_start = None
        self._phone_start = None
        self._mismatch_start = None
        self._drowsiness_start = None
        self._drinking_start = None
        self._page_turn_start = None
        self._posture_shift_start = None
        self._away_start = None

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
    ) -> DistractionAnalysisResult:
        """
        Analyze current frame and state for distractions, applying the false-positive whitelist.
        """
        # 1. State: AWAY -> Flagged (duration grows for the whole absence so
        # warnings and reports can tell a 20s bathroom trip from a 10-min walkaway)
        if presence_state == PresenceState.AWAY:
            if self._away_start is None:
                self._away_start = timestamp
            away_dur = timestamp - self._away_start
            return DistractionAnalysisResult(
                is_distracted=True,
                distraction_type=DistractionType.STUDENT_AWAY,
                focus_score=0.0,
                confidence=0.98,
                duration_seconds=round(away_dur, 1),
                whitelisted_action=None,
                reason="Student is away from study desk",
            )
        self._away_start = None

        # 2. Check Whitelisted Study Gestures FIRST (Priority 1)

        # A: Reading downwards or writing on desk
        if pose.is_reading_writing_pose or writing_gesture or pose.posture == PostureCategory.LOOKING_DOWN:
            action = WhitelistedAction.WRITING_NOTES if writing_gesture else WhitelistedAction.READING_DOWNWARDS
            self._looking_away_start = None  # Reset looking away timer
            return DistractionAnalysisResult(
                is_distracted=False,
                distraction_type=DistractionType.NONE,
                focus_score=100.0,
                confidence=0.95,
                duration_seconds=0.0,
                whitelisted_action=action,
                reason=f"Valid study behavior: {action.value.replace('_', ' ').title()}",
            )

        # B: Drinking water / beverage (< 6 seconds)
        if hand_to_mouth_gesture:
            if self._drinking_start is None:
                self._drinking_start = timestamp
            drink_dur = timestamp - self._drinking_start
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
            self._drinking_start = None

        # C: Page turning gesture (< 4 seconds)
        if page_turn_gesture:
            if self._page_turn_start is None:
                self._page_turn_start = timestamp
            pt_dur = timestamp - self._page_turn_start
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
            self._page_turn_start = None

        # D: Brief posture shift or stretch (< 4 seconds)
        if pose.posture == PostureCategory.HEAD_TILT or abs(pose.roll) > 20.0:
            if self._posture_shift_start is None:
                self._posture_shift_start = timestamp
            shift_dur = timestamp - self._posture_shift_start
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
            self._posture_shift_start = None

        # 3. Evaluate Flagged Distractions

        # A: Smartphone Interaction (> 4s)
        if phone_object_detected:
            if self._phone_start is None:
                self._phone_start = timestamp
            phone_dur = timestamp - self._phone_start
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
        else:
            self._phone_start = None

        # B: Identity Mismatch (> 15s)
        if not identity_match:
            if self._mismatch_start is None:
                self._mismatch_start = timestamp
            mismatch_dur = timestamp - self._mismatch_start
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
            self._mismatch_start = None

        # C: Drowsiness / Eyes Closed (> 4s)
        if liveness.ear > 0.0 and liveness.ear < 0.18:
            if self._drowsiness_start is None:
                self._drowsiness_start = timestamp
            drowsy_dur = timestamp - self._drowsiness_start
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
        else:
            self._drowsiness_start = None

        # D: Looking Away / Daydreaming (> 10s)
        is_looking_away = (abs(pose.yaw) > 35.0) or (pose.pitch < -20.0)
        if is_looking_away:
            if self._looking_away_start is None:
                self._looking_away_start = timestamp
            away_dur = timestamp - self._looking_away_start
            if away_dur >= self.LOOKING_AWAY_THRESHOLD:
                return DistractionAnalysisResult(
                    is_distracted=True,
                    distraction_type=DistractionType.LOOKING_AWAY,
                    focus_score=max(30.0, 100.0 - away_dur * 5.0),
                    confidence=0.88,
                    duration_seconds=round(away_dur, 1),
                    whitelisted_action=None,
                    reason=f"Looking away from study area for {away_dur:.1f}s",
                )
            else:
                # Still within threshold: slightly reduce focus score without flagging alert
                return DistractionAnalysisResult(
                    is_distracted=False,
                    distraction_type=DistractionType.NONE,
                    focus_score=max(70.0, 100.0 - away_dur * 3.0),
                    confidence=0.80,
                    duration_seconds=round(away_dur, 1),
                    whitelisted_action=None,
                    reason=f"Looking away ({away_dur:.1f}s / {self.LOOKING_AWAY_THRESHOLD}s threshold)",
                )
        else:
            self._looking_away_start = None

        # 4. Default: Focused on study
        return DistractionAnalysisResult(
            is_distracted=False,
            distraction_type=DistractionType.NONE,
            focus_score=100.0,
            confidence=0.95,
            duration_seconds=0.0,
            whitelisted_action=None,
            reason="Focused on study",
        )
