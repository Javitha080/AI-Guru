from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(tags=["study-session"])


# Pydantic models for Study Sessions
class CreateSessionRequest(BaseModel):
    student_id: Optional[str] = "student-primary"
    title: str = "Custom Study Session"
    subject: Optional[str] = "General"
    duration: Optional[int] = None
    target_duration_seconds: Optional[int] = None


class SessionResponse(BaseModel):
    id: str
    student_id: str
    title: str
    subject: str
    target_duration_seconds: int
    status: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None


class PaginatedSessionHistory(BaseModel):
    items: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int


class SessionReportResponse(BaseModel):
    session_id: str
    summary: str
    xp_earned: Optional[int] = None
    metrics: Dict[str, Any]


# Pydantic models for Gamification
class ProfileResponse(BaseModel):
    student_id: str
    xp: int
    level: int
    level_title: str
    streak: int
    total_sessions: int


class BadgeResponse(BaseModel):
    id: str
    name: str
    description: str
    icon_url: str
    earned: bool
    earned_at: Optional[float] = None


class RewardHistoryResponse(BaseModel):
    items: List[Dict[str, Any]]


class StudentNameRequest(BaseModel):
    student_name: str
    student_id: Optional[str] = "student-primary"


class StudentNameResponse(BaseModel):
    student_id: str
    student_name: str
    success: bool = True


def _mgr():
    from deeptutor.services.study.session_manager import StudySessionManager

    return StudySessionManager()


def _not_found(session_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Study session '{session_id}' not found")


async def _resolve_student_name(student_id: str, db_path=None) -> str:
    """Display name for parent notifications & reports: the wizard's supervision-rules
    entry when present, else users.display_name, else a capitalized tail of student id."""
    try:
        import json as _json

        import aiosqlite

        if db_path is None:
            from deeptutor.services.path_service import get_path_service

            db_path = get_path_service().user_dir / "chat_history.db"
        async with aiosqlite.connect(db_path) as db:
            from deeptutor.services.remote.kv_settings import ensure_kv_settings

            await ensure_kv_settings(db)
            cursor = await db.execute(
                "SELECT value FROM settings WHERE key = ?", ("supervision_rules_default",)
            )
            row = await cursor.fetchone()
            if row and row[0]:
                rules = _json.loads(row[0])
                name = str(rules.get("student_name") or "").strip()
                if name:
                    return name

            # Fallback to users table display_name
            user_id = f"user-{student_id}"
            cursor2 = await db.execute(
                "SELECT display_name FROM users WHERE id = ? OR username = ?",
                (user_id, f"student:{student_id}"),
            )
            user_row = await cursor2.fetchone()
            if user_row and user_row[0]:
                u_name = str(user_row[0]).strip()
                if u_name and u_name != student_id and not u_name.startswith("student:"):
                    return u_name
    except Exception:  # noqa: BLE001 - notification naming is best-effort
        pass
    return (student_id or "Student").split("-")[-1].capitalize() or "Student"


@router.post("/", response_model=Dict[str, Any])
@router.post("", response_model=Dict[str, Any])
async def create_session(req: CreateSessionRequest):
    """Create a new study session."""
    student_id = req.student_id or "student-primary"
    target_secs = req.target_duration_seconds or ((req.duration or 25) * 60)
    subject = req.subject or "General"
    title = req.title or "Study Session"

    try:
        return await _mgr().create_session(
            student_id=student_id,
            title=title,
            subject=subject,
            target_duration_seconds=target_secs,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Failed to create study session: {exc}"
        ) from exc


@router.get("/history/{student_id}", response_model=PaginatedSessionHistory)
async def list_past_sessions(
    student_id: str, limit: int = Query(20, ge=1), offset: int = Query(0, ge=0)
):
    """List past sessions with pagination."""
    try:
        return await _mgr().list_sessions(student_id, limit, offset)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to list sessions: {exc}") from exc


@router.get("/gamification/{student_id}/profile", response_model=ProfileResponse)
async def get_profile(student_id: str):
    """Get gamification profile."""
    from deeptutor.services.gamification.gamification_service import GamificationService

    try:
        return await GamificationService.get_profile(student_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to load profile: {exc}") from exc


@router.get("/gamification/{student_id}/badges", response_model=List[BadgeResponse])
async def get_badges(student_id: str):
    """Get all badges with earned/locked status."""
    from deeptutor.services.gamification.gamification_service import GamificationService

    try:
        return await GamificationService.get_badges(student_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to load badges: {exc}") from exc


@router.get("/gamification/{student_id}/rewards", response_model=RewardHistoryResponse)
async def get_rewards(student_id: str):
    """Get recent reward history."""
    from deeptutor.services.gamification.gamification_service import GamificationService

    try:
        return await GamificationService.get_rewards(student_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to load rewards: {exc}") from exc


@router.get("/student/name", response_model=StudentNameResponse)
async def get_student_name(student_id: str = "student-primary"):
    """Get the configured display name for the student."""
    name = await _resolve_student_name(student_id)
    return StudentNameResponse(student_id=student_id, student_name=name)


@router.post("/student/name", response_model=StudentNameResponse)
async def set_student_name(req: StudentNameRequest):
    """Set the display name for the student, updating settings and users table."""
    raw_name = req.student_name.strip()
    name = raw_name if raw_name else "Student"
    student_id = (req.student_id or "student-primary").strip() or "student-primary"

    try:
        import json as _json
        import time as _time

        import aiosqlite

        from deeptutor.services.path_service import get_path_service
        from deeptutor.services.remote.kv_settings import ensure_kv_settings

        db_path = get_path_service().user_dir / "chat_history.db"
        now = _time.time()
        user_id = f"user-{student_id}"

        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)

            # 1. Update supervision_rules_default in settings table
            cursor = await db.execute(
                "SELECT value FROM settings WHERE key = ?", ("supervision_rules_default",)
            )
            row = await cursor.fetchone()
            rules = {}
            if row and row[0]:
                try:
                    rules = _json.loads(row[0])
                except Exception:
                    rules = {}
            rules["student_name"] = name
            rules["updated_at"] = now
            if "daily_goal_minutes" not in rules:
                rules["daily_goal_minutes"] = 60
            if "alert_strictness" not in rules:
                rules["alert_strictness"] = "balanced"

            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, 'supervision', ?)",
                ("supervision_rules_default", _json.dumps(rules), now),
            )

            # 2. Update users table and students table (FK safe)
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.execute(
                "INSERT OR IGNORE INTO users (id, username, password_hash, role, display_name, avatar_url, created_at, updated_at)"
                " VALUES (?, ?, '', 'student', ?, '', ?, ?)",
                (user_id, f"student:{student_id}", name, now, now),
            )
            await db.execute(
                "UPDATE users SET display_name = ?, updated_at = ? WHERE id = ? OR username = ?",
                (name, now, user_id, f"student:{student_id}"),
            )
            await db.execute(
                "INSERT OR IGNORE INTO students (id, user_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (student_id, user_id, now, now),
            )
            await db.commit()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save student name: {exc}") from exc

    return StudentNameResponse(student_id=student_id, student_name=name)


@router.get("/{session_id}", response_model=Dict[str, Any])
async def get_session(session_id: str):
    """Get session details."""
    session = await _mgr().get_session(session_id)
    if not session:
        raise _not_found(session_id)
    return session


@router.post("/{session_id}/start", response_model=Dict[str, Any])
async def start_session(session_id: str):
    """Start session timer + notify parent (queued, survives offline)."""

    try:
        result = await _mgr().start_session(session_id)
    except KeyError:
        raise _not_found(session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to start session: {exc}") from exc

    try:
        from deeptutor.services.monitoring.notification_queue import (
            enqueue,
            flush_once,
            start_notification_worker,
        )

        student_name = await _resolve_student_name(
            str(result.get("student_id") or "student-primary")
        )
        start_notification_worker()
        await enqueue(
            "session_start",
            {
                "session_id": session_id,
                "student_name": student_name,
                "subject": result.get("subject", "General"),
                "target_minutes": round((result.get("target_duration_seconds") or 1500) / 60),
            },
        )
        from deeptutor.services.background import spawn_bg

        spawn_bg(flush_once(limit=1), name=f"session-start-flush-{session_id}")
    except Exception:  # noqa: BLE001
        pass  # parent notification is best-effort; never blocks the start
    return result


@router.post("/{session_id}/pause", response_model=Dict[str, Any])
async def pause_session(session_id: str):
    """Pause session."""
    try:
        result = await _mgr().pause_session(session_id)
    except KeyError:
        raise _not_found(session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to pause session: {exc}") from exc
    await _log_lifecycle_event(session_id, "SESSION_PAUSED")
    return result


@router.post("/{session_id}/resume", response_model=Dict[str, Any])
async def resume_session(session_id: str):
    """Resume session."""
    try:
        result = await _mgr().resume_session(session_id)
    except KeyError:
        raise _not_found(session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to resume session: {exc}") from exc
    await _log_lifecycle_event(session_id, "SESSION_RESUMED")
    return result


@router.post("/{session_id}/stop", response_model=Dict[str, Any])
async def stop_session(session_id: str):
    """Stop session, then await report generation + XP award (bounded).

    Awaiting keeps the completion screen's immediate GET /report truthful:
    stored feedback and xp_earned are already persisted when this returns.
    """
    import asyncio

    try:
        result = await _mgr().stop_session(session_id)
    except KeyError:
        raise _not_found(session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to stop session: {exc}") from exc

    try:
        from deeptutor.services.monitoring.dispatch import handle_session_completed

        student_id = str((result or {}).get("student_id") or "student-primary")
        await asyncio.wait_for(
            handle_session_completed(session_id, student_id),
            timeout=8.0,
        )
    except asyncio.TimeoutError:
        # Report generation still finishes in the background task spawned by
        # handle_session_completed internals; the client falls back gracefully.
        pass
    except Exception:  # noqa: BLE001
        pass  # completion side-effects are failure-isolated by design
    return result


@router.post("/{session_id}/abandon", response_model=Dict[str, Any])
async def abandon_session(session_id: str):
    """Abandon session (no XP)."""
    try:
        return await _mgr().abandon_session(session_id)
    except KeyError:
        raise _not_found(session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to abandon session: {exc}") from exc


@router.get("/{session_id}/report", response_model=SessionReportResponse)
async def get_session_report(session_id: str):
    """Get session report."""
    try:
        report = await _mgr().get_session_report(session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to build report: {exc}") from exc
    if not report:
        raise _not_found(session_id)
    return report


async def _log_lifecycle_event(session_id: str, event_type: str) -> None:
    """Persists SESSION_PAUSED / SESSION_RESUMED into monitoring_events."""
    try:
        from deeptutor.services.study.telemetry_logger import TelemetryLogger

        await TelemetryLogger().log_event(
            session_id=session_id,
            event_type=event_type,
            severity="info",
            confidence=1.0,
            duration_seconds=0.0,
            metadata={"source": "study_session_router"},
        )
    except Exception:  # noqa: BLE001
        pass  # telemetry must never block lifecycle transitions
