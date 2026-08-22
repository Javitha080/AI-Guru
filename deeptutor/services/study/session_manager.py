from __future__ import annotations

import logging
import time
from typing import Any, Dict, List
import uuid

import aiosqlite

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

class StudySessionManager:
    """Manages the lifecycle of study sessions."""

    def __init__(self) -> None:
        self.db_path = get_path_service().user_dir / 'chat_history.db'

    async def create_session(self, student_id: str, title: str, subject: str, target_duration_seconds: int) -> Dict[str, Any]:
        """Creates a new study session.

        The V1 schema has no 'created' status and requires ``start_time`` on
        every row, so creation immediately enters ``in_progress``; the
        router's explicit /start call refreshes ``start_time``.
        """
        session_id = uuid.uuid4().hex
        now = time.time()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO study_sessions (id, student_id, title, subject, target_duration_seconds, status, start_time, created_at, focus_score, engagement_score, distraction_count, warning_count)
                   VALUES (?, ?, ?, ?, ?, 'in_progress', ?, ?, 0, 0, 0, 0)""",
                (session_id, student_id, title, subject, target_duration_seconds, now, now)
            )
            await db.commit()

        return await self.get_session(session_id)

    async def start_session(self, session_id: str) -> None:
        """Starts a study session."""
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE study_sessions SET status = 'in_progress', start_time = ? WHERE id = ?",
                (now, session_id)
            )
            await db.commit()

    async def pause_session(self, session_id: str) -> None:
        """Pauses a study session."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE study_sessions SET status = 'paused' WHERE id = ?",
                (session_id,)
            )
            await db.commit()

    async def resume_session(self, session_id: str) -> None:
        """Resumes a paused study session."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE study_sessions SET status = 'in_progress' WHERE id = ?",
                (session_id,)
            )
            await db.commit()

    async def stop_session(self, session_id: str) -> None:
        """Stops a study session and calculates actual duration."""
        now = time.time()
        session = await self.get_session(session_id)
        if not session:
            return

        start_time = session.get('start_time')
        actual_duration = int(now - start_time) if start_time else 0

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE study_sessions SET status = 'completed', end_time = ?, actual_duration_seconds = ? WHERE id = ?",
                (now, actual_duration, session_id)
            )
            await db.commit()

    async def abandon_session(self, session_id: str) -> None:
        """Marks a session as abandoned."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE study_sessions SET status = 'abandoned' WHERE id = ?",
                (session_id,)
            )
            await db.commit()

    async def get_session(self, session_id: str) -> Dict[str, Any]:
        """Retrieves a session by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM study_sessions WHERE id = ?", (session_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
        return {}

    async def list_sessions(self, student_id: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """Lists sessions for a student."""
        sessions = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM study_sessions WHERE student_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (student_id, limit, offset)
            ) as cursor:
                async for row in cursor:
                    sessions.append(dict(row))
        return sessions

    async def update_scores(self, session_id: str, focus_score: float, engagement_score: float, distraction_count: int, warning_count: int) -> None:
        """Updates the running scores of a session."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE study_sessions SET focus_score = ?, engagement_score = ?, distraction_count = ?, warning_count = ? WHERE id = ?",
                (focus_score, engagement_score, distraction_count, warning_count, session_id)
            )
            await db.commit()

    async def get_session_report(self, session_id: str) -> Dict[str, Any]:
        """Assembles the report payload consumed by GET /{session_id}/report.

        Combines the session row, the stored evaluation report (when the
        ReportGenerator has run), and live telemetry counts — no canned data.
        """
        session = await self.get_session(session_id)
        if not session:
            return {}

        from deeptutor.services.study.report_generator import ReportGenerator
        from deeptutor.services.study.telemetry_logger import TelemetryLogger

        try:
            stored = await ReportGenerator().get_report(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Stored report unavailable for %s: %s", session_id, exc)
            stored = {}

        try:
            summary_counts = await TelemetryLogger().get_session_summary(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Telemetry summary unavailable for %s: %s", session_id, exc)
            summary_counts = {}

        warnings = int(summary_counts.get("by_type", {}).get("WARNING_ISSUED", 0))
        metrics = {
            "focus_score": session.get("focus_score") or 0,
            "engagement_score": session.get("engagement_score") or 0,
            "distraction_count": session.get("distraction_count") or 0,
            "warning_count": max(warnings, int(session.get("warning_count") or 0)),
            "actual_duration_seconds": session.get("actual_duration_seconds") or 0,
            "subject": session.get("subject"),
        }
        summary_text = stored.get("ai_tutor_feedback") or (
            f"Session on {metrics['subject']}: {round((metrics['actual_duration_seconds'] or 0) / 60)} min, "
            f"{warnings} focus warning(s)."
        )
        return {
            "session_id": session_id,
            "summary": summary_text,
            "xp_earned": None,  # XP lives in rewards; UI reads profile separately.
            "metrics": metrics,
            "stored_report_available": bool(stored),
            "productive_seconds": stored.get("productive_seconds"),
            "distracted_seconds": stored.get("distracted_seconds"),
            "topics": stored.get("topics", []),
        }
