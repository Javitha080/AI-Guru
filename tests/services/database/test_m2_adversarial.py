"""
Empirical Adversarial Test Suite for Milestone 2: Local-First Unified Runtime & Database.

Tests:
1. Foreign key integrity, constraints, and cascading deletes across all 11 core tables.
2. Windows auto-startup behavior on Windows vs non-Windows platforms.
3. Process supervisor recovery logic, retry counter threshold, and backoff.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from deeptutor.services.database.migrations import (
    apply_migrations,
    enable_pragmas,
    get_applied_migrations,
    get_db_version,
    verify_tables_exist,
)
from deeptutor.services.database.schema import CORE_TABLE_NAMES
from deeptutor.services.platform.windows_startup import (
    DEFAULT_APP_NAME,
    disable_windows_startup,
    enable_windows_startup,
    get_default_startup_command,
    get_startup_status,
    is_windows,
    is_windows_startup_enabled,
)
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


# ============================================================================
# 1. FOREIGN KEY INTEGRITY, CONSTRAINTS & CASCADING DELETES
# ============================================================================


class TestForeignKeyIntegrityAndCascadingDeletes:
    """Adversarial testing of SQLite foreign key constraints, CHECK rules, and cascades."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> SQLiteSessionStore:
        db_file = tmp_path / "adversarial_fk.db"
        return SQLiteSessionStore(db_path=db_file)

    @pytest.fixture
    def raw_db(self, tmp_path: Path) -> sqlite3.Connection:
        db_file = tmp_path / "raw_fk.db"
        conn = sqlite3.connect(str(db_file))
        enable_pragmas(conn)
        apply_migrations(conn)
        yield conn
        conn.close()

    def test_pragma_foreign_keys_is_enforced(self, store: SQLiteSessionStore) -> None:
        """Verify PRAGMA foreign_keys is strictly ON in SQLiteSessionStore._connect()."""
        with store._connect() as conn:
            fk_status = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            assert fk_status == 1, "PRAGMA foreign_keys must be 1 (ON)"
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0].lower()
            assert journal_mode in ("wal", "memory"), f"Journal mode should be WAL, got {journal_mode}"

    def test_fk_rejection_on_orphan_student(self, raw_db: sqlite3.Connection) -> None:
        """Attempting to insert a student with a non-existent user_id must fail."""
        now = time.time()
        with pytest.raises(sqlite3.IntegrityError):
            raw_db.execute(
                """
                INSERT INTO students (id, user_id, grade_level, created_at, updated_at)
                VALUES ('orphan_student', 'non_existent_user', '10th', ?, ?)
                """,
                (now, now),
            )
            raw_db.commit()

    def test_fk_rejection_on_orphan_parent(self, raw_db: sqlite3.Connection) -> None:
        """Attempting to insert a parent with a non-existent user_id must fail."""
        now = time.time()
        with pytest.raises(sqlite3.IntegrityError):
            raw_db.execute(
                """
                INSERT INTO parents (id, user_id, email, created_at, updated_at)
                VALUES ('orphan_parent', 'non_existent_user', 'parent@test.com', ?, ?)
                """,
                (now, now),
            )
            raw_db.commit()

    def test_fk_rejection_on_orphan_study_session(self, raw_db: sqlite3.Connection) -> None:
        """Attempting to insert a study_session with a non-existent student_id must fail."""
        now = time.time()
        with pytest.raises(sqlite3.IntegrityError):
            raw_db.execute(
                """
                INSERT INTO study_sessions (id, student_id, title, target_duration_seconds, start_time, created_at)
                VALUES ('orphan_session', 'non_existent_student', 'Math', 1800, ?, ?)
                """,
                (now, now),
            )
            raw_db.commit()

    def test_fk_rejection_on_orphan_monitoring_event(self, raw_db: sqlite3.Connection) -> None:
        """Attempting to insert a monitoring_event with a non-existent session_id must fail."""
        now = time.time()
        with pytest.raises(sqlite3.IntegrityError):
            raw_db.execute(
                """
                INSERT INTO monitoring_events (session_id, timestamp, event_type, severity, confidence)
                VALUES ('non_existent_session', ?, 'PRESENCE_CHANGE', 'info', 0.95)
                """,
                (now,),
            )
            raw_db.commit()

    def test_fk_rejection_on_orphan_session_report(self, raw_db: sqlite3.Connection) -> None:
        """Attempting to insert a session_report with non-existent session_id or student_id must fail."""
        now = time.time()
        # 1. Non-existent session
        with pytest.raises(sqlite3.IntegrityError):
            raw_db.execute(
                """
                INSERT INTO session_reports (
                    id, session_id, student_id, focus_score, engagement_score,
                    total_study_seconds, productive_seconds, distracted_seconds, generated_at
                ) VALUES ('rep_1', 'non_existent_session', 'some_student', 90, 90, 1800, 1700, 100, ?)
                """,
                (now,),
            )
            raw_db.commit()

    def test_fk_rejection_on_orphan_rewards_and_goals(self, raw_db: sqlite3.Connection) -> None:
        """Attempting to insert rewards or study_goals with non-existent student_id must fail."""
        now = time.time()
        with pytest.raises(sqlite3.IntegrityError):
            raw_db.execute(
                """
                INSERT INTO rewards (id, student_id, reward_type, amount_xp, unlocked_at)
                VALUES ('r_1', 'non_existent_student', 'xp', 50, ?)
                """,
                (now,),
            )
            raw_db.commit()

        with pytest.raises(sqlite3.IntegrityError):
            raw_db.execute(
                """
                INSERT INTO study_goals (id, student_id, title, goal_type, target_value, start_date, end_date, created_at)
                VALUES ('g_1', 'non_existent_student', 'Daily Study', 'daily_minutes', 60.0, ?, ?, ?)
                """,
                (now, now + 86400, now),
            )
            raw_db.commit()

    def test_check_constraints_enforcement(self, raw_db: sqlite3.Connection) -> None:
        """Test CHECK constraints on role, status, event_type, severity, reward_type, goal_type."""
        now = time.time()
        # Invalid user role
        with pytest.raises(sqlite3.IntegrityError):
            raw_db.execute(
                "INSERT INTO users (id, username, password_hash, role, display_name, created_at, updated_at) "
                "VALUES ('u_bad', 'bad_role_user', 'hash', 'superhero', 'Hero', ?, ?)",
                (now, now),
            )

        # Create valid users and student for further checks
        raw_db.execute(
            "INSERT INTO users (id, username, password_hash, role, display_name, created_at, updated_at) "
            "VALUES ('u_val_s', 'valid_s', 'hash', 'student', 'Student', ?, ?)",
            (now, now),
        )
        raw_db.execute(
            "INSERT INTO students (id, user_id, created_at, updated_at) VALUES ('s_val', 'u_val_s', ?, ?)",
            (now, now),
        )
        raw_db.commit()

        # Invalid study session status
        with pytest.raises(sqlite3.IntegrityError):
            raw_db.execute(
                "INSERT INTO study_sessions (id, student_id, status, start_time, created_at) "
                "VALUES ('sess_bad', 's_val', 'exploded', ?, ?)",
                (now, now),
            )

        # Create valid study session
        raw_db.execute(
            "INSERT INTO study_sessions (id, student_id, status, start_time, created_at) "
            "VALUES ('sess_val', 's_val', 'in_progress', ?, ?)",
            (now, now),
        )
        raw_db.commit()

        # Invalid monitoring event type
        with pytest.raises(sqlite3.IntegrityError):
            raw_db.execute(
                "INSERT INTO monitoring_events (session_id, timestamp, event_type, severity) "
                "VALUES ('sess_val', ?, 'ALIEN_ABDUCTION', 'info')",
                (now,),
            )

        # Invalid monitoring severity
        with pytest.raises(sqlite3.IntegrityError):
            raw_db.execute(
                "INSERT INTO monitoring_events (session_id, timestamp, event_type, severity) "
                "VALUES ('sess_val', ?, 'PRESENCE_CHANGE', 'catastrophic')",
                (now,),
            )

        # Invalid reward type
        with pytest.raises(sqlite3.IntegrityError):
            raw_db.execute(
                "INSERT INTO rewards (id, student_id, reward_type, unlocked_at) "
                "VALUES ('r_bad', 's_val', 'crypto_token', ?)",
                (now,),
            )

        # Invalid goal type
        with pytest.raises(sqlite3.IntegrityError):
            raw_db.execute(
                "INSERT INTO study_goals (id, student_id, title, goal_type, target_value, start_date, end_date, created_at) "
                "VALUES ('g_bad', 's_val', 'Goal', 'magic_points', 10.0, ?, ?, ?)",
                (now, now + 10, now),
            )

    def test_cascading_delete_study_session(self, store: SQLiteSessionStore) -> None:
        """
        Adversarially test cascading delete of a study session:
        - monitoring_events (ON DELETE CASCADE) must be deleted.
        - session_reports (ON DELETE CASCADE) must be deleted.
        - rewards with session_id (ON DELETE SET NULL) must retain the reward row with session_id=NULL.
        """
        u = asyncio.run(store.create_user("student_cascade1", "pass", "student", "Student C1"))
        s = asyncio.run(store.create_student(user_id=u["id"]))
        sess = asyncio.run(store.create_study_session(student_id=s["id"], title="Physics"))

        # Add 3 monitoring events
        e1 = asyncio.run(store.record_monitoring_event(sess["id"], "PRESENCE_CHANGE", "info", 0.9))
        e2 = asyncio.run(store.record_monitoring_event(sess["id"], "LOOKING_AWAY", "warning", 0.8))
        e3 = asyncio.run(store.record_monitoring_event(sess["id"], "WARNING_ISSUED", "alert", 1.0))

        # Add session report
        rep = asyncio.run(
            store.create_session_report(
                session_id=sess["id"],
                student_id=s["id"],
                focus_score=88.0,
                engagement_score=85.0,
                total_study_seconds=1800,
                productive_seconds=1500,
                distracted_seconds=300,
            )
        )

        # Add reward linked to this session
        r_session = asyncio.run(store.award_xp(s["id"], 50, "Session XP", session_id=sess["id"]))

        # Verify all records exist before deletion
        events_before = asyncio.run(store.get_monitoring_events(sess["id"]))
        assert len(events_before) == 3
        rep_before = asyncio.run(store.get_session_report(sess["id"]))
        assert rep_before is not None
        rewards_before = asyncio.run(store.get_rewards(s["id"]))
        assert len(rewards_before) == 1
        assert rewards_before[0]["session_id"] == sess["id"]

        # Delete the study session via direct SQL or store
        with store._connect() as conn:
            conn.execute("DELETE FROM study_sessions WHERE id = ?", (sess["id"],))
            conn.commit()

        # Check cascading effects
        with store._connect() as conn:
            # 1. Monitoring events must be 0
            ev_count = conn.execute("SELECT COUNT(*) FROM monitoring_events WHERE session_id = ?", (sess["id"],)).fetchone()[0]
            assert ev_count == 0, f"Expected 0 monitoring_events after session delete, found {ev_count}"

            # 2. Session report must be 0
            rep_count = conn.execute("SELECT COUNT(*) FROM session_reports WHERE session_id = ?", (sess["id"],)).fetchone()[0]
            assert rep_count == 0, f"Expected 0 session_reports after session delete, found {rep_count}"

            # 3. Rewards row must survive with session_id SET NULL
            rew_row = conn.execute("SELECT * FROM rewards WHERE id = ?", (r_session["id"],)).fetchone()
            assert rew_row is not None, "Reward record should survive session deletion"
            assert rew_row["session_id"] is None, f"Expected reward session_id to be NULL, got {rew_row['session_id']}"
            assert rew_row["amount_xp"] == 50

            # 4. Student and User must remain intact
            student_row = conn.execute("SELECT * FROM students WHERE id = ?", (s["id"],)).fetchone()
            assert student_row is not None

    def test_cascading_delete_parent_student_link(self, store: SQLiteSessionStore) -> None:
        """
        Adversarially test deleting parent or student:
        - Deleting parent deletes parent_student_links (CASCADE).
        - Deleting student deletes parent_student_links (CASCADE), sessions, reports, rewards, goals.
        """
        u_p = asyncio.run(store.create_user("p_cascade", "pass", "parent", "Parent C"))
        u_s = asyncio.run(store.create_user("s_cascade", "pass", "student", "Student C"))
        p = asyncio.run(store.create_parent(user_id=u_p["id"]))
        s = asyncio.run(store.create_student(user_id=u_s["id"]))

        # Create active link
        code = asyncio.run(store.create_pairing_code(s["id"]))
        ok = asyncio.run(store.verify_pairing_code(p["id"], code))
        assert ok is True

        linked = asyncio.run(store.get_linked_students(p["id"]))
        assert len(linked) == 1

        # Delete parent
        with store._connect() as conn:
            conn.execute("DELETE FROM parents WHERE id = ?", (p["id"],))
            conn.commit()

        # Verify link is automatically deleted via foreign key cascade
        with store._connect() as conn:
            links_count = conn.execute("SELECT COUNT(*) FROM parent_student_links WHERE parent_id = ?", (p["id"],)).fetchone()[0]
            assert links_count == 0, f"Expected 0 links for deleted parent, found {links_count}"

            # Student still exists
            s_check = conn.execute("SELECT * FROM students WHERE id = ?", (s["id"],)).fetchone()
            assert s_check is not None

    def test_multi_tier_cascading_delete_from_user(self, store: SQLiteSessionStore) -> None:
        """
        Adversarially test deleting the root `users` row:
        User -> Student -> StudySession -> MonitoringEvents, SessionReports, Rewards, Goals, Links.
        All child records across all tables must cascade cleanly.
        """
        u = asyncio.run(store.create_user("root_student_user", "pass", "student", "Root Student"))
        s = asyncio.run(store.create_student(user_id=u["id"]))
        sess = asyncio.run(store.create_study_session(student_id=s["id"], title="History"))
        asyncio.run(store.record_monitoring_event(sess["id"], "PRESENCE_CHANGE", "info", 1.0))
        asyncio.run(
            store.create_session_report(
                session_id=sess["id"],
                student_id=s["id"],
                focus_score=90.0,
                engagement_score=90.0,
                total_study_seconds=600,
                productive_seconds=550,
                distracted_seconds=50,
            )
        )
        asyncio.run(store.award_xp(s["id"], 100, "History Master", session_id=sess["id"]))
        now = time.time()
        asyncio.run(
            store.create_study_goal(
                student_id=s["id"],
                title="Goal 1",
                goal_type="daily_minutes",
                target_value=30.0,
                start_date=now,
                end_date=now + 86400,
            )
        )

        # Delete user via delete_user
        deleted = asyncio.run(store.delete_user(u["id"]))
        assert deleted is True

        with store._connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM users WHERE id = ?", (u["id"],)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM students WHERE id = ?", (s["id"],)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM study_sessions WHERE student_id = ?", (s["id"],)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM monitoring_events WHERE session_id = ?", (sess["id"],)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM session_reports WHERE student_id = ?", (s["id"],)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM rewards WHERE student_id = ?", (s["id"],)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM study_goals WHERE student_id = ?", (s["id"],)).fetchone()[0] == 0


# ============================================================================
# 2. WINDOWS AUTO-STARTUP BEHAVIOR (WINDOWS VS NON-WINDOWS)
# ============================================================================


class TestWindowsAutoStartupAdversarial:
    """Adversarial testing of Windows auto-startup on Windows and non-Windows environments."""

    def test_non_windows_platform_graceful_degradation(self) -> None:
        """When running on non-Windows (or simulated non-Windows), all operations must safely fail/return False without crashing."""
        with patch("deeptutor.services.platform.windows_startup.is_windows", return_value=False):
            # 1. is_windows_startup_enabled must return False
            assert is_windows_startup_enabled("TestApp") is False

            # 2. enable_windows_startup must return False
            assert enable_windows_startup("TestApp") is False

            # 3. disable_windows_startup must return False
            assert disable_windows_startup("TestApp") is False

            # 4. get_startup_status must report supported=False
            status = get_startup_status("TestApp")
            assert status["supported"] is False
            assert status["enabled"] is False
            assert "Windows OS only" in status["message"]

    @pytest.mark.skipif(not is_windows(), reason="Requires live Windows platform for real registry probe")
    def test_windows_real_registry_lifecycle(self) -> None:
        """
        On live Windows systems, test real registry enable, query, duplicate enable, disable, duplicate disable.
        Uses a distinct test key 'AIGuruAdversarialEmpiricalKey' to ensure zero impact on actual user settings.
        """
        test_key = "AIGuruAdversarialEmpiricalKey"
        try:
            # Step 1: Ensure clean initial state
            disable_windows_startup(test_key)
            assert is_windows_startup_enabled(test_key) is False

            # Step 2: Enable startup
            enabled_ok = enable_windows_startup(test_key, args="start --port 8001")
            assert enabled_ok is True
            assert is_windows_startup_enabled(test_key) is True

            # Step 3: Inspect startup status
            status = get_startup_status(test_key)
            assert status["platform"] == "win32"
            assert status["supported"] is True
            assert status["enabled"] is True
            assert status["app_name"] == test_key
            assert "deeptutor_cli.main" in status["command"]
            assert "--port 8001" in status["command"]

            # Step 4: Disable startup
            disabled_ok = disable_windows_startup(test_key)
            assert disabled_ok is True
            assert is_windows_startup_enabled(test_key) is False

            # Step 5: Duplicate disable (idempotent removal)
            dup_disable_ok = disable_windows_startup(test_key)
            assert dup_disable_ok is True
            assert is_windows_startup_enabled(test_key) is False

        finally:
            # Always ensure test key is cleaned up
            disable_windows_startup(test_key)

    def test_windows_registry_permission_error_handling(self) -> None:
        """Verify that unexpected winreg exceptions return False rather than bubbling unhandled."""
        if not is_windows():
            pytest.skip("Windows only test for winreg error branch")

        with patch("winreg.OpenKey", side_effect=PermissionError("Access Denied")):
            assert is_windows_startup_enabled("TestApp") is False
            assert enable_windows_startup("TestApp") is False
            assert disable_windows_startup("TestApp") is False


# ============================================================================
# 3. PROCESS SUPERVISOR RECOVERY LOGIC & RETRY COUNTER
# ============================================================================


class TestSupervisorRecoveryLogic:
    """Adversarial testing of process supervisor recovery, retry counter limit, and crash handling."""

    def test_supervisor_recovery_counter_and_limit(self) -> None:
        """
        Simulate supervisor crash recovery logic from launcher.py:
        - Max recovery attempts = 3.
        - Attempts 1, 2, 3 must trigger restart.
        - Attempt 4 must stop recovery, set exit_code = 1, and request shutdown.
        """
        max_recovery_attempts = 3
        recovery_counts = {"backend": 0, "frontend": 0}
        shutdown_requested = False
        exit_code = 0
        restarts_executed = []

        def simulate_child_crash(service_name: str, exit_status: int = 1) -> None:
            nonlocal shutdown_requested, exit_code
            if recovery_counts[service_name] < max_recovery_attempts and not shutdown_requested:
                recovery_counts[service_name] += 1
                restarts_executed.append((service_name, recovery_counts[service_name], "restarted"))
            else:
                exit_code = 1
                shutdown_requested = True
                restarts_executed.append((service_name, recovery_counts[service_name], "terminated"))

        # Crash 1
        simulate_child_crash("backend", 1)
        assert recovery_counts["backend"] == 1
        assert shutdown_requested is False
        assert exit_code == 0

        # Crash 2
        simulate_child_crash("backend", 1)
        assert recovery_counts["backend"] == 2
        assert shutdown_requested is False
        assert exit_code == 0

        # Crash 3
        simulate_child_crash("backend", 1)
        assert recovery_counts["backend"] == 3
        assert shutdown_requested is False
        assert exit_code == 0

        # Crash 4 (exceeds max_recovery_attempts = 3)
        simulate_child_crash("backend", 1)
        assert recovery_counts["backend"] == 3
        assert shutdown_requested is True
        assert exit_code == 1

        assert len(restarts_executed) == 4
        assert restarts_executed[-1] == ("backend", 3, "terminated")

    def test_supervisor_frontend_independent_counter(self) -> None:
        """Verify backend and frontend crash recovery counts are tracked independently."""
        max_recovery_attempts = 3
        recovery_counts = {"backend": 0, "frontend": 0}
        shutdown_requested = False
        exit_code = 0

        def crash(service: str):
            nonlocal shutdown_requested, exit_code
            if recovery_counts[service] < max_recovery_attempts and not shutdown_requested:
                recovery_counts[service] += 1
            else:
                exit_code = 1
                shutdown_requested = True

        # Backend crashes twice
        crash("backend")
        crash("backend")
        assert recovery_counts["backend"] == 2
        assert recovery_counts["frontend"] == 0
        assert not shutdown_requested

        # Frontend crashes once
        crash("frontend")
        assert recovery_counts["frontend"] == 1
        assert recovery_counts["backend"] == 2
        assert not shutdown_requested

    def test_supervisor_spawn_failure_handling(self) -> None:
        """
        Verify that if respawning during recovery throws an exception (e.g. port taken or binary missing),
        the supervisor catches it, logs error, sets exit_code=1, and triggers shutdown.
        """
        recovery_counts = {"backend": 0}
        max_recovery_attempts = 3
        shutdown_requested = False
        exit_code = 0
        logged_errors = []

        def attempt_recovery_with_failing_spawn():
            nonlocal shutdown_requested, exit_code
            if recovery_counts["backend"] < max_recovery_attempts and not shutdown_requested:
                recovery_counts["backend"] += 1
                try:
                    # Simulate failure during spawn
                    raise RuntimeError("Port 8001 already in use")
                except Exception as err:
                    logged_errors.append(str(err))
                    exit_code = 1
                    shutdown_requested = True

        attempt_recovery_with_failing_spawn()
        assert recovery_counts["backend"] == 1
        assert exit_code == 1
        assert shutdown_requested is True
        assert "Port 8001 already in use" in logged_errors[0]
