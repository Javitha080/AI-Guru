"""Comprehensive test suite for AI Guru XP system, Student Name setup, and Preflight checks."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3
import tempfile
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture()
def workspace(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="aiguru_test_xp_setup_"))
    from deeptutor.services import path_service as ps

    svc = ps.PathService(workspace_root=tmp)
    monkeypatch.setattr(ps.PathService, "_instance", svc, raising=False)

    db = svc.user_dir / "chat_history.db"
    db.parent.mkdir(parents=True, exist_ok=True)

    from deeptutor.services.database.migrations import apply_migrations, enable_pragmas

    conn = sqlite3.connect(db)
    enable_pragmas(conn)
    applied = apply_migrations(conn)
    conn.commit()
    conn.close()
    assert 1 in applied

    yield tmp


@pytest.fixture()
def client(workspace):
    from deeptutor.api.routers import study_session

    app = FastAPI()
    app.include_router(study_session.router, prefix="/api/v1/study-session")
    with TestClient(app) as c:
        yield c


# ===========================================================================
# 1. XP System & Gamification Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_xp_award_and_profile_progression(workspace):
    """Test XP accumulation, level progression, and level title thresholds."""
    from deeptutor.services.gamification.gamification_service import GamificationService

    student_id = "student-test-xp"

    # Initial profile on empty DB
    prof0 = await GamificationService.get_profile(student_id)
    assert prof0["xp"] == 0
    assert prof0["level"] == 1
    assert prof0["level_title"] == "Novice"

    # Reject zero and negative XP
    assert await GamificationService.award_xp(student_id, 0, "zero") is False
    assert await GamificationService.award_xp(student_id, -50, "negative") is False

    # Award 120 XP -> Level 1 (0-499)
    assert await GamificationService.award_xp(student_id, 120, "study_session:1") is True
    prof1 = await GamificationService.get_profile(student_id)
    assert prof1["xp"] == 120
    assert prof1["level"] == 1
    assert prof1["level_title"] == "Novice"

    # Award 400 XP -> Total 520 XP -> Level 2 (Apprentice)
    assert await GamificationService.award_xp(student_id, 400, "study_session:2") is True
    prof2 = await GamificationService.get_profile(student_id)
    assert prof2["xp"] == 520
    assert prof2["level"] == 2
    assert prof2["level_title"] == "Apprentice"

    # Award 1000 XP -> Total 1520 XP -> Level 4 (Scholar)
    assert await GamificationService.award_xp(student_id, 1000, "exam:1") is True
    prof3 = await GamificationService.get_profile(student_id)
    assert prof3["xp"] == 1520
    assert prof3["level"] == 4
    assert prof3["level_title"] == "Scholar"

    # Award 3000 XP -> Total 4520 XP -> Level 10 (Sage)
    assert await GamificationService.award_xp(student_id, 3000, "milestone:big") is True
    prof4 = await GamificationService.get_profile(student_id)
    assert prof4["xp"] == 4520
    assert prof4["level"] == 10
    assert prof4["level_title"] == "Sage"


@pytest.mark.asyncio
async def test_badge_evaluation_and_idempotency(workspace):
    """Test milestone badge checks and verify awards are idempotent."""
    from deeptutor.services.gamification.gamification_service import GamificationService

    student_id = "student-badge-test"

    # Initially no badges earned
    badges_pre = await GamificationService.get_badges(student_id)
    assert all(not b["earned"] for b in badges_pre)

    # Award 150 XP
    await GamificationService.award_xp(student_id, 150, "test:award")

    # Evaluate badges -> xp_100 should be earned
    newly = await GamificationService.check_and_award(student_id)
    assert "xp_100" in newly

    # Second check must be idempotent and return no new badges
    newly_repeat = await GamificationService.check_and_award(student_id)
    assert newly_repeat == []

    # Verify badge state in get_badges
    badges_post = await GamificationService.get_badges(student_id)
    xp_100_badge = next((b for b in badges_post if b["id"] == "xp_100"), None)
    assert xp_100_badge is not None
    assert xp_100_badge["earned"] is True
    assert xp_100_badge["earned_at"] is not None


@pytest.mark.asyncio
async def test_rewards_history_endpoint(workspace, client):
    """Test reward history items returned via API."""
    from deeptutor.services.gamification.gamification_service import GamificationService

    student_id = "student-primary"
    await GamificationService.award_xp(student_id, 75, "history:session:1")
    await GamificationService.award_xp(student_id, 150, "history:exam:1")

    res = client.get(f"/api/v1/study-session/gamification/{student_id}/rewards")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) >= 2
    reasons = [i["reason"] for i in items]
    assert "history:session:1" in reasons
    assert "history:exam:1" in reasons


# ===========================================================================
# 2. Student Name Setup & Resolution Tests
# ===========================================================================

def test_get_and_set_student_name_api(workspace, client):
    """Test GET and POST /api/v1/study-session/student/name endpoints."""
    # 1. Default name on fresh DB
    res_get = client.get("/api/v1/study-session/student/name")
    assert res_get.status_code == 200
    assert res_get.json()["student_name"] in ("Primary", "Student")

    # 2. Set new student name Elena
    res_set = client.post(
        "/api/v1/study-session/student/name",
        json={"student_name": "Elena", "student_id": "student-primary"},
    )
    assert res_set.status_code == 200
    assert res_set.json()["student_name"] == "Elena"

    # 3. Verify subsequent GET returns Elena
    res_get2 = client.get("/api/v1/study-session/student/name")
    assert res_get2.status_code == 200
    assert res_get2.json()["student_name"] == "Elena"

    # 4. Verify SQLite database directly
    db_file = workspace / "user" / "chat_history.db"
    con = sqlite3.connect(db_file)
    try:
        # Settings table verification
        row = con.execute(
            "SELECT value FROM settings WHERE key = 'supervision_rules_default'"
        ).fetchone()
        assert row is not None
        assert '"student_name": "Elena"' in row[0]

        # Users table verification
        user_row = con.execute(
            "SELECT display_name FROM users WHERE id = 'user-student-primary'"
        ).fetchone()
        assert user_row is not None
        assert user_row[0] == "Elena"
    finally:
        con.close()


@pytest.mark.asyncio
async def test_resolve_student_name_integration(workspace):
    """Verify _resolve_student_name helper reads configured student name."""
    from deeptutor.api.routers.study_session import _resolve_student_name, set_student_name, StudentNameRequest

    # Set name to Marcus
    await set_student_name(StudentNameRequest(student_name="Marcus", student_id="student-primary"))

    # Resolve name
    resolved = await _resolve_student_name("student-primary")
    assert resolved == "Marcus"


# ===========================================================================
# 3. Preflight & Setup Subsystems Tests
# ===========================================================================

def test_hardware_profiler_preflight():
    """Verify hardware profiler returns valid system capabilities."""
    from deeptutor.services.llm.hardware_profiler import get_hardware_profile

    profile = get_hardware_profile()
    assert profile.tier.value in ("LOW", "MEDIUM", "HIGH")
    assert profile.system_ram_gb > 0
    assert profile.cpu_cores_physical > 0
    assert len(profile.recommended_models) > 0


def test_migrations_fresh_install_tables(workspace):
    """Verify database migrations create all required tables."""
    from deeptutor.services.database.migrations import verify_tables_exist

    db_file = workspace / "user" / "chat_history.db"
    con = sqlite3.connect(db_file)
    try:
        table_status = verify_tables_exist(con)
        for table, exists in table_status.items():
            assert exists is True, f"Table {table} missing from fresh database"
    finally:
        con.close()
