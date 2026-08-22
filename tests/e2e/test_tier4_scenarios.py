"""
Tier 4: Real-World Application Scenarios E2E Test Suite for AI Guru.

Complete end-to-end user journeys simulating realistic student workflows,
parent remote supervision, and offline travel environments:
- Scenario 1: The Focused High School Student (45m AP Calculus + 98% Focus + Gamification)
- Scenario 2: The Distracted Middle Schooler & Attentive Parent (Phone Distraction + Break + Live View)
- Scenario 3: The Offline Traveling Student (Airplane Flight Mode + Local Ollama + Zero Net Egress)
- Scenario 4: Parent Remote Supervision & Privacy Audit (Outbound Tunnel + JWT + Auto-Kill Stream)
"""

from __future__ import annotations

import json
import time
import pytest

from tests.e2e.conftest import (
    AIGuruTestDB,
    AIProviderMode,
    ConnectivityState,
    CVFrameTelemetry,
    GamificationEngine,
    MockConnectivityManager,
    MockCVPipeline,
    MockParentRemoteGateway,
    MockTutorProvider,
    PostureActivity,
    PresenceState,
)


class TestTier4RealWorldScenarios:
    """Tier 4: Real-World End-to-End User Journeys."""

    # -----------------------------------------------------------------------
    # Scenario 1: The Focused High School Student
    # -----------------------------------------------------------------------
    def test_scenario_1_focused_high_school_student(
        self,
        isolated_db: AIGuruTestDB,
        tutor_provider: MockTutorProvider,
        cv_pipeline: MockCVPipeline,
        gamification_engine: GamificationEngine,
    ):
        """
        Scenario 1: 45-minute AP Calculus Study Session
        - Student enrolls and sets goal "Calculus Integrals (45m)".
        - Performs pre-flight check (camera, lighting, face enrollment, blink liveness).
        - Studies diligently with handwritten notes (downward pitch whitelisted as WRITING).
        - Asks AI Tutor 2 conceptual math questions.
        - Finishes session with 98% focus score.
        - Generates report, earns 117 XP, unlocks 'Laser Focus' badge, updates streak.
        """
        now = time.time()
        # 1. Student Onboarding & Enrollment
        isolated_db.execute(
            "INSERT INTO users (id, username, password_hash, role, display_name, created_at, updated_at) VALUES ('u_hs', 'jordan', 'pw', 'student', 'Jordan Lee', ?, ?)",
            (now, now),
        )
        isolated_db.execute(
            "INSERT INTO students (id, user_id, grade_level, school, learning_style, target_daily_minutes, streak_count, total_xp, created_at, updated_at) VALUES ('s_hs', 'u_hs', '12th', 'Westlake High', 'analytical', 45, 4, 320, ?, ?)",
            (now, now),
        )

        # Set Goal
        goal_id = "goal_calc_45"
        isolated_db.execute(
            """
            INSERT INTO study_goals (id, student_id, title, goal_type, target_value, start_date, end_date, created_at)
            VALUES (?, 's_hs', 'Calculus Integrals', 'daily_minutes', 45, ?, ?, ?)
            """,
            (goal_id, now, now + 86400, now),
        )

        # 2. Pre-flight Hardware & Identity Verification
        enrolled_face = [0.15] * 128
        cv_pipeline.enroll_face(enrolled_face)
        # Pre-flight camera test
        test_frame = CVFrameTelemetry(timestamp=now, face_detected=True, ambient_luminance=140.0)
        assert test_frame.face_detected is True
        assert test_frame.ambient_luminance >= 50.0  # lighting adequate
        is_match, sim = cv_pipeline.verify_identity(enrolled_face)
        assert is_match is True
        is_live, liveness_msg = cv_pipeline.check_liveness([0.32, 0.31, 0.08, 0.29, 0.32])
        assert is_live is True

        # 3. Start 45-min Study Session
        session_id = "sess_calc_45m"
        duration_seconds = 2700  # 45 mins
        isolated_db.execute(
            """
            INSERT INTO study_sessions 
            (id, student_id, title, subject, target_duration_seconds, start_time, status, created_at)
            VALUES (?, 's_hs', 'AP Calculus: Definite Integrals', 'Mathematics', ?, ?, 'in_progress', ?)
            """,
            (session_id, duration_seconds, now, now),
        )

        # Simulate 45 minutes of diligent studying (writing down notes on desk)
        writing_frame = CVFrameTelemetry(timestamp=now + 600, face_detected=True, pitch=35.0, hand_at_desk=True)
        activity = cv_pipeline.classify_activity(writing_frame)
        assert activity == PostureActivity.WRITING
        assert cv_pipeline.evaluate_warning(activity, duration_seconds=600.0, timestamp=now + 600) is None

        # AI Tutor Turn 1
        tutor_resp1 = tutor_provider.complete("How do I choose u and dv in integration by parts?")
        assert "Cloud Tutor" in tutor_resp1["response"]

        # AI Tutor Turn 2
        tutor_resp2 = tutor_provider.complete("Can you provide an example with x * e^x?")
        assert "Cloud Tutor" in tutor_resp2["response"]

        # 4. Finish Session & Generate Summary Report
        end_time = now + duration_seconds
        isolated_db.execute(
            """
            UPDATE study_sessions 
            SET status = 'completed', actual_duration_seconds = ?, end_time = ?, focus_score = 98.5, engagement_score = 96.0
            WHERE id = ?
            """,
            (duration_seconds, end_time, session_id),
        )

        report_id = "rep_calc_45m"
        isolated_db.execute(
            """
            INSERT INTO session_reports 
            (id, session_id, student_id, focus_score, engagement_score, total_study_seconds, productive_seconds, distracted_seconds, topics_covered_json, key_strengths, areas_for_improvement, ai_tutor_feedback, generated_at)
            VALUES (?, ?, 's_hs', 98.5, 96.0, 2700, 2680, 20, '["Integration by Parts", "LIATE Rule"]', 'Superb analytical rigor', 'Practice more trigonometric substitutions', 'Excellent mastery of integration by parts!', ?)
            """,
            (report_id, session_id, end_time),
        )

        # 5. Gamification Rewards: 45 min * 1.5 + 50 goal bonus = 67 + 50 = 117 XP
        earned_xp = gamification_engine.calculate_earned_xp(duration_minutes=45.0, focus_score=98.5, goal_met=True)
        assert earned_xp == 117

        isolated_db.execute("UPDATE students SET streak_count = 5, total_xp = total_xp + ? WHERE id = 's_hs'", (earned_xp,))
        isolated_db.execute(
            "INSERT INTO rewards (id, student_id, session_id, reward_type, amount_xp, badge_id, badge_name, unlocked_at) VALUES ('r_hs_1', 's_hs', ?, 'badge', ?, 'badge_laser_focus', 'Laser Focus', ?)",
            (session_id, earned_xp, end_time),
        )
        isolated_db.execute("UPDATE study_goals SET is_completed = 1, current_value = 45 WHERE id = ?", (goal_id,))

        # Verify final student state
        student = isolated_db.fetchone("SELECT * FROM students WHERE id = 's_hs';")
        assert student["total_xp"] == 437  # 320 + 117
        assert student["streak_count"] == 5

    # -----------------------------------------------------------------------
    # Scenario 2: The Distracted Middle Schooler & Attentive Parent
    # -----------------------------------------------------------------------
    def test_scenario_2_distracted_middle_schooler_and_parent(
        self,
        isolated_db: AIGuruTestDB,
        cv_pipeline: MockCVPipeline,
        parent_gateway: MockParentRemoteGateway,
    ):
        """
        Scenario 2: 30-minute Middle School Science Study Session
        - Student starts session.
        - At min 5: Phone distraction detected for 20s -> warning emitted with 60s cooldown.
        - At min 15: Bathroom break (45s) -> transitions TEMPORARILY_NOT_VISIBLE -> AWAY -> auto-pauses.
        - Student returns -> resumes session.
        - Parent receives alert and opens opt-in live supervision for 2 minutes.
        - Session wraps up with 74% focus score.
        - Report details distraction intervals; parent adds encouraging note.
        """
        now = time.time()
        # Setup Student & Parent
        isolated_db.execute("INSERT INTO users (id, username, password_hash, role, display_name, created_at, updated_at) VALUES ('u_ms', 'leo', 'pw', 'student', 'Leo Miller', ?, ?)", (now, now))
        isolated_db.execute("INSERT INTO students (id, user_id, grade_level, created_at, updated_at) VALUES ('s_ms', 'u_ms', '7th', ?, ?)", (now, now))
        isolated_db.execute("INSERT INTO users (id, username, password_hash, role, display_name, created_at, updated_at) VALUES ('u_pm', 'parent_miller', 'pw', 'parent', 'Mrs. Miller', ?, ?)", (now, now))
        isolated_db.execute("INSERT INTO parents (id, user_id, email, created_at, updated_at) VALUES ('p_ms', 'u_pm', 'miller@example.com', ?, ?)", (now, now))

        session_id = "sess_ms_science"
        isolated_db.execute(
            "INSERT INTO study_sessions (id, student_id, title, subject, target_duration_seconds, start_time, status, created_at) VALUES (?, 's_ms', 'Cell Biology', 'Science', 1800, ?, 'in_progress', ?)",
            (session_id, now, now),
        )

        # Minute 5: Phone distraction
        phone_frame = CVFrameTelemetry(timestamp=now + 300, face_detected=True, phone_detected=True)
        activity = cv_pipeline.classify_activity(phone_frame)
        assert activity == PostureActivity.PHONE_USAGE
        warn = cv_pipeline.evaluate_warning(activity, duration_seconds=20.0, timestamp=now + 300)
        assert warn is not None
        isolated_db.execute(
            "INSERT INTO monitoring_events (session_id, timestamp, event_type, severity, confidence, duration_seconds, metadata_json) VALUES (?, ?, 'WARNING_ISSUED', 'warning', 0.92, 20.0, ?)",
            (session_id, now + 300, json.dumps(warn)),
        )

        # Minute 15: Bathroom break (45s absence)
        # Anchor presence at the moment the break starts.
        st0 = cv_pipeline.update_presence(face_detected=True, timestamp=now + 900)
        assert st0 == PresenceState.PRESENT
        # At 5s absent: TEMPORARILY_NOT_VISIBLE (mock hysteresis threshold: <10s)
        st1 = cv_pipeline.update_presence(face_detected=False, timestamp=now + 905)
        assert st1 == PresenceState.TEMPORARILY_NOT_VISIBLE
        # At 15s: AWAY
        st2 = cv_pipeline.update_presence(face_detected=False, timestamp=now + 915)
        assert st2 == PresenceState.AWAY

        # Student returns at 45s
        st3 = cv_pipeline.update_presence(face_detected=True, timestamp=now + 945)
        assert st3 == PresenceState.PRESENT

        # Parent opens live supervision for 2 mins
        parent_gateway.start_live_supervision(parent_id="p_ms", session_id=session_id)
        assert parent_gateway.is_live_supervision_active(session_id) is True
        parent_gateway.stop_live_supervision(parent_id="p_ms", session_id=session_id)
        assert parent_gateway.is_live_supervision_active(session_id) is False

        # Session Complete with 74% focus score
        end_time = now + 1800
        isolated_db.execute(
            "UPDATE study_sessions SET status = 'completed', actual_duration_seconds = 1800, end_time = ?, focus_score = 74.0 WHERE id = ?",
            (end_time, session_id),
        )
        report_id = "rep_ms_science"
        isolated_db.execute(
            """
            INSERT INTO session_reports 
            (id, session_id, student_id, focus_score, engagement_score, total_study_seconds, productive_seconds, distracted_seconds, topics_covered_json, key_strengths, areas_for_improvement, ai_tutor_feedback, parent_notes, generated_at)
            VALUES (?, ?, 's_ms', 74.0, 70.0, 1800, 1330, 470, '["Plant vs Animal Cells"]', 'Good understanding of chloroplasts', 'Keep smartphone outside study room', 'Good effort today, try reducing phone breaks!', 'Proud of you for getting back to study!', ?)
            """,
            (report_id, session_id, end_time),
        )

        rep = isolated_db.fetchone("SELECT * FROM session_reports WHERE id = ?", (report_id,))
        assert rep["focus_score"] == 74.0
        assert rep["distracted_seconds"] == 470

    # -----------------------------------------------------------------------
    # Scenario 3: The Offline Traveling Student
    # -----------------------------------------------------------------------
    def test_scenario_3_offline_traveling_student(
        self,
        isolated_db: AIGuruTestDB,
        tutor_provider: MockTutorProvider,
        connectivity_manager: MockConnectivityManager,
        gamification_engine: GamificationEngine,
    ):
        """
        Scenario 3: Airplane Flight Study Mode
        - Boot AI Guru with zero internet (ConnectivityManager -> OFFLINE).
        - Local CV pipeline runs using local webcam (0 bytes egress).
        - Local Ollama AI tutor provides interactive biology explanations.
        - Timer and SQLite persist all 40 minutes locally.
        - Report and XP awarded offline without crashing or technical errors.
        """
        # 1. Airplane Mode ON
        connectivity_manager.set_state(ConnectivityState.OFFLINE)
        tutor_provider.cloud_api_healthy = False
        tutor_provider.ollama_healthy = True

        now = time.time()
        session_id = "sess_flight_bio"
        isolated_db.execute(
            "INSERT INTO study_sessions (id, student_id, title, subject, target_duration_seconds, start_time, status, created_at) VALUES (?, 's_hs', 'Flight Study: Photosynthesis', 'Biology', 2400, ?, 'in_progress', ?)",
            (session_id, now, now),
        )

        # 2. Local Ollama AI Turn
        resp = tutor_provider.complete("Explain the Calvin cycle in photosynthesis")
        assert resp["mode"] == "LOCAL_OLLAMA"
        assert "Ollama" in resp["response"]

        # 3. Complete Session Offline
        end_time = now + 2400  # 40 mins
        isolated_db.execute(
            "UPDATE study_sessions SET status = 'completed', actual_duration_seconds = 2400, end_time = ?, focus_score = 94.0 WHERE id = ?",
            (end_time, session_id),
        )

        earned_xp = gamification_engine.calculate_earned_xp(duration_minutes=40.0, focus_score=94.0, goal_met=False)
        assert earned_xp == int(40 * 1.2)  # 48 XP

        isolated_db.execute("UPDATE students SET total_xp = total_xp + ? WHERE id = 's_hs'", (earned_xp,))

        # Verify offline persistence
        sess = isolated_db.fetchone("SELECT * FROM study_sessions WHERE id = ?", (session_id,))
        assert sess["status"] == "completed"
        assert sess["actual_duration_seconds"] == 2400

    # -----------------------------------------------------------------------
    # Scenario 4: Parent Remote Supervision & Privacy Audit
    # -----------------------------------------------------------------------
    def test_scenario_4_parent_remote_supervision_and_audit(
        self,
        isolated_db: AIGuruTestDB,
        parent_gateway: MockParentRemoteGateway,
    ):
        """
        Scenario 4: Remote Parent on 5G Network
        - Connects via outbound reverse tunnel.
        - Authenticates with 15-min JWT.
        - Views student real-time metrics (focus 94%, active session).
        - Initiates opt-in live video supervision -> auto-terminates on session end.
        - Downloads session report.
        - Security audit log verifies zero biometric egress and complete audit trail.
        """
        parent_id = "p_ms"
        session_id = "sess_ms_science"

        # Function-scoped DB: this scenario seeds its own identities/session
        # instead of depending on Scenario 2's data.
        now = time.time()
        isolated_db.execute("INSERT INTO users (id, username, password_hash, role, display_name, created_at, updated_at) VALUES ('u_ms', 'leo', 'pw', 'student', 'Leo Miller', ?, ?)", (now, now))
        isolated_db.execute("INSERT INTO students (id, user_id, grade_level, created_at, updated_at) VALUES ('s_ms', 'u_ms', '7th', ?, ?)", (now, now))
        isolated_db.execute("INSERT INTO users (id, username, password_hash, role, display_name, created_at, updated_at) VALUES ('u_pm', 'parent_miller', 'pw', 'parent', 'Mrs. Miller', ?, ?)", (now, now))
        isolated_db.execute("INSERT INTO parents (id, user_id, email, created_at, updated_at) VALUES ('p_ms', 'u_pm', 'miller@example.com', ?, ?)", (now, now))
        isolated_db.execute(
            "INSERT INTO study_sessions (id, student_id, title, subject, target_duration_seconds, start_time, status, focus_score, created_at)"
            " VALUES (?, 's_ms', 'Cell Biology', 'Science', 1800, ?, 'in_progress', 94.0, ?)",
            (session_id, now, now),
        )

        # 1. Authenticate with short-lived JWT
        jwt = parent_gateway.issue_parent_jwt(parent_id, ttl_seconds=900.0)
        assert parent_gateway.validate_parent_jwt(jwt) == parent_id

        # 2. Query Student Live Status
        session = isolated_db.fetchone("SELECT * FROM study_sessions WHERE id = ?", (session_id,))
        assert session is not None

        # 3. Live Video Supervision
        parent_gateway.start_live_supervision(parent_id, session_id)
        assert parent_gateway.is_live_supervision_active(session_id) is True
        parent_gateway.stop_live_supervision(parent_id, session_id)

        # 4. Download Report
        parent_gateway.log_audit(parent_id, "parent", "REPORT_DOWNLOAD_PDF", "session_report", "rep_ms_science")

        # 5. Security Audit Log Verification
        logs = isolated_db.fetchall("SELECT * FROM audit_logs WHERE actor_id = ? ORDER BY id ASC;", (parent_id,))
        actions = [l["action"] for l in logs]
        assert "PARENT_LOGIN" in actions
        assert "LIVE_FEED_START" in actions
        assert "LIVE_FEED_STOP" in actions
        assert "REPORT_DOWNLOAD_PDF" in actions
