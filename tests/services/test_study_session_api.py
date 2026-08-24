"""HTTP-level lifecycle tests for /api/v1/study-session (Study Room backend).

Guards the fixes that made Study Room real:

* FK auto-provisioning — creating a session for ``student-primary`` on a fresh
  DB must succeed (users+students seeded), never return a fabricated id.
* No mock fallbacks — unknown sessions return 404, not canned payloads like
  ``{"summary": "Good job!", "xp_earned": 50}``.
* Response-shape integrity — start/pause/resume/stop return session dicts,
  history is paginated, report exposes real metrics + XP from ``rewards``.
* Stop awaits completion side-effects so the immediate report already carries
  stored feedback and awarded XP.

Runs against an isolated workspace DB with production migrations applied;
never touches real user data.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture()
def workspace(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="aiguru_ssapi_"))
    from deeptutor.services import path_service as ps

    svc = ps.PathService(workspace_root=tmp)
    monkeypatch.setattr(ps.PathService, "_instance", svc, raising=False)

    db = svc.user_dir / "chat_history.db"
    db.parent.mkdir(parents=True, exist_ok=True)

    import sqlite3

    from deeptutor.services.database.migrations import apply_migrations, enable_pragmas

    conn = sqlite3.connect(db)
    enable_pragmas(conn)
    applied = apply_migrations(conn)
    conn.commit()
    conn.close()
    assert 2 in applied

    yield tmp


@pytest.fixture()
def client(workspace):
    # Minimal app: just the study-session router (auth is disabled by default
    # in local mode, so require_auth passes through without a token).
    from deeptutor.api.routers import study_session

    app = FastAPI()
    app.include_router(study_session.router, prefix="/api/v1/study-session")
    with TestClient(app) as c:
        yield c


def _create(client: TestClient, **overrides) -> dict:
    payload = {
        "student_id": "student-primary",
        "title": "Algebra Focus",
        "subject": "Math",
        "target_duration_seconds": 900,
    }
    payload.update(overrides)
    res = client.post("/api/v1/study-session", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def test_create_auto_provisions_student_fk(workspace, client):
    """Fresh DB + no registered student: create must really insert the row."""
    data = _create(client)
    assert data["id"] and isinstance(data["id"], str)
    assert data["status"] == "in_progress"

    import sqlite3

    conn = sqlite3.connect(workspace / "user" / "chat_history.db")
    try:
        students = conn.execute(
            "SELECT COUNT(*) FROM students WHERE id = 'student-primary'"
        ).fetchone()[0]
        sessions = conn.execute(
            "SELECT COUNT(*) FROM study_sessions WHERE id = ?", (data["id"],)
        ).fetchone()[0]
    finally:
        conn.close()
    assert students == 1
    assert sessions == 1


def test_full_lifecycle_returns_real_dicts(workspace, client):
    sid = _create(client)["id"]

    started = client.post(f"/api/v1/study-session/{sid}/start")
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "in_progress"

    paused = client.post(f"/api/v1/study-session/{sid}/pause")
    assert paused.status_code == 200 and paused.json()["status"] == "paused"

    resumed = client.post(f"/api/v1/study-session/{sid}/resume")
    assert resumed.status_code == 200 and resumed.json()["status"] == "in_progress"

    stopped = client.post(f"/api/v1/study-session/{sid}/stop")
    assert stopped.status_code == 200, stopped.text
    body = stopped.json()
    assert body["status"] == "completed"
    assert isinstance(body["actual_duration_seconds"], int)

    got = client.get(f"/api/v1/study-session/{sid}")
    assert got.status_code == 200 and got.json()["id"] == sid


def test_report_shape_is_real_not_canned(workspace, client):
    sid = _create(client)["id"]
    client.post(f"/api/v1/study-session/{sid}/stop")

    res = client.get(f"/api/v1/study-session/{sid}/report")
    assert res.status_code == 200, res.text
    r = res.json()

    # The old router faked {"summary": "Good job!", "xp_earned": 50}.
    assert r["summary"] != "Good job!"
    assert isinstance(r["xp_earned"], int) and r["xp_earned"] >= 0
    metrics = r["metrics"]
    for key in (
        "focus_score",
        "engagement_score",
        "distraction_count",
        "warning_count",
        "actual_duration_seconds",
    ):
        assert key in metrics


def test_stop_awards_xp_before_returning(workspace, client):
    """Stop awaits handle_session_completed: XP row exists immediately after."""
    sid = _create(client)["id"]
    res = client.post(f"/api/v1/study-session/{sid}/stop")
    assert res.status_code == 200

    import sqlite3

    conn = sqlite3.connect(workspace / "user" / "chat_history.db")
    try:
        rows = conn.execute(
            "SELECT COALESCE(SUM(amount_xp), 0) FROM rewards"
            " WHERE session_id = ? AND reward_type = 'xp'",
            (sid,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert rows > 0

    report = client.get(f"/api/v1/study-session/{sid}/report").json()
    assert report["xp_earned"] == rows


def test_history_paginated_shape(workspace, client):
    _create(client)
    res = client.get("/api/v1/study-session/history/student-primary")
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body.keys()) == {"items", "total", "limit", "offset"}
    assert body["total"] >= 1 and len(body["items"]) >= 1


def test_unknown_session_404_never_fabricated(workspace, client):
    assert client.get("/api/v1/study-session/does-not-exist").status_code == 404
    assert client.post("/api/v1/study-session/does-not-exist/start").status_code == 404
    assert client.post("/api/v1/study-session/does-not-exist/pause").status_code == 404
    assert client.post("/api/v1/study-session/does-not-exist/stop").status_code == 404
    rep = client.get("/api/v1/study-session/does-not-exist/report")
    assert rep.status_code == 404
    assert "not found" in rep.json()["detail"].lower()


def test_gamification_endpoints_reflect_real_data(workspace, client):
    import asyncio

    from deeptutor.services.gamification.gamification_service import GamificationService

    asyncio.run(GamificationService.award_xp("student-primary", 120, "test:award"))

    prof = client.get("/api/v1/study-session/gamification/student-primary/profile")
    assert prof.status_code == 200
    p = prof.json()
    assert p["xp"] == 120  # not the old fake {"xp": 100, "streak": 3}
    assert p["level"] == 1

    badges = client.get("/api/v1/study-session/gamification/student-primary/badges")
    assert badges.status_code == 200
    assert all(set(b) >= {"id", "name", "earned"} for b in badges.json())

    rewards = client.get("/api/v1/study-session/gamification/student-primary/rewards")
    assert rewards.status_code == 200
    items = rewards.json()["items"]
    assert any(i["amount_xp"] == 120 for i in items)
