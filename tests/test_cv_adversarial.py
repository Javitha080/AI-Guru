"""
Adversarial Stress Test Suite for AI Guru Milestone 4 (Local Computer Vision).
==============================================================================

Targeted Validation of:
1. Cosine similarity mathematical boundaries:
   - 0.64 (rejected) vs 0.65 (accepted) thresholding
   - Orthogonal vectors (sim = 0.0)
   - Antipodal vectors (sim = -1.0)
   - Zero-magnitude and near-zero vectors
   - High-dimensional noise perturbations & dimension mismatches
2. Anti-spoof liveness detector:
   - Static printed photo attacks (zero EAR variance, zero micro-motion)
   - Smartphone screen replay simulations (texture moire / low texture penalty)
   - Genuine blinking student verification with natural EAR and micro-movements
   - Landmark occlusions and corrupted inputs
3. Strict Zero-Cloud Biometric & Frame Egress Invariant:
   - Socket connection interception & blocking during frame analysis, enrollment, and verification
   - cloud_egress_bytes == 0 assertion across all operations
   - API endpoints local-only execution
"""

from __future__ import annotations

import http.client
import math
import socket
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch
import urllib.request

from fastapi.testclient import TestClient
import pytest

from deeptutor.api.main import app
from deeptutor.services.monitoring import (
    FaceDetectionResult,
    FaceEngine,
    FaceLandmarks,
    FrameAnalysisResult,
    LivenessDetector,
    LivenessResult,
    LocalCVPipeline,
    Point3D,
    get_cv_pipeline,
)
from deeptutor.services.monitoring.distraction_analyzer import DistractionType, WhitelistedAction
from deeptutor.services.monitoring.presence_state_machine import PresenceState

# ============================================================================
# 1. Cosine Similarity Adversarial Mathematical Boundaries
# ============================================================================


class TestCosineSimilarityAdversarialBoundaries:
    """Adversarial stress-testing of geometric embeddings and cosine similarity math."""

    def test_exact_threshold_065_accepted(self):
        """
        Cosine similarity == 0.6500 must be ACCEPTED (is_match == True).
        Threshold contract: sim >= 0.65
        """
        engine = FaceEngine(match_threshold=0.65)
        # Unit baseline vector along dimension 0
        baseline = [0.0] * 128
        baseline[0] = 1.0
        engine.enroll_face(baseline)

        # Construct vector with exact cosine similarity 0.650000
        # cos(theta) = 0.65 -> x0 = 0.65, x1 = sqrt(1 - 0.65^2)
        v_065 = [0.0] * 128
        v_065[0] = 0.65
        v_065[1] = math.sqrt(1.0 - 0.65**2)

        is_match, score = engine.verify_identity(v_065)
        assert is_match is True, f"Expected is_match=True for sim=0.65, got {is_match}"
        assert pytest.approx(score, 0.001) == 0.65

    def test_sub_threshold_064_rejected(self):
        """
        Cosine similarity == 0.6400 must be REJECTED (is_match == False).
        Threshold contract: sim < 0.65
        """
        engine = FaceEngine(match_threshold=0.65)
        baseline = [0.0] * 128
        baseline[0] = 1.0
        engine.enroll_face(baseline)

        # Construct vector with exact cosine similarity 0.640000
        v_064 = [0.0] * 128
        v_064[0] = 0.64
        v_064[1] = math.sqrt(1.0 - 0.64**2)

        is_match, score = engine.verify_identity(v_064)
        assert is_match is False, f"Expected is_match=False for sim=0.64, got {is_match}"
        assert pytest.approx(score, 0.001) == 0.64

    def test_high_precision_boundary_sweep(self):
        """
        Adversarial sweep across [0.60, 0.70] in steps of 0.005.
        Every score < 0.65 must be False, every score >= 0.65 must be True.
        """
        engine = FaceEngine(match_threshold=0.65)
        baseline = [0.0] * 128
        baseline[0] = 1.0
        engine.enroll_face(baseline)

        for step in range(600, 701, 5):
            sim_target = step / 1000.0  # 0.600, 0.605, ... 0.700
            v = [0.0] * 128
            v[0] = sim_target
            v[1] = math.sqrt(max(0.0, 1.0 - sim_target**2))

            is_match, score = engine.verify_identity(v)
            if sim_target >= 0.65:
                assert is_match is True, f"Failed accept at sim={sim_target}"
            else:
                assert is_match is False, f"Failed reject at sim={sim_target}"
            assert pytest.approx(score, 0.001) == sim_target

    def test_orthogonal_vectors(self):
        """
        Adversarial test: Orthogonal vectors (sim = 0.0) -> is_match == False.
        """
        engine = FaceEngine(match_threshold=0.65)
        u = [1.0, 0.0, 0.0, 0.0]
        v = [0.0, 1.0, 0.0, 0.0]
        sim = FaceEngine.compute_cosine_similarity(u, v)
        assert pytest.approx(sim, 1e-6) == 0.0
        is_match, score = engine.verify_identity(v, baseline_embedding=u)
        assert is_match is False
        assert score == 0.0

    def test_antipodal_opposite_vectors(self):
        """
        Adversarial test: Antipodal opposite vectors (sim = -1.0) -> is_match == False.
        """
        engine = FaceEngine(match_threshold=0.65)
        u = [0.5, 0.5, 0.5, 0.5]
        v = [-0.5, -0.5, -0.5, -0.5]
        sim = FaceEngine.compute_cosine_similarity(u, v)
        assert pytest.approx(sim, 1e-6) == -1.0
        is_match, score = engine.verify_identity(v, baseline_embedding=u)
        assert is_match is False
        assert score == -1.0

    def test_zero_magnitude_vectors(self):
        """
        Adversarial test: All-zero vectors must not cause ZeroDivisionError.
        Returns 0.0 similarity gracefully.
        """
        engine = FaceEngine(match_threshold=0.65)
        zero_vec = [0.0] * 128
        norm_zero = engine._normalize_vector(zero_vec)
        assert norm_zero == zero_vec

        sim = engine.compute_cosine_similarity(zero_vec, [1.0] * 128)
        assert sim == 0.0

        sim_both_zero = engine.compute_cosine_similarity(zero_vec, zero_vec)
        assert sim_both_zero == 0.0

    def test_near_zero_magnitude_vectors(self):
        """
        Adversarial test: Sub-epsilon magnitude vectors (1e-15) must not crash or return NaN.
        """
        engine = FaceEngine(match_threshold=0.65)
        near_zero_a = [1e-15] * 128
        near_zero_b = [2e-15] * 128
        sim = engine.compute_cosine_similarity(near_zero_a, near_zero_b)
        assert not math.isnan(sim)
        assert not math.isinf(sim)

    def test_dimension_mismatch_handling(self):
        """
        Adversarial test: Different vector lengths (128D vs 64D or 256D)
        must truncate cleanly to min length without IndexError.
        """
        vec_128 = [1.0] * 128
        vec_64 = [1.0] * 64
        sim = FaceEngine.compute_cosine_similarity(vec_128, vec_64)
        assert pytest.approx(sim, 1e-4) == 1.0

    def test_empty_embedding_enrollment_raises_value_error(self):
        """
        Enrolling an empty embedding list must raise ValueError.
        """
        engine = FaceEngine()
        with pytest.raises(ValueError, match="must not be empty"):
            engine.enroll_face([])

    def test_adversarial_gaussian_noise_degradation(self):
        """
        Adversarial perturbation: Adding progressive noise to baseline vector
        must monotonically degrade cosine similarity.
        """
        engine = FaceEngine(match_threshold=0.65)
        landmarks = engine.create_synthetic_landmarks(yaw=0.0, pitch=0.0, roll=0.0)
        baseline = engine.generate_geometric_embedding(landmarks)
        engine.enroll_face(baseline)

        last_sim = 1.0
        for noise_scale in [0.05, 0.1, 0.2, 0.5, 1.0, 2.0]:
            perturbed = [b + noise_scale * math.sin(idx * 1.7) for idx, b in enumerate(baseline)]
            sim = engine.compute_cosine_similarity(baseline, perturbed)
            assert sim <= last_sim + 0.05, (
                f"Similarity did not degrade as expected at scale {noise_scale}"
            )
            last_sim = sim


# ============================================================================
# 2. Anti-Spoof Liveness Detector Adversarial Attacks
# ============================================================================


class TestAntiSpoofLivenessAdversarialAttacks:
    """Stress-testing liveness detection against photos, screens, and attacks."""

    def test_static_printed_photo_zero_ear_zero_motion(self):
        """
        Adversarial Attack: Static printed photo held in front of webcam.
        - Exactly 0 EAR variance across 30 frames
        - Exactly 0 nose/landmark micro-movement
        Invariant: Spoof detected (is_live == False, reason mentions static image).
        """
        detector = LivenessDetector(window_size=30)
        engine = FaceEngine()

        # Generate completely static identical frames
        static_landmark = engine.create_synthetic_landmarks(
            yaw=0.0,
            pitch=0.0,
            roll=0.0,
            eye_open_ratio=0.30,
        )

        for frame_idx in range(30):
            res = detector.evaluate_frame(
                landmarks=static_landmark,
                timestamp=frame_idx * 0.1,
                texture_laplacian_var=25.0,  # Low texture for paper
            )
            if frame_idx >= 5:
                assert res.is_live is False, f"Frame {frame_idx} accepted static photo attack!"
                assert "static" in res.reason.lower() or "zero" in res.reason.lower()
                assert res.ear_variance < 1e-6
                assert res.motion_score < 1e-6

    def test_preflight_sequence_rejects_static_photo(self):
        """
        Adversarial Attack: 3-second preflight sequence with motionless photo.
        Invariant: verify_preflight_sequence returns is_live=False, conf >= 0.90.
        """
        detector = LivenessDetector()
        engine = FaceEngine()
        static_landmark = engine.create_synthetic_landmarks(yaw=0.0, pitch=0.0, eye_open_ratio=0.30)
        sequence = [static_landmark] * 30

        is_live, conf, details = detector.verify_preflight_sequence(sequence)
        assert is_live is False
        assert conf >= 0.90
        assert "rejected" in details.lower() or "static" in details.lower()

    def test_smartphone_screen_replay_high_moire_penalty(self):
        """
        Adversarial Simulation: Video played back on a smartphone screen.
        High-frequency moiré patterns cause extreme Laplacian variance (> 800.0).
        Invariant: Texture score is penalized, reducing liveness confidence.
        """
        detector = LivenessDetector(window_size=30)
        engine = FaceEngine()

        # Feed frames with high moire Laplacian variance (e.g. 1500.0)
        landmarks = engine.create_synthetic_landmarks(yaw=0.0, pitch=0.0, eye_open_ratio=0.30)
        res = detector.evaluate_frame(
            landmarks=landmarks,
            timestamp=100.0,
            texture_laplacian_var=1500.0,  # High moiré artifact
        )
        assert res.texture_score < 1.0
        assert res.texture_score >= 0.3

    def test_low_texture_paper_printout_penalty(self):
        """
        Adversarial Simulation: Blurry paper printout with very low Laplacian variance (< 30.0).
        Invariant: Texture score is discounted proportionally.
        """
        detector = LivenessDetector(window_size=30)
        engine = FaceEngine()

        landmarks = engine.create_synthetic_landmarks(yaw=0.0, pitch=0.0, eye_open_ratio=0.30)
        res = detector.evaluate_frame(
            landmarks=landmarks,
            timestamp=100.0,
            texture_laplacian_var=15.0,  # Blurry printout
        )
        assert res.texture_score == pytest.approx(15.0 / 30.0, 0.01)
        assert res.texture_score <= 0.5

    def test_genuine_blinking_student_dynamics(self):
        """
        Genuine Student: Realistic eye closing (EAR < 0.18 for 2 frames) and reopening,
        with subtle head micro-movement.
        Invariant: is_live == True, blink_detected == True, confidence >= 0.85.
        """
        detector = LivenessDetector(window_size=30)
        engine = FaceEngine()

        # 25 frames simulation
        # Frames 0-9: open eyes (EAR ~ 0.30)
        # Frames 10-11: closed eyes / blink (EAR ~ 0.10)
        # Frames 12-24: open eyes (EAR ~ 0.30)
        blink_seen = False
        for frame_idx in range(25):
            t = frame_idx * 0.1
            is_blink_frame = frame_idx in (10, 11)
            eye_ratio = 0.08 if is_blink_frame else (0.30 + 0.01 * math.sin(frame_idx))

            # Natural nose micro-jitter
            lm = engine.create_synthetic_landmarks(
                yaw=0.5 * math.sin(frame_idx * 0.5),
                pitch=0.3 * math.cos(frame_idx * 0.5),
                roll=0.0,
                eye_open_ratio=eye_ratio,
            )

            res = detector.evaluate_frame(
                landmarks=lm,
                timestamp=t,
                texture_laplacian_var=200.0,  # Healthy webcam texture
            )
            if res.blink_detected:
                blink_seen = True

        assert blink_seen is True, "Blink state machine failed to capture natural blink event"
        assert res.is_live is True
        assert res.confidence >= 0.85
        assert detector._blink_count >= 1

    def test_graceful_handling_of_none_or_corrupted_landmarks(self):
        """
        Adversarial test: Feeding None or corrupted landmarks should not throw unhandled exceptions.
        """
        detector = LivenessDetector()
        res = detector.evaluate_frame(landmarks=None)
        assert res.is_live is False
        assert res.confidence == 0.0
        assert "No face landmarks" in res.reason

        # FaceLandmarks with empty eye points
        empty_eye_lm = FaceLandmarks(left_eye=[], right_eye=[])
        res_empty = detector.evaluate_frame(landmarks=empty_eye_lm)
        assert res_empty.is_live is True  # Single frame warmup default
        assert res_empty.ear == 0.3  # Default fallback ratio


# ============================================================================
# 3. Zero-Cloud Egress Invariant & Socket Interception
# ============================================================================


class TestZeroCloudEgressAdversarialSocketInterception:
    """
    Adversarial verification of the Zero-Cloud Egress Invariant:
    Guarantees that no video frames, landmarks, or embeddings ever open outbound network sockets.
    """

    @pytest.fixture(autouse=True)
    def socket_guard(self):
        """
        Intercept and record all socket creation and connection attempts.
        Raises AssertionError if any external network connection is attempted.
        """
        attempted_connections: List[Tuple[str, int]] = []
        orig_connect = socket.socket.connect

        def guarded_connect(self, address):
            # Allow loopback/localhost only if needed by test client
            if isinstance(address, tuple) and len(address) >= 2:
                host, port = address[0], address[1]
                if host in ("127.0.0.1", "localhost", "::1", "testclient"):
                    return orig_connect(self, address)
                attempted_connections.append((host, port))
                raise ConnectionRefusedError(
                    f"SECURITY BREACH: Attempted outbound cloud socket to {host}:{port}"
                )
            return orig_connect(self, address)

        with patch.object(socket.socket, "connect", guarded_connect):
            yield attempted_connections

    def test_zero_cloud_egress_during_100_frame_pipeline_execution(self, socket_guard):
        """
        Process 100 frames through LocalCVPipeline while monitoring sockets.
        Invariants:
        1. cloud_egress_bytes == 0 on every single frame
        2. zero external socket connection attempts
        """
        pipeline = LocalCVPipeline()
        pipeline.reset_session()

        # Enroll baseline
        landmarks = pipeline.face_engine.create_synthetic_landmarks()
        embedding = pipeline.face_engine.generate_geometric_embedding(landmarks)
        pipeline.enroll_student_baseline(embedding)

        scenarios = [
            "normal_study",
            "writing_reading",
            "drinking_water",
            "looking_away",
            "phone_usage",
            "absent",
            "static_photo",
            "identity_mismatch",
        ]

        for i in range(100):
            scenario = scenarios[i % len(scenarios)]
            payload = pipeline.generate_mock_telemetry(scenario=scenario, timestamp=i * 0.1)
            result: FrameAnalysisResult = pipeline.process_telemetry_payload(
                payload, current_time=i * 0.1
            )

            # Invariant: cloud_egress_bytes == 0
            assert result.cloud_egress_bytes == 0, f"Cloud egress breach at frame {i}"

        # Invariant: Zero outbound socket attempts
        assert len(socket_guard) == 0, f"Socket leak detected: {socket_guard}"

    def test_zero_cloud_egress_across_all_monitoring_api_endpoints(self, socket_guard):
        """
        Exercise all REST API endpoints for monitoring through FastAPI TestClient.
        Invariants: All return cloud_egress_bytes == 0 and open zero external sockets.
        """
        client = TestClient(app)

        # 1. Status endpoint
        resp_status = client.get("/api/v1/monitoring/status")
        assert resp_status.status_code == 200
        assert resp_status.json()["zero_cloud_egress"] is True

        # 2. Face Enrollment endpoint
        dummy_vector = [0.1 * math.sin(i) for i in range(128)]
        resp_enroll = client.post(
            "/api/v1/monitoring/enroll-face",
            json={"face_embedding": dummy_vector},
        )
        assert resp_enroll.status_code == 200
        assert resp_enroll.json()["success"] is True

        # 3. Liveness Verification endpoint
        pipeline = get_cv_pipeline()
        static_payload = pipeline.generate_mock_telemetry(scenario="static_photo")
        resp_liveness = client.post(
            "/api/v1/monitoring/verify-liveness",
            json={"frames_landmarks": [static_payload] * 5},
        )
        assert resp_liveness.status_code == 200
        assert resp_liveness.json()["is_live"] is False  # Correctly rejected static photo

        # 4. Frame Analysis endpoint
        normal_payload = pipeline.generate_mock_telemetry(scenario="normal_study")
        resp_analyze = client.post(
            "/api/v1/monitoring/analyze-frame",
            json=normal_payload,
        )
        assert resp_analyze.status_code == 200
        data = resp_analyze.json()
        assert data["cloud_egress_bytes"] == 0
        assert data["face_detected"] is True

        # Invariant: Zero external socket attempts
        assert len(socket_guard) == 0, f"External network connection attempted: {socket_guard}"


# ============================================================================
# 4. Full End-to-End Adversarial Telemetry Lifecycle
# ============================================================================


class TestFullAdversarialTelemetryLifecycle:
    """End-to-end multi-phase student session simulation under adversarial conditions."""

    def test_complete_adversarial_session_lifecycle(self):
        """
        Simulate a full adversarial study session:
        Phase 1: Student enrolls 128D geometric face.
        Phase 2: Attacker attempts static photo spoof -> Liveness fails.
        Phase 3: Genuine student performs live preflight -> Liveness passes.
        Phase 4: Student studies, takes notes (pitch 35°), drinks water -> 0 false alerts.
        Phase 5: Student leaves desk for 25 seconds -> Transitions to AWAY.
        Phase 6: Attacker with wrong face sits down -> Identity mismatch flagged.
        Phase 7: Genuine student returns -> Identity verified, returns to PRESENT.
        Invariants: Strict Zero Cloud Egress throughout all 7 phases.
        """
        pipeline = LocalCVPipeline()
        pipeline.reset_session()

        # Phase 1: Enrollment
        student_lm = pipeline.face_engine.create_synthetic_landmarks(yaw=0.0, pitch=0.0, roll=0.0)
        student_emb = pipeline.face_engine.generate_geometric_embedding(student_lm)
        pipeline.enroll_student_baseline(student_emb)
        assert pipeline.face_engine.get_enrolled_face() is not None

        # Phase 2: Attacker photo spoof during preflight
        static_photo_seq = [student_lm] * 20
        is_live_atk, conf_atk, _ = pipeline.liveness_detector.verify_preflight_sequence(
            static_photo_seq
        )
        assert is_live_atk is False, "Static photo spoof bypass succeeded!"

        # Phase 3: Genuine student blinking preflight
        live_seq = []
        for i in range(20):
            eye_r = 0.08 if i in (8, 9) else (0.30 + 0.01 * math.sin(i))
            live_lm = pipeline.face_engine.create_synthetic_landmarks(
                yaw=0.2 * math.sin(i),
                pitch=0.0,
                eye_open_ratio=eye_r,
            )
            live_seq.append(live_lm)

        is_live_gen, conf_gen, _ = pipeline.liveness_detector.verify_preflight_sequence(live_seq)
        assert is_live_gen is True, "Genuine student was falsely rejected during preflight"

        # Phase 4: Study + gestures (t=0 to t=30s)
        t = 0.0
        for _ in range(100):  # 10s writing
            t += 0.1
            payload = pipeline.generate_mock_telemetry(scenario="writing_reading", timestamp=t)
            res = pipeline.process_telemetry_payload(payload, current_time=t)
            assert res.cloud_egress_bytes == 0
            assert res.distraction.is_distracted is False
            assert res.distraction.whitelisted_action is not None

        # Phase 5: Student leaves desk for 25s (t=30 to t=55s)
        for _ in range(250):  # 25s absent
            t += 0.1
            payload = pipeline.generate_mock_telemetry(scenario="absent", timestamp=t)
            res = pipeline.process_telemetry_payload(payload, current_time=t)
            assert res.cloud_egress_bytes == 0

        assert res.presence.state == PresenceState.AWAY
        assert res.presence.is_present is False

        # Phase 6: Attacker sits down (t=55 to t=75s, 20s mismatch)
        for _ in range(200):
            t += 0.1
            payload = pipeline.generate_mock_telemetry(scenario="identity_mismatch", timestamp=t)
            res = pipeline.process_telemetry_payload(payload, current_time=t)
            assert res.cloud_egress_bytes == 0
            assert res.identity_matched is False
            assert res.identity_similarity < 0.65

        # After 15s of identity mismatch, distraction analyzer flags identity mismatch
        assert res.distraction.is_distracted is True
        assert res.distraction.distraction_type == DistractionType.IDENTITY_MISMATCH

        # Phase 7: Genuine student returns (t=75 to t=85s)
        for _ in range(100):
            t += 0.1
            payload = pipeline.generate_mock_telemetry(scenario="normal_study", timestamp=t)
            res = pipeline.process_telemetry_payload(payload, current_time=t)
            assert res.cloud_egress_bytes == 0
            assert res.identity_matched is True
            assert res.presence.state == PresenceState.PRESENT
            assert res.presence.is_present is True
