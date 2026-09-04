"""
Comprehensive Test Suite for AI Guru Study Monitoring Engine (Local CV).
========================================================================

Covers Requirement R4:
1. Presence state machine transitions and temporal hysteresis (5s -> TEMPORARILY_NOT_VISIBLE, 20s -> AWAY, instant PRESENT recovery).
2. Face verification cosine similarity mathematics and threshold gating (>= 0.65).
3. Anti-spoof liveness detector (pass live blink/movement, reject static printed photo/screens).
4. False-positive distraction filter (reading/writing/drinking whitelisted, phone/away flagged).
5. Warning manager 60-second category cooldown and confidence filtering.
6. Zero-cloud biometric egress invariant and API endpoints.
"""

import math
import time

from fastapi.testclient import TestClient
import pytest

from deeptutor.api.main import app
from deeptutor.services.monitoring.cv_pipeline import (
    FrameAnalysisResult,
    LocalCVPipeline,
    get_cv_pipeline,
)
from deeptutor.services.monitoring.distraction_analyzer import (
    DistractionAnalysisResult,
    DistractionAnalyzer,
    DistractionType,
    WhitelistedAction,
)
from deeptutor.services.monitoring.engagement_estimator import (
    EngagementEstimator,
    EngagementSnapshot,
)
from deeptutor.services.monitoring.face_engine import (
    FaceDetectionResult,
    FaceEngine,
    FaceLandmarks,
    Point3D,
)
from deeptutor.services.monitoring.liveness_detector import (
    LivenessDetector,
    LivenessResult,
)
from deeptutor.services.monitoring.pose_gaze import (
    GazeResult,
    HeadPoseResult,
    PoseGazeEstimator,
    PostureCategory,
)
from deeptutor.services.monitoring.presence_state_machine import (
    PresenceState,
    PresenceStateMachine,
    PresenceStateResult,
)
from deeptutor.services.monitoring.warning_manager import (
    WarningEvent,
    WarningManager,
)

# ============================================================================
# 1. Presence State Machine Tests (Temporal Hysteresis)
# ============================================================================


class TestPresenceStateMachine:
    """Test 4-state presence machine and hysteresis transitions."""

    def test_initial_face_detection_sets_present(self):
        sm = PresenceStateMachine(temp_absent_seconds=5.0, away_seconds=20.0)
        res = sm.update(face_detected=True, confidence=0.95, timestamp=100.0)
        assert res.state == PresenceState.PRESENT
        assert res.is_present is True
        assert res.unobserved_duration_seconds == 0.0

    def test_grace_period_remains_present(self):
        sm = PresenceStateMachine(temp_absent_seconds=5.0, away_seconds=20.0)
        sm.update(face_detected=True, confidence=0.95, timestamp=100.0)

        # 2 seconds unobserved (< 5.0s threshold)
        res = sm.update(face_detected=False, confidence=0.0, timestamp=102.0)
        assert res.state == PresenceState.PRESENT
        assert res.unobserved_duration_seconds == 2.0

    def test_temporal_transition_to_temporarily_not_visible(self):
        sm = PresenceStateMachine(temp_absent_seconds=5.0, away_seconds=20.0)
        sm.update(face_detected=True, confidence=0.95, timestamp=100.0)

        # 6 seconds unobserved (>= 5.0s and < 20.0s)
        res = sm.update(face_detected=False, confidence=0.0, timestamp=106.0)
        assert res.state == PresenceState.TEMPORARILY_NOT_VISIBLE
        assert res.is_present is False
        assert res.unobserved_duration_seconds == 6.0

    def test_temporal_transition_to_away(self):
        sm = PresenceStateMachine(temp_absent_seconds=5.0, away_seconds=20.0)
        sm.update(face_detected=True, confidence=0.95, timestamp=100.0)

        # 22 seconds unobserved (>= 20.0s)
        res = sm.update(face_detected=False, confidence=0.0, timestamp=122.0)
        assert res.state == PresenceState.AWAY
        assert res.is_present is False
        assert res.unobserved_duration_seconds == 22.0
        assert len(sm.history) >= 1

    def test_instant_recovery_to_present_on_redetection(self):
        sm = PresenceStateMachine(temp_absent_seconds=5.0, away_seconds=20.0)
        sm.update(face_detected=True, confidence=0.95, timestamp=100.0)
        sm.update(face_detected=False, confidence=0.0, timestamp=125.0)  # AWAY

        # Re-detected at t=130.0 -> INSTANT return to PRESENT
        res = sm.update(face_detected=True, confidence=0.92, timestamp=130.0)
        assert res.state == PresenceState.PRESENT
        assert res.is_present is True
        assert res.state_changed is True
        assert res.unobserved_duration_seconds == 0.0

    def test_dark_room_transitions_to_unknown(self):
        sm = PresenceStateMachine(min_luminance=20.0)
        sm.update(face_detected=True, timestamp=100.0)
        res = sm.update(face_detected=False, timestamp=105.0, brightness=10.0)  # luminance=10 < 20
        assert res.state == PresenceState.UNKNOWN


# ============================================================================
# 2. Face Verification & Cosine Similarity Tests
# ============================================================================


class TestFaceEngineVerification:
    """Test cosine similarity math, vector normalization, and 0.65 threshold."""

    def test_cosine_similarity_identical_vectors(self):
        vec = [0.1, 0.5, 0.8, -0.2, 0.4]
        sim = FaceEngine.compute_cosine_similarity(vec, vec)
        assert pytest.approx(sim, 0.0001) == 1.0

    def test_cosine_similarity_orthogonal_vectors(self):
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [0.0, 1.0, 0.0]
        sim = FaceEngine.compute_cosine_similarity(vec_a, vec_b)
        assert pytest.approx(sim, 0.0001) == 0.0

    def test_cosine_similarity_opposite_vectors(self):
        vec_a = [0.5, 0.5]
        vec_b = [-0.5, -0.5]
        sim = FaceEngine.compute_cosine_similarity(vec_a, vec_b)
        assert pytest.approx(sim, 0.0001) == -1.0

    def test_face_verification_match_threshold(self):
        engine = FaceEngine(match_threshold=0.65)
        baseline = [1.0, 0.0, 0.0, 0.0]
        engine.enroll_face(baseline)

        # Vector with ~0.8 cosine similarity -> MATCH
        matching_vec = [0.8, 0.6, 0.0, 0.0]
        is_match, score = engine.verify_identity(matching_vec)
        assert is_match is True
        assert score >= 0.65

        # Vector with ~0.3 cosine similarity -> MISMATCH
        mismatch_vec = [0.3, 0.95, 0.0, 0.0]
        is_match, score = engine.verify_identity(mismatch_vec)
        assert is_match is False
        assert score < 0.65

    def test_geometric_embedding_generation_128d(self):
        engine = FaceEngine()
        landmarks = engine.create_synthetic_landmarks(yaw=0.0, pitch=0.0, roll=0.0)
        embedding = engine.generate_geometric_embedding(landmarks)
        assert len(embedding) == 128
        # Check L2 norm equals 1.0
        norm = math.sqrt(sum(x * x for x in embedding))
        assert pytest.approx(norm, 0.001) == 1.0


# ============================================================================
# 3. Anti-Spoof Liveness Detector Tests
# ============================================================================


class TestAntiSpoofLivenessDetector:
    """Test passive/active liveness detection, EAR blinks, and static photo rejection."""

    def test_ear_calculation(self):
        detector = LivenessDetector()
        # Open eye landmarks
        open_eye = [
            Point3D(0.4, 0.5, 0.0),
            Point3D(0.43, 0.48, 0.0),
            Point3D(0.47, 0.48, 0.0),
            Point3D(0.5, 0.5, 0.0),
            Point3D(0.47, 0.52, 0.0),
            Point3D(0.43, 0.52, 0.0),
        ]
        ear_open = detector.calculate_eye_aspect_ratio(open_eye)
        assert ear_open > 0.25

        # Closed eye landmarks (very small vertical distance)
        closed_eye = [
            Point3D(0.4, 0.5, 0.0),
            Point3D(0.43, 0.498, 0.0),
            Point3D(0.47, 0.498, 0.0),
            Point3D(0.5, 0.5, 0.0),
            Point3D(0.47, 0.502, 0.0),
            Point3D(0.43, 0.502, 0.0),
        ]
        ear_closed = detector.calculate_eye_aspect_ratio(closed_eye)
        assert ear_closed < 0.15

    def test_live_sequence_with_blinks_passes(self):
        detector = LivenessDetector(window_size=20)
        engine = FaceEngine()

        frames = []
        # Generate 15 frames with natural blinks and micro-motions
        for i in range(15):
            eye_ratio = 0.10 if (i == 7 or i == 8) else (0.30 + 0.02 * math.sin(i))
            lm = engine.create_synthetic_landmarks(
                yaw=0.5 * math.sin(i),
                pitch=0.3 * math.cos(i),
                roll=0.0,
                eye_open_ratio=eye_ratio,
            )
            frames.append(lm)

        is_live, conf, details = detector.verify_preflight_sequence(frames)
        assert is_live is True
        assert conf >= 0.80
        assert "Live" in details

    def test_static_printed_photo_rejected(self):
        detector = LivenessDetector(window_size=20)
        engine = FaceEngine()

        # Generate completely static identical frames (zero blink, zero motion)
        static_lm = engine.create_synthetic_landmarks(yaw=0.0, pitch=0.0, eye_open_ratio=0.30)
        frames = [static_lm] * 20

        is_live, conf, details = detector.verify_preflight_sequence(frames)
        assert is_live is False
        assert "rejected" in details.lower() or "static" in details.lower()


# ============================================================================
# 4. False-Positive Distraction Filter Tests
# ============================================================================


class TestDistractionAnalyzerWhitelist:
    """Test study whitelist (reading/writing/drinking) and flagged distractions."""

    def test_reading_downwards_is_whitelisted(self):
        analyzer = DistractionAnalyzer()
        pose = HeadPoseResult(
            yaw=5.0,
            pitch=35.0,  # Looking down at desk
            roll=0.0,
            posture=PostureCategory.LOOKING_DOWN,
            is_facing_screen=False,
            is_reading_writing_pose=True,
        )
        liveness = LivenessResult(
            is_live=True,
            confidence=0.95,
            blink_detected=False,
            ear=0.28,
            ear_variance=0.001,
            motion_score=0.001,
            texture_score=1.0,
            reason="Live",
        )

        res = analyzer.analyze(
            timestamp=100.0,
            presence_state=PresenceState.PRESENT,
            pose=pose,
            liveness=liveness,
            identity_match=True,
        )
        assert res.is_distracted is False
        assert res.distraction_type == DistractionType.NONE
        assert res.focus_score == 100.0
        assert res.whitelisted_action == WhitelistedAction.READING_DOWNWARDS

    def test_writing_notes_is_whitelisted(self):
        analyzer = DistractionAnalyzer()
        pose = HeadPoseResult(
            yaw=0.0,
            pitch=30.0,
            roll=0.0,
            posture=PostureCategory.LOOKING_DOWN,
            is_facing_screen=False,
            is_reading_writing_pose=True,
        )
        liveness = LivenessResult(
            is_live=True,
            confidence=0.95,
            blink_detected=False,
            ear=0.28,
            ear_variance=0.001,
            motion_score=0.001,
            texture_score=1.0,
            reason="Live",
        )

        res = analyzer.analyze(
            timestamp=100.0,
            presence_state=PresenceState.PRESENT,
            pose=pose,
            liveness=liveness,
            identity_match=True,
            writing_gesture=True,
        )
        assert res.is_distracted is False
        assert res.focus_score == 100.0
        assert res.whitelisted_action == WhitelistedAction.WRITING_NOTES

    def test_drinking_water_is_whitelisted(self):
        analyzer = DistractionAnalyzer()
        pose = HeadPoseResult(
            yaw=0.0,
            pitch=5.0,
            roll=0.0,
            posture=PostureCategory.HEAD_CENTER,
            is_facing_screen=True,
            is_reading_writing_pose=False,
        )
        liveness = LivenessResult(
            is_live=True,
            confidence=0.95,
            blink_detected=False,
            ear=0.28,
            ear_variance=0.001,
            motion_score=0.001,
            texture_score=1.0,
            reason="Live",
        )

        # Initial sip (duration 3s < 6s max)
        res = analyzer.analyze(
            timestamp=103.0,
            presence_state=PresenceState.PRESENT,
            pose=pose,
            liveness=liveness,
            identity_match=True,
            hand_to_mouth_gesture=True,
        )
        assert res.is_distracted is False
        assert res.whitelisted_action == WhitelistedAction.DRINKING_WATER
        assert res.focus_score == 100.0

    def test_prolonged_looking_away_is_flagged(self):
        analyzer = DistractionAnalyzer()
        pose = HeadPoseResult(
            yaw=45.0,  # Turned head far right (> 35 deg)
            pitch=0.0,
            roll=0.0,
            posture=PostureCategory.LOOKING_RIGHT,
            is_facing_screen=False,
            is_reading_writing_pose=False,
        )
        liveness = LivenessResult(
            is_live=True,
            confidence=0.95,
            blink_detected=False,
            ear=0.28,
            ear_variance=0.001,
            motion_score=0.001,
            texture_score=1.0,
            reason="Live",
        )

        # At t=100.0: first looking away frame
        res1 = analyzer.analyze(
            timestamp=100.0,
            presence_state=PresenceState.PRESENT,
            pose=pose,
            liveness=liveness,
            identity_match=True,
        )
        assert res1.is_distracted is False  # Within threshold grace

        # At t=112.0: 12 seconds looking away (> 10s threshold) -> Flagged
        res2 = analyzer.analyze(
            timestamp=112.0,
            presence_state=PresenceState.PRESENT,
            pose=pose,
            liveness=liveness,
            identity_match=True,
        )
        assert res2.is_distracted is True
        assert res2.distraction_type == DistractionType.LOOKING_AWAY
        assert res2.duration_seconds >= 10.0

    def test_phone_detected_is_flagged(self):
        analyzer = DistractionAnalyzer()
        pose = HeadPoseResult(
            yaw=0.0,
            pitch=10.0,
            roll=0.0,
            posture=PostureCategory.HEAD_CENTER,
            is_facing_screen=True,
            is_reading_writing_pose=False,
        )
        liveness = LivenessResult(
            is_live=True,
            confidence=0.95,
            blink_detected=False,
            ear=0.28,
            ear_variance=0.001,
            motion_score=0.001,
            texture_score=1.0,
            reason="Live",
        )

        # First frame phone seen
        analyzer.analyze(
            timestamp=100.0,
            presence_state=PresenceState.PRESENT,
            pose=pose,
            liveness=liveness,
            identity_match=True,
            phone_object_detected=True,
        )

        # 5 seconds phone interaction (> 4s threshold)
        res = analyzer.analyze(
            timestamp=105.0,
            presence_state=PresenceState.PRESENT,
            pose=pose,
            liveness=liveness,
            identity_match=True,
            phone_object_detected=True,
        )
        assert res.is_distracted is True
        assert res.distraction_type == DistractionType.PHONE_DETECTED


# ============================================================================
# 5. Warning Manager & 60-Second Cooldown Tests
# ============================================================================


class TestWarningManagerCooldown:
    """Test 60-second cooldown per category and confidence filtering."""

    def test_low_confidence_distraction_suppresses_warning(self):
        wm = WarningManager(cooldown_seconds=60.0, min_confidence=0.80)
        distraction = DistractionAnalysisResult(
            is_distracted=True,
            distraction_type=DistractionType.LOOKING_AWAY,
            focus_score=30.0,
            confidence=0.72,  # < 0.80 threshold
            duration_seconds=12.0,
        )
        event = wm.evaluate_and_dispatch(timestamp=100.0, distraction=distraction)
        assert event is None

    def test_warning_issued_and_throttled_by_60s_cooldown(self):
        wm = WarningManager(cooldown_seconds=60.0, min_confidence=0.80)
        distraction = DistractionAnalysisResult(
            is_distracted=True,
            distraction_type=DistractionType.LOOKING_AWAY,
            focus_score=30.0,
            confidence=0.90,
            duration_seconds=12.0,
        )

        # 1. First warning at t=100.0 -> Issued successfully
        event1 = wm.evaluate_and_dispatch(timestamp=100.0, distraction=distraction)
        assert event1 is not None
        assert event1.category == DistractionType.LOOKING_AWAY.value
        assert "focus" in event1.message.lower()

        # 2. Second warning at t=120.0 (20s elapsed < 60s cooldown) -> Suppressed
        event2 = wm.evaluate_and_dispatch(timestamp=120.0, distraction=distraction)
        assert event2 is None
        assert wm.get_cooldown_remaining(DistractionType.LOOKING_AWAY.value, 120.0) == 40.0

        # 3. Third warning at t=165.0 (65s elapsed > 60s cooldown) -> Issued
        event3 = wm.evaluate_and_dispatch(timestamp=165.0, distraction=distraction)
        assert event3 is not None

    def test_distinct_categories_have_independent_cooldowns(self):
        wm = WarningManager(cooldown_seconds=60.0, min_confidence=0.80)

        # Looking away alert at t=100.0
        d_look = DistractionAnalysisResult(
            is_distracted=True,
            distraction_type=DistractionType.LOOKING_AWAY,
            focus_score=30.0,
            confidence=0.90,
            duration_seconds=12.0,
        )
        e1 = wm.evaluate_and_dispatch(timestamp=100.0, distraction=d_look)
        assert e1 is not None

        # Phone alert at t=110.0 (different category) -> Should NOT be blocked by looking away cooldown
        d_phone = DistractionAnalysisResult(
            is_distracted=True,
            distraction_type=DistractionType.PHONE_DETECTED,
            focus_score=20.0,
            confidence=0.92,
            duration_seconds=5.0,
        )
        e2 = wm.evaluate_and_dispatch(timestamp=110.0, distraction=d_phone)
        assert e2 is not None
        assert e2.category == DistractionType.PHONE_DETECTED.value


# ============================================================================
# 6. Local Pipeline & Zero-Cloud Invariant Tests
# ============================================================================


class TestLocalCVPipelineAndAPI:
    """Test LocalCVPipeline execution and zero-cloud data leak invariant."""

    def test_zero_cloud_egress_invariant(self):
        pipeline = LocalCVPipeline()
        pipeline.reset_session()

        payload = pipeline.generate_mock_telemetry(scenario="normal_study", timestamp=100.0)
        res = pipeline.process_telemetry_payload(payload, current_time=100.0)

        # Zero cloud egress invariant
        assert res.cloud_egress_bytes == 0
        assert res.face_detected is True
        assert res.presence.state == PresenceState.PRESENT
        assert res.engagement.score >= 80.0

    def test_writing_mock_scenario(self):
        pipeline = LocalCVPipeline()
        pipeline.reset_session()

        payload = pipeline.generate_mock_telemetry(scenario="writing_reading", timestamp=100.0)
        res = pipeline.process_telemetry_payload(payload, current_time=100.0)

        assert res.distraction.is_distracted is False
        assert res.distraction.whitelisted_action is not None
        assert res.distraction.focus_score == 100.0

    def test_api_status_endpoint(self):
        client = TestClient(app)
        resp = client.get("/api/v1/monitoring/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["zero_cloud_egress"] is True
        assert data["target_fps"] in (1, 2, 4, 5, 7, 8, 10)

    def test_api_enroll_face_endpoint(self):
        client = TestClient(app)
        dummy_vector = [0.1] * 128
        resp = client.post(
            "/api/v1/monitoring/enroll-face",
            json={"face_embedding": dummy_vector},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["dimension"] == 128

    def test_api_analyze_frame_endpoint(self):
        client = TestClient(app)
        pipeline = get_cv_pipeline()
        mock_payload = pipeline.generate_mock_telemetry(scenario="normal_study")

        resp = client.post(
            "/api/v1/monitoring/analyze-frame",
            json=mock_payload,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["face_detected"] is True
        assert data["presence"]["is_present"] is True
        assert data["cloud_egress_bytes"] == 0
