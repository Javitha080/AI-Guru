"""
AI Guru Distraction Analyzer with False-Positive Whitelist Filter.
==================================================================

Detects study distractions while strictly whitelisting valid study behaviors.

Priority order (hard signals BEFORE the whitelist — a phone on the desk IS
the reading pose, an impostor looking down must never be whitelisted, and a
student asleep face-down classifies as READING_DOWNWARDS):

1. AWAY (student absent)
2. PHONE_DETECTED   (smartphone visible > 4s)
3. IDENTITY_MISMATCH (face != enrolled student > 15s)
4. DROWSINESS       (PERCLOS > 15% / eyes closed > 2.5s / yawn > 2s)
5. Whitelist: reading downwards, writing, page turns, drinking, stretches
6. LOOKING_AWAY     (> 10s)

Guarantees 100% local execution.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
import enum
import logging
from typing import Deque, Dict, List, Optional, Tuple

from deeptutor.services.monitoring.liveness_detector import LivenessResult
from deeptutor.services.monitoring.monitoring_config import DEFAULT_THRESHOLDS
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
    focus_score: float  # 0.0 to 100.0
    confidence: float  # 0.0 to 1.0
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

    # Time thresholds for flagging distractions (seconds) — defaults mirror
    # monitoring_config.DEFAULT_THRESHOLDS (single source of truth).
    LOOKING_AWAY_THRESHOLD: float = DEFAULT_THRESHOLDS.looking_away_seconds
    PHONE_DETECTED_THRESHOLD: float = DEFAULT_THRESHOLDS.phone_seconds
    IDENTITY_MISMATCH_THRESHOLD: float = DEFAULT_THRESHOLDS.identity_mismatch_seconds
    DROWSINESS_THRESHOLD: float = DEFAULT_THRESHOLDS.drowsiness_seconds

    # Whitelist duration tolerances
    MAX_DRINKING_DURATION: float = DEFAULT_THRESHOLDS.max_drinking_seconds
    MAX_PAGE_TURN_DURATION: float = DEFAULT_THRESHOLDS.max_page_turn_seconds
    MAX_POSTURE_SHIFT_DURATION: float = DEFAULT_THRESHOLDS.max_posture_shift_seconds

    # Continuous (quadratic) focus normalization angles — focus degrades
    # smoothly as the head drifts instead of dropping off a binary cliff.
    # Inside the neutral band (natural seated micro-movement) focus stays 100.
    YAW_FULL_RANGE: float = DEFAULT_THRESHOLDS.yaw_full_range
    PITCH_FULL_RANGE: float = DEFAULT_THRESHOLDS.pitch_full_range
    YAW_NEUTRAL_BAND: float = DEFAULT_THRESHOLDS.yaw_neutral_band
    PITCH_NEUTRAL_BAND: float = DEFAULT_THRESHOLDS.pitch_neutral_band
    MIN_GAZE_FACTOR: float = DEFAULT_THRESHOLDS.min_gaze_factor
    YAW_AWAY_DEG: float = DEFAULT_THRESHOLDS.yaw_away_deg
    PITCH_UP_DEG: float = DEFAULT_THRESHOLDS.pitch_up_deg

    # --- PERCLOS drowsiness (replaces the fixed EAR<0.18 rule) -----------
    # PERCLOS: fraction of eye-closed samples over a sliding window. A
    # reader's spontaneous blinks contribute ~3-6%; drowsy hovering near
    # ~15%+; sustained closure is the immediate cue.
    PERCLOS_WINDOW_S: float = DEFAULT_THRESHOLDS.perclos_window_seconds
    PERCLOS_THRESHOLD: float = DEFAULT_THRESHOLDS.perclos_threshold
    CLOSED_LEVEL: float = DEFAULT_THRESHOLDS.eye_closure_closed_level
    SUSTAINED_CLOSED_S: float = DEFAULT_THRESHOLDS.drowsiness_sustained_closed_seconds
    YAWN_LEVEL: float = DEFAULT_THRESHOLDS.yawn_open_level
    YAWN_SUSTAINED_S: float = DEFAULT_THRESHOLDS.yawn_sustained_seconds
    PERSONAL_EAR_BASELINE_S: float = DEFAULT_THRESHOLDS.personal_ear_baseline_seconds
    PERSONAL_EAR_CLOSED_RATIO: float = DEFAULT_THRESHOLDS.personal_ear_closed_ratio
    # EAR above which a sample can contribute to the personal open-eye
    # baseline (excludes fully-closed/blinking frames from the median).
    EAR_OPEN_FLOOR: float = 0.10
    # Absolute fallback when no personal baseline exists yet (pre-baseline
    # frames only; the fixed-cut era is over for established baselines).
    EAR_CLOSED_THRESHOLD: float = DEFAULT_THRESHOLDS.ear_closed

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
        # (timestamp, eyes_closed) samples feeding the PERCLOS window.
        self._closure_hist: Deque[Tuple[float, bool]] = collections.deque()
        # (timestamp, ear) samples used to lock the personal open-eye baseline.
        self._ear_baseline_hist: Deque[Tuple[float, float]] = collections.deque()
        self._ear_baseline: Optional[float] = None
        self._last_yawn_start: Optional[float] = None

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

    # ------------------------------------------------------------ PERCLOS

    def _observe_eyes(
        self, timestamp: float, liveness: LivenessResult, eye_closure: Optional[float]
    ) -> bool:
        """Feed one frame's eye state; returns True when eyes are closed.

        Prefers the MediaPipe blendshape closure (per-person normalized by the
        model); falls back to EAR against the student's PERSONAL open-eye
        baseline — a fixed 0.18 cut flagged squinting readers as drowsy.
        """
        ear = float(liveness.ear or 0.0)
        self._maintain_ear_baseline(timestamp, ear)

        if eye_closure is not None:
            closed = eye_closure >= self.CLOSED_LEVEL
        elif self._ear_baseline is not None and ear > 0.0:
            closed = ear < self._ear_baseline * self.PERSONAL_EAR_CLOSED_RATIO
        elif ear > 0.0:
            closed = ear < self.EAR_CLOSED_THRESHOLD
        else:
            return False

        self._closure_hist.append((timestamp, closed))
        while self._closure_hist and timestamp - self._closure_hist[0][0] > self.PERCLOS_WINDOW_S:
            self._closure_hist.popleft()
        return closed

    def _maintain_ear_baseline(self, timestamp: float, ear: float) -> None:
        """Lock a personal open-eye EAR baseline from the first seconds of data."""
        if self._ear_baseline is not None:
            return
        if ear <= self.EAR_OPEN_FLOOR:
            return
        self._ear_baseline_hist.append((timestamp, ear))
        # Enough samples AND enough wall time before we trust the median.
        if len(self._ear_baseline_hist) < 10:
            return
        span = timestamp - self._ear_baseline_hist[0][0]
        if span < self.PERSONAL_EAR_BASELINE_S:
            return
        self._ear_baseline = _median([e for _, e in self._ear_baseline_hist])

    def _perclos(self, now: float) -> float:
        """Fraction of eye-closed samples inside the sliding window."""
        while self._closure_hist and now - self._closure_hist[0][0] > self.PERCLOS_WINDOW_S:
            self._closure_hist.popleft()
        if len(self._closure_hist) < 10:
            return 0.0
        return sum(1 for _, c in self._closure_hist if c) / len(self._closure_hist)

    def _yawn_sustained(self, timestamp: float, jaw_open: Optional[float]) -> bool:
        """True once jawOpen has stayed high for YAWN_SUSTAINED_S."""
        if jaw_open is None:
            self._last_yawn_start = None
            return False
        if jaw_open >= self.YAWN_LEVEL:
            if self._last_yawn_start is None:
                self._last_yawn_start = timestamp
            return timestamp - self._last_yawn_start >= self.YAWN_SUSTAINED_S
        self._last_yawn_start = None
        return False

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
        self._closure_hist.clear()
        self._ear_baseline_hist.clear()
        self._ear_baseline = None
        self._last_yawn_start = None

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
            action = (
                WhitelistedAction.WRITING_NOTES
                if writing_gesture
                else WhitelistedAction.READING_DOWNWARDS
            )
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
        eye_closure: Optional[float] = None,
        jaw_open: Optional[float] = None,
    ) -> DistractionAnalysisResult:
        """
        Analyze current frame and state for distractions, applying the false-positive whitelist.
        ``gaze`` is optional; when provided it modulates the continuous focus score.
        ``eye_closure`` / ``jaw_open`` are MediaPipe blendshape signals (0-1);
        when absent the drowsiness stage falls back to personal-baseline EAR.

        Priority order: AWAY → PHONE → IDENTITY → DROWSINESS → whitelist →
        LOOKING_AWAY → focused. Hard signals run BEFORE the whitelist because
        a phone on the desk *is* the reading pose, an impostor looking down
        must never be whitelisted, and a student asleep face-down on the desk
        classifies as READING_DOWNWARDS.
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

        # 2. Continuous quadratic focus: Focus = 100·(1−(|yaw|/45)²)·(1−(|pitch|/35)²)·GazeFactor.
        # Sub-threshold head drift degrades the score smoothly instead of
        # sitting at a flat 100 until a binary threshold trips.
        gaze_factor = self._gaze_factor(gaze)
        yaw_term = self._quadratic_term(pose.yaw, self.YAW_NEUTRAL_BAND, self.YAW_FULL_RANGE)
        pitch_term = self._quadratic_term(
            pose.pitch, self.PITCH_NEUTRAL_BAND, self.PITCH_FULL_RANGE
        )
        continuous_focus = round(
            max(0.0, min(100.0, 100.0 * yaw_term * pitch_term * gaze_factor)), 1
        )

        # 3. Hard signal A: Smartphone Interaction (> 4s) — BEFORE the
        # whitelist: the phone-on-desk pose equals the reading pose, so
        # whitelisting first made phone alerts impossible while reading.
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
        else:
            self._clear("phone")

        # 4. Hard signal B: Identity Mismatch (> 15s) — an impostor looking
        # down must not ride the whitelist either.
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

        # 5. Drowsiness (PERCLOS + sustained closure + yawn). Blendshape-based
        # closure is safe to run before the whitelist — unlike raw EAR, it
        # does not drop just because the student looks down to read.
        eyes_closed = self._observe_eyes(timestamp, liveness, eye_closure)
        perclos = self._perclos(timestamp)
        closed_continuously = 0.0
        if eyes_closed and self._closure_hist:
            first_closed_ts = self._closure_hist[-1][0]
            for ts, closed in reversed(self._closure_hist):
                if not closed:
                    break
                first_closed_ts = ts
            closed_continuously = timestamp - first_closed_ts
        drowsy_dur = self._since("drowsiness", timestamp) if (eyes_closed or perclos > 0.0) else 0.0
        if (
            perclos >= self.PERCLOS_THRESHOLD
            or closed_continuously >= self.SUSTAINED_CLOSED_S
            or self._yawn_sustained(timestamp, jaw_open)
        ):
            return DistractionAnalysisResult(
                is_distracted=True,
                distraction_type=DistractionType.DROWSINESS,
                focus_score=15.0,
                confidence=0.90,
                duration_seconds=round(max(drowsy_dur, closed_continuously), 1),
                whitelisted_action=None,
                reason=(
                    f"Drowsiness detected (PERCLOS {perclos:.0%}, "
                    f"eyes closed {closed_continuously:.1f}s)"
                ),
            )
        if not eyes_closed and perclos < self.PERCLOS_THRESHOLD:
            self._clear("drowsiness")

        # 6. Whitelisted Study Gestures. A pending phone keeps its marker so
        # the nudge tier can still fire during a whitelisted action.
        whitelisted = self.check_whitelist(
            timestamp, pose, writing_gesture, hand_to_mouth_gesture, page_turn_gesture
        )
        if whitelisted is not None:
            if phone_object_detected:
                whitelisted.pending_distraction_type = DistractionType.PHONE_DETECTED
                whitelisted.duration_seconds = round(self._since("phone", timestamp), 1)
            return whitelisted

        # 7. Flagged: Looking Away / Daydreaming (> 10s)
        if phone_object_detected:
            # Below alert threshold but the phone is visible: surface a
            # pending marker (non-whitelisted case) so the nudge tier acts.
            return DistractionAnalysisResult(
                is_distracted=False,
                distraction_type=DistractionType.NONE,
                focus_score=continuous_focus,
                confidence=0.80,
                duration_seconds=round(self._since("phone", timestamp), 1),
                whitelisted_action=None,
                reason=(
                    f"Phone visible ({self._since('phone', timestamp):.1f}s / "
                    f"{self.PHONE_DETECTED_THRESHOLD}s threshold)"
                ),
                pending_distraction_type=DistractionType.PHONE_DETECTED,
            )

        is_looking_away = (abs(pose.yaw) > self.YAW_AWAY_DEG) or (pose.pitch < self.PITCH_UP_DEG)
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

        # 8. Default: Focused on study (continuous score reflects micro-drift)
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


def _median(values: List[float]) -> float:
    """Median of a non-empty float list (no numpy dependency)."""
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return float(ordered[mid])
    return (float(ordered[mid - 1]) + float(ordered[mid])) / 2.0
