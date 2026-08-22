from __future__ import annotations
import logging
import time
import datetime
import aiosqlite
from typing import Dict, Any, Optional
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

class StreakTracker:
    """Manages student study streaks."""

    def __init__(self) -> None:
        self.db_path = get_path_service().user_dir / 'chat_history.db'

    async def _get_setting(self, db: aiosqlite.Connection, key: str) -> Optional[str]:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
        return None

    async def _set_setting(self, db: aiosqlite.Connection, key: str, value: str) -> None:
        await db.execute(
            """INSERT INTO settings (key, value) VALUES (?, ?) 
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value)
        )

    async def record_study_day(self, student_id: str) -> None:
        """Records a study day, updating streak if applicable."""
        today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        
        async with aiosqlite.connect(self.db_path) as db:
            last_date_str = await self._get_setting(db, f"streak_last_study_{student_id}")
            
            if last_date_str == today:
                return # Already studied today
                
            # Process streak logic
            streak_count = 1
            if last_date_str:
                last_date = datetime.date.fromisoformat(last_date_str)
                days_diff = (datetime.date.fromisoformat(today) - last_date).days
                
                if days_diff == 1:
                    # Increment streak
                    async with db.execute("SELECT streak_count FROM students WHERE id = ?", (student_id,)) as cursor:
                        row = await cursor.fetchone()
                        streak_count = (row[0] if row else 0) + 1
                elif days_diff > 1:
                    # Check for freezes... simplistic implementation
                    freezes = int(await self._get_setting(db, f"freezes_{student_id}") or "0")
                    if freezes >= days_diff - 1:
                        # used freezes
                        await self._set_setting(db, f"freezes_{student_id}", str(freezes - (days_diff - 1)))
                        async with db.execute("SELECT streak_count FROM students WHERE id = ?", (student_id,)) as cursor:
                            row = await cursor.fetchone()
                            streak_count = (row[0] if row else 0) + 1
            
            await db.execute("UPDATE students SET streak_count = ? WHERE id = ?", (streak_count, student_id))
            await self._set_setting(db, f"streak_last_study_{student_id}", today)
            
            # Award milestone bonuses
            milestones = {7: 500, 14: 1000, 30: 3000, 60: 5000, 100: 10000}
            if streak_count in milestones:
                # Add XP bonus
                await db.execute(
                    "UPDATE students SET total_xp = total_xp + ? WHERE id = ?",
                    (milestones[streak_count], student_id)
                )
            
            await db.commit()

    async def check_streak(self, student_id: str) -> int:
        """Checks and potentially breaks streak if missed."""
        today = datetime.datetime.now(datetime.timezone.utc).date()
        
        async with aiosqlite.connect(self.db_path) as db:
            last_date_str = await self._get_setting(db, f"streak_last_study_{student_id}")
            
            streak_count = 0
            if last_date_str:
                last_date = datetime.date.fromisoformat(last_date_str)
                days_diff = (today - last_date).days
                
                async with db.execute("SELECT streak_count FROM students WHERE id = ?", (student_id,)) as cursor:
                    row = await cursor.fetchone()
                    current_streak = row[0] if row else 0
                
                if days_diff > 1:
                    freezes = int(await self._get_setting(db, f"freezes_{student_id}") or "0")
                    if freezes < days_diff - 1:
                        # Streak broken
                        await db.execute("UPDATE students SET streak_count = 0 WHERE id = ?", (student_id,))
                        await db.commit()
                        streak_count = 0
                    else:
                        streak_count = current_streak
                else:
                    streak_count = current_streak
                    
        return streak_count

    async def use_freeze(self, student_id: str) -> bool:
        """Uses a streak freeze."""
        async with aiosqlite.connect(self.db_path) as db:
            freezes = int(await self._get_setting(db, f"freezes_{student_id}") or "0")
            if freezes < 1:
                return False
            
            await self._set_setting(db, f"freezes_{student_id}", str(freezes - 1))
            await db.commit()
            return True

    async def get_streak_info(self, student_id: str) -> Dict[str, Any]:
        """Gets info about the student's streak."""
        streak = await self.check_streak(student_id)
        
        async with aiosqlite.connect(self.db_path) as db:
            last_date = await self._get_setting(db, f"streak_last_study_{student_id}")
            freezes = int(await self._get_setting(db, f"freezes_{student_id}") or "0")
            
        return {
            "streak_count": streak,
            "last_study_date": last_date,
            "freezes_available": freezes
        }
