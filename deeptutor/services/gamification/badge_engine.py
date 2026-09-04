from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Set
import uuid

import aiosqlite

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)


class BadgeEngine:
    """Manages unlocking and checking badges."""

    BADGE_CATALOG = {
        "first_session": "Complete first study session",
        "early_bird": "Study before 8 AM",
        "night_owl": "Study after 10 PM",
        "focus_master": "100% focus score in a session",
        "streak_7": "7-day streak",
        "streak_30": "30-day streak",
        "streak_100": "100-day streak",
        "hour_warrior": "1 hour session",
        "marathon": "3 hour session",
        "xp_100": "Reach 100 total XP",
        "xp_1000": "Reach 1000 total XP",
        "xp_10000": "Reach 10000 total XP",
        "ten_sessions": "Complete 10 sessions",
        "fifty_sessions": "Complete 50 sessions",
        "perfectionist": "5 consecutive sessions with >90% focus",
    }

    def __init__(self) -> None:
        self.db_path = get_path_service().user_dir / "chat_history.db"

    async def _get_earned_badge_ids(self, student_id: str) -> Set[str]:
        earned = set()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT reward_type FROM rewards WHERE student_id = ? AND reward_type LIKE 'badge_%'",
                (student_id,),
            ) as cursor:
                async for row in cursor:
                    earned.add(row[0].replace("badge_", ""))
        return earned

    async def _award_badge(self, student_id: str, badge_id: str, session_id: str = None) -> None:
        reward_id = uuid.uuid4().hex
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO rewards (id, student_id, session_id, reward_type, amount, created_at)
                   VALUES (?, ?, ?, ?, 0, ?)""",
                (reward_id, student_id, session_id, f"badge_{badge_id}", now),
            )
            await db.commit()

    async def check_and_award(self, student_id: str, session_id: str = None) -> None:
        """Evaluates badges and awards them if earned."""
        earned = await self._get_earned_badge_ids(student_id)
        to_award = set()

        async with aiosqlite.connect(self.db_path) as db:
            # Get basic student stats
            total_xp = 0
            streak_count = 0
            async with db.execute(
                "SELECT total_xp, streak_count FROM students WHERE id = ?", (student_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    total_xp, streak_count = row

            # Get session stats
            sessions_count = 0
            async with db.execute(
                "SELECT COUNT(*) FROM study_sessions WHERE student_id = ?", (student_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    sessions_count = row[0]

            # Simple logic for XP badges
            if total_xp >= 100 and "xp_100" not in earned:
                to_award.add("xp_100")
            if total_xp >= 1000 and "xp_1000" not in earned:
                to_award.add("xp_1000")
            if total_xp >= 10000 and "xp_10000" not in earned:
                to_award.add("xp_10000")

            # Streak badges
            if streak_count >= 7 and "streak_7" not in earned:
                to_award.add("streak_7")
            if streak_count >= 30 and "streak_30" not in earned:
                to_award.add("streak_30")
            if streak_count >= 100 and "streak_100" not in earned:
                to_award.add("streak_100")

            # Session counts
            if sessions_count >= 1 and "first_session" not in earned:
                to_award.add("first_session")
            if sessions_count >= 10 and "ten_sessions" not in earned:
                to_award.add("ten_sessions")
            if sessions_count >= 50 and "fifty_sessions" not in earned:
                to_award.add("fifty_sessions")

            # Time based badges (need actual session logic, left simple for now)
            if session_id:
                async with db.execute(
                    "SELECT focus_score, actual_duration_seconds FROM study_sessions WHERE id = ?",
                    (session_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        focus, duration = row
                        if focus == 100 and "focus_master" not in earned:
                            to_award.add("focus_master")
                        if duration and duration >= 3600 and "hour_warrior" not in earned:
                            to_award.add("hour_warrior")
                        if duration and duration >= 10800 and "marathon" not in earned:
                            to_award.add("marathon")

        for badge_id in to_award:
            await self._award_badge(student_id, badge_id, session_id)

    async def get_badges(self, student_id: str) -> List[Dict[str, Any]]:
        """Lists all badges and their status."""
        earned = await self._get_earned_badge_ids(student_id)
        result = []
        for b_id, desc in self.BADGE_CATALOG.items():
            result.append({"id": b_id, "description": desc, "earned": b_id in earned})
        return result

    async def get_earned_badges(self, student_id: str) -> List[Dict[str, Any]]:
        """Lists only earned badges."""
        badges = await self.get_badges(student_id)
        return [b for b in badges if b["earned"]]
