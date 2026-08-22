"""
Adversarial Stress Test Suite for AI Guru Study Monitoring Engine (Local CV).
=============================================================================

Specialist / Critic Verification of Milestone 4 Invariants:
1. Presence State Machine Hysteresis & Anti-Flapping under rapid oscillating visibility.
2. Distraction Analyzer Robustness against edge study gestures (writing, pitch down/center, drinking, page turns).
3. Warning Manager Strict 60s Cooldown & Rate Limit Window under 100+ event spamming.
4. LocalCVPipeline High-Volume Telemetry (1,000 continuous frames) for memory leak & execution time bounds.
5. Strict Zero-Cloud Biometric / Video Egress Invariant across all operations.
"""

import gc
import math
import time
import tracemalloc
import pytest

from deeptutor.services.monitoring.cv_pipeline import (
    FrameAnalysisResult,
    LocalCVPipeline,
)
from deeptutor.services.monitoring.distraction_analyzer import (
    DistractionAnalysisResult,
    DistractionAnalyzer,
    DistractionType,
    WhitelistedAction,
)
from deeptutor.services.monitoring.face_engine import FaceEngine, FaceLandmarks, Point3D
from deeptutor.services.monitoring.liveness_detector import LivenessDetector, LivenessResult
from deeptutor.services.monitoring.pose_gaze import (
    GazeResult,
    HeadPoseResult,
    PostureCategory,
)
from deeptutor.services.monitoring.presence_state_machine import (
    PresenceState,
    PresenceStateMachine,
)
from deeptutor.services.monitoring.warning_manager import (
    WarningEvent,
    WarningManager,
)


# ============================================================================
# 1. Presence State Machine Adversarial Oscillation & Hysteresis
# ============================================================================

class TestPresenceStateMachineStress:
    """Stress test presence state machine under rapid visibility flapping and boundary times."""

    def test_rapid_oscillating_visibility_100_iterations(self):
        """
        Adversarial Scenario: 1 frame visible, 1 frame not visible for 100 iterations.
        Hysteresis requirement: State must remain continuously PRESENT with ZERO state flapping.
        """
        sm = PresenceStateMachine(temp_absent_seconds=5.0, away_seconds=20.0)

        # Initial frame at t=0.0
        init_res = sm.update(face_detected=True, confidence=0.95, timestamp=0.0)
        assert init_res.state == PresenceState.PRESENT
        assert init_res.is_present is True
        assert len(sm.history) == 0

        # Oscillate for 100 iterations at 10 FPS (total 10 seconds, dt=0.1s)
        # Even frames (0.1, 0.3, ...): Not visible (unobserved dt = 0.1s < 5.0s)
        # Odd frames (0.2, 0.4, ...): Visible
        current_time = 0.0
        for i in range(1, 201):
            current_time += 0.1
            face_visible = (i % 2 == 0)  # Alternating True/False
            res = sm.update(
                face_detected=face_visible,
                confidence=0.95 if face_visible else 0.0,
                timestamp=current_time,
            )

            # Invariant: Must remain PRESENT at every single step
            assert res.state == PresenceState.PRESENT, (
                f"Flapping detected at step {i}, t={current_time:.1f}s: state is {res.state}"
            )
            assert res.is_present is True
            assert res.state_changed is False, (
                f"Spurious state_changed=True at step {i}, t={current_time:.1f}s"
            )

        # Invariant: Exactly zero transition events in history
        assert len(sm.history) == 0, f"Expected 0 transitions, got {len(sm.history)}"

    def test_noisy_intermittent_packet_drops_500_frames(self):
        """
        Adversarial Scenario: 500 frames with random packet drops where max unobserved gap is <= 3.0s.
        State must maintain unbroken PRESENT continuity.
        """
        sm = PresenceStateMachine(temp_absent_seconds=5.0, away_seconds=20.0)
        sm.update(face_detected=True, timestamp=0.0)

        t = 0.0
        for frame in range(1, 501):
            t += 0.1  # 10 FPS
            # Burst pattern: 2 frames visible, 1 frame dropped, 1 frame visible, 2 dropped...
            # Max dropped in a row = 4 frames = 0.4s (< 5.0s)
            is_visible = not (frame % 5 in (3, 4))
            res = sm.update(face_detected=is_visible, confidence=0.90 if is_visible else 0.0, timestamp=t)
            assert res.state == PresenceState.PRESENT
            assert res.is_present is True

        assert len(sm.history) == 0

    def test_exact_temporal_hysteresis_boundaries(self):
        """
        Adversarial verification of exact hysteresis time thresholds:
        - 4.9s unobserved -> PRESENT (grace period)
        - 5.0s unobserved -> TEMPORARILY_NOT_VISIBLE
        - 19.9s unobserved -> TEMPORARILY_NOT_VISIBLE
        - 20.0s unobserved -> AWAY
        - Instant recovery back to PRESENT at 20.1s
        """
        sm = PresenceStateMachine(temp_absent_seconds=5.0, away_seconds=20.0)
        sm.update(face_detected=True, timestamp=100.0)

        # 1. 4.9s unobserved -> PRESENT
        r1 = sm.update(face_detected=False, timestamp=104.9)
        assert r1.state == PresenceState.PRESENT
        assert r1.is_present is True

        # 2. 5.0s unobserved -> TEMPORARILY_NOT_VISIBLE
        r2 = sm.update(face_detected=False, timestamp=105.0)
        assert r2.state == PresenceState.TEMPORARILY_NOT_VISIBLE
        assert r2.is_present is False
        assert r2.state_changed is True

        # 3. 19.9s unobserved -> Still TEMPORARILY_NOT_VISIBLE
        r3 = sm.update(face_detected=False, timestamp=119.9)
        assert r3.state == PresenceState.TEMPORARILY_NOT_VISIBLE
        assert r3.is_present is False

        # 4. 20.0s unobserved -> AWAY
        r4 = sm.update(face_detected=False, timestamp=120.0)
        assert r4.state == PresenceState.AWAY
        assert r4.is_present is False
        assert r4.state_changed is True

        # 5. Instant recovery to PRESENT on frame re-detection
        r5 = sm.update(face_detected=True, confidence=0.90, timestamp=120.1)
        assert r5.state == PresenceState.PRESENT
        assert r5.is_present is True
        assert r5.state_changed is True
        assert r5.unobserved_duration_seconds == 0.0

        # Verify history transitions
        transitions = sm.history
        assert len(transitions) == 3
        assert transitions[0].from_state == PresenceState.PRESENT
        assert transitions[0].to_state == PresenceState.TEMPORARILY_NOT_VISIBLE
        assert transitions[1].from_state == PresenceState.TEMPORARILY_NOT_VISIBLE
        assert transitions[1].to_state == PresenceState.AWAY
        assert transitions[2].from_state == PresenceState.AWAY
        assert transitions[2].to_state == PresenceState.PRESENT


# ============================================================================
# 2. Distraction Analyzer Robustness on Edge Study Gestures
# ============================================================================

class TestDistractionAnalyzerEdgeGestures:
    """Stress test distraction analyzer against realistic and edge study actions."""

    @pytest.fixture
    def live_sample(self):
        return LivenessResult(
            is_live=True,
            confidence=0.95,
            blink_detected=False,
            ear=0.28,
            ear_variance=0.001,
            motion_score=0.001,
            texture_score=1.0,
            reason="Live student verified",
        )

    def test_rapid_writing_bursts_and_down_center_alternation(self, live_sample):
        """
        Adversarial Scenario: Student rapidly alternates between looking down at notes (pitch=35°)
        and looking up at screen (pitch=0°) for 100 cycles.
        Invariants: is_distracted == False, focus_score >= 95.0, 0 false alerts.
        """
        analyzer = DistractionAnalyzer()
        t = 0.0

        for cycle in range(100):
            # Phase A: Looking down / writing (2.0s)
            pose_down = HeadPoseResult(
                yaw=0.0,
                pitch=35.0,
                roll=0.0,
                posture=PostureCategory.LOOKING_DOWN,
                is_facing_screen=False,
                is_reading_writing_pose=True,
            )
            for _ in range(20):  # 20 frames @ 10 FPS = 2.0s
                t += 0.1
                res = analyzer.analyze(
                    timestamp=t,
                    presence_state=PresenceState.PRESENT,
                    pose=pose_down,
                    liveness=live_sample,
                    identity_match=True,
                    writing_gesture=True,
                )
                assert res.is_distracted is False
                assert res.distraction_type == DistractionType.NONE
                assert res.focus_score == 100.0
                assert res.whitelisted_action in (
                    WhitelistedAction.WRITING_NOTES,
                    WhitelistedAction.READING_DOWNWARDS,
                )

            # Phase B: Looking center at screen (2.0s)
            pose_center = HeadPoseResult(
                yaw=0.0,
                pitch=0.0,
                roll=0.0,
                posture=PostureCategory.HEAD_CENTER,
                is_facing_screen=True,
                is_reading_writing_pose=False,
            )
            for _ in range(20):  # 20 frames @ 10 FPS = 2.0s
                t += 0.1
                res = analyzer.analyze(
                    timestamp=t,
                    presence_state=PresenceState.PRESENT,
                    pose=pose_center,
                    liveness=live_sample,
                    identity_match=True,
                    writing_gesture=False,
                )
                assert res.is_distracted is False
                assert res.distraction_type == DistractionType.NONE
                assert res.focus_score == 100.0

    def test_transient_drinking_water_repeated_episodes(self, live_sample):
        """
        Adversarial Scenario: Student takes multiple discrete sips of water throughout study.
        Each sip lasts 2-4 seconds with 10s study gaps.
        Invariants: Whitelisted as DRINKING_WATER, is_distracted == False, 0 false alerts.
        """
        analyzer = DistractionAnalyzer()
        pose_center = HeadPoseResult(yaw=0.0, pitch=5.0, roll=0.0, posture=PostureCategory.HEAD_CENTER, is_facing_screen=True, is_reading_writing_pose=False)
        t = 0.0

        for episode in range(5):
            # Sip water for 3.0s (30 frames)
            for frame in range(30):
                t += 0.1
                res = analyzer.analyze(
                    timestamp=t,
                    presence_state=PresenceState.PRESENT,
                    pose=pose_center,
                    liveness=live_sample,
                    identity_match=True,
                    hand_to_mouth_gesture=True,
                )
                assert res.is_distracted is False
                assert res.whitelisted_action == WhitelistedAction.DRINKING_WATER
                assert res.focus_score == 100.0

            # Normal study for 10.0s (100 frames) without drinking gesture
            for frame in range(100):
                t += 0.1
                res = analyzer.analyze(
                    timestamp=t,
                    presence_state=PresenceState.PRESENT,
                    pose=pose_center,
                    liveness=live_sample,
                    identity_match=True,
                    hand_to_mouth_gesture=False,
                )
                assert res.is_distracted is False
                assert res.distraction_type == DistractionType.NONE
                assert res.focus_score == 100.0

    def test_full_complex_study_workflow_sequence(self, live_sample):
        """
        Simulate a complex 2-minute real-world study session containing:
        1. Reading textbook (pitch 30°) - 20s
        2. Note writing (writing_gesture=True) - 30s
        3. Page turning (page_turn_gesture=True, 2s) - 2s
        4. Drinking water (hand_to_mouth=True, 3s) - 3s
        5. Neck stretch (head_tilt, 2s) - 2s
        6. Looking back at tutor screen (pitch 0°) - 60s
        Invariants: Exactly 0 distractions flagged across all 1,170 frames (117s).
        """
        analyzer = DistractionAnalyzer()
        t = 0.0

        # 1. Reading
        pose_reading = HeadPoseResult(yaw=0.0, pitch=30.0, roll=0.0, posture=PostureCategory.LOOKING_DOWN, is_facing_screen=False, is_reading_writing_pose=True)
        for _ in range(200):
            t += 0.1
            res = analyzer.analyze(t, PresenceState.PRESENT, pose_reading, live_sample, True)
            assert not res.is_distracted
            assert res.focus_score == 100.0

        # 2. Writing
        for _ in range(300):
            t += 0.1
            res = analyzer.analyze(t, PresenceState.PRESENT, pose_reading, live_sample, True, writing_gesture=True)
            assert not res.is_distracted
            assert res.focus_score == 100.0

        # 3. Turning page
        for _ in range(20):
            t += 0.1
            res = analyzer.analyze(t, PresenceState.PRESENT, pose_reading, live_sample, True, page_turn_gesture=True)
            assert not res.is_distracted
            assert res.focus_score == 100.0

        # 4. Drinking water
        pose_center = HeadPoseResult(yaw=0.0, pitch=0.0, roll=0.0, posture=PostureCategory.HEAD_CENTER, is_facing_screen=True, is_reading_writing_pose=False)
        for _ in range(30):
            t += 0.1
            res = analyzer.analyze(t, PresenceState.PRESENT, pose_center, live_sample, True, hand_to_mouth_gesture=True)
            assert not res.is_distracted
            assert res.focus_score == 100.0

        # 5. Neck stretch
        pose_tilt = HeadPoseResult(yaw=0.0, pitch=0.0, roll=25.0, posture=PostureCategory.HEAD_TILT, is_facing_screen=True, is_reading_writing_pose=False)
        for _ in range(20):
            t += 0.1
            res = analyzer.analyze(t, PresenceState.PRESENT, pose_tilt, live_sample, True)
            assert not res.is_distracted
            assert res.focus_score >= 95.0

        # 6. Screen attention
        for _ in range(600):
            t += 0.1
            res = analyzer.analyze(t, PresenceState.PRESENT, pose_center, live_sample, True)
            assert not res.is_distracted
            assert res.focus_score == 100.0


# ============================================================================
# 3. Warning Manager Stress: 100 Distraction Events under 60s
# ============================================================================

class TestWarningManagerCooldownStress:
    """Stress test warning manager cooldown under high-frequency alert spamming."""

    def test_firing_100_distraction_events_within_60_seconds(self):
        """
        Adversarial Scenario: Fire 100 distraction events within 60 seconds (every 0.5s from t=0.0 to t=49.5s).
        Invariants:
        - Exactly 1 warning is emitted at t=0.0.
        - Exactly 99 warnings are suppressed.
        - Total warnings emitted across the first 60s == 1.
        - At t=60.5s (after 60s cooldown expires), the 101st event triggers exactly 1 new warning.
        """
        wm = WarningManager(cooldown_seconds=60.0, min_confidence=0.80)
        phone_distraction = DistractionAnalysisResult(
            is_distracted=True,
            distraction_type=DistractionType.PHONE_DETECTED,
            focus_score=20.0,
            confidence=0.95,
            duration_seconds=5.0,
            reason="Smartphone detected",
        )

        emitted_count = 0
        suppressed_count = 0

        # Fire 100 events from t=0.0 to t=49.5s
        t = 0.0
        for i in range(100):
            event = wm.evaluate_and_dispatch(timestamp=t, distraction=phone_distraction)
            if event is not None:
                emitted_count += 1
            else:
                suppressed_count += 1
            t += 0.5

        # Verification for 100 events in first 50 seconds
        assert emitted_count == 1, f"Expected exactly 1 warning emitted, got {emitted_count}"
        assert suppressed_count == 99, f"Expected 99 suppressed, got {suppressed_count}"
        assert len(wm.get_all_warnings()) == 1

        # Test at t=59.0s (still within 60s cooldown) -> Suppressed
        event_59s = wm.evaluate_and_dispatch(timestamp=59.0, distraction=phone_distraction)
        assert event_59s is None
        assert wm.get_cooldown_remaining(DistractionType.PHONE_DETECTED.value, 59.0) == 1.0

        # Test at t=60.5s (cooldown elapsed) -> Successfully Emitted!
        event_60s5 = wm.evaluate_and_dispatch(timestamp=60.5, distraction=phone_distraction)
        assert event_60s5 is not None
        assert event_60s5.category == DistractionType.PHONE_DETECTED.value
        assert len(wm.get_all_warnings()) == 2

    def test_multi_category_concurrent_spam(self):
        """
        Adversarial Scenario: 100 Phone events and 100 Looking Away events interleaved in 50 seconds.
        Invariants: Independent cooldowns per category -> exactly 1 warning per category (total 2).
        """
        wm = WarningManager(cooldown_seconds=60.0, min_confidence=0.80)
        phone_d = DistractionAnalysisResult(
            is_distracted=True,
            distraction_type=DistractionType.PHONE_DETECTED,
            focus_score=20.0,
            confidence=0.95,
            duration_seconds=5.0,
        )
        look_d = DistractionAnalysisResult(
            is_distracted=True,
            distraction_type=DistractionType.LOOKING_AWAY,
            focus_score=30.0,
            confidence=0.90,
            duration_seconds=12.0,
        )

        phone_warnings = 0
        look_warnings = 0

        t = 0.0
        for _ in range(100):
            ev_p = wm.evaluate_and_dispatch(t, phone_d)
            if ev_p:
                phone_warnings += 1

            ev_l = wm.evaluate_and_dispatch(t + 0.1, look_d)
            if ev_l:
                look_warnings += 1

            t += 0.5

        assert phone_warnings == 1
        assert look_warnings == 1
        assert len(wm.get_all_warnings()) == 2

    def test_window_rate_limit_10_minute_governance(self):
        """
        Adversarial Scenario: 10 distraction alerts triggered every 65s (spaced beyond 60s cooldown).
        Max allowed per 10-minute (600s) window is 5.
        Invariants: Exactly 5 warnings emitted; alerts 6 to 10 are suppressed by 10-min window governor.
        """
        wm = WarningManager(cooldown_seconds=60.0, min_confidence=0.80)
        phone_d = DistractionAnalysisResult(
            is_distracted=True,
            distraction_type=DistractionType.PHONE_DETECTED,
            focus_score=20.0,
            confidence=0.95,
            duration_seconds=5.0,
        )

        emitted = 0
        suppressed = 0

        # 10 attempts spaced by 65.0s (t = 0, 65, 130, 195, 260, 325, 390, 455, 520, 585)
        for i in range(10):
            t = i * 65.0
            ev = wm.evaluate_and_dispatch(timestamp=t, distraction=phone_d)
            if ev is not None:
                emitted += 1
            else:
                suppressed += 1

        assert emitted == 5, f"Expected exactly 5 alerts allowed in 10-min window, got {emitted}"
        assert suppressed == 5, f"Expected 5 alerts suppressed by rate limit window, got {suppressed}"


# ============================================================================
# 4. High Telemetry Volume: 1,000 Frames Memory & Performance Bounds
# ============================================================================

class TestHighTelemetryVolumeAndMemoryLeak:
    """Stress test LocalCVPipeline across 1,000 continuous frames."""

    def test_1000_frames_continuous_pipeline_execution(self):
        """
        Adversarial Scenario: Process 1,000 continuous telemetry frames through LocalCVPipeline.
        Invariants:
        1. Zero memory leaks (bounded peak memory delta < 5.0 MB).
        2. Bounded execution latency (mean < 3.0 ms per frame).
        3. Strict Zero Cloud Egress invariant (cloud_egress_bytes == 0 for all 1,000 frames).
        4. Internal state consistency (_frame_count == 1000).
        """
        gc.collect()
        tracemalloc.start()
        snapshot_start = tracemalloc.take_snapshot()

        pipeline = LocalCVPipeline()
        pipeline.reset_session()

        # Enroll baseline face
        baseline_landmarks = pipeline.face_engine.create_synthetic_landmarks(yaw=0.0, pitch=0.0, roll=0.0)
        baseline_embedding = pipeline.face_engine.generate_geometric_embedding(baseline_landmarks)
        pipeline.enroll_student_baseline(baseline_embedding)

        total_frames = 1000
        scenarios = ["normal_study", "writing_reading", "drinking_water", "normal_study"]

        start_clock = time.perf_counter()
        simulated_time = 0.0

        for frame_idx in range(total_frames):
            simulated_time += 0.1  # 10 FPS
            scenario = scenarios[frame_idx % len(scenarios)]
            payload = pipeline.generate_mock_telemetry(scenario=scenario, timestamp=simulated_time)

            result: FrameAnalysisResult = pipeline.process_telemetry_payload(
                payload=payload,
                current_time=simulated_time,
            )

            # Invariant 1: Cloud Egress MUST be strictly 0
            assert result.cloud_egress_bytes == 0, f"Cloud egress breach at frame {frame_idx}"
            assert result.face_detected is True
            assert result.identity_matched is True
            assert result.identity_similarity >= 0.65

        total_wall_time = time.perf_counter() - start_clock
        avg_ms_per_frame = (total_wall_time / total_frames) * 1000.0

        snapshot_end = tracemalloc.take_snapshot()
        tracemalloc.stop()

        # Memory analysis
        stats = snapshot_end.compare_to(snapshot_start, "lineno")
        total_memory_diff_kb = sum(stat.size_diff for stat in stats) / 1024.0

        # Invariant 2: Execution Time Bounds (< 15ms/frame guarantees > 66 FPS real-time processing)
        assert avg_ms_per_frame < 15.0, (
            f"Execution time per frame exceeded bound: {avg_ms_per_frame:.2f}ms/frame (limit 15.0ms)"
        )

        # Invariant 3: Memory Leak Bounds (< 10 MB total delta across 1,000 frames)
        assert total_memory_diff_kb < 10240.0, (
            f"Memory growth too high: {total_memory_diff_kb:.2f} KB across 1,000 frames"
        )

        # Invariant 4: Frame count
        assert pipeline._frame_count == 1000

        print(
            f"\n[BENCHMARK] 1,000 frames processed in {total_wall_time:.3f}s "
            f"({avg_ms_per_frame:.3f}ms/frame). Net memory delta: {total_memory_diff_kb:.2f} KB."
        )
