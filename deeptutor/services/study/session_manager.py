from __future__ import annotations

import logging
import time
from typing import Any, Dict, List
import uuid

import aiosqlite

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)


class SessionStateError(ValueError):
    """Illegal lifecycle transition (router maps to HTTP 409)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


# Sessions with no meaningful activity are never scored — a synthesized
# 100 would be a fake report. Below this the report records focus 0
# (unmeasured) with honest feedback text instead of a formula score.
MIN_MEASURABLE_SECONDS = 60

# Idle wall-clock after which an open session is presumed leaked (browser
# closed, stop never called). Lazy-swept to 'abandoned' on read so the
# parent dashboard never sums unbounded phantom minutes.
STALE_SESSION_SECONDS = 2 * 3600

TERMINAL_STATUSES = ("completed", "abandoned")


class StudySessionManager:
    """Manages the lifecycle of study sessions."""

    def __init__(self) -> None:
        self.db_path = get_path_service().user_dir / "chat_history.db"
        # Structural open-guard: a missing parent dir surfaces from sqlite as
        # the cryptic "unable to open database file". Ensure it up front so
        # fresh installs / wiped dirs fail loudly here instead of mid-write.
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Study DB parent not writable: %s", exc)

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

    async def create_session(
        self,
        student_id: str,
        title: str,
        subject: str,
        target_duration_seconds: int,
        paper_id: str | None = None,
        bank_paper_id: str | None = None,
        grade: int | None = None,
        is_custom_exam: bool = False,
        monitoring_enabled: bool = True,
    ) -> Dict[str, Any]:
        """Creates a new study session.

        The V1 schema has no 'created' status and requires ``start_time`` on
        every row, so creation immediately enters ``in_progress`` for schema
        compatibility — but ``last_resume_time`` stays NULL until the
        explicit /start call opens the first active stretch. Live duration
        helpers (``live_duration_seconds``) therefore report 0 for the idle
        gap between create and start instead of phantom study minutes.

        Paper linkage (v10 columns) is best-effort: older DBs without the
        migration still create the session, just without the linkage.
        """
        session_id = uuid.uuid4().hex
        now = time.time()

        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_student(db, student_id)
            await db.execute(
                """INSERT INTO study_sessions (id, student_id, title, subject, target_duration_seconds, status, start_time, last_resume_time, created_at, focus_score, engagement_score, distraction_count, warning_count)
                   VALUES (?, ?, ?, ?, ?, 'in_progress', ?, NULL, ?, 0, 0, 0, 0)""",
                (session_id, student_id, title, subject, target_duration_seconds, now, now),
            )
            await db.commit()
            # v10 paper linkage — tolerate pre-migration DBs.
            try:
                async with db.execute("PRAGMA table_info(study_sessions)") as cur:
                    cols = {row[1] for row in await cur.fetchall()}
                updates: dict[str, Any] = {}
                if "paper_id" in cols and paper_id:
                    updates["paper_id"] = str(paper_id)[:128]
                if "bank_paper_id" in cols and bank_paper_id:
                    updates["bank_paper_id"] = str(bank_paper_id)[:128]
                if "grade" in cols and grade is not None:
                    try:
                        updates["grade"] = int(grade)
                    except (TypeError, ValueError):
                        pass
                if "is_custom_exam" in cols and is_custom_exam:
                    updates["is_custom_exam"] = 1
                # v13 monitoring flag — honest offline sessions persist 0 so
                # reports/dashboards never present them as measured focus.
                # Tolerates pre-migration DBs like the v10 linkage above.
                if "monitoring_enabled" in cols and not monitoring_enabled:
                    updates["monitoring_enabled"] = 0
                if updates:
                    sets = ", ".join(f"{k} = ?" for k in updates)
                    await db.execute(
                        f"UPDATE study_sessions SET {sets} WHERE id = ?",
                        (*updates.values(), session_id),
                    )
                    await db.commit()
            except Exception:
                pass

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
        """Starts a study session (opens the first active stretch).

        Idempotent: re-starting an already-active session keeps the original
        ``start_time`` (rewriting it would destroy the wall-clock ceiling
        that caps reported duration). Terminal sessions raise
        SessionStateError (409).
        """
        session = await self._require_session(session_id)
        if session.get("status") in TERMINAL_STATUSES:
            raise SessionStateError(f"session is {session.get('status')}, cannot start")
        now = time.time()
        if session.get("status") == "in_progress" and session.get("last_resume_time"):
            return session  # already open — no-op
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE study_sessions SET status = 'in_progress', last_resume_time = ? WHERE id = ?",
                (now, session_id),
            )
            await db.commit()
        return await self._require_session(session_id)

    async def pause_session(self, session_id: str) -> Dict[str, Any]:
        """Pauses a study session, banking the active stretch into worked_seconds.

        ``worked_seconds`` accumulates only time actually spent studying; the
        paused wall-clock between pause and resume is excluded from duration
        and XP. Idempotent for already-paused rows; terminal rows raise
        SessionStateError (409).
        """
        session = await self._require_session(session_id)
        if session.get("status") in TERMINAL_STATUSES:
            raise SessionStateError(f"session is {session.get('status')}, cannot pause")
        if session.get("status") == "paused":
            return session  # idempotent — already banked
        now = time.time()
        worked = float(session.get("worked_seconds") or 0.0)
        last_resume = session.get("last_resume_time")
        if session.get("status") == "in_progress" and last_resume:
            worked += max(0.0, now - float(last_resume))
        # Defensive ceiling: never bank more than elapsed wall-clock.
        start_time = session.get("start_time")
        if start_time:
            worked = min(worked, max(0.0, now - float(start_time)))
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE study_sessions SET status = 'paused', worked_seconds = ?, last_resume_time = NULL WHERE id = ?",
                (worked, session_id),
            )
            await db.commit()
        return await self._require_session(session_id)

    async def resume_session(self, session_id: str) -> Dict[str, Any]:
        """Resumes a paused study session (opens a fresh active stretch).

        Idempotent for already-active rows (double-tap safe); terminal rows
        and rows that were never started raise SessionStateError (409).
        """
        session = await self._require_session(session_id)
        if session.get("status") in TERMINAL_STATUSES:
            raise SessionStateError(f"session is {session.get('status')}, cannot resume")
        if session.get("status") == "in_progress" and session.get("last_resume_time"):
            return session  # idempotent — stretch already open
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE study_sessions SET status = 'in_progress', last_resume_time = ? WHERE id = ?",
                (now, session_id),
            )
            await db.commit()
        return await self._require_session(session_id)

    async def stop_session(self, session_id: str) -> Dict[str, Any]:
        """Stops a study session and records the pause-aware actual duration.

        Idempotent: stopping an already-completed session returns it
        unchanged (callers must not double-award XP on retry). Stopping an
        abandoned session raises SessionStateError (409) — abandoned is
        terminal and must never rewrite history.
        """
        session = await self._require_session(session_id)
        if session.get("status") == "completed":
            return session  # idempotent — no re-bank, no XP side-effect
        if session.get("status") == "abandoned":
            raise SessionStateError("session is abandoned, cannot stop")
        now = time.time()
        worked = float(session.get("worked_seconds") or 0.0)
        last_resume = session.get("last_resume_time")
        if session.get("status") == "in_progress" and last_resume:
            # Close the final open active stretch.
            worked += max(0.0, now - float(last_resume))
        # 'paused' rows already banked their stretch in pause_session.

        start_time = session.get("start_time")
        # Defensive ceiling: never report more than elapsed wall-clock,
        # even if the system clock jumps between resume and stop.
        wall = int(now - start_time) if start_time else 0
        actual_duration = min(int(worked), max(0, wall))

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE study_sessions SET status = 'completed', end_time = ?, actual_duration_seconds = ?, worked_seconds = ?, last_resume_time = NULL WHERE id = ?",
                (now, actual_duration, worked, session_id),
            )
            await db.commit()
        return await self._require_session(session_id)

    async def abandon_session(self, session_id: str) -> Dict[str, Any]:
        """Marks a session as abandoned (no XP, no report).

        Terminal guard: abandoning a completed session raises
        SessionStateError (409) — completed history is immutable.
        Idempotent for already-abandoned rows.
        """
        session = await self._require_session(session_id)
        if session.get("status") == "completed":
            raise SessionStateError("session is completed, cannot abandon")
        if session.get("status") == "abandoned":
            return session  # idempotent
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE study_sessions SET status = 'abandoned', end_time = ?, last_resume_time = NULL WHERE id = ?",
                (time.time(), session_id),
            )
            await db.commit()
        return await self._require_session(session_id)

    async def retarget_session(self, session_id: str, target_duration_seconds: int) -> Dict[str, Any]:
        """Adopts a new countdown target (e.g. a past paper's own duration).

        Only open sessions (in_progress/paused) may retarget — terminal rows
        raise SessionStateError (409) so completed history stays immutable.
        Bounds-checked: out-of-range targets raise ValueError (router maps to
        422) instead of corrupting remaining-time math. Banked
        worked_seconds are untouched; remaining time is recomputed from the
        new target on the next read.
        """
        try:
            target = int(target_duration_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"target_duration_seconds must be an integer: {exc}") from exc
        if isinstance(target_duration_seconds, bool) or not 60 <= target <= 8 * 3600:
            raise ValueError("target_duration_seconds must be 60-28800")
        session = await self._require_session(session_id)
        if session.get("status") in TERMINAL_STATUSES:
            raise SessionStateError(
                f"session is {session.get('status')}, cannot retarget"
            )
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE study_sessions SET target_duration_seconds = ? WHERE id = ?",
                (target, session_id),
            )
            await db.commit()
        return await self._require_session(session_id)

    async def get_session(self, session_id: str) -> Dict[str, Any]:
        """Retrieves a session by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM study_sessions WHERE id = ?", (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
        return {}

    async def list_sessions(
        self, student_id: str, limit: int = 20, offset: int = 0
    ) -> Dict[str, Any]:
        """Lists sessions for a student (paginated payload matching the router model).

        Runs the lazy stale sweep first so leaked 'in_progress' rows never
        inflate the parent dashboard with unbounded phantom minutes.
        """
        try:
            await self.sweep_stale_sessions()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Stale sweep skipped for %s: %s", student_id, exc)
        items: List[Dict[str, Any]] = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT COUNT(*) AS n FROM study_sessions WHERE student_id = ?", (student_id,)
            ) as cursor:
                total = int((await cursor.fetchone())["n"])
            async with db.execute(
                "SELECT * FROM study_sessions WHERE student_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (student_id, limit, offset),
            ) as cursor:
                async for row in cursor:
                    items.append(dict(row))
        return {"items": items, "total": total, "limit": int(limit), "offset": int(offset)}

    async def update_scores(
        self,
        session_id: str,
        focus_score: float,
        engagement_score: float,
        distraction_count: int,
        warning_count: int,
    ) -> None:
        """Updates the running scores of a session (range-validated).

        Out-of-range scores and negative counters are programmer errors from
        the CV pipeline — rejected (ValueError) instead of persisted, so a
        buggy frame can never write a fake 999% focus into the parent board.
        """
        try:
            focus = float(focus_score)
            engagement = float(engagement_score)
            distractions = int(distraction_count)
            warnings = int(warning_count)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"non-numeric score payload: {exc}") from exc
        if not (0.0 <= focus <= 100.0):
            raise ValueError(f"focus_score {focus} out of range 0-100")
        if not (0.0 <= engagement <= 100.0):
            raise ValueError(f"engagement_score {engagement} out of range 0-100")
        if distractions < 0 or warnings < 0:
            raise ValueError("distraction/warning counts must be >= 0")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE study_sessions SET focus_score = ?, engagement_score = ?, distraction_count = ?, warning_count = ? WHERE id = ?",
                (focus, engagement, distractions, warnings, session_id),
            )
            await db.commit()

    async def pause_on_disconnect(self, session_id: str) -> Dict[str, Any]:
        """Best-effort banking when the monitoring socket drops.

        Called from the WS disconnect path: an 'in_progress' row with an open
        stretch would otherwise keep accruing phantom minutes forever. Only
        touches 'in_progress' rows; everything else (paused/terminal) is
        returned untouched. Never raises — disconnect cleanup must not crash.
        """
        try:
            session = await self.get_session(session_id)
            if not session or session.get("status") != "in_progress":
                return session
            return await self.pause_session(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("pause_on_disconnect skipped for %s: %s", session_id, exc)
            return {}

    async def sweep_stale_sessions(
        self, older_than_seconds: float = STALE_SESSION_SECONDS, limit: int = 200
    ) -> int:
        """Abandons leaked open sessions idle longer than the threshold.

        Lazy reaper for browsers closed without stop: any 'in_progress' /
        'paused' row whose last activity (last_resume_time, else start_time,
        else created_at) is older than the threshold becomes 'abandoned' with
        its banked worked_seconds preserved. Returns the count swept.
        """
        now = time.time()
        cutoff = now - older_than_seconds
        swept = 0
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, status, start_time, created_at, last_resume_time,"
                " COALESCE(worked_seconds, 0) AS worked"
                " FROM study_sessions WHERE status IN ('in_progress', 'paused')"
                " ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = [dict(r) for r in await cursor.fetchall()]
            for row in rows:
                last_activity = (
                    row.get("last_resume_time")
                    or row.get("start_time")
                    or row.get("created_at")
                    or 0
                )
                try:
                    idle = now - float(last_activity)
                except (TypeError, ValueError):
                    idle = older_than_seconds + 1  # corrupt clock → sweep it
                if idle < older_than_seconds:
                    continue
                # Bank any open stretch before closing (capped at wall-clock).
                worked = float(row.get("worked") or 0.0)
                if row.get("status") == "in_progress" and row.get("last_resume_time"):
                    try:
                        worked += max(0.0, now - float(row["last_resume_time"]))
                    except (TypeError, ValueError):
                        pass
                    try:
                        if row.get("start_time"):
                            worked = min(worked, max(0.0, now - float(row["start_time"])))
                    except (TypeError, ValueError):
                        pass
                await db.execute(
                    "UPDATE study_sessions SET status = 'abandoned', end_time = ?,"
                    " actual_duration_seconds = ?, worked_seconds = ?,"
                    " last_resume_time = NULL WHERE id = ? AND status IN"
                    " ('in_progress', 'paused')",
                    (now, int(worked), worked, row["id"]),
                )
                swept += 1
            await db.commit()
        if swept:
            logger.info("Swept %d stale study session(s) to abandoned", swept)
        return swept

    async def get_session_report(self, session_id: str) -> Dict[str, Any]:
        """Assembles the report payload consumed by GET /{session_id}/report.

        Honest-null contract: unmeasured scores are None (never a synthesized
        0/100), and the summary is empty when no stored report exists — the
        old fabricated "Session on X: N min" fallback is gone. Callers
        distinguish pending vs ready via ``report_ready``/``reason``.
        """
        try:
            await self.sweep_stale_sessions()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Stale sweep skipped for %s: %s", session_id, exc)
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
        distraction_count = int(summary_counts.get("by_type", {}).get("LOOKING_AWAY", 0)) + int(
            summary_counts.get("by_type", {}).get("PHONE_DETECTED", 0)
        )

        def _honest_score(raw: Any, stored_value: Any = None) -> float | None:
            """Map unmeasured 0/NULL to None; keep real measurements."""
            has_telem = bool(
                summary_counts.get("total_events", 0) > 0 or warnings > 0 or distraction_count > 0
            )
            for candidate in (stored_value, raw):
                try:
                    value = float(candidate) if candidate is not None else None
                except (TypeError, ValueError):
                    continue
                if value is not None and (value > 0 or (value == 0.0 and has_telem)):
                    return round(value, 1)
            return None

        stored_focus = (stored or {}).get("focus_score")
        stored_engagement = (stored or {}).get("engagement_score")
        metrics = {
            "focus_score": _honest_score(session.get("focus_score"), stored_focus),
            "engagement_score": _honest_score(
                session.get("engagement_score"), stored_engagement
            ),
            "distraction_count": max(distraction_count, int(session.get("distraction_count") or 0)),
            "warning_count": max(warnings, int(session.get("warning_count") or 0)),
            "actual_duration_seconds": session.get("actual_duration_seconds") or 0,
            "subject": session.get("subject"),
        }
        if stored:
            summary_text = stored.get("ai_tutor_feedback") or ""
            reason = ""
            report_ready = True
        elif session.get("status") == "abandoned":
            summary_text = ""
            reason = "abandoned"
            report_ready = False
        elif session.get("status") in ("in_progress", "paused"):
            summary_text = ""
            reason = "in_progress"
            report_ready = False
        else:
            summary_text = ""
            reason = "not_generated"
            report_ready = False
        xp_earned = await self._session_xp(session_id)
        return {
            "session_id": session_id,
            "summary": summary_text,
            "xp_earned": xp_earned,
            "metrics": metrics,
            "stored_report_available": bool(stored),
            "report_ready": report_ready,
            "reason": reason,
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
