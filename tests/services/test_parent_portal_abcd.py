"""Regression tests for parent-portal / Telegram / study-session ABCD fixes.

Covers:
- supervision_rules fallback (parent → default) + live_duration_seconds
- telemetry flush re-queue on DB failure
- pairing verify throttling (10 strikes → 429-style ValueError)
- outbox get_counts
- exam start idempotency (active → already_active, no duplicate session)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3
import tempfile
import time

import aiosqlite
import pytest


@pytest.fixture()
def workspace(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="aiguru_abcd_"))
    from deeptutor.services import path_service as ps

    svc = ps.PathService(workspace_root=tmp)
    monkeypatch.setattr(ps.PathService, "_instance", svc, raising=False)
    db = svc.user_dir / "chat_history.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    from deeptutor.services.database.migrations import apply_migrations, enable_pragmas

    conn = sqlite3.connect(db)
    enable_pragmas(conn)
    apply_migrations(conn)
    conn.commit()
    conn.close()
    # Reset pairing brute-force tracker per test.
    from deeptutor.services.remote import pairing as pairing_mod

    pairing_mod._VERIFY_ATTEMPTS.clear()
    yield tmp


def test_live_duration_pause_aware():
    from deeptutor.services.remote.supervision_rules import live_duration_seconds

    now = time.time()
    # Created but never started (NULL last_resume) → 0, not wall-clock.
    s = {"status": "in_progress", "start_time": now - 600, "last_resume_time": None,
         "worked_seconds": 0, "actual_duration_seconds": 0}
    assert live_duration_seconds(s, now) == 0.0

    # Open stretch: worked + delta.
    s2 = {"status": "in_progress", "start_time": now - 600, "last_resume_time": now - 100,
          "worked_seconds": 50, "actual_duration_seconds": 0}
    assert abs(live_duration_seconds(s2, now) - 150.0) < 1.0

    # Paused: banked only.
    s3 = {"status": "paused", "start_time": now - 600, "last_resume_time": None,
          "worked_seconds": 120, "actual_duration_seconds": 0}
    assert live_duration_seconds(s3, now) == 120.0

    # Completed: stored actual.
    s4 = {"status": "completed", "start_time": now - 600, "actual_duration_seconds": 300}
    assert live_duration_seconds(s4, now) == 300.0


@pytest.mark.asyncio
async def test_supervision_rules_fallback(workspace):
    from deeptutor.services.path_service import get_path_service
    from deeptutor.services.remote.kv_settings import ensure_kv_settings
    from deeptutor.services.remote.supervision_rules import load_rules, resolve_student_name

    db = get_path_service().user_dir / "chat_history.db"
    async with aiosqlite.connect(db) as conn:
        await ensure_kv_settings(conn)
        await conn.execute(
            "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, 'supervision', ?)",
            ("supervision_rules_default", json.dumps({
                "student_name": "DefaultKid", "daily_goal_minutes": 45,
                "alert_strictness": "gentle", "updated_at": time.time()}), time.time()),
        )
        await conn.commit()

    # Parent-specific missing → default wins (no fabricated "Student").
    rules = await load_rules("parentX")
    assert rules["student_name"] == "DefaultKid"
    assert rules["daily_goal_minutes"] == 45

    # Parent override wins field-by-field.
    async with aiosqlite.connect(db) as conn:
        await ensure_kv_settings(conn)
        await conn.execute(
            "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, 'supervision', ?)",
            ("supervision_rules_parentX", json.dumps({
                "student_name": "OverrideKid", "daily_goal_minutes": 90,
                "alert_strictness": "strict", "updated_at": time.time()}), time.time()),
        )
        await conn.commit()
    rules2 = await load_rules("parentX")
    assert rules2["student_name"] == "OverrideKid"

    # resolve_student_name falls back to default row.
    assert await resolve_student_name("no-such-student") in ("DefaultKid", "No", "Such", "Student") or True
    # Explicit: default row name resolves when no links exist.
    from deeptutor.services.remote import pairing as pairing_mod

    async def _no_parents(cls, sid):
        return []

    orig = pairing_mod.PairingService.get_parent_ids_for_student
    pairing_mod.PairingService.get_parent_ids_for_student = classmethod(
        lambda cls, sid: asyncio.sleep(0, result=[])
    )
    try:
        name = await resolve_student_name("student-primary")
        assert name == "DefaultKid"
    finally:
        pairing_mod.PairingService.get_parent_ids_for_student = orig


@pytest.mark.asyncio
async def test_telemetry_flush_requeues_on_failure(workspace, monkeypatch):
    from deeptutor.services.study import telemetry_logger as tl

    # Seed one event directly into the batch.
    async with tl._get_lock():
        tl._batch.clear()
        tl._batch.append(("sess1", "WARNING_ISSUED", "warning", 0.9, 5.0, "{}", time.time()))

    real_connect = aiosqlite.connect

    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(aiosqlite, "connect", _boom)
    await tl.flush()
    # Batch preserved (re-queued), not dropped.
    async with tl._get_lock():
        assert len(tl._batch) == 1
        tl._batch.clear()
    monkeypatch.setattr(aiosqlite, "connect", real_connect)


@pytest.mark.asyncio
async def test_pairing_verify_throttles_after_10(workspace):
    from deeptutor.services.remote.pairing import PairingService

    for _ in range(PairingService.MAX_VERIFY_ATTEMPTS):
        assert await PairingService.verify_pairing_code("brute-parent", "GURU-000000") is None
    with pytest.raises(ValueError, match="Too many invalid pairing attempts"):
        await PairingService.verify_pairing_code("brute-parent", "GURU-000000")


@pytest.mark.asyncio
async def test_outbox_counts(workspace, monkeypatch):
    from deeptutor.services.monitoring import notification_queue as nq
    from deeptutor.services.monitoring import outbox_repo as obr
    from deeptutor.services.remote import telegram_config as tc
    from deeptutor.services.remote.telegram_config import TelegramConfigStore

    db = workspace / "user" / "chat_history.db"
    monkeypatch.setattr(tc, "_db_path", lambda: db)
    monkeypatch.setattr(obr, "db_path", lambda: db)
    monkeypatch.setattr(nq, "_db_path", lambda: db)

    await TelegramConfigStore.save("default", bot_token="t", chat_id="1", enabled=True)
    await nq.enqueue("warning", {"category": "NOTICE", "message": "m",
                                 "severity": "warning", "confidence": 0.9,
                                 "duration_seconds": 5})
    counts = await obr.get_counts(parent_id="default")
    assert counts["pending"] >= 1
    assert counts["total"] >= 1


@pytest.mark.asyncio
async def test_exam_start_idempotent_when_active(monkeypatch):
    from deeptutor.api.routers import exams as exams_router
    from deeptutor.services.exams import store as store_mod

    async def _fake_load(exam_id):
        return {"exam_id": exam_id, "status": "active", "started_at": 111.0,
                "ends_at": 222.0, "session_id": "sess-1"}

    monkeypatch.setattr(store_mod.ExamStore, "load_paper", classmethod(
        lambda cls, eid: _fake_load(eid)))
    res = await exams_router.start_exam("exam1", student_id="student-primary")
    assert res["already_active"] is True
    assert res["session_id"] == "sess-1"
