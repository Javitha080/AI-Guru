"""Honest tests for the gamification engines (XP, badges, streaks).

Plain-language promise: every number asserted here is read back from a real
migrated SQLite database — no hardcoded demo scores. If the engines write to
a column that does not exist, or a query disagrees with the real schema,
these tests fail instead of silently passing.

Covers:
- XPEngine: focus-tier multipliers persist real rows and update student totals.
- BadgeEngine: badge rows use the real (reward_type='badge', badge_id) shape
  and earned badges read back correctly.
- StreakTracker: same-day idempotency, consecutive-day increment, freeze use,
  all through the dual-shape settings bridge.
"""

from __future__ import annotations

import datetime
from pathlib import Path
import sqlite3
import time

import aiosqlite
import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch):
    """Isolated workspace with a real migrated database (never real user data)."""
    from deeptutor.services import path_service as ps

    svc = ps.PathService(workspace_root=tmp_path)
    monkeypatch.setattr(ps.PathService, "_instance", svc, raising=False)

    db = svc.user_dir / "chat_history.db"
    db.parent.mkdir(parents=True, exist_ok=True)

    from deeptutor.services.database.migrations import apply_migrations, enable_pragmas

    conn = sqlite3.connect(db)
    enable_pragmas(conn)
    apply_migrations(conn)
    conn.commit()
    conn.close()
    return db


async def _seed_student(db_path: Path, student_id: str = "student-engines") -> None:
    now = time.time()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO users (id, username, password_hash, role, display_name,"
            " avatar_url, created_at, updated_at) VALUES (?, ?, '', 'student', ?, '', ?, ?)",
            (f"user-{student_id}", f"user-{student_id}", student_id, now, now),
        )
        await db.execute(
            "INSERT INTO students (id, user_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?)",
            (student_id, f"user-{student_id}", now, now),
        )
        await db.commit()


# ------------------------------------------------------------------ XP engine


async def test_xp_engine_persists_real_row_and_student_total(workspace: Path):
    """A 30-minute, 95-focus session earns 30*10*2.0 = 600 XP in rewards."""
    from deeptutor.services.gamification.xp_engine import XPEngine

    await _seed_student(workspace)
    engine = XPEngine()

    earned = await engine.award_session_xp("student-engines", "sess-1", 30.0, 95.0)
    assert earned == 600, f"expected 600 XP for 30min@95 focus, got {earned}"

    async with aiosqlite.connect(workspace) as db:
        async with db.execute(
            "SELECT amount_xp, reward_type FROM rewards WHERE session_id = ?", ("sess-1",)
        ) as cur:
            row = await cur.fetchone()
        assert row is not None, "no rewards row was persisted for the session"
        assert row[0] == 600 and row[1] == "xp"

        async with db.execute(
            "SELECT total_xp FROM students WHERE id = ?", ("student-engines",)
        ) as cur:
            total = (await cur.fetchone())[0]
        assert total == 600, f"student total_xp should be 600, got {total}"

    profile = await engine.get_student_xp("student-engines")
    assert profile["total_xp"] == 600
    assert profile["level"] == engine.get_level(600)
    assert profile["title"] == engine.get_level_title(profile["level"])


async def test_xp_engine_focus_tiers_and_zero_minutes(workspace: Path):
    """Each focus tier multiplies honestly; zero study earns zero and writes nothing."""
    from deeptutor.services.gamification.xp_engine import XPEngine

    await _seed_student(workspace)
    engine = XPEngine()

    assert await engine.award_session_xp("student-engines", "s-low", 10.0, 40.0) == 50
    assert await engine.award_session_xp("student-engines", "s-mid", 10.0, 60.0) == 100
    assert await engine.award_session_xp("student-engines", "s-high", 10.0, 80.0) == 150
    assert await engine.award_session_xp("student-engines", "s-peak", 10.0, 95.0) == 200

    assert await engine.award_session_xp("student-engines", "s-zero", 0.0, 90.0) == 0
    async with aiosqlite.connect(workspace) as db:
        async with db.execute("SELECT COUNT(*) FROM rewards") as cur:
            assert (await cur.fetchone())[0] == 4, "zero-minute session must not write a row"


# ------------------------------------------------------------------ badges


async def test_badge_engine_award_and_readback_use_real_shape(workspace: Path):
    """Awarded badges read back as earned through the real badge_id column."""
    from deeptutor.services.gamification.badge_engine import BadgeEngine

    await _seed_student(workspace)
    engine = BadgeEngine()

    assert await engine.get_earned_badges("student-engines") == []
    await engine._award_badge("student-engines", "first_session", "sess-1")

    async with aiosqlite.connect(workspace) as db:
        async with db.execute(
            "SELECT reward_type, badge_id, amount_xp FROM rewards WHERE student_id = ?",
            ("student-engines",),
        ) as cur:
            row = await cur.fetchone()
        assert row == ("badge", "first_session", 0), f"unexpected badge row shape: {row}"

    earned = await engine.get_earned_badges("student-engines")
    assert [b["id"] for b in earned] == ["first_session"]
    catalog = await engine.get_badges("student-engines")
    assert len(catalog) == len(BadgeEngine.BADGE_CATALOG)
    assert sum(1 for b in catalog if b["earned"]) == 1


async def test_badge_engine_check_and_award_first_session(workspace: Path):
    """One completed study session unlocks first_session — counted, not assumed."""
    from deeptutor.services.gamification.badge_engine import BadgeEngine

    await _seed_student(workspace)
    now = time.time()
    async with aiosqlite.connect(workspace) as db:
        await db.execute(
            "INSERT INTO study_sessions (id, student_id, status, start_time, created_at)"
            " VALUES ('sess-b1', 'student-engines', 'completed', ?, ?)",
            (now - 600, now - 600),
        )
        await db.commit()

    engine = BadgeEngine()
    await engine.check_and_award("student-engines", "sess-b1")
    assert "first_session" in await engine._get_earned_badge_ids("student-engines")

    # Second evaluation must not duplicate the badge row.
    await engine.check_and_award("student-engines", "sess-b1")
    async with aiosqlite.connect(workspace) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM rewards WHERE student_id = ? AND badge_id = ?",
            ("student-engines", "first_session"),
        ) as cur:
            assert (await cur.fetchone())[0] == 1, "badge was awarded twice"


# ------------------------------------------------------------------ streaks


async def test_streak_tracker_first_day_and_idempotency(workspace: Path):
    """First study day starts a streak of 1; repeating today changes nothing."""
    from deeptutor.services.gamification.streak_tracker import StreakTracker

    await _seed_student(workspace)
    tracker = StreakTracker()

    await tracker.record_study_day("student-engines")
    info = await tracker.get_streak_info("student-engines")
    assert info["streak_count"] == 1, f"expected streak 1, got {info}"
    assert info["last_study_date"] == datetime.date.today().isoformat()

    await tracker.record_study_day("student-engines")
    info2 = await tracker.get_streak_info("student-engines")
    assert info2["streak_count"] == 1, "same-day repeat must not inflate the streak"


async def test_streak_tracker_consecutive_day_increments(workspace: Path):
    """Yesterday + streak 3, studying today honestly continues to 4."""
    from deeptutor.services.gamification.streak_tracker import StreakTracker
    from deeptutor.services.remote.kv_settings import ensure_kv_settings

    await _seed_student(workspace)
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    async with aiosqlite.connect(workspace) as db:
        await ensure_kv_settings(db)
        await db.execute(
            "INSERT INTO settings (key, value, category, updated_at) VALUES (?, ?, 'general', ?)",
            ("streak_last_study_student-engines", yesterday, time.time()),
        )
        await db.execute(
            "UPDATE students SET streak_count = 3 WHERE id = ?", ("student-engines",)
        )
        await db.commit()

    tracker = StreakTracker()
    await tracker.record_study_day("student-engines")
    info = await tracker.get_streak_info("student-engines")
    assert info["streak_count"] == 4, f"expected continued streak 4, got {info}"


async def test_streak_tracker_freeze_use_and_empty(workspace: Path):
    """Using a freeze with none available fails honestly; granting one works."""
    from deeptutor.services.gamification.streak_tracker import StreakTracker
    from deeptutor.services.remote.kv_settings import ensure_kv_settings

    await _seed_student(workspace)
    tracker = StreakTracker()

    assert await tracker.use_freeze("student-engines") is False

    async with aiosqlite.connect(workspace) as db:
        await ensure_kv_settings(db)
        await db.execute(
            "INSERT INTO settings (key, value, category, updated_at) VALUES (?, ?, 'general', ?)",
            ("freezes_student-engines", "2", time.time()),
        )
        await db.commit()

    assert await tracker.use_freeze("student-engines") is True
    info = await tracker.get_streak_info("student-engines")
    assert info["freezes_available"] == 1, f"expected 1 freeze left, got {info}"
