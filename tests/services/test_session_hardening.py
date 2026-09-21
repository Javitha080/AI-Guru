"""Hardening regression tests for the session-close → report → parent chain.

Covers the null/fake report class of bugs:
- terminal state immutability (completed/abandoned reject further moves)
- stop idempotency (no double XP on retry)
- start preserves start_time (wall-clock ceiling intact)
- score/telemetry validation (no fake 999% / negative durations)
- honest reports (unmeasured = None/0 + empty summary, never fake 100)
- stale sweep (leaked in_progress rows auto-abandon)
- router input validation (422s) and 409 conflict mapping

Async tests run under pytest-asyncio (one loop per test, mirroring the
single long-lived production loop) instead of per-call ``asyncio.run`` —
loop churn plus the telemetry module's process-global batch/flusher made
combined runs flaky.
"""

from __future__ import annotations

import asyncio
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
def tmpdb(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "chat_history.db"
    conn = sqlite3.connect(db_path)
    apply_migrations(conn)
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
        "deeptutor.services.study.report_generator.get_path_service",
        lambda: _FakePathService(),
    )
    monkeypatch.setattr(
        "deeptutor.services.monitoring.notification_queue._db_path", lambda: db_path
    )
    monkeypatch.setattr(
        "deeptutor.services.gamification.gamification_service._db_path", lambda: db_path
    )
    # Hermetic telemetry: the batch queue + flusher task are process-global.
    # Drain leftovers so one test's queued events can never spill (FK cascade)
    # into the next test's DB.
    from deeptutor.services.study import telemetry_logger as _tel

    _tel._batch.clear()
    _tel._flush_task = None
    yield db_path
    _tel._batch.clear()
    _tel._flush_task = None


@pytest.fixture()
def http(tmpdb):
    app = FastAPI()
    app.include_router(study_session.router, prefix="/api/v1/study-session")
    return TestClient(app)


def _mgr():
    from deeptutor.services.study.session_manager import StudySessionManager

    return StudySessionManager()


# --- state machine --------------------------------------------------------


@pytest.mark.asyncio
async def test_terminal_sessions_are_immutable(tmpdb):
    from deeptutor.services.study.session_manager import SessionStateError

    m = _mgr()
    s = await m.create_session("stu-1", "T", "Math", 900)
    sid = s["id"]
    await m.stop_session(sid)
    for op in (m.pause_session, m.resume_session, m.start_session, m.abandon_session):
        with pytest.raises(SessionStateError):
            await op(sid)

    s2 = await m.create_session("stu-1", "T2", "Math", 900)
    await m.abandon_session(s2["id"])
    with pytest.raises(SessionStateError):
        await m.stop_session(s2["id"])
    # abandon is idempotent
    assert (await m.abandon_session(s2["id"]))["status"] == "abandoned"


@pytest.mark.asyncio
async def test_stop_is_idempotent_no_double_bank(tmpdb):
    m = _mgr()
    s = await m.create_session("stu-1", "T", "Math", 900)
    first = await m.stop_session(s["id"])
    second = await m.stop_session(s["id"])
    assert first["status"] == "completed"
    assert second["status"] == "completed"
    assert second["actual_duration_seconds"] == first["actual_duration_seconds"]


@pytest.mark.asyncio
async def test_start_preserves_start_time(tmpdb):
    m = _mgr()
    s = await m.create_session("stu-1", "T", "Math", 900)
    original_start = float(s["start_time"])
    await asyncio.sleep(0.05)
    restarted = await m.start_session(s["id"])
    assert float(restarted["start_time"]) == pytest.approx(original_start, abs=0.001)


@pytest.mark.asyncio
async def test_pause_resume_idempotent(tmpdb):
    m = _mgr()
    s = await m.create_session("stu-1", "T", "Math", 900)
    await m.pause_session(s["id"])
    again = await m.pause_session(s["id"])
    assert again["status"] == "paused"
    await m.resume_session(s["id"])
    again2 = await m.resume_session(s["id"])
    assert again2["status"] == "in_progress"


# --- validation -----------------------------------------------------------


@pytest.mark.asyncio
async def test_update_scores_rejects_garbage(tmpdb):
    m = _mgr()
    s = await m.create_session("stu-1", "T", "Math", 900)
    with pytest.raises(ValueError):
        await m.update_scores(s["id"], 999.0, 50.0, 0, 0)
    with pytest.raises(ValueError):
        await m.update_scores(s["id"], 50.0, -5.0, 0, 0)
    with pytest.raises(ValueError):
        await m.update_scores(s["id"], 50.0, 50.0, -1, 0)
    # valid write works
    await m.update_scores(s["id"], 80.0, 70.0, 2, 1)
    row = await m.get_session(s["id"])
    assert row["focus_score"] == 80.0


@pytest.mark.asyncio
async def test_telemetry_rejects_garbage_accepts_good(tmpdb):
    from deeptutor.services.study.telemetry_logger import TelemetryLogger

    tel = TelemetryLogger()
    good_meta = {"message": "ok"}
    assert await tel.log_event("sess-1", "WARNING_ISSUED", "warning", 0.9, 5.0, good_meta) is True
    assert (
        await tel.log_event("sess-1", "WARNING_ISSUED", "warning", 1.5, 5.0, good_meta)
        is False
    )
    assert (
        await tel.log_event("sess-1", "WARNING_ISSUED", "warning", 0.9, -3.0, good_meta)
        is False
    )
    assert (
        await tel.log_event("sess-1", "BOGUS_TYPE", "warning", 0.9, 5.0, good_meta) is False
    )
    assert (
        await tel.log_event("sess-1", "WARNING_ISSUED", "critical", 0.9, 5.0, good_meta)
        is False
    )
    assert (
        await tel.log_event("bad id!!", "WARNING_ISSUED", "warning", 0.9, 5.0, good_meta)
        is False
    )
    assert (
        await tel.log_event("sess-1", "WARNING_ISSUED", "warning", 0.9, 5.0, {"m": "x" * 9000})
        is False
    )


# --- honest reports -------------------------------------------------------


@pytest.mark.asyncio
async def test_instant_stop_report_is_honest_not_fake(tmpdb):
    m = _mgr()
    s = await m.create_session("stu-1", "T", "Math", 900)
    await m.stop_session(s["id"])
    report = await m.get_session_report(s["id"])
    assert report["metrics"]["focus_score"] is None
    assert report["metrics"]["engagement_score"] is None
    assert report["summary"] == ""
    assert report["report_ready"] is False


@pytest.mark.asyncio
async def test_measured_session_keeps_real_score(tmpdb):
    m = _mgr()
    s = await m.create_session("stu-1", "T", "Math", 900)
    await m.update_scores(s["id"], 82.5, 77.0, 2, 1)
    await m.stop_session(s["id"])
    report = await m.get_session_report(s["id"])
    assert report["metrics"]["focus_score"] == 82.5
    assert report["metrics"]["engagement_score"] == 77.0


@pytest.mark.asyncio
async def test_report_generator_never_synthesizes_100(tmpdb):
    from deeptutor.services.study.report_generator import ReportGenerator

    m = _mgr()
    s = await m.create_session("stu-1", "T", "Math", 900)
    await m.stop_session(s["id"])
    stored = await ReportGenerator().generate_report(s["id"], "stu-1")
    assert float(stored["focus_score"]) == 0.0
    assert "could not be measured" in stored["ai_tutor_feedback"]


@pytest.mark.asyncio
async def test_double_completion_awards_xp_once(tmpdb):
    from deeptutor.services.monitoring.dispatch import handle_session_completed

    m = _mgr()
    s = await m.create_session("stu-1", "T", "Math", 900)
    await m.update_scores(s["id"], 80.0, 75.0, 1, 1)
    await m.stop_session(s["id"])
    await handle_session_completed(s["id"], "stu-1")
    await handle_session_completed(s["id"], "stu-1")

    conn = sqlite3.connect(tmpdb)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM rewards WHERE session_id = ? AND reward_type = 'xp'",
            (s["id"],),
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 1


@pytest.mark.asyncio
async def test_unmeasured_session_earns_floor_not_fake_bonus(tmpdb):
    from deeptutor.services.monitoring.dispatch import _award_session_xp

    m = _mgr()
    s = await m.create_session("stu-floor", "T", "Math", 900)
    xp = await _award_session_xp(s["id"], "stu-floor", 0.0, 0.0)
    assert xp == 5  # honest floor, not the old ~80 from fake focus 100


@pytest.mark.asyncio
async def test_abandoned_session_earns_nothing(tmpdb):
    from deeptutor.services.monitoring.dispatch import handle_session_completed

    m = _mgr()
    s = await m.create_session("stu-1", "T", "Math", 900)
    await m.abandon_session(s["id"])
    await handle_session_completed(s["id"], "stu-1")

    conn = sqlite3.connect(tmpdb)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM rewards WHERE session_id = ?", (s["id"],)
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 0


# --- stale sweep ----------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_open_session_swept_to_abandoned(tmpdb):
    m = _mgr()
    s = await m.create_session("stu-1", "T", "Math", 900)
    old = time.time() - 3 * 3600
    conn = sqlite3.connect(tmpdb)
    try:
        conn.execute(
            "UPDATE study_sessions SET start_time = ?, last_resume_time = ?, created_at = ? WHERE id = ?",
            (old, old, old, s["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    swept = await m.sweep_stale_sessions()
    assert swept >= 1
    row = await m.get_session(s["id"])
    assert row["status"] == "abandoned"


@pytest.mark.asyncio
async def test_fresh_session_survives_sweep(tmpdb):
    m = _mgr()
    s = await m.create_session("stu-1", "T", "Math", 900)
    assert await m.sweep_stale_sessions() == 0
    assert (await m.get_session(s["id"]))["status"] == "in_progress"


# --- monitoring flag + retarget ------------------------------------------------


@pytest.mark.asyncio
async def test_create_session_monitoring_flag(tmpdb):
    m = _mgr()
    defaulted = await m.create_session("stu-1", "T", "Math", 900)
    assert defaulted.get("monitoring_enabled", 1) == 1
    offline = await m.create_session(
        "stu-1", "T-off", "Math", 900, monitoring_enabled=False
    )
    assert offline["monitoring_enabled"] == 0


@pytest.mark.asyncio
async def test_retarget_updates_open_session_target(tmpdb):
    m = _mgr()
    s = await m.create_session("stu-1", "T", "Math", 900)
    updated = await m.retarget_session(s["id"], 3600)
    assert updated["target_duration_seconds"] == 3600
    # banked work is untouched by a retarget
    assert float(updated.get("worked_seconds") or 0.0) >= 0.0


@pytest.mark.asyncio
async def test_retarget_rejects_garbage_and_terminal(tmpdb):
    from deeptutor.services.study.session_manager import SessionStateError

    m = _mgr()
    s = await m.create_session("stu-1", "T", "Math", 900)
    for bad in (0, -5, 59, 8 * 3600 + 1, True, None):
        with pytest.raises(ValueError):
            await m.retarget_session(s["id"], bad)  # type: ignore[arg-type]
    # target unchanged after rejected writes
    assert (await m.get_session(s["id"]))["target_duration_seconds"] == 900
    await m.stop_session(s["id"])
    with pytest.raises(SessionStateError):
        await m.retarget_session(s["id"], 1800)
    s2 = await m.create_session("stu-1", "T2", "Math", 900)
    await m.abandon_session(s2["id"])
    with pytest.raises(SessionStateError):
        await m.retarget_session(s2["id"], 1800)
    with pytest.raises(KeyError):
        await m.retarget_session("no-such-session", 1800)


def test_router_retarget_validation_and_conflicts(http):
    sid = http.post("/api/v1/study-session", json={"title": "T"}).json()["id"]
    ok = http.patch(
        f"/api/v1/study-session/{sid}/target",
        json={"target_duration_seconds": 3600},
    )
    assert ok.status_code == 200
    assert ok.json()["target_duration_seconds"] == 3600
    assert (
        http.patch(
            f"/api/v1/study-session/{sid}/target",
            json={"target_duration_seconds": 10},
        ).status_code
        == 422
    )
    assert (
        http.patch(
            f"/api/v1/study-session/{sid}/target",
            json={},
        ).status_code
        == 422
    )
    assert (
        http.patch(
            "/api/v1/study-session/no-such-session/target",
            json={"target_duration_seconds": 1800},
        ).status_code
        == 404
    )
    assert http.post(f"/api/v1/study-session/{sid}/stop").status_code == 200
    assert (
        http.patch(
            f"/api/v1/study-session/{sid}/target",
            json={"target_duration_seconds": 1800},
        ).status_code
        == 409
    )


def test_router_create_persists_monitoring_flag(http):
    sid = http.post(
        "/api/v1/study-session",
        json={"title": "T-off", "monitoring_enabled": False},
    ).json()["id"]
    row = http.get(f"/api/v1/study-session/{sid}").json()
    assert row["monitoring_enabled"] == 0


# --- router-level (sync TestClient; no loop churn) ------------------------


def test_router_rejects_bad_create_payloads(http):
    assert http.post("/api/v1/study-session", json={"title": ""}).status_code == 422
    assert (
        http.post(
            "/api/v1/study-session", json={"title": "T", "target_duration_seconds": -5}
        ).status_code
        == 422
    )
    assert (
        http.post(
            "/api/v1/study-session", json={"title": "T", "duration": 9999}
        ).status_code
        == 422
    )
    assert (
        http.post(
            "/api/v1/study-session", json={"title": "T", "student_id": "bad id!!"}
        ).status_code
        == 422
    )


def test_router_rejects_bad_session_id_format(http):
    assert http.get("/api/v1/study-session/bad%20id!!").status_code in (404, 422)
    assert http.post("/api/v1/study-session/bad%20id!!/stop").status_code in (404, 422)


def test_router_terminal_transition_is_409(http):
    sid = http.post("/api/v1/study-session", json={"title": "T"}).json()["id"]
    assert http.post(f"/api/v1/study-session/{sid}/stop").status_code == 200
    assert http.post(f"/api/v1/study-session/{sid}/resume").status_code == 409
    assert http.post(f"/api/v1/study-session/{sid}/pause").status_code == 409
    assert http.post(f"/api/v1/study-session/{sid}/abandon").status_code == 409
    # idempotent re-stop stays 200
    assert http.post(f"/api/v1/study-session/{sid}/stop").status_code == 200

    sid2 = http.post("/api/v1/study-session", json={"title": "T2"}).json()["id"]
    assert http.post(f"/api/v1/study-session/{sid2}/abandon").status_code == 200
    assert http.post(f"/api/v1/study-session/{sid2}/stop").status_code == 409
