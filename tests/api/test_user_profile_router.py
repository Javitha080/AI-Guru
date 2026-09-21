"""Tests for user_profile API router.

Validates profile reading, updating, allow-list validation, dual-shape settings,
FK provisioning, and status check for onboarding.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import user_profile
from deeptutor.services.database.migrations import apply_migrations


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    """Router over an isolated, fully-migrated temp database."""
    db_path = tmp_path / "chat_history.db"
    conn = sqlite3.connect(db_path)
    apply_migrations(conn)
    conn.close()

    class _FakePathService:
        user_dir = tmp_path

    monkeypatch.setattr(
        "deeptutor.api.routers.user_profile.get_path_service",
        lambda: _FakePathService(),
    )
    monkeypatch.setattr(
        "deeptutor.services.gamification.gamification_service.get_path_service",
        lambda: _FakePathService(),
    )

    app = FastAPI()
    app.include_router(user_profile.router, prefix="/api/v1/user/profile")
    return TestClient(app), db_path


def test_get_profile_unconfigured(client):
    test_client, _ = client
    res = test_client.get("/api/v1/user/profile")
    assert res.status_code == 200
    data = res.json()
    assert data["student_id"] == "student-primary"
    assert data["is_configured"] is False
    assert data["grade_level"] == ""
    assert data["learning_style"] == "visual"
    assert data["target_daily_minutes"] == 60
    assert data["preferred_subjects"] == []
    assert data["tutor_tone"] == "encouraging"


def test_get_status_unconfigured(client):
    test_client, _ = client
    res = test_client.get("/api/v1/user/profile/status")
    assert res.status_code == 200
    data = res.json()
    assert data["is_configured"] is False
    assert data["display_name"] == ""


def test_update_profile_success(client):
    test_client, db_path = client
    payload = {
        "display_name": "Alex Morgan",
        "avatar": "icon:sparkles:amber",
        "grade_level": "Grade 12 (A/L)",
        "learning_style": "step_by_step",
        "target_daily_minutes": 90,
        "school": "Royal College",
        "preferred_subjects": ["Mathematics", "Physics", "ICT"],
        "tutor_tone": "rigorous",
    }
    res = test_client.post("/api/v1/user/profile", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["display_name"] == "Alex Morgan"
    assert data["avatar"] == "icon:sparkles:amber"
    assert data["grade_level"] == "Grade 12 (A/L)"
    assert data["learning_style"] == "step_by_step"
    assert data["target_daily_minutes"] == 90
    assert data["school"] == "Royal College"
    assert data["preferred_subjects"] == ["Mathematics", "Physics", "ICT"]
    assert data["tutor_tone"] == "rigorous"
    assert data["is_configured"] is True

    # Verify status reflects configured
    status_res = test_client.get("/api/v1/user/profile/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["is_configured"] is True
    assert status_data["display_name"] == "Alex Morgan"
    assert status_data["avatar"] == "icon:sparkles:amber"

    # Verify raw SQLite database
    conn = sqlite3.connect(db_path)
    user_row = conn.execute(
        "SELECT display_name, avatar_url FROM users WHERE id = 'user-student-primary'"
    ).fetchone()
    assert user_row == ("Alex Morgan", "icon:sparkles:amber")

    student_row = conn.execute(
        "SELECT grade_level, learning_style, target_daily_minutes FROM students WHERE id = 'student-primary'"
    ).fetchone()
    assert student_row == ("Grade 12 (A/L)", "step_by_step", 90)

    # Verify settings table kv pairs
    configured_row = conn.execute(
        "SELECT value FROM settings WHERE key = 'user_profile_configured'"
    ).fetchone()
    assert configured_row[0] == "true"

    pers_row = conn.execute(
        "SELECT value FROM settings WHERE key = 'student_personalizations_default'"
    ).fetchone()
    pers = json.loads(pers_row[0])
    assert pers["preferred_subjects"] == ["Mathematics", "Physics", "ICT"]
    assert pers["tutor_tone"] == "rigorous"

    # Verify supervision_rules_default sync
    rules_row = conn.execute(
        "SELECT value FROM settings WHERE key = 'supervision_rules_default'"
    ).fetchone()
    rules = json.loads(rules_row[0])
    assert rules["student_name"] == "Alex Morgan"
    assert rules["daily_goal_minutes"] == 90

    conn.close()


def test_avatar_validation_rejects_invalid_names(client):
    test_client, _ = client
    # Invalid icon name
    res = test_client.post("/api/v1/user/profile", json={"avatar": "icon:invalid_icon:amber"})
    assert res.status_code == 422

    # Invalid color name
    res = test_client.post("/api/v1/user/profile", json={"avatar": "icon:sparkles:neon_green"})
    assert res.status_code == 422

    # Valid img marker
    res = test_client.post("/api/v1/user/profile", json={"avatar": "img:2"})
    assert res.status_code == 200
    assert res.json()["avatar"] == "img:2"


def test_target_minutes_validation(client):
    test_client, _ = client
    # Less than 15 mins
    res = test_client.post("/api/v1/user/profile", json={"target_daily_minutes": 5})
    assert res.status_code == 422

    # Greater than 480 mins
    res = test_client.post("/api/v1/user/profile", json={"target_daily_minutes": 600})
    assert res.status_code == 422


def test_avatar_only_patch_does_not_complete_onboarding(client):
    test_client, _ = client
    res = test_client.post("/api/v1/user/profile", json={"avatar": "icon:star:blue"})
    assert res.status_code == 200
    assert res.json()["is_configured"] is False
    status_res = test_client.get("/api/v1/user/profile/status")
    assert status_res.json()["is_configured"] is False


def test_empty_display_name_rejected(client):
    test_client, _ = client
    res = test_client.post("/api/v1/user/profile", json={"display_name": "   "})
    assert res.status_code == 422


def test_invalid_style_and_tone_rejected(client):
    test_client, _ = client
    res = test_client.post("/api/v1/user/profile", json={"learning_style": "analytical"})
    assert res.status_code == 422
    res = test_client.post("/api/v1/user/profile", json={"tutor_tone": "strict"})
    assert res.status_code == 422


def test_status_masks_unset_display_name(client):
    test_client, _ = client
    test_client.post("/api/v1/user/profile", json={"avatar": "icon:star:blue"})
    status_data = test_client.get("/api/v1/user/profile/status").json()
    assert status_data["display_name"] == ""
    assert "student-primary" not in status_data["display_name"]


def test_get_persists_provisioned_rows(client):
    test_client, db_path = client
    res = test_client.get("/api/v1/user/profile")
    assert res.status_code == 200
    conn = sqlite3.connect(db_path)
    try:
        user_row = conn.execute(
            "SELECT id, display_name FROM users WHERE id = 'user-student-primary'"
        ).fetchone()
        assert user_row is not None
        # Fresh rows must not seed the raw student_id as a display name.
        assert user_row[1] == ""
        student_row = conn.execute(
            "SELECT id FROM students WHERE id = 'student-primary'"
        ).fetchone()
        assert student_row is not None
    finally:
        conn.close()
