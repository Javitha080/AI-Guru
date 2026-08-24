"""HTTP-level regression tests for the study-session router.

Covers the class of bugs where lifecycle endpoints returned ``None`` against a
``Dict[str,Any]`` response model (guaranteed 500), returned fabricated demo
data on failure, or exposed a list where the response model demanded a
pagination envelope. Also proves the pause-aware duration accounting
(migration 003 columns).
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
import time

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import study_session
from deeptutor.services.database.migrations import apply_migrations


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    """Router over an isolated, fully-migrated temp database."""
    db_path = tmp_path / "chat_history.db"
    conn = sqlite3.connect(db_path)
    apply_migrations(conn)  # includes migration 003 (pause-aware columns)
    conn.close()

    class _FakePathService:
        user_dir = tmp_path

    monkeypatch.setattr(
        "deeptutor.services.study.session_manager.get_path_service",
        lambda: _FakePathService(),
    )
    monkeypatch.setattr(
        "deeptutor.services.study.telemetry_logger.get_path_service",
        lambda: _FakePathService(),
    )
    monkeypatch.setattr(
        "deeptutor.services.monitoring.notification_queue._db_path", lambda: db_path
    )
    monkeypatch.setattr(
        "deeptutor.services.gamification.gamification_service._db_path", lambda: db_path
    )

    app = FastAPI()
    app.include_router(study_session.router, prefix="/api/v1/study-session")
    return TestClient(app), db_path


def _raw(db_path: Path, sql: str, params: tuple = ()):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def test_lifecycle_endpoints_return_real_dicts(client):
    http, _db = client

    created = http.post(
        "/api/v1/study-session",
        json={"student_id": "student-primary", "title": "Math", "subject": "Algebra"},
    )
    assert created.status_code == 200
    body = created.json()
    assert isinstance(body, dict) and body["id"] and body["status"] == "in_progress"
    sid = body["id"]

    for action, expected_status in (
        ("start", "in_progress"),
        ("pause", "paused"),
        ("resume", "in_progress"),
    ):
        res = http.post(f"/api/v1/study-session/{sid}/{action}")
        assert res.status_code == 200, f"{action} must not 500"
        payload = res.json()
        assert isinstance(payload, dict)
        assert payload["status"] == expected_status

    stopped = http.post(f"/api/v1/study-session/{sid}/stop")
    assert stopped.status_code == 200
    final = stopped.json()
    assert final["status"] == "completed"
    assert isinstance(final["actual_duration_seconds"], int)


def test_history_returns_pagination_envelope(client):
    http, _db = client
    http.post("/api/v1/study-session", json={"student_id": "hist-student"})

    res = http.get("/api/v1/study-session/history/hist-student")
    assert res.status_code == 200
    page = res.json()
    assert set(page.keys()) >= {"items", "total", "limit", "offset"}
    assert page["total"] >= 1 and len(page["items"]) >= 1


def test_unknown_session_is_404_not_fabricated_data(client):
    http, _db = client
    assert http.get("/api/v1/study-session/nope").status_code == 404
    assert http.post("/api/v1/study-session/nope/stop").status_code == 404
    assert http.post("/api/v1/study-session/nope/pause").status_code == 404
    assert http.get("/api/v1/study-session/nope/report").status_code == 404


def test_pause_time_is_excluded_from_duration(client):
    http, db = client
    sid = http.post("/api/v1/study-session", json={}).json()["id"]

    # Simulate: session created 1000 s ago, active stretch opened 100 s ago,
    # 50 s of prior validated work banked. Wall clock says ~1000 s of study;
    # only ~150 s was actually spent unpaused.
    now = time.time()
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "UPDATE study_sessions SET start_time = ?, last_resume_time = ?, worked_seconds = 50",
            (now - 1000, now - 100),
        )
        conn.commit()
    finally:
        conn.close()

    assert http.post(f"/api/v1/study-session/{sid}/pause").status_code == 200
    row = _raw(db, "SELECT worked_seconds, status FROM study_sessions WHERE id = ?", (sid,))
    assert row[1] == "paused"
    # Banked: prior 50 s + this stretch (~100 s), NOT the full wall clock.
    assert 140 <= float(row[0]) <= 165

    assert http.post(f"/api/v1/study-session/{sid}/resume").status_code == 200
    stopped = http.post(f"/api/v1/study-session/{sid}/stop").json()
    # Old wall-clock math would have reported ~1000 s here.
    assert 140 <= stopped["actual_duration_seconds"] <= 170


def test_report_shape_after_stop(client):
    http, _db = client
    sid = http.post("/api/v1/study-session", json={"subject": "Physics"}).json()["id"]
    http.post(f"/api/v1/study-session/{sid}/stop")

    report = http.get(f"/api/v1/study-session/{sid}/report")
    assert report.status_code == 200
    data = report.json()
    assert data["session_id"] == sid
    assert isinstance(data["metrics"], dict)
    assert data["xp_earned"] is None or isinstance(data["xp_earned"], int)
