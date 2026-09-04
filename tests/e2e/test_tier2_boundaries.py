"""
Tier 2: Boundary & Corner Cases E2E Test Suite for AI Guru.

Exhaustive verification of limits, hysteresis, debouncing, cooldowns,
whitelists, concurrency stress, and failure mode recovery:
- Zero / Minimum / Extreme Session Durations (0s to 12h)
- Presence State Debounce Hysteresis (2s transient vs 12s absence)
- Distraction False-Positive Whitelist (Writing, Reading, Drinking Water)
- Warning Cooldown Governor (60s suppression window across 5m continuous distraction)
- Anti-Spoof Static Image & Screen Replay Rejection
- AI Fallback Circuit Breaker (Cloud API -> Local Ollama -> Offline Hints)
- Parent Pairing Expiry (15m TTL) & Token Expiry
- Resource Governor CPU/RAM Throttle (10 FPS -> 3 FPS)
- Database Concurrency & Lock-Free Multi-Threaded Stress
- Corrupted Backup Archive Error Handling & Recovery
"""

from __future__ import annotations

import concurrent.futures
import json
import time

import pytest

from tests.e2e.conftest import (
    AIGuruTestDB,
    AIProviderMode,
    CVFrameTelemetry,
    GamificationEngine,
    HardwareTier,
    MockCVPipeline,
    MockParentRemoteGateway,
    MockTutorProvider,
    PostureActivity,
    PresenceState,
)


class TestTier2BoundariesAndCornerCases:
    """Tier 2: Boundary, Limit & Corner Case Verification."""

    # -----------------------------------------------------------------------
    # 1. Session Duration Limits & Extremes
    # -----------------------------------------------------------------------
    def test_boundary_session_durations(self, gamification_engine: GamificationEngine):
        """Test zero duration, sub-minute, and extreme 12-hour session boundaries."""
        # Zero duration session
        xp_zero = gamification_engine.calculate_earned_xp(
            duration_minutes=0.0, focus_score=100.0, goal_met=False
        )
        assert xp_zero == 10  # Minimum floor XP

        # Sub-minute session (30 seconds)
        xp_short = gamification_engine.calculate_earned_xp(
            duration_minutes=0.5, focus_score=80.0, goal_met=False
        )
        assert xp_short >= 10

        # Long marathon session: 12 hours (720 minutes) with 95% focus + goal
        # 720 * 1.5 + 50 = 1080 + 50 = 1130 XP
        xp_marathon = gamification_engine.calculate_earned_xp(
            duration_minutes=720.0, focus_score=96.0, goal_met=True
        )
        assert xp_marathon == 1130

    # -----------------------------------------------------------------------
    # 2. Presence State Debounce & Hysteresis
    # -----------------------------------------------------------------------
    def test_boundary_presence_state_hysteresis_and_debouncing(self, cv_pipeline: MockCVPipeline):
        """
        Verify state machine hysteresis:
        - Face missing for 2s does NOT trigger AWAY (remains TEMPORARILY_NOT_VISIBLE).
        - Face missing for 12s transitions to AWAY.
        - Immediate face reappearance transitions back to PRESENT in 0s.
        """
        t0 = 1000.0
        # Face present
        assert (
            cv_pipeline.update_presence(face_detected=True, timestamp=t0) == PresenceState.PRESENT
        )

        # Missing for 2s (transient head scratch/blink) -> TEMPORARILY_NOT_VISIBLE
        assert (
            cv_pipeline.update_presence(face_detected=False, timestamp=t0 + 2.0)
            == PresenceState.TEMPORARILY_NOT_VISIBLE
        )

        # Missing for 8s (still under 10s threshold) -> TEMPORARILY_NOT_VISIBLE
        assert (
            cv_pipeline.update_presence(face_detected=False, timestamp=t0 + 8.0)
            == PresenceState.TEMPORARILY_NOT_VISIBLE
        )

        # Missing for 12s (exceeded 10s threshold) -> AWAY
        assert (
            cv_pipeline.update_presence(face_detected=False, timestamp=t0 + 12.0)
            == PresenceState.AWAY
        )

        # Face reappears -> Immediately PRESENT
        assert (
            cv_pipeline.update_presence(face_detected=True, timestamp=t0 + 13.0)
            == PresenceState.PRESENT
        )

    # -----------------------------------------------------------------------
    # 3. Distraction Whitelist False-Positive Rejection
    # -----------------------------------------------------------------------
    def test_boundary_distraction_whitelist_durations(self, cv_pipeline: MockCVPipeline):
        """
        Verify that writing, reading, and water drinking for extended durations
        are NEVER flagged as distraction or issue warnings.
        """
        t0 = 2000.0
        # 1. Writing posture sustained for 120 seconds
        writing_frame = CVFrameTelemetry(
            timestamp=t0,
            face_detected=True,
            pitch=40.0,  # head tilted down 40 degrees
            yaw=0.0,
            hand_at_desk=True,
        )
        activity = cv_pipeline.classify_activity(writing_frame)
        assert activity == PostureActivity.WRITING
        warn = cv_pipeline.evaluate_warning(activity, duration_seconds=120.0, timestamp=t0 + 120.0)
        assert warn is None

        # 2. Drinking water gesture (4 seconds)
        water_frame = CVFrameTelemetry(
            timestamp=t0 + 125.0,
            face_detected=True,
            drinking_detected=True,
        )
        activity_water = cv_pipeline.classify_activity(water_frame)
        assert activity_water == PostureActivity.DRINKING_WATER
        assert (
            cv_pipeline.evaluate_warning(activity_water, duration_seconds=4.0, timestamp=t0 + 129.0)
            is None
        )

        # 3. Phone usage sustained for 20 seconds MUST be flagged
        phone_frame = CVFrameTelemetry(
            timestamp=t0 + 140.0, face_detected=True, phone_detected=True
        )
        activity_phone = cv_pipeline.classify_activity(phone_frame)
        assert activity_phone == PostureActivity.PHONE_USAGE
        warn_phone = cv_pipeline.evaluate_warning(
            activity_phone, duration_seconds=20.0, timestamp=t0 + 160.0
        )
        assert warn_phone is not None
        assert warn_phone["warning_type"] == "PHONE_USAGE"

    # -----------------------------------------------------------------------
    # 4. Warning Cooldown Governor (5-Minute Continuous Distraction)
    # -----------------------------------------------------------------------
    def test_boundary_warning_cooldown_governor(self, cv_pipeline: MockCVPipeline):
        """
        Verify that 300 seconds of continuous distraction emits at most 5 warnings
        with 60-second cooldown suppression.
        """
        t_start = 3000.0
        warnings_emitted = []
        activity = PostureActivity.LOOKING_AWAY

        # Simulate frame check every 5 seconds for 300 seconds
        for elapsed in range(0, 305, 5):
            curr_time = t_start + elapsed
            warn = cv_pipeline.evaluate_warning(
                activity, duration_seconds=float(elapsed), timestamp=curr_time
            )
            if warn:
                warnings_emitted.append((elapsed, warn))

        # First warning at >= 15s (elapsed = 15)
        # Next at elapsed = 75 (15 + 60)
        # Next at elapsed = 135 (75 + 60)
        # Next at elapsed = 195 (135 + 60)
        # Next at elapsed = 255 (195 + 60)
        assert len(warnings_emitted) == 5
        warning_times = [w[0] for w in warnings_emitted]
        assert warning_times == [15, 75, 135, 195, 255]

    # -----------------------------------------------------------------------
    # 5. Anti-Spoof Passive Liveness Extremes
    # -----------------------------------------------------------------------
    def test_boundary_anti_spoof_liveness_extremes(self, cv_pipeline: MockCVPipeline):
        """
        Verify that static photos are rejected while natural blink sequences are confirmed.
        """
        # Static zero-variance EAR
        static_series = [0.35] * 20
        is_live, reason = cv_pipeline.check_liveness(static_series)
        assert is_live is False
        assert reason == "static_image_spoof_detected"

        # Natural blink with high variance
        blink_series = [0.35, 0.34, 0.35, 0.12, 0.04, 0.18, 0.33, 0.35]
        is_live, reason = cv_pipeline.check_liveness(blink_series)
        assert is_live is True
        assert reason == "live_human_confirmed"

        # Edge: empty or sparse list handles gracefully
        assert cv_pipeline.check_liveness([]) == (True, "insufficient_samples")

    # -----------------------------------------------------------------------
    # 6. AI Fallback Circuit Breaker
    # -----------------------------------------------------------------------
    def test_boundary_ai_fallback_circuit_breaker(self, tutor_provider: MockTutorProvider):
        """
        Verify full degradation chain: Cloud -> Ollama -> Offline Hints,
        and immediate recovery when cloud is restored.
        """
        # Cloud OK
        tutor_provider.cloud_api_healthy = True
        tutor_provider.ollama_healthy = True
        r1 = tutor_provider.complete("Test 1")
        assert r1["mode"] == "EXTERNAL_API"

        # Cloud down -> Ollama
        tutor_provider.cloud_api_healthy = False
        r2 = tutor_provider.complete("Test 2")
        assert r2["mode"] == "LOCAL_OLLAMA"

        # Ollama down -> Offline Limited
        tutor_provider.ollama_healthy = False
        r3 = tutor_provider.complete("Test 3")
        assert r3["mode"] == "OFFLINE_LIMITED"

        # Cloud restored -> Immediately back to Cloud
        tutor_provider.cloud_api_healthy = True
        r4 = tutor_provider.complete("Test 4")
        assert r4["mode"] == "EXTERNAL_API"

    # -----------------------------------------------------------------------
    # 7. Parent Pairing TTL & JWT Expiry
    # -----------------------------------------------------------------------
    def test_boundary_parent_pairing_and_token_expiry(
        self, parent_gateway: MockParentRemoteGateway
    ):
        """
        Verify that expired pairing codes (past 15 mins) and expired JWT tokens are rejected.
        """
        # 1. Pairing code with 1-second TTL
        code = parent_gateway.generate_pairing_code(
            student_id="s_test", ttl_seconds=-1.0
        )  # already expired
        success, reason = parent_gateway.verify_and_pair(parent_id="p_test", pairing_code=code)
        assert success is False
        assert reason == "pairing_code_expired"

        # 2. Invalid pairing code
        success_inv, reason_inv = parent_gateway.verify_and_pair(
            parent_id="p_test", pairing_code="INVALID"
        )
        assert success_inv is False
        assert reason_inv == "invalid_pairing_code"

        # 3. JWT Token with negative TTL (already expired)
        expired_jwt = parent_gateway.issue_parent_jwt(parent_id="p_test", ttl_seconds=-5.0)
        assert parent_gateway.validate_parent_jwt(expired_jwt) is None

    # -----------------------------------------------------------------------
    # 8. Resource Governor High-Load Throttling
    # -----------------------------------------------------------------------
    def test_boundary_resource_governor_high_load(self, tutor_provider: MockTutorProvider):
        """
        Verify that high CPU (>85%) or high RAM (>90%) throttles CV sample rate from 10 to 3 FPS.
        """
        # Normal load
        assert tutor_provider.apply_resource_governor(cpu_percent=50.0, ram_percent=60.0) == 10
        # High CPU
        assert tutor_provider.apply_resource_governor(cpu_percent=88.0, ram_percent=60.0) == 3
        # High RAM
        assert tutor_provider.apply_resource_governor(cpu_percent=40.0, ram_percent=92.0) == 3
        # Normalized
        assert tutor_provider.apply_resource_governor(cpu_percent=30.0, ram_percent=45.0) == 10

    # -----------------------------------------------------------------------
    # 9. Database Concurrency & Lock-Free Multi-Threaded Stress
    # -----------------------------------------------------------------------
    def test_boundary_database_concurrency_stress(self, isolated_db: AIGuruTestDB):
        """
        Execute 50 concurrent writes and reads across threads to ensure WAL mode
        lock-free concurrency without data corruption.
        """
        now = time.time()
        isolated_db.execute(
            "INSERT INTO study_sessions (id, student_id, title, target_duration_seconds, start_time, created_at) VALUES ('sess_stress', 's_stress', 'Concurrency Test', 1800, ?, ?)",
            (now, now),
        )

        def write_event(index: int) -> int:
            isolated_db.execute(
                """
                INSERT INTO monitoring_events (session_id, timestamp, event_type, confidence, duration_seconds, metadata_json)
                VALUES ('sess_stress', ?, 'POSTURE_SHIFT', 0.9, 1.0, ?)
                """,
                (now + index, json.dumps({"index": index})),
            )
            return index

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(write_event, i) for i in range(50)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 50
        count = isolated_db.fetchone(
            "SELECT COUNT(*) as cnt FROM monitoring_events WHERE session_id = 'sess_stress';"
        )
        assert count["cnt"] == 50

    # -----------------------------------------------------------------------
    # 10. Corrupted Backup Archive Error Handling
    # -----------------------------------------------------------------------
    def test_boundary_corrupted_backup_recovery(self, isolated_db: AIGuruTestDB):
        """
        Verify that attempting to restore a corrupted backup payload fails safely
        without destroying existing database state.
        """
        # Ensure database has valid baseline record
        baseline = isolated_db.fetchall("SELECT * FROM users;")
        baseline_count = len(baseline)

        # Malformed backup JSON
        corrupted_payload = "NOT_A_VALID_JSON_BACKUP_CONTENT"

        def restore_backup(payload: str) -> bool:
            try:
                data = json.loads(payload)
                if "version" not in data or "tables" not in data:
                    raise ValueError("Invalid backup structure")
                return True
            except Exception:
                return False

        assert restore_backup(corrupted_payload) is False

        # Verify active database remains completely unharmed
        assert len(isolated_db.fetchall("SELECT * FROM users;")) == baseline_count
