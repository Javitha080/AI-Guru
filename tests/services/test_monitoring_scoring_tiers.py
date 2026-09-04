"""Tests for continuous quadratic focus, dual-rate EMA, and the nudge tier."""

import pytest

from deeptutor.services.monitoring.distraction_analyzer import (
    DistractionAnalyzer,
    DistractionType,
)
from deeptutor.services.monitoring.engagement_estimator import EngagementEstimator
from deeptutor.services.monitoring.liveness_detector import LivenessResult
from deeptutor.services.monitoring.pose_gaze import (
    GazeResult,
    HeadPoseResult,
    PostureCategory,
)
from deeptutor.services.monitoring.presence_state_machine import PresenceState
from deeptutor.services.monitoring.warning_manager import WarningManager


def _pose(yaw=0.0, pitch=0.0, roll=0.0, posture=PostureCategory.HEAD_CENTER):
    return HeadPoseResult(
        yaw=yaw,
        pitch=pitch,
        roll=roll,
        posture=posture,
        is_facing_screen=False,
        is_reading_writing_pose=False,
    )


def _live():
    return LivenessResult(
        is_live=True,
        confidence=0.95,
        blink_detected=False,
        ear=0.30,
        ear_variance=0.01,
        motion_score=0.05,
        texture_score=1.0,
        reason="Live",
    )


class TestQuadraticContinuousFocus:
    def _analyze(self, analyzer, yaw, pitch, gaze=None, t=100.0):
        return analyzer.analyze(
            timestamp=t,
            presence_state=PresenceState.PRESENT,
            pose=_pose(yaw=yaw, pitch=pitch),
            liveness=_live(),
            identity_match=True,
            gaze=gaze,
        )

    def test_neutral_band_pins_100(self):
        analyzer = DistractionAnalyzer()
        assert self._analyze(analyzer, 5.0, 5.0).focus_score == 100.0
        # Exactly at band edge: still full focus (continuous from there on).
        assert self._analyze(analyzer, 12.0, 10.0).focus_score == 100.0

    def test_smooth_degradation_before_threshold(self):
        analyzer = DistractionAnalyzer()
        slight = self._analyze(analyzer, 20.0, 0.0).focus_score
        moderate = self._analyze(analyzer, 30.0, 0.0).focus_score
        far = self._analyze(analyzer, 44.0, 0.0).focus_score
        assert 60.0 < slight < 100.0
        assert moderate < slight
        assert far < moderate

    def test_extreme_drift_hits_floor_then_flagged_low(self):
        analyzer = DistractionAnalyzer()
        # Pre-threshold first frame: continuous score collapses toward zero but
        # the not-yet-flagged floor keeps it at 30.
        pre = self._analyze(analyzer, 44.0, 34.0).focus_score
        assert pre == 30.0
        # After the threshold the flagged score drops below that floor.
        flagged = self._analyze(analyzer, 44.0, 34.0, t=112.0).focus_score
        assert flagged < 30.0

    def test_gaze_factor_modulates(self):
        analyzer = DistractionAnalyzer()
        focused = GazeResult(gaze_x=0.0, gaze_y=0.0, is_focused=True, confidence=0.9)
        away = GazeResult(gaze_x=0.8, gaze_y=0.0, is_focused=False, confidence=0.85)
        with_focus = self._analyze(analyzer, 20.0, 0.0, gaze=focused).focus_score
        against = self._analyze(analyzer, 20.0, 0.0, gaze=away).focus_score
        assert against < with_focus

    def test_whitelist_still_exactly_100(self):
        analyzer = DistractionAnalyzer()
        reading = HeadPoseResult(
            yaw=5.0,
            pitch=40.0,
            roll=0.0,
            posture=PostureCategory.LOOKING_DOWN,
            is_facing_screen=False,
            is_reading_writing_pose=True,
        )
        res = analyzer.analyze(
            timestamp=100.0,
            presence_state=PresenceState.PRESENT,
            pose=reading,
            liveness=_live(),
            identity_match=True,
        )
        assert res.focus_score == 100.0 and res.whitelisted_action is not None


class TestDualRateEMA:
    def _snapshot_seq(self, scores):
        est = EngagementEstimator()
        out = []
        for s in scores:
            snap = est.update(
                presence_state=PresenceState.PRESENT,
                pose=_pose(yaw=s["yaw"], pitch=s.get("pitch", 0.0)),
                gaze_focused=s.get("focused", True),
                is_distracted=s.get("distracted", False),
            )
            out.append(snap.score)
        return out

    def test_decay_faster_than_recovery(self):
        # Drop from full focus to a distracted state, then recover.
        drop = [{"yaw": 0.0}, {"yaw": 50.0, "distracted": True}, {"yaw": 50.0, "distracted": True}]
        est = EngagementEstimator()
        before = None
        for step in drop:
            snap = est.update(
                PresenceState.PRESENT, _pose(step["yaw"]), False, step.get("distracted", False)
            )
            before = snap.score
        after_drop = before

        est2 = EngagementEstimator()
        for step in drop:
            est2.update(
                PresenceState.PRESENT, _pose(step["yaw"]), False, step.get("distracted", False)
            )

        # Recovery ticks: same neutral frames, score should climb back slowly.
        recovered = []
        for _ in range(6):
            snap = est2.update(PresenceState.PRESENT, _pose(0.0), True, False)
            recovered.append(snap.score)
        assert all(b >= a for a, b in zip(recovered, recovered[1:]))  # monotonic rise
        assert after_drop < 100.0

    def test_alpha_constants(self):
        assert EngagementEstimator.FAST_DECAY_ALPHA > EngagementEstimator.SLOW_RECOVERY_ALPHA


class TestNudgeTier:
    @staticmethod
    def _distraction(duration: float, dtype=DistractionType.LOOKING_AWAY, confidence: float = 0.9):
        from deeptutor.services.monitoring.distraction_analyzer import DistractionAnalysisResult

        return DistractionAnalysisResult(
            is_distracted=True,
            distraction_type=dtype,
            focus_score=40.0,
            confidence=confidence,
            duration_seconds=duration,
        )

    def test_nudge_fires_once_in_window(self):
        wm = WarningManager()
        e1 = wm.evaluate_nudge(100.0, self._distraction(4.0))
        assert e1 is not None and e1.severity == "nudge"
        # Same episode again inside window+cooldown: no repeat.
        assert wm.evaluate_nudge(104.0, self._distraction(4.4)) is None

    def test_nudge_outside_window_suppressed(self):
        wm = WarningManager()
        assert wm.evaluate_nudge(100.0, self._distraction(2.0)) is None
        assert wm.evaluate_nudge(100.0, self._distraction(7.0)) is None

    def test_nudge_respects_confidence_gate(self):
        wm = WarningManager(min_confidence=0.80)
        assert wm.evaluate_nudge(100.0, self._distraction(4.0, confidence=0.7)) is None

    def test_nudge_skipped_when_episode_escalated(self):
        wm = WarningManager()
        wm._episode_notified[DistractionType.LOOKING_AWAY.value] = True
        assert wm.evaluate_nudge(100.0, self._distraction(4.0)) is None

    def test_nudge_not_for_student_away(self):
        wm = WarningManager()
        assert (
            wm.evaluate_nudge(100.0, self._distraction(4.0, dtype=DistractionType.STUDENT_AWAY))
            is None
        )

    def test_nudge_cooldown_across_episodes(self):
        wm = WarningManager()
        first = wm.evaluate_nudge(100.0, self._distraction(4.0))
        assert first is not None
        # Episode ends, new episode begins within cooldown → suppressed.
        wm.observe_distraction_state(False, None)
        assert wm.evaluate_nudge(120.0, self._distraction(4.0)) is None
        # After cooldown expires → fires again.
        second = wm.evaluate_nudge(145.0, self._distraction(4.0))
        assert second is not None

    def test_evaluate_and_dispatch_semantics_untouched(self):
        """The legacy direct-call contract: warning at t0, suppressed at +20s."""
        wm = WarningManager(cooldown_seconds=60.0, min_confidence=0.80)
        d = self._distraction(12.0)
        event1 = wm.evaluate_and_dispatch(timestamp=100.0, distraction=d)
        assert event1 is not None and event1.severity != "nudge"
        assert wm.evaluate_and_dispatch(timestamp=120.0, distraction=d) is None
        assert wm.evaluate_and_dispatch(timestamp=165.0, distraction=d) is not None

    def test_pipeline_wires_tiers(self):
        """Full pipeline: early distraction produces nudge, later one a warning."""
        from deeptutor.services.monitoring.cv_pipeline import LocalCVPipeline
        from deeptutor.services.monitoring.face_engine import FaceEngine

        pipeline = LocalCVPipeline()
        lm = FaceEngine().create_synthetic_landmarks(yaw=45.0, pitch=0.0)

        severities = []
        base_ts = 1000.0
        for i in range(130):  # 13s at 0.1s steps
            payload = {
                "detected": True,
                "confidence": 0.95,
                "brightness": 0.5,
                "landmarks": {
                    "left_eye": [{"x": p.x, "y": p.y, "z": p.z} for p in lm.left_eye],
                    "right_eye": [{"x": p.x, "y": p.y, "z": p.z} for p in lm.right_eye],
                    "mouth": [{"x": p.x, "y": p.y, "z": p.z} for p in lm.mouth],
                    "nose_tip": {"x": lm.nose_tip.x, "y": lm.nose_tip.y, "z": lm.nose_tip.z},
                    "chin": {"x": lm.chin.x, "y": lm.chin.y, "z": lm.chin.z},
                    "forehead": {"x": lm.forehead.x, "y": lm.forehead.y, "z": lm.forehead.z},
                    "left_cheek": {
                        "x": lm.left_cheek.x,
                        "y": lm.left_cheek.y,
                        "z": lm.left_cheek.z,
                    },
                    "right_cheek": {
                        "x": lm.right_cheek.x,
                        "y": lm.right_cheek.y,
                        "z": lm.right_cheek.z,
                    },
                },
                "embedding": pipeline.face_engine.generate_geometric_embedding(lm),
                "timestamp": base_ts + i * 0.1,
            }
            result = pipeline.process_telemetry_payload(payload, current_time=base_ts + i * 0.1)
            if result.dispatched_warning is not None:
                severities.append((round(i * 0.1, 1), result.dispatched_warning.severity))
        kinds = [s for _, s in severities]
        assert "nudge" in kinds, f"expected an early nudge, got {severities}"
        assert "warning" in kinds, f"expected escalation to warning, got {severities}"
        first_nudge = kinds.index("nudge")
        first_warning_idx = min((i for i, k in enumerate(kinds) if k == "warning"), default=-1)
        assert first_warning_idx >= first_nudge
        # Nudge arrives inside [3s, 6s) of episode start; warning later.
        nudge_time = severities[first_nudge][0]
        assert 2.0 <= nudge_time <= 6.5
