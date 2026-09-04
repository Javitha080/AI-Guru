"""AI Guru Gamification facade — real reads/writes over the V1 schema.

This replaces the phantom ``gamification_service`` module every gamification
endpoint has been importing since the AI Guru build. Everything here speaks
the actual ``rewards`` / ``study_sessions`` / ``students`` columns defined in
``services/database/schema.py``:

    rewards(id, student_id, session_id, reward_type ∈ ('xp','badge',
        'streak_bonus','milestone'), amount_xp, badge_id, badge_name,
        badge_icon, reason, unlocked_at)

Badges reuse ``BadgeEngine.BADGE_CATALOG`` descriptions but are evaluated
against real session/reward rows with idempotent inserts (reason =
``badge:<id>``).
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import sqlite3
import time
from typing import Any, Dict, List, Optional
import uuid

from deeptutor.services.gamification.badge_engine import BadgeEngine
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

_LEVEL_STEP = 500
_LEVEL_TITLES = [(10, "Sage"), (7, "Master"), (4, "Scholar"), (2, "Apprentice"), (0, "Novice")]


def _db_path():
    return get_path_service().user_dir / "chat_history.db"


def _ensure_student(conn: sqlite3.Connection, student_id: str) -> None:
    now = time.time()
    user_id = f"user-{student_id}"
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, role, display_name, avatar_url, created_at, updated_at)"
        " VALUES (?, ?, '', 'student', ?, '', ?, ?)",
        (user_id, f"student:{student_id}", student_id, now, now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO students (id, user_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (student_id, user_id, now, now),
    )


class GamificationService:
    """Single source of truth for XP / badges / rewards on-device."""

    # ------------------------------------------------------------- internals

    @staticmethod
    def _level_for(xp: int) -> int:
        return max(1, min(99, xp // _LEVEL_STEP + 1))

    @staticmethod
    def _title_for(level: int) -> str:
        for threshold, title in _LEVEL_TITLES:
            if level >= threshold:
                return title
        return "Novice"

    @staticmethod
    async def _totals(student_id: str) -> Dict[str, Any]:
        import aiosqlite

        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT COALESCE(SUM(amount_xp), 0) AS xp FROM rewards"
                " WHERE student_id = ? AND reward_type = 'xp'",
                (student_id,),
            )
            xp = int((await cur.fetchone())["xp"])

            cur = await db.execute(
                "SELECT COUNT(*) AS n FROM study_sessions"
                " WHERE student_id = ? AND status = 'completed'",
                (student_id,),
            )
            total_sessions = int((await cur.fetchone())["n"])

            cur = await db.execute(
                "SELECT MAX(focus_score) AS best FROM study_sessions WHERE student_id = ?",
                (student_id,),
            )
            best_focus = float((await cur.fetchone())["best"] or 0)

            cur = await db.execute(
                "SELECT start_time, actual_duration_seconds FROM study_sessions"
                " WHERE student_id = ? AND status IN ('completed','in_progress')",
                (student_id,),
            )
            rows = await cur.fetchall()

        # Consecutive-day streak (a day counts when any session started on it).
        days = sorted({datetime.fromtimestamp(r["start_time"]).date() for r in rows})
        streak = 0
        if days:
            today = datetime.now().date()
            cursor_day = today if today in days else today - timedelta(days=1)
            day_set = set(days)
            while cursor_day in day_set:
                streak += 1
                cursor_day -= timedelta(days=1)

        max_minutes = max((int((r["actual_duration_seconds"] or 0) / 60) for r in rows), default=0)
        return {
            "xp": xp,
            "total_sessions": total_sessions,
            "best_focus": best_focus,
            "streak": streak,
            "max_session_minutes": max_minutes,
        }

    @staticmethod
    async def _earned_badge_ids(student_id: str) -> set[str]:
        import aiosqlite

        async with aiosqlite.connect(_db_path()) as db:
            cur = await db.execute(
                "SELECT badge_id FROM rewards WHERE student_id = ? AND reward_type = 'badge'",
                (student_id,),
            )
            return {str(r[0]) for r in await cur.fetchall()}

    # ------------------------------------------------------------- public API

    @staticmethod
    async def award_xp(
        student_id: str,
        xp: int,
        reason: str,
        session_id: Optional[str] = None,
    ) -> bool:
        """Insert an XP reward row (FK-safe). Idempotency is the caller's duty."""
        if xp <= 0:
            return False
        conn = sqlite3.connect(_db_path())
        try:
            _ensure_student(conn, student_id)
            conn.execute(
                "INSERT INTO rewards (id, student_id, session_id, reward_type, amount_xp,"
                " badge_id, badge_name, badge_icon, reason, unlocked_at)"
                " VALUES (?, ?, ?, 'xp', ?, '', '', '', ?, ?)",
                (
                    f"reward-{uuid.uuid4().hex[:12]}",
                    student_id,
                    session_id,
                    int(xp),
                    reason,
                    time.time(),
                ),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    @staticmethod
    async def check_and_award(student_id: str, session_id: Optional[str] = None) -> List[str]:
        """Evaluate milestone badges and persist newly earned ones."""
        totals = await GamificationService._totals(student_id)
        earned = await GamificationService._earned_badge_ids(student_id)

        conditions: Dict[str, bool] = {
            "first_session": totals["total_sessions"] >= 1,
            "ten_sessions": totals["total_sessions"] >= 10,
            "fifty_sessions": totals["total_sessions"] >= 50,
            "xp_100": totals["xp"] >= 100,
            "xp_1000": totals["xp"] >= 1000,
            "xp_10000": totals["xp"] >= 10000,
            "streak_7": totals["streak"] >= 7,
            "streak_30": totals["streak"] >= 30,
            "streak_100": totals["streak"] >= 100,
            "hour_warrior": totals["max_session_minutes"] >= 60,
            "marathon": totals["max_session_minutes"] >= 180,
            "focus_master": totals["best_focus"] >= 100,
        }

        newly: List[str] = []
        conn = sqlite3.connect(_db_path())
        try:
            _ensure_student(conn, student_id)
            now = time.time()
            for badge_id, achieved in conditions.items():
                if not achieved or badge_id in earned:
                    continue
                description = BadgeEngine.BADGE_CATALOG.get(
                    badge_id, badge_id.replace("_", " ").title()
                )
                conn.execute(
                    "INSERT INTO rewards (id, student_id, session_id, reward_type, amount_xp,"
                    " badge_id, badge_name, badge_icon, reason, unlocked_at)"
                    " VALUES (?, ?, ?, 'badge', 0, ?, ?, '', ?, ?)",
                    (
                        f"reward-{uuid.uuid4().hex[:12]}",
                        student_id,
                        session_id,
                        badge_id,
                        description,
                        f"badge:{badge_id}",
                        now,
                    ),
                )
                newly.append(badge_id)
            conn.commit()
        finally:
            conn.close()
        if newly:
            logger.info("Awarded badges %s to %s", newly, student_id)
        return newly

    @staticmethod
    async def get_profile(student_id: str) -> Dict[str, Any]:
        totals = await GamificationService._totals(student_id)
        level = GamificationService._level_for(totals["xp"])
        return {
            "student_id": student_id,
            "xp": totals["xp"],
            "level": level,
            "level_title": GamificationService._title_for(level),
            "streak": totals["streak"],
            "total_sessions": totals["total_sessions"],
        }

    @staticmethod
    async def get_badges(student_id: str) -> List[Dict[str, Any]]:
        catalog = BadgeEngine.BADGE_CATALOG
        earned = await GamificationService._earned_badge_ids(student_id)

        import aiosqlite

        earned_at: Dict[str, float] = {}
        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT badge_id, unlocked_at FROM rewards"
                " WHERE student_id = ? AND reward_type = 'badge'",
                (student_id,),
            )
            for r in await cur.fetchall():
                earned_at[str(r["badge_id"])] = float(r["unlocked_at"] or 0)

        out: List[Dict[str, Any]] = []
        for badge_id, description in catalog.items():
            is_earned = badge_id in earned
            out.append(
                {
                    "id": badge_id,
                    "name": badge_id.replace("_", " ").title(),
                    "description": description,
                    "icon_url": "",
                    "earned": is_earned,
                    "earned_at": earned_at.get(badge_id),
                }
            )
        return out

    @staticmethod
    async def get_rewards(student_id: str, limit: int = 30) -> Dict[str, Any]:
        import aiosqlite

        items: List[Dict[str, Any]] = []
        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT reward_type, amount_xp, badge_name, reason, unlocked_at"
                " FROM rewards WHERE student_id = ? ORDER BY unlocked_at DESC LIMIT ?",
                (student_id, int(limit)),
            )
            for r in await cur.fetchall():
                items.append(
                    {
                        "type": r["reward_type"],
                        "amount_xp": int(r["amount_xp"] or 0),
                        "badge_name": r["badge_name"] or "",
                        "reason": r["reason"] or "",
                        "unlocked_at": float(r["unlocked_at"] or 0),
                    }
                )
        return {"items": items}
