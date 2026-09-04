"""
Tests for AI Guru SQLiteSessionStore domain CRUD helper methods.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import time

import pytest

from deeptutor.services.session.sqlite_store import SQLiteSessionStore


@pytest.fixture
def store(tmp_path: Path) -> SQLiteSessionStore:
    return SQLiteSessionStore(db_path=tmp_path / "test_domain.db")


def test_user_crud(store: SQLiteSessionStore) -> None:
    # 1. Create user
    user = asyncio.run(
        store.create_user(
            username="student_alice",
            password_hash="hash_12345",
            role="student",
            display_name="Alice Smith",
        )
    )
    assert user["username"] == "student_alice"
    assert user["role"] == "student"
    assert user["display_name"] == "Alice Smith"

    # 2. Get user by id and username
    fetched = asyncio.run(store.get_user(user["id"]))
    assert fetched is not None
    assert fetched["username"] == "student_alice"

    by_uname = asyncio.run(store.get_user_by_username("student_alice"))
    assert by_uname is not None
    assert by_uname["id"] == user["id"]

    # 3. List users
    users = asyncio.run(store.list_users(role="student"))
    assert len(users) == 1
    assert users[0]["username"] == "student_alice"

    # 4. Update user
    updated = asyncio.run(store.update_user(user["id"], {"display_name": "Alice Cooper"}))
    assert updated is True
    re_fetched = asyncio.run(store.get_user(user["id"]))
    assert re_fetched["display_name"] == "Alice Cooper"

    # 5. Delete user
    deleted = asyncio.run(store.delete_user(user["id"]))
    assert deleted is True
    assert asyncio.run(store.get_user(user["id"])) is None


def test_student_and_parent_crud(store: SQLiteSessionStore) -> None:
    # Create user accounts
    u_student = asyncio.run(store.create_user("s1", "pass", "student", "Student One"))
    u_parent = asyncio.run(store.create_user("p1", "pass", "parent", "Parent One"))

    # Student CRUD
    student = asyncio.run(
        store.create_student(
            user_id=u_student["id"],
            grade_level="10th",
            school="Lincoln High",
            target_daily_minutes=45,
        )
    )
    assert student["grade_level"] == "10th"
    assert student["total_xp"] == 0

    by_uid = asyncio.run(store.get_student_by_user_id(u_student["id"]))
    assert by_uid is not None
    assert by_uid["id"] == student["id"]

    # XP & Streak
    new_xp = asyncio.run(store.update_student_xp(student["id"], 50))
    assert new_xp == 50
    streak_ok = asyncio.run(store.update_student_streak(student["id"], 3))
    assert streak_ok is True

    # Face embedding
    emb_ok = asyncio.run(store.set_student_face_embedding(student["id"], [0.1, 0.2, 0.3]))
    assert emb_ok is True
    student_record = asyncio.run(store.get_student(student["id"]))
    assert student_record["face_embedding"] == [0.1, 0.2, 0.3]
    assert student_record["total_xp"] == 50
    assert student_record["streak_count"] == 3

    # Parent CRUD
    parent = asyncio.run(
        store.create_parent(
            user_id=u_parent["id"],
            email="parent@example.com",
            phone_number="555-0100",
        )
    )
    assert parent["email"] == "parent@example.com"
    fetched_parent = asyncio.run(store.get_parent(parent["id"]))
    assert fetched_parent is not None
    assert fetched_parent["phone_number"] == "555-0100"


def test_pairing_handshake(store: SQLiteSessionStore) -> None:
    u_s = asyncio.run(store.create_user("s_pair", "pass", "student", "Student Pair"))
    u_p = asyncio.run(store.create_user("p_pair", "pass", "parent", "Parent Pair"))
    student = asyncio.run(store.create_student(user_id=u_s["id"]))
    parent = asyncio.run(store.create_parent(user_id=u_p["id"]))

    # Generate pairing code
    code = asyncio.run(store.create_pairing_code(student["id"], expires_in_seconds=300))
    assert code.startswith("GURU-")

    # Invalid code
    assert asyncio.run(store.verify_pairing_code(parent["id"], "INVALID-CODE")) is False

    # Valid pairing code
    verified = asyncio.run(store.verify_pairing_code(parent["id"], code))
    assert verified is True

    # Code should be consumed and invalid for second use
    assert asyncio.run(store.verify_pairing_code(parent["id"], code)) is False

    # Check links
    linked_students = asyncio.run(store.get_linked_students(parent["id"]))
    assert len(linked_students) == 1
    assert linked_students[0]["student_id"] == student["id"]

    linked_parents = asyncio.run(store.get_linked_parents(student["id"]))
    assert len(linked_parents) == 1
    assert linked_parents[0]["parent_id"] == parent["id"]

    # Revoke link
    revoked = asyncio.run(store.revoke_parent_student_link(parent["id"], student["id"]))
    assert revoked is True
    assert len(asyncio.run(store.get_linked_students(parent["id"]))) == 0


def test_study_session_and_monitoring_events(store: SQLiteSessionStore) -> None:
    u_s = asyncio.run(store.create_user("s_sess", "pass", "student", "Student Sess"))
    student = asyncio.run(store.create_student(user_id=u_s["id"]))

    # Create study session
    sess = asyncio.run(
        store.create_study_session(
            student_id=student["id"],
            title="Calculus Integration",
            subject="Mathematics",
            target_duration_seconds=3600,
        )
    )
    assert sess["status"] == "in_progress"
    assert sess["target_duration_seconds"] == 3600

    # Record monitoring events
    e1 = asyncio.run(
        store.record_monitoring_event(
            session_id=sess["id"],
            event_type="PRESENCE_CHANGE",
            severity="info",
            confidence=0.98,
            duration_seconds=0.0,
            metadata={"presence": "PRESENT"},
        )
    )
    assert e1 > 0

    e2 = asyncio.run(
        store.record_monitoring_event(
            session_id=sess["id"],
            event_type="LOOKING_AWAY",
            severity="warning",
            confidence=0.85,
            duration_seconds=4.2,
            metadata={"yaw": 38.5},
        )
    )
    assert e2 > e1

    # Query monitoring events
    events = asyncio.run(store.get_monitoring_events(sess["id"]))
    assert len(events) == 2
    assert events[0]["event_type"] == "PRESENCE_CHANGE"
    assert events[0]["metadata"]["presence"] == "PRESENT"
    assert events[1]["event_type"] == "LOOKING_AWAY"

    # Finish study session
    finished = asyncio.run(
        store.finish_study_session(
            sess["id"],
            stats={
                "focus_score": 92.5,
                "engagement_score": 88.0,
                "distraction_count": 1,
                "warning_count": 1,
                "actual_duration_seconds": 3540,
                "ai_summary": "Great focus on calculus problems.",
            },
        )
    )
    assert finished is not None
    assert finished["status"] == "completed"
    assert finished["focus_score"] == 92.5
    assert finished["distraction_count"] == 1
    assert finished["ai_summary"] == "Great focus on calculus problems."


def test_session_report_and_rewards(store: SQLiteSessionStore) -> None:
    u_s = asyncio.run(store.create_user("s_rep", "pass", "student", "Student Rep"))
    student = asyncio.run(store.create_student(user_id=u_s["id"]))
    sess = asyncio.run(store.create_study_session(student_id=student["id"]))

    # Create report
    report = asyncio.run(
        store.create_session_report(
            session_id=sess["id"],
            student_id=student["id"],
            focus_score=95.0,
            engagement_score=90.0,
            total_study_seconds=1800,
            productive_seconds=1710,
            distracted_seconds=90,
            topics_covered=["Quadratic Equations", "Factoring"],
            key_strengths="Consistent attention throughout session",
            areas_for_improvement="Quick posture adjustments",
            ai_tutor_feedback="Mastered quadratic formula quickly.",
        )
    )
    assert report["focus_score"] == 95.0
    assert len(report["topics_covered"]) == 2

    # Get report
    fetched_rep = asyncio.run(store.get_session_report(sess["id"]))
    assert fetched_rep is not None
    assert fetched_rep["key_strengths"] == "Consistent attention throughout session"

    # Award rewards & XP
    r_xp = asyncio.run(store.award_xp(student["id"], 60, "Completed 30m study session", sess["id"]))
    assert r_xp["amount_xp"] == 60

    r_badge = asyncio.run(
        store.award_reward(
            student_id=student["id"],
            reward_type="badge",
            badge_id="laser_focus",
            badge_name="Laser Focus",
            badge_icon="target",
            reason="Maintained >90% focus score",
        )
    )
    assert r_badge["badge_id"] == "laser_focus"

    rewards = asyncio.run(store.get_rewards(student["id"]))
    assert len(rewards) == 2


def test_study_goals_and_settings_and_audit(store: SQLiteSessionStore) -> None:
    u_s = asyncio.run(store.create_user("s_goal", "pass", "student", "Student Goal"))
    student = asyncio.run(store.create_student(user_id=u_s["id"]))

    # Study Goals
    now = time.time()
    goal = asyncio.run(
        store.create_study_goal(
            student_id=student["id"],
            title="Study 60 minutes daily",
            goal_type="daily_minutes",
            target_value=60.0,
            start_date=now,
            end_date=now + 86400 * 7,
            reward_xp=100,
        )
    )
    assert goal["target_value"] == 60.0

    # Update goal progress
    upd = asyncio.run(store.update_study_goal(goal["id"], current_value=30.0))
    assert upd is True
    goals = asyncio.run(store.get_study_goals(student["id"], active_only=True))
    assert len(goals) == 1
    assert goals[0]["current_value"] == 30.0

    # Settings
    set_ok = asyncio.run(store.set_db_setting("theme", "liquid_glass", "ui"))
    assert set_ok is True
    val = asyncio.run(store.get_db_setting("theme"))
    assert val == "liquid_glass"

    # Audit log
    log_id = asyncio.run(
        store.record_audit_log(
            action="PARENT_LOGIN",
            actor_id="parent_01",
            actor_role="parent",
            ip_address="127.0.0.1",
            resource_type="dashboard",
            details={"browser": "chrome"},
        )
    )
    assert log_id > 0
    logs = asyncio.run(store.list_audit_logs(actor_id="parent_01"))
    assert len(logs) == 1
    assert logs[0]["action"] == "PARENT_LOGIN"
    assert logs[0]["details"]["browser"] == "chrome"
