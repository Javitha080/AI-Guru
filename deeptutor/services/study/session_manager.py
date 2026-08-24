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

    @staticmethod
    async def _ensure_student(db: aiosqlite.Connection, student_id: str) -> None:
        """FK provisioning: ``study_sessions.student_id`` references students(id).

        Mirrors gamification_service._ensure_student so a fresh install can
        create sessions without any prior registration step.
        """
        now = time.time()
        user_id = f"user-{student_id}"
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role, display_name, avatar_url, created_at, updated_at)"
            " VALUES (?, ?, '', 'student', ?, '', ?, ?)",
            (user_id, f"student:{student_id}", student_id, now, now),
        )
        await db.execute(
            "INSERT OR IGNORE INTO students (id, user_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (student_id, user_id, now, now),
        )

    async def create_session(self, student_id: str, title: str, subject: str, target_duration_seconds: int) -> Dict[str, Any]:
        """Creates a new study session.

        The V1 schema has no 'created' status and requires ``start_time`` on
        every row, so creation immediately enters ``in_progress``; the
        router's explicit /start call refreshes ``start_time``.
        """
        session_id = uuid.uuid4().hex
        now = time.time()

        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_student(db, student_id)
            await db.execute(
                """INSERT INTO study_sessions (id, student_id, title, subject, target_duration_seconds, status, start_time, last_resume_time, created_at, focus_score, engagement_score, distraction_count, warning_count)
                   VALUES (?, ?, ?, ?, ?, 'in_progress', ?, ?, ?, 0, 0, 0, 0)""",
                (session_id, student_id, title, subject, target_duration_seconds, now, now, now)
            )
            await db.commit()

        session = await self.get_session(session_id)
        if not session:
            raise RuntimeError(f"study session {session_id} vanished right after insert")
        return session

    async def _require_session(self, session_id: str) -> Dict[str, Any]:
        """Fetches a session or raises KeyError (router maps to 404)."""
        session = await self.get_session(session_id)
        if not session:
            raise KeyError(f"Study session '{session_id}' not found")
        return session

    async def start_session(self, session_id: str) -> Dict[str, Any]:
        """Starts a study session (opens the first active stretch)."""
        await self._require_session(session_id)
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE study_sessions SET status = 'in_progress', start_time = ?, last_resume_time = ? WHERE id = ?",
                (now, now, session_id)
            )
            await db.commit()
        return await self._require_session(session_id)

    async def pause_session(self, session_id: str) -> Dict[str, Any]:
        """Pauses a study session, banking the active stretch into worked_seconds.

        ``worked_seconds`` accumulates only time actually spent studying; the
        paused wall-clock between pause and resume is excluded from duration
        and XP.
        """
        await self._require_session(session_id)
        now = time.time()
        session = await self.get_session(session_id)
        worked = float(session.get('worked_seconds') or 0.0)
        last_resume = session.get('last_resume_time')
        if session.get('status') == 'in_progress' and last_resume:
            worked += max(0.0, now - float(last_resume))
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE study_sessions SET status = 'paused', worked_seconds = ?, last_resume_time = NULL WHERE id = ?",
                (worked, session_id)
            )
            await db.commit()
        return await self._require_session(session_id)

    async def resume_session(self, session_id: str) -> Dict[str, Any]:
        """Resumes a paused study session (opens a fresh active stretch)."""
        await self._require_session(session_id)
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE study_sessions SET status = 'in_progress', last_resume_time = ? WHERE id = ?",
                (now, session_id)
            )
            await db.commit()
        return await self._require_session(session_id)

    async def stop_session(self, session_id: str) -> Dict[str, Any]:
        """Stops a study session and records the pause-aware actual duration."""
        session = await self._require_session(session_id)
        now = time.time()

        if session.get('status') != 'completed':
            worked = float(session.get('worked_seconds') or 0.0)
            last_resume = session.get('last_resume_time')
            if session.get('status') == 'in_progress' and last_resume:
                # Close the final open active stretch.
                worked += max(0.0, now - float(last_resume))
            # 'paused' rows already banked their stretch in pause_session.

            start_time = session.get('start_time')
            # Defensive ceiling: never report more than elapsed wall-clock,
            # even if the system clock jumps between resume and stop.
            wall = int(now - start_time) if start_time else 0
            actual_duration = min(int(worked), max(0, wall))

            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE study_sessions SET status = 'completed', end_time = ?, actual_duration_seconds = ?, worked_seconds = ?, last_resume_time = NULL WHERE id = ?",
                    (now, actual_duration, worked, session_id)
                )
                await db.commit()
        return await self._require_session(session_id)

    async def abandon_session(self, session_id: str) -> Dict[str, Any]:
        """Marks a session as abandoned."""
        await self._require_session(session_id)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE study_sessions SET status = 'abandoned', end_time = ?, last_resume_time = NULL WHERE id = ?",
                (time.time(), session_id)
            )
            await db.commit()
        return await self._require_session(session_id)

    async def get_session(self, session_id: str) -> Dict[str, Any]:
        """Retrieves a session by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM study_sessions WHERE id = ?", (session_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
        return {}

    async def list_sessions(self, student_id: str, limit: int = 20, offset: int = 0) -> Dict[str, Any]:
        """Lists sessions for a student (paginated payload matching the router model)."""
        items: List[Dict[str, Any]] = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT COUNT(*) AS n FROM study_sessions WHERE student_id = ?",
                (student_id,)
            ) as cursor:
                total = int((await cursor.fetchone())["n"])
            async with db.execute(
                "SELECT * FROM study_sessions WHERE student_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (student_id, limit, offset)
            ) as cursor:
                async for row in cursor:
                    items.append(dict(row))
        return {"items": items, "total": total, "limit": int(limit), "offset": int(offset)}

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

        # Info-level presence pings (STUDENT_AWAY) are not warnings.
        warnings = int(summary_counts.get("actionable_warnings", 0))
        distraction_count = int(summary_counts.get("by_type", {}).get("LOOKING_AWAY", 0)) + \
            int(summary_counts.get("by_type", {}).get("PHONE_DETECTED", 0))
        metrics = {
            "focus_score": session.get("focus_score") or 0,
            "engagement_score": session.get("engagement_score") or 0,
            "distraction_count": max(distraction_count, int(session.get("distraction_count") or 0)),
            "warning_count": max(warnings, int(session.get("warning_count") or 0)),
            "actual_duration_seconds": session.get("actual_duration_seconds") or 0,
            "subject": session.get("subject"),
        }
        summary_text = stored.get("ai_tutor_feedback") or (
            f"Session on {metrics['subject']}: {round((metrics['actual_duration_seconds'] or 0) / 60)} min, "
            f"{warnings} focus warning(s)."
        )
        xp_earned = await self._session_xp(session_id)
        return {
            "session_id": session_id,
            "summary": summary_text,
            "xp_earned": xp_earned,
            "metrics": metrics,
            "stored_report_available": bool(stored),
            "productive_seconds": stored.get("productive_seconds"),
            "distracted_seconds": stored.get("distracted_seconds"),
            "topics": stored.get("topics", []),
        }

    async def _session_xp(self, session_id: str) -> int:
        """Real XP awarded to this session from the rewards table."""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT COALESCE(SUM(amount_xp), 0) FROM rewards WHERE session_id = ? AND reward_type = 'xp'",
                (session_id,),
            )
            row = await cur.fetchone()
        return int(row[0] or 0) if row else 0
