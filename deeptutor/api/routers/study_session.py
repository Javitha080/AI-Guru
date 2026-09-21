import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from deeptutor.api.routers.auth import require_auth
from deeptutor.api.routers.ownership import (
    _is_local_admin,
    require_session_owner,
    require_student_owner,
    resolve_student_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["study-session"])

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_STUDENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Target durations outside this window are rejected: <=0/negative would
# corrupt averages, multi-day values are never real study sessions.
MIN_TARGET_SECONDS = 60
MAX_TARGET_SECONDS = 8 * 3600


def _check_session_id(session_id: str) -> None:
    if not _SESSION_ID_RE.match(session_id or ""):
        raise HTTPException(status_code=422, detail="Invalid session_id format")


def _check_student_id(student_id: str) -> None:
    if not _STUDENT_ID_RE.match(student_id or ""):
        raise HTTPException(status_code=422, detail="Invalid student_id format")


# Pydantic models for Study Sessions
class CreateSessionRequest(BaseModel):
    student_id: Optional[str] = "student-primary"
    title: str = "Custom Study Session"
    subject: Optional[str] = "General"
    duration: Optional[int] = None
    target_duration_seconds: Optional[int] = None
    # Paper linkage persisted via v10 columns on study_sessions.
    monitoring_enabled: Optional[bool] = None
    paper_id: Optional[str] = None
    bank_paper_id: Optional[str] = None
    grade: Optional[int] = None
    is_custom_exam: Optional[bool] = None

    @field_validator("paper_id", "bank_paper_id")
    @classmethod
    def paper_id_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if not _SESSION_ID_RE.match(v):
            raise ValueError("Invalid paper id format")
        return v

    @field_validator("grade")
    @classmethod
    def grade_valid(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if not isinstance(v, int) or isinstance(v, bool):
            raise ValueError("grade must be an integer")
        if v < 1 or v > 13:
            raise ValueError("grade must be 1-13")
        return v

    @field_validator("student_id")
    @classmethod
    def student_id_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not _STUDENT_ID_RE.match(v):
            raise ValueError("Invalid student_id format")
        return v

    @field_validator("title")
    @classmethod
    def title_valid(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("title must not be empty")
        if len(v) > 120:
            raise ValueError("title must be at most 120 characters")
        return v

    @field_validator("subject")
    @classmethod
    def subject_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if len(v) > 60:
            raise ValueError("subject must be at most 60 characters")
        return v or "General"

    @field_validator("duration")
    @classmethod
    def duration_valid(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if not isinstance(v, int) or isinstance(v, bool):
            raise ValueError("duration must be an integer number of minutes")
        if v < 1 or v > 480:
            raise ValueError("duration must be 1-480 minutes")
        return v

    @field_validator("target_duration_seconds")
    @classmethod
    def target_valid(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if not isinstance(v, int) or isinstance(v, bool):
            raise ValueError("target_duration_seconds must be an integer")
        if v < MIN_TARGET_SECONDS or v > MAX_TARGET_SECONDS:
            raise ValueError(
                f"target_duration_seconds must be {MIN_TARGET_SECONDS}-{MAX_TARGET_SECONDS}"
            )
        return v


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


def _state_conflict(exc: Exception) -> HTTPException:
    """Maps SessionStateError to 409 (terminal/illegal transitions)."""
    detail = getattr(exc, "detail", None) or str(exc) or "Illegal session transition"
    return HTTPException(status_code=409, detail=detail)


async def _resolve_student_name(student_id: str, db_path=None) -> str:
    """Display name for parent notifications & reports.

    Delegates to the shared supervision-rules resolver: linked parents'
    overrides first, then the canonical default row, then users table.
    Never raises — notification naming is best-effort.
    """
    try:
        from deeptutor.services.remote.supervision_rules import resolve_student_name

        return await resolve_student_name(student_id, db_path=db_path)
    except Exception:  # noqa: BLE001 - notification naming is best-effort
        pass
    return (student_id or "Student").split("-")[-1].capitalize() or "Student"


@router.post("/", response_model=Dict[str, Any])
@router.post("", response_model=Dict[str, Any])
@router.post("/create", response_model=Dict[str, Any])
async def create_session(
    req: CreateSessionRequest,
    user: Any = Depends(require_auth),
):
    """Create a new study session (paper linkage persisted via v10 columns)."""
    student_id = (
        resolve_student_id(user)
        if not _is_local_admin(user)
        else (req.student_id or "student-primary").strip() or "student-primary"
    )
    _check_student_id(student_id)
    target_secs = req.target_duration_seconds or ((req.duration or 25) * 60)
    if target_secs < MIN_TARGET_SECONDS or target_secs > MAX_TARGET_SECONDS:
        raise HTTPException(
            status_code=422,
            detail=f"target_duration_seconds must be {MIN_TARGET_SECONDS}-{MAX_TARGET_SECONDS}",
        )
    subject = (req.subject or "General").strip() or "General"
    title = (req.title or "Study Session").strip() or "Study Session"
    paper_id = (req.paper_id or "").strip() or None
    bank_paper_id = (req.bank_paper_id or "").strip() or None
    for pid, label in ((paper_id, "paper_id"), (bank_paper_id, "bank_paper_id")):
        if pid is not None and not _SESSION_ID_RE.match(pid):
            raise HTTPException(status_code=422, detail=f"Invalid {label} format")
    grade = req.grade
    if grade is not None and (not isinstance(grade, int) or isinstance(grade, bool) or grade < 1 or grade > 13):
        raise HTTPException(status_code=422, detail="grade must be 1-13")

    try:
        return await _mgr().create_session(
            student_id=student_id,
            title=title,
            subject=subject,
            target_duration_seconds=target_secs,
            paper_id=paper_id,
            bank_paper_id=bank_paper_id,
            grade=grade,
            is_custom_exam=bool(req.is_custom_exam),
            monitoring_enabled=False if req.monitoring_enabled is False else True,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Failed to create study session: {exc}"
        ) from exc


@router.get("/history/{student_id}", response_model=PaginatedSessionHistory)
async def list_past_sessions(
    student_id: str,
    _owner: str = Depends(require_student_owner),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List past sessions with pagination."""
    _check_student_id(student_id)
    try:
        return await _mgr().list_sessions(student_id, limit, offset)
    except Exception as exc:  # noqa: BLE001
        logger.exception("List sessions failed for %s: %s", student_id, exc)
        raise HTTPException(status_code=500, detail="Could not list sessions. Try again.") from exc


@router.get("/gamification/{student_id}/profile", response_model=ProfileResponse)
async def get_profile(
    student_id: str,
    _owner: str = Depends(require_student_owner),
):
    """Get gamification profile."""
    from deeptutor.services.gamification.gamification_service import GamificationService

    try:
        return await GamificationService.get_profile(student_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Load profile failed for %s: %s", student_id, exc)
        raise HTTPException(status_code=500, detail="Could not load profile. Try again.") from exc


@router.get("/gamification/{student_id}/badges", response_model=List[BadgeResponse])
async def get_badges(
    student_id: str,
    _owner: str = Depends(require_student_owner),
):
    """Get all badges with earned/locked status."""
    from deeptutor.services.gamification.gamification_service import GamificationService

    try:
        return await GamificationService.get_badges(student_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Load badges failed for %s: %s", student_id, exc)
        raise HTTPException(status_code=500, detail="Could not load badges. Try again.") from exc


@router.get("/gamification/{student_id}/rewards", response_model=RewardHistoryResponse)
async def get_rewards(
    student_id: str,
    _owner: str = Depends(require_student_owner),
):
    """Get recent reward history."""
    from deeptutor.services.gamification.gamification_service import GamificationService

    try:
        return await GamificationService.get_rewards(student_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Load rewards failed for %s: %s", student_id, exc)
        raise HTTPException(status_code=500, detail="Could not load rewards. Try again.") from exc


@router.get("/student/name", response_model=StudentNameResponse)
async def get_student_name(
    student_id: str = "student-primary",
    user: Any = Depends(require_auth),
):
    """Get the configured display name for the student."""
    resolved = resolve_student_id(user) if not _is_local_admin(user) else student_id
    name = await _resolve_student_name(resolved)
    return StudentNameResponse(student_id=resolved, student_name=name)


@router.post("/student/name", response_model=StudentNameResponse)
async def set_student_name(
    req: StudentNameRequest,
    user: Any = Depends(require_auth),
):
    """Set the display name for the student, updating settings and users table.

    Legacy compatibility shim over the canonical ``/api/v1/user/profile``
    store: writes through the shared kv helper (dual-shape safe) and mirrors
    the name into ``users`` + ``supervision_rules_default``. When a real name
    (not the ``"Student"`` placeholder) is provided the per-student
    ``user_profile_configured`` flag is also set so onboarding gates agree.
    """
    raw_name = req.student_name.strip()
    name = raw_name if raw_name else "Student"
    student_id = (
        resolve_student_id(user)
        if not _is_local_admin(user)
        else (req.student_id or "student-primary").strip() or "student-primary"
    )

    try:
        import time as _time

        import aiosqlite

        from deeptutor.services.path_service import get_path_service
        from deeptutor.services.remote.kv_settings import (
            ensure_kv_settings,
            kv_get,
            kv_set,
        )

        db_path = get_path_service().user_dir / "chat_history.db"
        now = _time.time()
        user_id = f"user-{student_id}"

        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)

            # 1. Update supervision_rules_default via the shared kv helper
            # (dual-shape safe — never hand-roll settings SQL).
            import json as _json

            rules_raw = await kv_get(db, "supervision_rules_default")
            rules = {}
            if rules_raw:
                try:
                    rules = _json.loads(rules_raw) if isinstance(rules_raw, str) else {}
                except Exception:
                    rules = {}
            if not isinstance(rules, dict):
                rules = {}
            rules["student_name"] = name
            rules["updated_at"] = now
            if "daily_goal_minutes" not in rules:
                rules["daily_goal_minutes"] = 60
            if "alert_strictness" not in rules:
                rules["alert_strictness"] = "balanced"
            await kv_set(db, "supervision_rules_default", _json.dumps(rules), category="supervision")

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

            # 3. Keep onboarding gates consistent: a real name completes the
            # profile flag (placeholder "Student" never does on its own).
            if raw_name:
                from deeptutor.api.routers.user_profile import (
                    _LEGACY_CONFIGURED_KEY,
                    _configured_key,
                )

                await kv_set(
                    db,
                    _configured_key(student_id),
                    "true",
                    category="user_profile",
                )
                # Backward-compat: legacy global readers check the unscoped key.
                if _configured_key(student_id) != _LEGACY_CONFIGURED_KEY:
                    await kv_set(
                        db,
                        _LEGACY_CONFIGURED_KEY,
                        "true",
                        category="user_profile",
                    )
            await db.commit()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save student name: {exc}") from exc

    return StudentNameResponse(student_id=student_id, student_name=name)


@router.get("/{session_id}", response_model=Dict[str, Any])
async def get_session(
    session_id: str,
    _owner: str = Depends(require_session_owner),
):
    """Get session details."""
    _check_session_id(session_id)
    session = await _mgr().get_session(session_id)
    if not session:
        raise _not_found(session_id)
    return session


class RetargetSessionRequest(BaseModel):
    target_duration_seconds: int

    @field_validator("target_duration_seconds")
    @classmethod
    def target_valid(cls, v: int) -> int:
        if not isinstance(v, int) or isinstance(v, bool):
            raise ValueError("target_duration_seconds must be an integer")
        if v < MIN_TARGET_SECONDS or v > MAX_TARGET_SECONDS:
            raise ValueError(
                f"target_duration_seconds must be {MIN_TARGET_SECONDS}-{MAX_TARGET_SECONDS}"
            )
        return v


@router.patch("/{session_id}/target", response_model=Dict[str, Any])
async def retarget_session(
    session_id: str,
    req: RetargetSessionRequest,
    _owner: str = Depends(require_session_owner),
):
    """Adopt a new countdown target for an open session.

    Used when a student starts a past paper mid-session: the paper's own
    duration becomes the session target so the HUD clock and the server
    reconcile agree. Open sessions only — terminal rows reject with 409.
    """
    _check_session_id(session_id)
    try:
        return await _mgr().retarget_session(session_id, req.target_duration_seconds)
    except KeyError:
        raise _not_found(session_id)
    except ValueError as exc:
        from deeptutor.services.study.session_manager import SessionStateError

        if isinstance(exc, SessionStateError):
            raise _state_conflict(exc)
        raise HTTPException(status_code=422, detail=str(exc) or "Invalid target")
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Retarget failed for %s", session_id)
        raise HTTPException(status_code=500, detail="Could not update session target. Try again.")


@router.post("/{session_id}/start", response_model=Dict[str, Any])
async def start_session(
    session_id: str,
    _owner: str = Depends(require_session_owner),
):
    """Start session timer + notify parent (queued, survives offline)."""
    _check_session_id(session_id)

    try:
        result = await _mgr().start_session(session_id)
    except KeyError:
        raise _not_found(session_id)
    except ValueError as exc:
        # SessionStateError subclasses ValueError — import locally to avoid
        # router/service cycles at module import time.
        from deeptutor.services.study.session_manager import SessionStateError

        if isinstance(exc, SessionStateError):
            raise _state_conflict(exc)
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to start session: {exc}") from exc

    try:
        from deeptutor.services.monitoring.notification_queue import (
            enqueue_for_student,
            flush_once,
            start_notification_worker,
        )

        student_id = str(result.get("student_id") or "student-primary")
        student_name = await _resolve_student_name(student_id)
        start_notification_worker()
        await enqueue_for_student(
            "session_start",
            {
                "session_id": session_id,
                "student_id": student_id,
                "student_name": student_name,
                "subject": result.get("subject", "General"),
                "target_minutes": round((result.get("target_duration_seconds") or 1500) / 60),
            },
            student_id,
        )
        from deeptutor.services.background import spawn_bg

        spawn_bg(flush_once(limit=1), name=f"session-start-flush-{session_id}")
    except Exception:  # noqa: BLE001
        pass  # parent notification is best-effort; never blocks the start
    return result


@router.post("/{session_id}/pause", response_model=Dict[str, Any])
async def pause_session(
    session_id: str,
    _owner: str = Depends(require_session_owner),
):
    """Pause session."""
    _check_session_id(session_id)
    try:
        result = await _mgr().pause_session(session_id)
    except KeyError:
        raise _not_found(session_id)
    except ValueError as exc:
        from deeptutor.services.study.session_manager import SessionStateError

        if isinstance(exc, SessionStateError):
            raise _state_conflict(exc)
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to pause session: {exc}") from exc
    await _log_lifecycle_event(session_id, "SESSION_PAUSED")
    return result


@router.post("/{session_id}/resume", response_model=Dict[str, Any])
async def resume_session(
    session_id: str,
    _owner: str = Depends(require_session_owner),
):
    """Resume session."""
    _check_session_id(session_id)
    try:
        result = await _mgr().resume_session(session_id)
    except KeyError:
        raise _not_found(session_id)
    except ValueError as exc:
        from deeptutor.services.study.session_manager import SessionStateError

        if isinstance(exc, SessionStateError):
            raise _state_conflict(exc)
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to resume session: {exc}") from exc
    await _log_lifecycle_event(session_id, "SESSION_RESUMED")
    return result


@router.post("/{session_id}/stop", response_model=Dict[str, Any])
async def stop_session(
    session_id: str,
    _owner: str = Depends(require_session_owner),
):
    """Stop session, then await report generation + XP award (bounded).

    Awaiting keeps the completion screen's immediate GET /report truthful:
    stored feedback and xp_earned are already persisted when this returns.
    Re-stopping a completed session is a no-op success (no double XP, no duplicate side-effects).
    """
    import asyncio

    _check_session_id(session_id)
    session_before = await _mgr().get_session(session_id)
    was_completed = bool(session_before and session_before.get("status") == "completed")
    try:
        result = await _mgr().stop_session(session_id)
    except KeyError:
        raise _not_found(session_id)
    except ValueError as exc:
        from deeptutor.services.study.session_manager import SessionStateError

        if isinstance(exc, SessionStateError):
            raise _state_conflict(exc)
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to stop session: {exc}") from exc

    if not was_completed:
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
async def abandon_session(
    session_id: str,
    _owner: str = Depends(require_session_owner),
):
    """Abandon session (no XP). Terminal: completed rows reject with 409."""
    _check_session_id(session_id)
    try:
        return await _mgr().abandon_session(session_id)
    except KeyError:
        raise _not_found(session_id)
    except ValueError as exc:
        from deeptutor.services.study.session_manager import SessionStateError

        if isinstance(exc, SessionStateError):
            raise _state_conflict(exc)
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to abandon session: {exc}") from exc


@router.get("/{session_id}/report", response_model=SessionReportResponse)
async def get_session_report(
    session_id: str,
    _owner: str = Depends(require_session_owner),
):
    """Get session report (honest nulls when unmeasured/pending)."""
    _check_session_id(session_id)
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
