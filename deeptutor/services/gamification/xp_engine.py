from __future__ import annotations

import logging
import time
from typing import Any, Dict
import uuid

import aiosqlite

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)


class XPEngine:
    """Handles XP calculation and leveling."""

    def __init__(self) -> None:
        self.db_path = get_path_service().user_dir / "chat_history.db"

    async def award_session_xp(
        self, student_id: str, session_id: str, study_minutes: float, focus_score: float
    ) -> int:
        """Calculates and awards XP for a study session."""
        base_xp = int(study_minutes * 10)

        if focus_score < 50:
            multiplier = 0.5
        elif focus_score < 70:
            multiplier = 1.0
        elif focus_score < 90:
            multiplier = 1.5
        else:
            multiplier = 2.0

        earned_xp = int(base_xp * multiplier)
        if earned_xp <= 0:
            return 0

        reward_id = uuid.uuid4().hex
        now = time.time()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO rewards (id, student_id, session_id, reward_type, amount, created_at)
                   VALUES (?, ?, ?, 'xp', ?, ?)""",
                (reward_id, student_id, session_id, earned_xp, now),
            )

            # Update student total XP (assuming table students exists or similar; adapting based on requirements)
            await db.execute(
                """UPDATE students SET total_xp = total_xp + ? WHERE id = ?""",
                (earned_xp, student_id),
            )
            await db.commit()

        return earned_xp

    async def get_student_xp(self, student_id: str) -> Dict[str, Any]:
        """Returns total XP and current level for a student."""
        total_xp = 0
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT total_xp FROM students WHERE id = ?", (student_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    total_xp = row[0]

        level = self.get_level(total_xp)
        title = self.get_level_title(level)
        return {"total_xp": total_xp, "level": level, "title": title}

    def get_level(self, total_xp: int) -> int:
        """Calculates level based on total XP.
        Level 1 = 100xp, Level n = sum(100*i for i=1..n)
        """
        level = 0
        xp_required = 0
        while level < 50:
            next_req = xp_required + (100 * (level + 1))
            if total_xp >= next_req:
                xp_required = next_req
                level += 1
            else:
                break
        return max(1, level)

    def get_level_title(self, level: int) -> str:
        """Returns the title associated with the level."""
        if level <= 5:
            return "Novice"
        elif level <= 10:
            return "Apprentice"
        elif level <= 20:
            return "Scholar"
        elif level <= 30:
            return "Expert"
        elif level <= 40:
            return "Master"
        else:
            return "Grandmaster"
