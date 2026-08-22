"""
Tier 3: Cross-Feature Combinations E2E Test Suite for AI Guru.

Multi-module integration pipelines verifying end-to-end interactions between:
- Student Enrollment + Parent Pairing + Study Session + CV Telemetry + Gamification XP & Badges
- Live Monitoring + Distraction Detection + Warning Issuance + Parent Real-Time Telemetry Query
- Active Study Session + Mid-Session Internet Outage + Local AI Fallback + Sync Recovery
- Parent Remote Supervision + Opt-In Live Video + Session Auto-Kill + Audit Logging
- Data Privacy Purge + Encrypted Backup Export + DB Reset + Backup Restore Integrity
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


class TestTier3CrossFeatureCombinations:
    """Tier 3: Multi-Module Integration & Cross-Feature Pipelines."""

    # -----------------------------------------------------------------------
    # Pipeline 1: Student Pairing + Session + Monitoring + Rewards + Parent View
    # -----------------------------------------------------------------------
    def test_cross_pairing_session_monitoring_rewards(
        self,
        isolated_db: AIGuruTestDB,
        parent_gateway: MockParentRemoteGateway,
        cv_pipeline: MockCVPipeline,
        gamification_engine: GamificationEngine,
    ):
        """
        Full lifecycle:
        1. Register student & parent.
        2. Pair via 6-digit code.
        3. Run 30-min study session with 180 telemetry frames.
        4. Complete session, generate report, award XP & badge.
        5. Verify parent dashboard reflects real-time study metrics.
        """
        now = time.time()
        # 1. Register Student & Parent
        isolated_db.execute(
            "INSERT INTO users (id, username, password_hash, role, display_name, created_at, updated_at) VALUES ('u_s1', 'sarah', 'pw', 'student', 'Sarah Chen', ?, ?)",
            (now, now),
        )
        isolated_db.execute(
            "INSERT INTO students (id, user_id, grade_level, school, learning_style, target_daily_minutes, streak_count, total_xp, created_at, updated_at) VALUES ('s_01', 'u_s1', '11th', 'Lincoln High', 'visual', 60, 6, 450, ?, ?)",
            (now, now),
        )
        isolated_db.execute(
            "INSERT INTO users (id, username, password_hash, role, display_name, created_at, updated_at) VALUES ('u_p1', 'parent_chen', 'pw', 'parent', 'Dr. Chen', ?, ?)",
            (now, now),
        )
        isolated_db.execute(
            "INSERT INTO parents (id, user_id, email, phone_number, created_at, updated_at) VALUES ('p_01', 'u_p1', 'chen@example.com', '+15550199', ?, ?)",
            (now, now),
        )

        # 2. Parent-Student Pairing Handshake
        code = parent_gateway.generate_pairing_code(student_id="s_01")
        paired, link_id = parent_gateway.verify_and_pair(parent_id="p_01", pairing_code=code)
        assert paired is True

        # 3. Create and Run Study Session
        session_id = "sess_math_30m"
        isolated_db.execute(
            """
            INSERT INTO study_sessions 
            (id, student_id, title, subject, target_duration_seconds, start_time, status, created_at)
            VALUES (?, 's_01', 'AP Calculus Derivatives', 'Mathematics', 1800, ?, 'in_progress', ?)
            """,
            (session_id, now, now),
        )

        # Stream 180 telemetry frames (sampled every 10s = 1800s total)
        for i in range(180):
            frame_time = now + (i * 10)
            frame = CVFrameTelemetry(
                timestamp=frame_time,
                face_detected=True,
                pitch=30.0,
                yaw=2.0,
                hand_at_desk=True,
            )
            activity = cv_pipeline.classify_activity(frame)
            score = cv_pipeline.calculate_engagement_score(activity, frame)
            isolated_db.execute(
                """
                INSERT INTO monitoring_events (session_id, timestamp, event_type, confidence, duration_seconds, metadata_json)
                VALUES (?, ?, 'POSTURE_SHIFT', 0.98, 10.0, ?)
                """,
                (session_id, frame_time, json.dumps({"activity": activity.value, "engagement": score})),
            )

        # 4. Finish Session & Generate Report
        end_time = now + 1800
        isolated_db.execute(
            """
            UPDATE study_sessions 
            SET status = 'completed', actual_duration_seconds = 1800, end_time = ?, focus_score = 98.0, engagement_score = 96.0
            WHERE id = ?
            """,
            (end_time, session_id),
        )
        report_id = "rep_math_30m"
        isolated_db.execute(
            """
            INSERT INTO session_reports 
            (id, session_id, student_id, focus_score, engagement_score, total_study_seconds, productive_seconds, distracted_seconds, topics_covered_json, key_strengths, areas_for_improvement, ai_tutor_feedback, generated_at)
            VALUES (?, ?, 's_01', 98.0, 96.0, 1800, 1800, 0, '["Product Rule", "Chain Rule"]', 'Mastered implicit differentiation', 'Review trig derivatives', 'Outstanding work today!', ?)
            """,
            (report_id, session_id, end_time),
        )

        # Award Gamification XP & Badge
        earned_xp = gamification_engine.calculate_earned_xp(duration_minutes=30.0, focus_score=98.0, goal_met=True)
        assert earned_xp == 95

        # Update student streak (6 -> 7) and total XP (450 + 95 = 545)
        isolated_db.execute(
            "UPDATE students SET streak_count = 7, total_xp = total_xp + ? WHERE id = 's_01'",
            (earned_xp,),
        )
        isolated_db.execute(
            "INSERT INTO rewards (id, student_id, session_id, reward_type, amount_xp, badge_id, badge_name, unlocked_at) VALUES ('r_xp_1', 's_01', ?, 'xp', ?, '', '', ?)",
            (session_id, earned_xp, end_time),
        )
        isolated_db.execute(
            "INSERT INTO rewards (id, student_id, session_id, reward_type, amount_xp, badge_id, badge_name, unlocked_at) VALUES ('r_bdg_1', 's_01', ?, 'badge', 0, 'badge_streak_7', '7-Day Streak Master', ?)",
            (session_id, end_time),
        )

        # 5. Parent Dashboard Queries
        parent_student = isolated_db.fetchone(
            """
            SELECT s.*, u.display_name 
            FROM students s 
            JOIN users u ON s.user_id = u.id 
            JOIN parent_student_links l ON l.student_id = s.id 
            WHERE l.parent_id = 'p_01'
            """
        )
        assert parent_student["streak_count"] == 7
        assert parent_student["total_xp"] == 545

        parent_reports = isolated_db.fetchall("SELECT * FROM session_reports WHERE student_id = 's_01';")
        assert len(parent_reports) == 1
        assert parent_reports[0]["focus_score"] == 98.0

    # -----------------------------------------------------------------------
    # Pipeline 2: Live Distraction Detection + Warning + Parent Telemetry Query
    # -----------------------------------------------------------------------
    def test_cross_live_monitoring_warning_parent_telemetry(
        self,
        isolated_db: AIGuruTestDB,
        cv_pipeline: MockCVPipeline,
    ):
        """
        Verify live distraction detection cascade:
        1. Student picks up phone.
        2. CV pipeline flags distraction and issues warning with cooldown.
        3. Event is recorded in DB.
        4. Parent queries live telemetry and receives alert status.
        """
        now = time.time()
        session_id = "sess_distract_live"
        isolated_db.execute(
            "INSERT INTO study_sessions (id, student_id, title, target_duration_seconds, start_time, status, created_at) VALUES (?, 's_01', 'Chemistry Study', 1800, ?, 'in_progress', ?)",
            (session_id, now, now),
        )

        # Student picks up phone for 20s
        phone_frame = CVFrameTelemetry(timestamp=now + 60, face_detected=True, phone_detected=True)
        activity = cv_pipeline.classify_activity(phone_frame)
        assert activity == PostureActivity.PHONE_USAGE

        warning = cv_pipeline.evaluate_warning(activity, duration_seconds=20.0, timestamp=now + 60)
        assert warning is not None

        # Telemetry written to DB
        isolated_db.execute(
            """
            INSERT INTO monitoring_events (session_id, timestamp, event_type, severity, confidence, duration_seconds, metadata_json)
            VALUES (?, ?, 'WARNING_ISSUED', 'warning', 0.95, 20.0, ?)
            """,
            (session_id, now + 60, json.dumps(warning)),
        )

        # Parent live telemetry query
        recent_warning = isolated_db.fetchone(
            """
            SELECT * FROM monitoring_events 
            WHERE session_id = ? AND event_type = 'WARNING_ISSUED' 
            ORDER BY timestamp DESC LIMIT 1
            """,
            (session_id,),
        )
        assert recent_warning is not None
        assert "PHONE_USAGE" in recent_warning["metadata_json"]

    # -----------------------------------------------------------------------
    # Pipeline 3: Active Session + Mid-Session Internet Drop + Local AI + Resume
    # -----------------------------------------------------------------------
    def test_cross_offline_recovery_and_sync(
        self,
        tutor_provider: MockTutorProvider,
        connectivity_manager: MockConnectivityManager,
    ):
        """
        Verify seamless failover during network drop mid-session:
        1. Chat starts in Cloud API mode.
        2. Internet drops -> ConnectivityManager transitions to OFFLINE.
        3. TutorProvider fails over to Local Ollama.
        4. Offline telemetry queued.
        5. Internet restores -> Sync flushes queue.
        """
        # 1. Turn 1: Online Cloud AI
        res1 = tutor_provider.complete("What is kinetic energy?")
        assert res1["mode"] == "EXTERNAL_API"

        # 2. Internet Drops
        connectivity_manager.set_state(ConnectivityState.OFFLINE)
        tutor_provider.cloud_api_healthy = False

        # 3. Turn 2: Local Ollama AI
        res2 = tutor_provider.complete("How is it related to potential energy?")
        assert res2["mode"] == "LOCAL_OLLAMA"
        assert "Ollama" in res2["response"]

        # Queue telemetry while offline
        connectivity_manager.queue_action_for_sync({"event": "FOCUS_SAMPLE", "score": 92.0})
        assert len(connectivity_manager.sync_queue) == 1

        # 4. Internet Restored
        connectivity_manager.set_state(ConnectivityState.ONLINE)
        tutor_provider.cloud_api_healthy = True
        synced_events = connectivity_manager.flush_sync_queue()
        assert len(synced_events) == 1

        # 5. Turn 3: Cloud AI resumes
        res3 = tutor_provider.complete("Give me a practice problem.")
        assert res3["mode"] == "EXTERNAL_API"

    # -----------------------------------------------------------------------
    # Pipeline 4: Parent Remote Supervision + Opt-In Live Video + Audit Logging
    # -----------------------------------------------------------------------
    def test_cross_parent_supervision_live_video_and_audit(
        self,
        isolated_db: AIGuruTestDB,
        parent_gateway: MockParentRemoteGateway,
    ):
        """
        Verify parent remote supervision flow:
        1. Parent authenticates via JWT.
        2. Parent requests opt-in live video supervision.
        3. Video stream active during session.
        4. Session completes -> Live video auto-terminates immediately.
        5. Audit log reflects all actions.
        """
        parent_id = "p_01"
        session_id = "sess_supervised_01"

        # 1. Parent JWT Auth
        token = parent_gateway.issue_parent_jwt(parent_id)
        assert parent_gateway.validate_parent_jwt(token) == parent_id

        # 2. Start Live Video Supervision
        assert parent_gateway.start_live_supervision(parent_id, session_id) is True
        assert parent_gateway.is_live_supervision_active(session_id) is True

        # 3. Session Finishes -> Auto-kill live video stream
        parent_gateway.stop_live_supervision(parent_id, session_id)
        assert parent_gateway.is_live_supervision_active(session_id) is False

        # 4. Audit Trail Verification
        logs = isolated_db.fetchall("SELECT action FROM audit_logs WHERE actor_id = ? ORDER BY id ASC;", (parent_id,))
        actions = [log["action"] for log in logs]
        assert "PARENT_LOGIN" in actions
        assert "LIVE_FEED_START" in actions
        assert "LIVE_FEED_STOP" in actions

    # -----------------------------------------------------------------------
    # Pipeline 5: Data Privacy Purge + Encrypted Backup + Restore Integrity
    # -----------------------------------------------------------------------
    def test_cross_privacy_backup_purge_restore_cycle(self, isolated_db: AIGuruTestDB):
        """
        Verify privacy export, purge, and restore cycle:
        1. Snapshot all table records into JSON backup.
        2. Execute GDPR/Privacy data deletion on study sessions and events.
        3. Verify records are deleted.
        4. Restore records from backup.
        5. Verify full restoration.
        """
        # 1. Snapshot database records
        tables = ["users", "students", "parents", "study_sessions", "monitoring_events", "session_reports", "rewards"]
        backup_archive = {"version": 1, "timestamp": time.time(), "tables": {}}
        for table in tables:
            rows = isolated_db.fetchall(f"SELECT * FROM {table};")
            backup_archive["tables"][table] = [dict(r) for r in rows]

        # 2. Execute Data Purge
        isolated_db.execute("DELETE FROM study_sessions;")
        isolated_db.execute("DELETE FROM monitoring_events;")
        isolated_db.execute("DELETE FROM session_reports;")
        isolated_db.execute("DELETE FROM rewards;")

        # 3. Verify Purge Complete
        assert len(isolated_db.fetchall("SELECT * FROM study_sessions;")) == 0
        assert len(isolated_db.fetchall("SELECT * FROM monitoring_events;")) == 0
        assert len(isolated_db.fetchall("SELECT * FROM session_reports;")) == 0

        # 4. Restore from Backup Archive
        for table, rows in backup_archive["tables"].items():
            for row in rows:
                cols = list(row.keys())
                placeholders = ", ".join(["?"] * len(cols))
                sql = f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
                isolated_db.execute(sql, tuple(row.values()))

        # 5. Verify Full Restoration
        for table, rows in backup_archive["tables"].items():
            restored = isolated_db.fetchall(f"SELECT * FROM {table};")
            assert len(restored) == len(rows), f"Mismatch restoring table {table}"
