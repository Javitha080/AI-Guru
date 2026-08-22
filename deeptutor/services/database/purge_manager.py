"""
AI Guru Data Purge Manager.
===========================

Granular data deletion with safety confirmations for GDPR/COPPA compliance.
All destructive operations require an explicit confirmation phrase.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import aiosqlite

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)


class PurgeManager:
    """Granular data deletion with safety confirmations."""

    CONFIRMATION_PHRASE = "DELETE MY DATA"

    def __init__(self) -> None:
        self.db_path = get_path_service().user_dir / "chat_history.db"

    def _verify_confirmation(self, confirmation: str) -> None:
        """Raises ValueError if confirmation doesn't match."""
        if confirmation != self.CONFIRMATION_PHRASE:
            raise ValueError(
                f"Confirmation phrase must be exactly '{self.CONFIRMATION_PHRASE}'"
            )

    async def purge_monitoring_history(
        self, student_id: str, confirmation: str
    ) -> Dict[str, Any]:
        """Delete all monitoring_events for a student's sessions."""
        self._verify_confirmation(confirmation)

        async with aiosqlite.connect(self.db_path) as db:
            # monitoring_events links via session_id, so delete events
            # for all sessions belonging to this student
            cursor = await db.execute(
                """DELETE FROM monitoring_events WHERE session_id IN
                   (SELECT id FROM study_sessions WHERE student_id = ?)""",
                (student_id,),
            )
            deleted_count = cursor.rowcount
            await db.commit()

        logger.info(
            "Purged %d monitoring events for student %s", deleted_count, student_id
        )
        return {"deleted_count": deleted_count, "tables_affected": ["monitoring_events"]}

    async def purge_session_history(
        self, student_id: str, confirmation: str
    ) -> Dict[str, Any]:
        """Delete all study_sessions, session_reports, and monitoring_events for a student."""
        self._verify_confirmation(confirmation)

        total_deleted = 0
        tables_affected: List[str] = []

        async with aiosqlite.connect(self.db_path) as db:
            # Order matters due to foreign keys: events → reports → sessions
            for table, where in [
                ("monitoring_events", "session_id IN (SELECT id FROM study_sessions WHERE student_id = ?)"),
                ("session_reports", "student_id = ?"),
                ("study_sessions", "student_id = ?"),
            ]:
                cursor = await db.execute(
                    f"DELETE FROM {table} WHERE {where}", (student_id,)
                )
                if cursor.rowcount > 0:
                    total_deleted += cursor.rowcount
                    tables_affected.append(table)
            await db.commit()

        logger.info(
            "Purged %d session records for student %s", total_deleted, student_id
        )
        return {"deleted_count": total_deleted, "tables_affected": tables_affected}

    async def purge_rewards(
        self, student_id: str, confirmation: str
    ) -> Dict[str, Any]:
        """Delete all rewards and reset XP/streak for a student."""
        self._verify_confirmation(confirmation)

        total_deleted = 0

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM rewards WHERE student_id = ?", (student_id,)
            )
            total_deleted += cursor.rowcount

            # Reset XP and streak in students table
            await db.execute(
                "UPDATE students SET total_xp = 0, streak_count = 0 WHERE id = ?",
                (student_id,),
            )
            await db.commit()

        logger.info(
            "Purged %d rewards and reset XP/streak for student %s",
            total_deleted,
            student_id,
        )
        return {
            "deleted_count": total_deleted,
            "tables_affected": ["rewards", "students"],
        }

    async def purge_student_data(
        self, student_id: str, confirmation: str
    ) -> Dict[str, Any]:
        """Delete ALL data for a student (sessions, events, reports, rewards, goals, the student record)."""
        self._verify_confirmation(confirmation)

        total_deleted = 0
        tables_affected: List[str] = []

        # Delete in dependency order (children first)
        delete_specs = [
            ("monitoring_events", "session_id IN (SELECT id FROM study_sessions WHERE student_id = ?)"),
            ("session_reports", "student_id = ?"),
            ("rewards", "student_id = ?"),
            ("study_goals", "student_id = ?"),
            ("study_sessions", "student_id = ?"),
            ("parent_student_links", "student_id = ?"),
            ("students", "id = ?"),
        ]

        async with aiosqlite.connect(self.db_path) as db:
            for table, where in delete_specs:
                try:
                    cursor = await db.execute(
                        f"DELETE FROM {table} WHERE {where}", (student_id,)
                    )
                    if cursor.rowcount > 0:
                        total_deleted += cursor.rowcount
                        tables_affected.append(table)
                except Exception as e:
                    logger.warning("Failed to purge from %s: %s", table, e)
            await db.commit()

        logger.info(
            "Purged %d total records for student %s across %s",
            total_deleted,
            student_id,
            tables_affected,
        )
        return {"deleted_count": total_deleted, "tables_affected": tables_affected}

    async def factory_reset(self, confirmation: str) -> Dict[str, Any]:
        """Delete ALL AI Guru data from all 11 core tables. Nuclear option."""
        self._verify_confirmation(confirmation)

        # All tables from schema.py in safe deletion order
        tables = [
            "monitoring_events",
            "session_reports",
            "rewards",
            "study_goals",
            "study_sessions",
            "parent_student_links",
            "audit_logs",
            "settings",
            "students",
            "parents",
            "users",
        ]
        total_deleted = 0
        tables_affected: List[str] = []

        async with aiosqlite.connect(self.db_path) as db:
            # Temporarily disable foreign keys for clean wipe
            await db.execute("PRAGMA foreign_keys = OFF")
            for table in tables:
                try:
                    cursor = await db.execute(f"DELETE FROM {table}")
                    if cursor.rowcount > 0:
                        total_deleted += cursor.rowcount
                        tables_affected.append(table)
                except Exception as e:
                    logger.warning("Failed to purge table %s: %s", table, e)
            await db.execute("PRAGMA foreign_keys = ON")
            await db.commit()

        logger.warning(
            "FACTORY RESET: purged %d records across %d tables",
            total_deleted,
            len(tables_affected),
        )
        return {"deleted_count": total_deleted, "tables_affected": tables_affected}
