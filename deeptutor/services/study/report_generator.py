from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List
import uuid

import aiosqlite

from deeptutor.services.path_service import get_path_service
from deeptutor.services.study.session_manager import (
    MIN_MEASURABLE_SECONDS,
    StudySessionManager,
)
from deeptutor.services.study.telemetry_logger import TelemetryLogger

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generates and manages study session reports against the V1 schema.

    ``session_reports`` columns (schema.py): id TEXT PK, session_id UNIQUE,
    student_id, focus_score NOT NULL, engagement_score NOT NULL,
    total_study_seconds INT NOT NULL, productive_seconds INT NOT NULL,
    distracted_seconds INT NOT NULL, topics_covered_json, key_strengths,
    areas_for_improvement, ai_tutor_feedback, parent_notes, generated_at.
    """

    def __init__(self) -> None:
        self.db_path = get_path_service().user_dir / "chat_history.db"
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Report DB parent not writable: %s", exc)
        self.session_manager = StudySessionManager()
        self.telemetry_logger = TelemetryLogger()

    async def generate_report(self, session_id: str, student_id: str) -> Dict[str, Any]:
        """Generates a report for a completed session from real telemetry."""
        session = await self.session_manager.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        events = await self.telemetry_logger.get_session_events(session_id)

        actual_duration = int(session.get("actual_duration_seconds") or 0)

        distracted_seconds = 0.0
        for event in events:
            if event["event_type"] in ("LOOKING_AWAY", "PHONE_DETECTED"):
                distracted_seconds += float(event.get("duration_seconds") or 0.0)
        distracted_seconds = min(distracted_seconds, float(actual_duration))

        productive_seconds = max(0.0, float(actual_duration) - distracted_seconds)
        # Info-level presence pings (STUDENT_AWAY etc.) are not warnings.
        warning_count = sum(
            1
            for e in events
            if e["event_type"] == "WARNING_ISSUED" and e.get("severity") in ("warning", "alert")
        )

        # Honest scoring: a live-measured session score (>0, persisted by the
        # monitoring loop) wins. Otherwise the formula applies ONLY when there
        # is real signal (warnings or distracted seconds on a meaningful
        # session) — a zero-telemetry stub must record 0 (unmeasured), never
        # a synthesized 100 that the parent board would render as perfect.
        measured_focus = None
        try:
            candidate = float(session.get("focus_score") or 0)
            measured_focus = candidate if candidate > 0 else None
        except (TypeError, ValueError):
            measured_focus = None
        measured_engagement = None
        try:
            candidate = float(session.get("engagement_score") or 0)
            measured_engagement = candidate if candidate > 0 else None
        except (TypeError, ValueError):
            measured_engagement = None

        has_signal = warning_count > 0 or distracted_seconds > 0
        meaningful = actual_duration >= MIN_MEASURABLE_SECONDS
        if measured_focus is not None:
            focus_score = measured_focus
        elif has_signal and meaningful:
            focus_score = max(
                0.0, 100.0 - 5.0 * warning_count - distracted_seconds / 60.0 * 2.0
            )
        else:
            focus_score = 0.0  # unmeasured — no fake perfect score
        if measured_engagement is not None:
            engagement_score = measured_engagement
        elif focus_score > 0:
            engagement_score = focus_score
        else:
            engagement_score = 0.0
        focus_score = round(min(100.0, max(0.0, focus_score)), 1)
        engagement_score = round(min(100.0, max(0.0, engagement_score)), 1)

        # AI summary is best-effort: a real LLM call when configured (bounded
        # so session completion stays snappy), an honest deterministic
        # fallback otherwise.
        ai_summary = ""
        try:
            import asyncio as _asyncio

            from deeptutor.services.llm.factory import complete

            prompt = (
                "Generate a brief, encouraging study summary (max 3 sentences) for this session.\n"
                f"Subject: {session.get('subject')}\n"
                f"Duration minutes: {actual_duration // 60}\n"
                f"Productive minutes: {productive_seconds // 60}\n"
                f"Distraction warnings: {warning_count}\n"
            )
            ai_summary = str(await _asyncio.wait_for(complete(prompt=prompt), timeout=6.0))[:600]
        except Exception as e:  # noqa: BLE001
            logger.info(f"AI summary skipped ({e}); using deterministic text.")
            ai_summary = (
                f"You studied {session.get('subject', 'General')} for {actual_duration // 60} minutes "
                f"with {warning_count} focus warning(s). Productive time: {int(productive_seconds) // 60} min."
            )

        now = time.time()
        if focus_score <= 0:
            # Unmeasured stub (too short / monitoring never ran): persist the
            # row for shape-compat but say so honestly instead of faking 100.
            ai_summary = (
                f"You studied {session.get('subject', 'General')} for "
                f"{actual_duration // 60} minute(s). Focus could not be measured "
                f"— the session was too short or monitoring was not active."
            )
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM session_reports WHERE session_id = ?", (session_id,))
            await db.execute(
                """INSERT INTO session_reports (
                       id, session_id, student_id, focus_score, engagement_score,
                       total_study_seconds, productive_seconds, distracted_seconds,
                       topics_covered_json, key_strengths, areas_for_improvement,
                       ai_tutor_feedback, parent_notes, generated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?)""",
                (
                    uuid.uuid4().hex,
                    session_id,
                    student_id,
                    round(focus_score, 1),
                    round(engagement_score, 1),
                    actual_duration,
                    int(productive_seconds),
                    int(distracted_seconds),
                    json.dumps([session.get("subject", "General")]),
                    "",
                    "",
                    ai_summary,
                    now,
                ),
            )
            await db.commit()

        return await self.get_report(session_id)

    async def get_report(self, session_id: str) -> Dict[str, Any]:
        """Fetches the stored report row (real columns) for a session."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM session_reports WHERE session_id = ?", (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    data = dict(row)
                    try:
                        data["topics"] = json.loads(data.pop("topics_covered_json") or "[]")
                    except Exception:  # noqa: BLE001
                        data["topics"] = []
                        data.pop("topics_covered_json", None)
                    return data
        return {}

    async def list_reports(self, student_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Lists reports for a student."""
        reports: List[Dict[str, Any]] = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM session_reports WHERE student_id = ? ORDER BY generated_at DESC LIMIT ?",
                (student_id, limit),
            ) as cursor:
                async for row in cursor:
                    data = dict(row)
                    try:
                        data["topics"] = json.loads(data.pop("topics_covered_json") or "[]")
                    except Exception:  # noqa: BLE001
                        data["topics"] = []
                    reports.append(data)
        return reports
