"""Regression tests for the CV safety-engine fixes (Sept 2026 patch set).

Covers the verified review findings:
- C1: phone/identity checks run BEFORE the study-gesture whitelist
- C2: liveness verdict is consumed (spoof rides IDENTITY_MISMATCH) and the
      blink evidence decays (BLINK_RECENCY_S)
- C5/Patch B constants: phone detection is time-based with majority voting
- Patch D: transformation-matrix euler extraction + per-session neutral
      calibration
- Patch E: PERCLOS/personal-baseline drowsiness replaces the fixed EAR<0.18
- C3: geometric embedding cannot false-flag, but SFace templates enroll
- H1-adjacent: cosine dimension mismatch rejects instead of truncating
- M7: engagement stability is rate-normalized (deg/s)
- M9: gentle strictness no longer disables nudges
- identity_store: encrypted persistence round-trip
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from deeptutor.services.monitoring.distraction_analyzer import (
    DistractionAnalyzer,
    DistractionType,
)
from deeptutor.services.monitoring.engagement_estimator import EngagementEstimator
from deeptutor.services.monitoring.face_engine import FaceEngine
from deeptutor.services.monitoring.face_solvers import euler_from_face_matrix
from deeptutor.services.monitoring.liveness_detector import LivenessDetector, LivenessResult
from deeptutor.services.monitoring.neutral_calibrator import NeutralCalibrator
from deeptutor.services.monitoring.pose_gaze import HeadPoseResult, PostureCategory
from deeptutor.services.monitoring.presence_state_machine import PresenceState
from deeptutor.services.monitoring.warning_manager import WarningManager


def _pose(yaw=0.0, pitch=0.0, roll=0.0, reading=False):
    return HeadPoseResult(
        yaw=yaw,
        pitch=pitch,
        roll=roll,
        posture=PostureCategory.LOOKING_DOWN if reading else PostureCategory.HEAD_CENTER,
        is_facing_screen=not reading,
        is_reading_writing_pose=reading,
    )


def _live(ear: float = 0.30) -> LivenessResult:
    return LivenessResult(
        is_live=True,
        confidence=0.95,
        blink_detected=False,
        ear=ear,
        ear_variance=0.01,
        motion_score=0.05,
        texture_score=1.0,
        reason="test fixture",
    )


# ---------------------------------------------------------------------------
# Patch D: transformation-matrix → euler
# ---------------------------------------------------------------------------


def _rot_zyx(yaw_deg: float, pitch_deg: float, roll_deg: float) -> np.ndarray:
    """Build the matrix whose Z-Y-X decomposition euler_from_face_matrix inverts.

    The extractor implements the standard ZYX decomposition
    (yaw=atan2(-R20,·), pitch'=atan2(R21,R22), roll=atan2(R10,R00)) with a
    pitch sign-flip on output; its inverse is R = Rz(roll)·Ry(yaw)·Rx(-pitch),
    i.e. Z-angle=roll, Y-angle=yaw, X-angle=-pitch.
    """
    y, p, r = (math.radians(a) for a in (roll_deg, yaw_deg, -pitch_deg))
    cy, sy = math.cos(y), math.sin(y)
    cp, sp = math.cos(p), math.sin(p)
    cr, sr = math.cos(r), math.sin(r)
    return np.array(
        [
            [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr],
        ]
    )


class TestEulerFromFaceMatrix:
    @pytest.mark.parametrize(
        "yaw,pitch,roll",
        [(0, 0, 0), (20, -35, 10), (-15, 25, -8), (10, 5, 0), (-30, -10, 15)],
    )
    def test_round_trip(self, yaw, pitch, roll):
        R = _rot_zyx(yaw, pitch, roll)
        mat = np.eye(4)
        mat[:3, :3] = R
        out_yaw, out_pitch, out_roll = euler_from_face_matrix(mat)
        assert out_yaw == pytest.approx(yaw, abs=1e-6)
        assert out_pitch == pytest.approx(pitch, abs=1e-6)
        assert out_roll == pytest.approx(roll, abs=1e-6)

    def test_accepts_flat_16(self):
        out = euler_from_face_matrix(np.eye(4).reshape(-1))
        assert out == (pytest.approx(0.0), pytest.approx(0.0), pytest.approx(0.0))


class TestNeutralCalibrator:
    def test_locks_after_samples_then_subtracts(self):
        cal = NeutralCalibrator(samples=5)
        for _ in range(5):
            out = cal.apply(2.0, 8.0, 1.0)
        assert out == (2.0, 8.0, 1.0)  # pass-through while collecting
        assert cal.calibrated
        yaw, pitch, roll = cal.apply(5.0, 12.0, 2.0)
        assert (yaw, pitch, roll) == (3.0, 4.0, 1.0)

    def test_extreme_startup_frames_never_poison_the_zero(self):
        cal = NeutralCalibrator(samples=3)
        for _ in range(10):
            cal.apply(60.0, -30.0, 40.0)  # student starts turned away
        assert not cal.calibrated

    def test_reset(self):
        cal = NeutralCalibrator(samples=1)
        cal.apply(1.0, 2.0, 3.0)
        assert cal.calibrated
        cal.reset()
        assert not cal.calibrated


# ---------------------------------------------------------------------------
# Patch C: blink recency + history-gated static branch
# ---------------------------------------------------------------------------


class TestLivenessBlinkRecency:
    def _static_landmarks(self):
        return FaceEngine().create_synthetic_landmarks(yaw=0.0, pitch=0.0)

    def test_blink_evidence_decays(self):
        det = LivenessDetector()
        lm = self._static_landmarks()
        # Blink at t=10 (closed then open).
        det.evaluate_frame(lm, timestamp=10.0)
        closed = FaceEngine().create_synthetic_landmarks(yaw=0.0, pitch=0.0, eye_open_ratio=0.05)
        det.evaluate_frame(closed, timestamp=10.1)
        det.evaluate_frame(lm, timestamp=10.2)
        assert det._last_blink_time == pytest.approx(10.2)
        # 40+ frames of motionless video: the blink leaves both the 30-frame
        # EAR window and the 30s recency horizon — a photograph from here on.
        res = None
        for i in range(45):
            res = det.evaluate_frame(lm, timestamp=11.0 + i * 2.0)
        assert res.is_live is False
        assert res.confidence >= 0.90

    def test_static_branch_never_fires_on_short_history(self):
        det = LivenessDetector()
        lm = self._static_landmarks()
        res = None
        for i in range(9):  # ~2.5s of observation — under the 10s gate
            res = det.evaluate_frame(lm, timestamp=2.0 + i * 0.3)
        assert res.is_live is True  # warm-up cannot judge a photograph yet

    def test_recent_blink_still_counts(self):
        det = LivenessDetector()
        lm = self._static_landmarks()
        det.evaluate_frame(lm, timestamp=10.0)
        det.evaluate_frame(
            FaceEngine().create_synthetic_landmarks(yaw=0.0, pitch=0.0, eye_open_ratio=0.05),
            timestamp=10.1,
        )
        det.evaluate_frame(lm, timestamp=10.2)
        res = det.evaluate_frame(lm, timestamp=25.0)  # 15s after the blink
        assert res.is_live is True


# ---------------------------------------------------------------------------
# Patch A: hard signals beat the whitelist
# ---------------------------------------------------------------------------


class TestHardSignalsBeatWhitelist:
    def test_phone_in_reading_pose_is_flagged(self):
        a = DistractionAnalyzer()
        # Warm the phone timer below threshold, then cross it — while the
        # student is in a textbook-perfect reading pose the whole time.
        a.analyze(
            timestamp=100.0,
            presence_state=PresenceState.PRESENT,
            pose=_pose(pitch=30.0, reading=True),
            liveness=_live(),
            identity_match=True,
            phone_object_detected=True,
        )
        res = a.analyze(
            timestamp=105.0,
            presence_state=PresenceState.PRESENT,
            pose=_pose(pitch=30.0, reading=True),
            liveness=_live(),
            identity_match=True,
            phone_object_detected=True,
        )
        assert res.is_distracted is True
        assert res.distraction_type == DistractionType.PHONE_DETECTED

    def test_impostor_looking_down_is_not_whitelisted(self):
        a = DistractionAnalyzer()
        res = None
        for t in (100.0, 108.0, 116.5):  # >15s sustained mismatch
            res = a.analyze(
                timestamp=t,
                presence_state=PresenceState.PRESENT,
                pose=_pose(pitch=30.0, reading=True),
                liveness=_live(),
                identity_match=False,
            )
        assert res.is_distracted is True
        assert res.distraction_type == DistractionType.IDENTITY_MISMATCH

    def test_whitelist_still_applies_without_hard_signals(self):
        a = DistractionAnalyzer()
        res = a.analyze(
            timestamp=100.0,
            presence_state=PresenceState.PRESENT,
            pose=_pose(pitch=30.0, reading=True),
            liveness=_live(),
            identity_match=True,
        )
        assert res.focus_score == 100.0
        assert res.whitelisted_action is not None

    def test_pending_phone_marker_survives_whitelist(self):
        a = DistractionAnalyzer()
        res = a.analyze(
            timestamp=100.0,
            presence_state=PresenceState.PRESENT,
            pose=_pose(pitch=30.0, reading=True),
            liveness=_live(),
            identity_match=True,
            phone_object_detected=True,
        )
        assert res.is_distracted is False
        assert res.pending_distraction_type == DistractionType.PHONE_DETECTED


# ---------------------------------------------------------------------------
# Patch E: PERCLOS / personal-baseline drowsiness
# ---------------------------------------------------------------------------


class TestPerclosDrowsiness:
    def test_sustained_closed_eyes_flag_drowsiness_in_reading_pose(self):
        a = DistractionAnalyzer()
        res = None
        for i in range(30):  # 3s at 0.1s
            res = a.analyze(
                timestamp=100.0 + i * 0.1,
                presence_state=PresenceState.PRESENT,
                pose=_pose(pitch=35.0, reading=True),  # face-down on the desk
                liveness=_live(ear=0.30),
                identity_match=True,
                eye_closure=0.95,
            )
        assert res.is_distracted is True
        assert res.distraction_type == DistractionType.DROWSINESS

    def test_normal_blinking_reader_stays_focused(self):
        a = DistractionAnalyzer()
        for i in range(120):  # 12s: blinks (~0.2s closed) a few times a minute
            closed = (i % 50) < 2
            res = a.analyze(
                timestamp=100.0 + i * 0.1,
                presence_state=PresenceState.PRESENT,
                pose=_pose(pitch=30.0, reading=True),
                liveness=_live(ear=0.30),
                identity_match=True,
                eye_closure=0.9 if closed else 0.05,
            )
        assert res.is_distracted is False
        assert res.distraction_type == DistractionType.NONE

    def test_personal_ear_baseline_saves_the_squinter(self):
        a = DistractionAnalyzer()
        # First ~6s: natural open-eye EAR of 0.22 (a squinty reader — the old
        # fixed 0.18 cut flagged this person the moment they read).
        for i in range(60):
            a._observe_eyes(100.0 + i * 0.1, _live(ear=0.22), None)
        assert a._ear_baseline == pytest.approx(0.22)
        # Now reading with eyelids lowered to 0.15: above 0.22*0.6=0.132 → open.
        closed = a._observe_eyes(200.0, _live(ear=0.15), None)
        assert closed is False

    def test_yawn_cue(self):
        a = DistractionAnalyzer()
        res = None
        for i in range(30):
            res = a.analyze(
                timestamp=100.0 + i * 0.1,
                presence_state=PresenceState.PRESENT,
                pose=_pose(),
                liveness=_live(),
                identity_match=True,
                eye_closure=0.05,
                jaw_open=0.8,
            )
        assert res.distraction_type == DistractionType.DROWSINESS


# ---------------------------------------------------------------------------
# Patch C wiring: a static photo swap rides IDENTITY_MISMATCH
# ---------------------------------------------------------------------------


class TestSpoofConsumedByIdentityPath:
    def test_static_frames_eventually_flag_identity(self):
        from deeptutor.services.monitoring.cv_pipeline import LocalCVPipeline
        from deeptutor.services.monitoring.synthetic import generate_mock_telemetry

        pipeline = LocalCVPipeline()
        engine = FaceEngine()
        enrolled_lm = engine.create_synthetic_landmarks(yaw=0.0, pitch=0.0)
        pipeline.enroll_student_baseline(
            engine.generate_geometric_embedding(enrolled_lm), identity_mode="geometric"
        )

        final = None
        for i in range(300):  # 30s at 0.1s steps
            frame_payload = generate_mock_telemetry(
                pipeline.face_engine, scenario="static_photo", timestamp=float(i) * 0.1
            )
            final = pipeline.process_telemetry_payload(frame_payload, current_time=0.1 + i * 0.1)
        # The liveness verdict is now CONSUMED: sustained static → spoof rides
        # the identity-mismatch path (spoof at ~10s + 15s mismatch timer).
        assert final.liveness.is_live is False
        assert final.spoof_suspected is True
        assert final.identity_matched is False
        assert final.distraction.distraction_type == DistractionType.IDENTITY_MISMATCH

    def test_unenrolled_sessions_still_pass(self):
        from deeptutor.services.monitoring.cv_pipeline import LocalCVPipeline
        from deeptutor.services.monitoring.synthetic import generate_mock_telemetry

        pipeline = LocalCVPipeline()
        final = None
        for i in range(300):
            payload = generate_mock_telemetry(
                pipeline.face_engine, scenario="static_photo", timestamp=float(i) * 0.1
            )
            final = pipeline.process_telemetry_payload(payload, current_time=0.1 + i * 0.1)
        # No baseline enrolled: legacy pass (pre-enrollment sessions unflagged),
        # but the spoof IS recorded for diagnostics.
        assert final.identity_matched is True
        assert final.spoof_suspected is True


# ---------------------------------------------------------------------------
# Patch B constants: phone cadence/voting
# ---------------------------------------------------------------------------


class TestPhoneDetectorConstants:
    def test_time_based_cadence_beats_throttling(self):
        from deeptutor.services.monitoring import python_face_processor as pfp

        # At governor-throttled 3 fps a tick is ~0.33s; the 0.5s cadence means
        # the detector STILL runs roughly every other tick — the old
        # every-5-ticks + 1.5s TTL scheme starved the 4s timer instead.
        assert pfp.PHONE_DETECT_INTERVAL_S < 1.0
        assert pfp.PHONE_VOTES_REQUIRED <= pfp.PHONE_VOTE_WINDOW

    def test_vote_window_is_a_deque_with_cap(self):
        proc = pfp_module().PythonFaceProcessor()
        assert proc._phone_votes.maxlen == 6
        for _ in range(10):
            proc._phone_votes.append(True)
        assert len(proc._phone_votes) == 6  # capped
        assert proc._phone_votes.count(True) == 6


def pfp_module():
    from deeptutor.services.monitoring import python_face_processor as pfp

    return pfp


# ---------------------------------------------------------------------------
# Cosine dimension mismatch rejects (no silent truncation)
# ---------------------------------------------------------------------------


class TestCosineDimensionMismatch:
    def test_mismatched_dimensions_score_zero(self):
        eng = FaceEngine()
        a = [1.0] * 128
        b = [1.0] * 64
        assert eng.compute_cosine_similarity(a, b) == 0.0
        assert eng.verify_identity(b, a) == (False, 0.0)

    def test_geometric_impostor_cannot_be_distinguished(self):
        """Documents the KNOWN geometric limit: two different frontal faces
        both pass the 0.65 threshold — the reason SFace enrollment exists."""
        eng = FaceEngine()
        a = eng.create_synthetic_landmarks(yaw=0.0, pitch=0.0)
        b = eng.create_synthetic_landmarks(yaw=0.0, pitch=0.0)
        b.nose_tip.x += 0.01  # different person, subtly different geometry
        emb_a = eng.generate_geometric_embedding(a)
        emb_b = eng.generate_geometric_embedding(b)
        is_match, sim = eng.verify_identity(emb_b, emb_a)
        assert is_match is True and sim > 0.9


# ---------------------------------------------------------------------------
# M7: rate-normalized engagement stability
# ---------------------------------------------------------------------------


class TestEngagementStabilityRate:
    def test_same_angular_velocity_same_stability_across_fps(self):
        est_fast = EngagementEstimator()  # 10 fps
        est_slow = EngagementEstimator()  # 5 fps, same physical motion
        # 30 deg/s sweep: 3 deg/tick at 10fps, 6 deg/tick at 5fps.
        for i in range(10):
            est_fast.update(PresenceState.PRESENT, _pose(yaw=i * 3.0), True, timestamp=i * 0.1)
        for i in range(10):
            est_slow.update(PresenceState.PRESENT, _pose(yaw=i * 6.0), True, timestamp=i * 0.2)
        fast = est_fast._compute_stability()
        slow = est_slow._compute_stability()
        assert fast == pytest.approx(slow)

    def test_erratic_motion_penalized(self):
        est = EngagementEstimator()
        sign = 1.0
        for i in range(10):
            est.update(PresenceState.PRESENT, _pose(yaw=sign * 20.0), True, timestamp=i * 0.1)
            sign *= -1  # 400 deg/s thrash
        assert est._compute_stability() <= 0.3


# ---------------------------------------------------------------------------
# M9: gentle strictness keeps nudges alive
# ---------------------------------------------------------------------------


class TestNudgeUnderGentleProfile:
    def _pending(self, confidence=0.80):
        from deeptutor.services.monitoring.distraction_analyzer import (
            DistractionAnalysisResult,
        )

        return DistractionAnalysisResult(
            is_distracted=False,
            distraction_type=DistractionType.NONE,
            focus_score=70.0,
            confidence=confidence,
            duration_seconds=4.0,
            pending_distraction_type=DistractionType.LOOKING_AWAY,
        )

    def test_gentle_profile_still_nudges_pending(self):
        wm = WarningManager(min_confidence=0.85)  # "gentle"
        event = wm.evaluate_nudge(100.0, self._pending(0.80))
        assert event is not None and event.severity == "nudge"

    def test_very_low_confidence_still_suppressed(self):
        wm = WarningManager(min_confidence=0.85)
        assert wm.evaluate_nudge(100.0, self._pending(0.60)) is None


# ---------------------------------------------------------------------------
# identity_store: encrypted persistence round-trip
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_db(tmp_path: Path):
    import sqlite3

    from deeptutor.services.database.schema import PRAGMAS, V1_SCHEMA_DDL
    from deeptutor.services.path_service import get_path_service

    service = get_path_service()
    original_root = service._project_root
    original_user_dir = service._user_data_dir
    service._project_root = tmp_path
    service._user_data_dir = tmp_path / "data" / "user"
    service._user_data_dir.mkdir(parents=True, exist_ok=True)
    db_path = service.user_dir / "chat_history.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(PRAGMAS.split(";")[0] + ";")
        conn.executescript(V1_SCHEMA_DDL)
        conn.commit()
    finally:
        conn.close()
    yield str(db_path)
    service._project_root = original_root
    service._user_data_dir = original_user_dir


class TestIdentityStore:
    @pytest.mark.asyncio  # type: ignore[misc]
    async def test_round_trip(self, isolated_db):
        from deeptutor.services.monitoring import identity_store

        emb = [0.01 * i for i in range(128)]
        assert await identity_store.has_baseline(isolated_db) is False
        assert await identity_store.save_baseline(isolated_db, emb, "sface") is True
        loaded = await identity_store.load_baseline(isolated_db)
        assert loaded is not None
        restored, mode = loaded
        assert restored == pytest.approx(emb)
        assert mode == "sface"
        assert await identity_store.has_baseline(isolated_db) is True
        await identity_store.clear_baseline(isolated_db)
        assert await identity_store.load_baseline(isolated_db) is None

    @pytest.mark.asyncio  # type: ignore[misc]
    async def test_baseline_survives_restart_simulation(self, isolated_db):
        """The exact regression: baseline lived in process memory only."""
        from deeptutor.services.monitoring import identity_store
        from deeptutor.services.monitoring.cv_pipeline import LocalCVPipeline

        pipeline = LocalCVPipeline()
        emb = [0.02 * (i % 13) for i in range(128)]
        pipeline.enroll_student_baseline(emb, identity_mode="geometric")
        await identity_store.save_baseline(isolated_db, emb, "geometric")

        # "Restart": fresh pipeline hydrates from the store.
        fresh = LocalCVPipeline()
        from deeptutor.services.monitoring.cv_pipeline import hydrate_identity_baseline

        await hydrate_identity_baseline(fresh)
        assert fresh.face_engine.get_enrolled_face() is not None
        assert fresh.enrolled_identity_mode == "geometric"


# ---------------------------------------------------------------------------
# SFace engine unit behavior (no model required)
# ---------------------------------------------------------------------------


class TestSFaceEngine:
    def test_unavailable_without_model(self):
        """No 37MB model in the test env: default creation degrades softly."""
        from deeptutor.services.monitoring.face_identity import SFaceIdentity

        inst = SFaceIdentity.create_default()
        assert inst is None or inst.available is False

    def test_enroll_median_is_outlier_robust(self):
        from deeptutor.services.monitoring.face_identity import SFaceIdentity

        rng = np.random.default_rng(7)
        samples = [rng.normal(0.5, 0.01, 128) for _ in range(10)]
        samples[3] = rng.normal(5.0, 1.0, 128)  # one garbage frame

        class _Bare:
            enroll_median = SFaceIdentity.enroll_median

        template = _Bare().enroll_median(samples)
        assert template is not None and len(template) == 128
        assert np.allclose(template, np.median(np.stack(samples), axis=0))
        assert abs(template[0] - 0.5) < 0.05  # outlier did not drag the median
