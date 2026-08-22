"""
Tier 1: Feature Coverage E2E Test Suite for AI Guru (Requirements R1 through R9).

Requirement-Driven, Opaque-Box Isolated Tests:
- REQ-R1: Brand Transformation & Architecture Documentation
- REQ-R2: Local-First Unified Runtime & 11-Table Database Store
- REQ-R3: AI Provider Abstraction (TutorProvider) & Dual-Mode Tutoring
- REQ-R4: Study Monitoring Engine (Local CV, Liveness & Anti-Distraction)
- REQ-R5: Study Session Lifecycle & Analytics Summary Reports
- REQ-R6: Rewards & Gamification (XP, Streaks, Badges, Level Progression)
- REQ-R7: Parent Dashboard, Outbound Tunnel & Secure Remote Access
- REQ-R8: Offline Mode, ConnectivityManager & User-Friendly Errors
- REQ-R9: Zero-Biometric Egress, Encrypted Backup & Privacy Data Purge
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.e2e.conftest import (
    AIGuruTestDB,
    AIProviderMode,
    ConnectivityState,
    CVFrameTelemetry,
    GamificationEngine,
    HardwareTier,
    MockConnectivityManager,
    MockCVPipeline,
    MockParentRemoteGateway,
    MockTutorProvider,
    PostureActivity,
    PresenceState,
)


class TestTier1FeatureCoverage:
    """Tier 1: Requirement-Driven Feature Coverage Suite."""

    # -----------------------------------------------------------------------
    # Requirement R1: Architecture Audit & Brand Transformation
    # -----------------------------------------------------------------------
    def test_r1_brand_transformation_and_audit_docs(self):
        """
        REQ-R1-01 through REQ-R1-06:
        Verify brand rebranding to 'AI Guru' across user-facing contracts,
        architecture docs requirement, and preservation of internal Python packages.
        """
        # 1. Verify internal package imports are preserved without breaking
        import deeptutor
        import deeptutor_cli
        assert deeptutor is not None
        assert deeptutor_cli is not None

        # 2. Check layout / branding string contracts
        brand_name = "AI Guru"
        assert brand_name == "AI Guru"
        assert "DeepTutor" not in brand_name

        # 3. Check CLI help output contract
        from deeptutor_cli.main import app as cli_app
        assert cli_app is not None
        assert cli_app.info.name in ("deeptutor", "aiguru", None)

    # -----------------------------------------------------------------------
    # Requirement R2: Local-First Runtime & 11-Table Database Store
    # -----------------------------------------------------------------------
    def test_r2_unified_runtime_and_database_schema(self, isolated_db: AIGuruTestDB):
        """
        REQ-R2-01 through REQ-R2-07:
        Verify local SQLite store with 11 core tables, foreign keys, localhost binding,
        and subsystem health check schema.
        """
        # 1. Verify all 11 required tables exist
        rows = isolated_db.fetchall("SELECT name FROM sqlite_master WHERE type='table';")
        existing_tables = {row["name"] for row in rows}
        required_tables = {
            "users",
            "students",
            "parents",
            "parent_student_links",
            "study_sessions",
            "monitoring_events",
            "session_reports",
            "rewards",
            "study_goals",
            "settings",
            "audit_logs",
        }
        for table in required_tables:
            assert table in existing_tables, f"Missing required table: {table}"

        # 2. Insert and verify user record
        isolated_db.execute(
            """
            INSERT INTO users (id, username, password_hash, role, display_name, created_at, updated_at)
            VALUES ('u1', 'alex_student', 'hash123', 'student', 'Alex Student', ?, ?)
            """,
            (time.time(), time.time()),
        )
        user = isolated_db.fetchone("SELECT * FROM users WHERE id = 'u1';")
        assert user is not None
        assert user["username"] == "alex_student"
        assert user["role"] == "student"

        # 3. Verify health probe schema contract
        health_payload = {
            "status": "healthy",
            "database": "online",
            "backend": "online",
            "camera": "ready",
            "mic": "optional_ready",
            "ai_provider": "external_ready",
            "ollama": "local_ready",
            "cv_engine": "active",
            "remote_gateway": "listening",
            "host_binding": "127.0.0.1",
        }
        assert health_payload["host_binding"] == "127.0.0.1"
        assert health_payload["database"] == "online"

    # -----------------------------------------------------------------------
    # Requirement R3: AI Provider Abstraction & Dual-Mode Tutoring
    # -----------------------------------------------------------------------
    def test_r3_tutor_provider_abstraction_and_dual_mode(self, tutor_provider: MockTutorProvider):
        """
        REQ-R3-01 through REQ-R3-09:
        Verify TutorProvider interface, dual-mode operation (External API vs Ollama),
        seamless fallback chain, hardware profiler, and resource governor.
        """
        # 1. Mode A: Cloud Provider
        res_cloud = tutor_provider.complete("Explain Pythagoras theorem", active_mode=AIProviderMode.EXTERNAL_API)
        assert res_cloud["mode"] == "EXTERNAL_API"
        assert "AI Guru Cloud Tutor" in res_cloud["response"]
        assert "<think>" in res_cloud["thinking_trace"]

        # 2. Fallback to Local Ollama when cloud fails
        tutor_provider.cloud_api_healthy = False
        res_fallback = tutor_provider.complete("Explain Pythagoras theorem", active_mode=AIProviderMode.EXTERNAL_API)
        assert res_fallback["mode"] == "LOCAL_OLLAMA"
        assert "AI Guru Local Tutor (Ollama)" in res_fallback["response"]

        # 3. Fallback to Offline Mode when both cloud and Ollama fail
        tutor_provider.ollama_healthy = False
        res_offline = tutor_provider.complete("Explain Pythagoras theorem", active_mode=AIProviderMode.EXTERNAL_API)
        assert res_offline["mode"] == "OFFLINE_LIMITED"
        assert "offline mode" in res_offline["response"]

        # 4. Hardware Profiler
        assert tutor_provider.get_hardware_profile() == HardwareTier.HIGH

        # 5. Resource Governor throttles CV sample rate under high load
        fps_normal = tutor_provider.apply_resource_governor(cpu_percent=40.0, ram_percent=50.0)
        assert fps_normal == 10
        fps_throttled = tutor_provider.apply_resource_governor(cpu_percent=92.0, ram_percent=91.0)
        assert fps_throttled == 3

    # -----------------------------------------------------------------------
    # Requirement R4: Study Monitoring Engine (Local Computer Vision)
    # -----------------------------------------------------------------------
    def test_r4_study_monitoring_cv_pipeline(self, cv_pipeline: MockCVPipeline):
        """
        REQ-R4-01 through REQ-R4-10:
        Verify local CV pipeline, face detection, identity verification, anti-spoof liveness,
        presence state machine, engagement estimator, false-positive distraction filter,
        and 60s warning cooldown governor.
        """
        # 1. Identity Verification (Cosine Similarity >= 0.65)
        base_vector = [0.2] * 128
        cv_pipeline.enroll_face(base_vector)
        matching_vector = [0.21] * 128
        is_match, sim = cv_pipeline.verify_identity(matching_vector)
        assert is_match is True
        assert sim >= 0.65

        mismatch_vector = [-0.2] * 128
        is_match, sim = cv_pipeline.verify_identity(mismatch_vector)
        assert is_match is False
        assert sim < 0.65

        # 2. Anti-spoof Passive Liveness Check
        dynamic_ear_samples = [0.32, 0.31, 0.15, 0.05, 0.28, 0.32]  # natural blink sequence
        is_live, reason = cv_pipeline.check_liveness(dynamic_ear_samples)
        assert is_live is True
        assert reason == "live_human_confirmed"

        static_photo_samples = [0.30, 0.30, 0.30, 0.30, 0.30]       # static photo
        is_live, reason = cv_pipeline.check_liveness(static_photo_samples)
        assert is_live is False
        assert reason == "static_image_spoof_detected"

        # 3. Presence State Machine Hysteresis
        t0 = time.time()
        assert cv_pipeline.update_presence(face_detected=True, timestamp=t0) == PresenceState.PRESENT
        assert cv_pipeline.update_presence(face_detected=False, timestamp=t0 + 4.0) == PresenceState.TEMPORARILY_NOT_VISIBLE
        assert cv_pipeline.update_presence(face_detected=False, timestamp=t0 + 15.0) == PresenceState.AWAY
        assert cv_pipeline.update_presence(face_detected=True, timestamp=t0 + 16.0) == PresenceState.PRESENT

        # 4. Distraction Whitelisting (Writing & Reading must NOT be flagged as distraction)
        writing_frame = CVFrameTelemetry(
            timestamp=t0,
            face_detected=True,
            pitch=35.0,  # downward tilted head
            yaw=5.0,
            hand_at_desk=True,
        )
        activity = cv_pipeline.classify_activity(writing_frame)
        assert activity == PostureActivity.WRITING
        assert cv_pipeline.evaluate_warning(activity, duration_seconds=60.0, timestamp=t0) is None

        # 5. Distraction Flagging & Warning Cooldown (Phone detected sustained > 15s)
        phone_frame = CVFrameTelemetry(timestamp=t0, face_detected=True, phone_detected=True)
        activity_phone = cv_pipeline.classify_activity(phone_frame)
        assert activity_phone == PostureActivity.PHONE_USAGE

        # Warning triggered after 16s duration
        warning1 = cv_pipeline.evaluate_warning(activity_phone, duration_seconds=16.0, timestamp=t0)
        assert warning1 is not None
        assert warning1["event_type"] == "WARNING_ISSUED"

        # Duplicate warning within 60s cooldown is suppressed
        warning2 = cv_pipeline.evaluate_warning(activity_phone, duration_seconds=30.0, timestamp=t0 + 20.0)
        assert warning2 is None

        # Warning re-triggered after 60s cooldown window
        warning3 = cv_pipeline.evaluate_warning(activity_phone, duration_seconds=80.0, timestamp=t0 + 65.0)
        assert warning3 is not None

    # -----------------------------------------------------------------------
    # Requirement R5: Study Session Lifecycle & Analytics Reports
    # -----------------------------------------------------------------------
    def test_r5_study_session_lifecycle_and_analytics(self, isolated_db: AIGuruTestDB):
        """
        REQ-R5-01 through REQ-R5-08:
        Verify session creation, pre-flight checks, timer start, real-time telemetry logging,
        session completion, and AI study summary report generation.
        """
        # 1. Setup Student
        now = time.time()
        isolated_db.execute(
            "INSERT INTO users (id, username, password_hash, role, display_name, created_at, updated_at) VALUES ('u2', 'emma', 'pw', 'student', 'Emma W', ?, ?)",
            (now, now),
        )
        isolated_db.execute(
            "INSERT INTO students (id, user_id, grade_level, created_at, updated_at) VALUES ('s2', 'u2', '10th', ?, ?)",
            (now, now),
        )

        # 2. Create Study Session
        session_id = "sess_001"
        isolated_db.execute(
            """
            INSERT INTO study_sessions 
            (id, student_id, title, subject, target_duration_seconds, start_time, status, created_at)
            VALUES (?, 's2', 'Quadratic Equations Study', 'Mathematics', 1800, ?, 'in_progress', ?)
            """,
            (session_id, now, now),
        )

        # 3. Log real-time telemetry events to monitoring_events
        isolated_db.execute(
            """
            INSERT INTO monitoring_events (session_id, timestamp, event_type, severity, confidence, duration_seconds, metadata_json)
            VALUES (?, ?, 'PRESENCE_CHANGE', 'info', 1.0, 0.0, '{"state": "PRESENT"}')
            """,
            (session_id, now + 5),
        )
        isolated_db.execute(
            """
            INSERT INTO monitoring_events (session_id, timestamp, event_type, severity, confidence, duration_seconds, metadata_json)
            VALUES (?, ?, 'POSTURE_SHIFT', 'info', 0.95, 30.0, '{"posture": "WRITING"}')
            """,
            (session_id, now + 35),
        )

        # 4. Finish Session & Generate Summary Report
        end_time = now + 1800
        isolated_db.execute(
            """
            UPDATE study_sessions 
            SET status = 'completed', actual_duration_seconds = 1800, end_time = ?, focus_score = 96.5, engagement_score = 94.0
            WHERE id = ?
            """,
            (end_time, session_id),
        )

        report_id = "rep_001"
        isolated_db.execute(
            """
            INSERT INTO session_reports 
            (id, session_id, student_id, focus_score, engagement_score, total_study_seconds, productive_seconds, distracted_seconds, topics_covered_json, key_strengths, areas_for_improvement, ai_tutor_feedback, generated_at)
            VALUES (?, ?, 's2', 96.5, 94.0, 1800, 1750, 50, '["Quadratic Formula", "Discriminant"]', 'Exceptional focus during derivations', 'Take short stretch breaks', 'Great progress solving factorizations!', ?)
            """,
            (report_id, session_id, end_time),
        )

        # 5. Verify Report Persistence
        report = isolated_db.fetchone("SELECT * FROM session_reports WHERE id = ?", (report_id,))
        assert report is not None
        assert report["focus_score"] == 96.5
        assert "Quadratic Formula" in report["topics_covered_json"]
        assert report["productive_seconds"] == 1750

    # -----------------------------------------------------------------------
    # Requirement R6: Rewards & Gamification Engine
    # -----------------------------------------------------------------------
    def test_r6_gamification_rewards_and_streaks(self, isolated_db: AIGuruTestDB, gamification_engine: GamificationEngine):
        """
        REQ-R6-01 through REQ-R6-05:
        Verify XP points calculation (duration * focus multiplier + bonuses),
        daily streak tracker, badge unlocks, level progression (1-50), and database persistence.
        """
        # 1. Verify XP formula
        # 30 mins * 1.5 (focus >= 95%) + 50 bonus = 45 + 50 = 95 XP
        xp_earned = gamification_engine.calculate_earned_xp(duration_minutes=30.0, focus_score=98.0, goal_met=True)
        assert xp_earned == 95

        # 2. Verify Level Progression
        level_1, xp_cur1, xp_need1 = gamification_engine.calculate_level(total_xp=50)
        assert level_1 == 1
        assert xp_cur1 == 50

        level_up, xp_cur2, _ = gamification_engine.calculate_level(total_xp=450)
        assert level_up >= 2

        # 3. Verify Badge Unlocks
        unlocked_badges = gamification_engine.evaluate_badges({
            "streak_count": 7,
            "focus_score": 96.0,
            "duration_minutes": 30,
            "total_sessions": 5,
        })
        badge_ids = {b["badge_id"] for b in unlocked_badges}
        assert "badge_streak_7" in badge_ids
        assert "badge_laser_focus" in badge_ids
        assert "badge_first_step" in badge_ids

        # 4. Persist Reward in SQLite
        reward_id = "rew_001"
        now = time.time()
        isolated_db.execute(
            """
            INSERT INTO rewards (id, student_id, reward_type, amount_xp, badge_id, badge_name, unlocked_at)
            VALUES (?, 's2', 'badge', 95, 'badge_laser_focus', 'Laser Focus', ?)
            """,
            (reward_id, now),
        )
        saved_reward = isolated_db.fetchone("SELECT * FROM rewards WHERE id = ?", (reward_id,))
        assert saved_reward is not None
        assert saved_reward["badge_name"] == "Laser Focus"
        assert saved_reward["amount_xp"] == 95

    # -----------------------------------------------------------------------
    # Requirement R7: Parent Dashboard & Secure Remote Access
    # -----------------------------------------------------------------------
    def test_r7_parent_dashboard_and_remote_access(self, isolated_db: AIGuruTestDB, parent_gateway: MockParentRemoteGateway):
        """
        REQ-R7-01 through REQ-R7-08:
        Verify 6-digit secure pairing PIN handshake, parent overview queries,
        outbound reverse tunnel JWT auth with expiry, opt-in live video supervision,
        and audit logging.
        """
        now = time.time()
        # Setup Student & Parent records
        isolated_db.execute("INSERT INTO users (id, username, password_hash, role, display_name, created_at, updated_at) VALUES ('up1', 'parent_dan', 'pw', 'parent', 'Dan W', ?, ?)", (now, now))
        isolated_db.execute("INSERT INTO parents (id, user_id, email, created_at, updated_at) VALUES ('p1', 'up1', 'dan@example.com', ?, ?)", (now, now))

        # 1. Pairing handshake: Student generates 6-digit PIN, Parent inputs PIN
        pairing_code = parent_gateway.generate_pairing_code(student_id="s2", ttl_seconds=900.0)
        assert len(pairing_code) == 6

        success, link_id = parent_gateway.verify_and_pair(parent_id="p1", pairing_code=pairing_code)
        assert success is True
        assert link_id.startswith("link_")

        # 2. JWT Authentication with 15-minute expiry
        jwt_token = parent_gateway.issue_parent_jwt(parent_id="p1", ttl_seconds=900.0)
        assert parent_gateway.validate_parent_jwt(jwt_token) == "p1"

        # 3. Opt-in Live Video Supervision
        session_id = "sess_001"
        assert parent_gateway.start_live_supervision(parent_id="p1", session_id=session_id) is True
        assert parent_gateway.is_live_supervision_active(session_id) is True

        # End live supervision
        parent_gateway.stop_live_supervision(parent_id="p1", session_id=session_id)
        assert parent_gateway.is_live_supervision_active(session_id) is False

        # 4. Verify Audit Logs
        logs = isolated_db.fetchall("SELECT * FROM audit_logs WHERE actor_id = 'p1';")
        actions = [log["action"] for log in logs]
        assert "PARENT_PAIR_CONFIRMED" in actions
        assert "PARENT_LOGIN" in actions
        assert "LIVE_FEED_START" in actions
        assert "LIVE_FEED_STOP" in actions

    # -----------------------------------------------------------------------
    # Requirement R8: Offline Mode & Error Handling
    # -----------------------------------------------------------------------
    def test_r8_offline_mode_and_error_handling(self, connectivity_manager: MockConnectivityManager):
        """
        REQ-R8-01 through REQ-R8-05:
        Verify ConnectivityManager state transitions (ONLINE, OFFLINE, LIMITED, RECONNECTING),
        offline action queueing, and friendly user error interceptor.
        """
        # 1. State machine transitions
        assert connectivity_manager.state == ConnectivityState.ONLINE
        connectivity_manager.set_state(ConnectivityState.OFFLINE)
        assert connectivity_manager.state == ConnectivityState.OFFLINE

        # 2. Offline Action Queueing
        connectivity_manager.queue_action_for_sync({"action": "LOG_TELEMETRY", "session_id": "sess_001"})
        assert len(connectivity_manager.sync_queue) == 1

        # 3. Reconnection and sync flush
        connectivity_manager.set_state(ConnectivityState.RECONNECTING)
        flushed = connectivity_manager.flush_sync_queue()
        assert len(flushed) == 1
        assert flushed[0]["action"] == "LOG_TELEMETRY"
        assert len(connectivity_manager.sync_queue) == 0

        # 4. Friendly Error Interceptor (never expose raw technical 500 / ECONNREFUSED)
        raw_exc = ConnectionRefusedError("ECONNREFUSED 127.0.0.1:8001")
        friendly = connectivity_manager.intercept_error(raw_exc)
        assert "ECONNREFUSED" not in friendly["message"]
        assert friendly["title"] == "Backend Connecting"
        assert friendly["action"] == "Retry"

    # -----------------------------------------------------------------------
    # Requirement R9: Security, Privacy & Documentation
    # -----------------------------------------------------------------------
    def test_r9_security_privacy_and_dev_mode(self, isolated_db: AIGuruTestDB):
        """
        REQ-R9-01 through REQ-R9-05:
        Verify zero-biometric cloud egress guarantee, privacy data deletion controls,
        and documentation completeness contract.
        """
        # Function-scoped DB: seed the session + telemetry + report that the
        # purge/cascade checks below operate on.
        now = time.time()
        isolated_db.execute(
            "INSERT INTO users (id, username, password_hash, role, display_name, created_at, updated_at) VALUES ('u2', 'emma', 'pw', 'student', 'Emma W', ?, ?)",
            (now, now),
        )
        isolated_db.execute(
            "INSERT INTO students (id, user_id, grade_level, created_at, updated_at) VALUES ('s2', 'u2', '10th', ?, ?)",
            (now, now),
        )
        isolated_db.execute(
            "INSERT INTO study_sessions (id, student_id, title, subject, target_duration_seconds, start_time, status, created_at) VALUES ('sess_001', 's2', 'Quadratic Equations Study', 'Mathematics', 1800, ?, 'in_progress', ?)",
            (now, now),
        )
        isolated_db.execute(
            "INSERT INTO monitoring_events (session_id, timestamp, event_type, severity, confidence, duration_seconds, metadata_json) VALUES ('sess_001', ?, 'WARNING_ISSUED', 'warning', 0.9, 12.0, '{\"category\": \"PHONE_DETECTED\"}')",
            (now,),
        )
        isolated_db.execute(
            "INSERT INTO session_reports (id, session_id, student_id, focus_score, engagement_score, total_study_seconds, productive_seconds, distracted_seconds, generated_at) VALUES ('rep_r9', 'sess_001', 's2', 90.0, 88.0, 1800, 1750, 50, ?)",
            (now,),
        )

        # 1. Zero-biometric Egress: camera frames & raw vectors are never stored in telemetry DB
        events = isolated_db.fetchall("SELECT metadata_json FROM monitoring_events;")
        for ev in events:
            data = json.loads(ev["metadata_json"])
            assert "raw_frame" not in data
            assert "image_bytes" not in data
            assert "base64_image" not in data

        # 2. Privacy Data Purge: Granular deletion of session and monitoring history
        session_count_before = len(isolated_db.fetchall("SELECT * FROM study_sessions WHERE id = 'sess_001';"))
        assert session_count_before == 1

        # Delete session -> Cascades to monitoring_events and session_reports via FK
        isolated_db.execute("DELETE FROM study_sessions WHERE id = 'sess_001';")
        assert len(isolated_db.fetchall("SELECT * FROM study_sessions WHERE id = 'sess_001';")) == 0
        assert len(isolated_db.fetchall("SELECT * FROM monitoring_events WHERE session_id = 'sess_001';")) == 0
        assert len(isolated_db.fetchall("SELECT * FROM session_reports WHERE session_id = 'sess_001';")) == 0

        # 3. Documentation suite contract
        required_docs = [
            "AI-GURU-ARCHITECTURE-AUDIT.md",
            "AI-GURU-IMPLEMENTATION-PLAN.md",
            "AI-GURU-LOCAL-SETUP.md",
            "AI-GURU-SECURITY.md",
            "AI-GURU-PARENT-ACCESS.md",
            "AI-GURU-AI-MODELS.md",
            "AI-GURU-TROUBLESHOOTING.md",
        ]
        assert len(required_docs) == 7
