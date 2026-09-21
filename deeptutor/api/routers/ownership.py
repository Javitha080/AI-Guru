"""Session / sitting ownership guards — Phase 1 IDOR fix.

Every session-scoped, sitting-scoped, camera, and monitoring endpoint must use
one of these dependencies so that user A can never read, pause, stop, or stream
user B's data.

Design:
- ``resolve_student_id(user)`` maps an authenticated user to their student
  identity (derived from the token, never from the request body).
- ``require_session_owner`` / ``require_sitting_owner`` / ``require_exam_owner`` /
  ``require_student_owner`` verify the authenticated user owns the target resource.
- When AUTH_ENABLED=false, the local admin owns everything (single-user mode).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import aiosqlite
from fastapi import Depends, HTTPException, status

from deeptutor.api.routers.auth import require_auth
from deeptutor.services import auth as _auth
from deeptutor.services.auth import TokenPayload
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

# Single-user default: when auth is off, every resource is owned by this ID.
_LOCAL_STUDENT_ID = "student-primary"


def resolve_student_id(user: Any = None) -> str:
    """Derive the canonical student_id from the authenticated token.

    In single-user mode (AUTH_ENABLED=false, user is None) this returns
    ``"student-primary"`` — the hardcoded identity used throughout the app.
    In multi-user mode, the user_id from the JWT maps through the
    ``students`` table; if no row exists yet, one is auto-provisioned
    using the same pattern as ``StudySessionManager._ensure_student``.
    """
    if not _auth.AUTH_ENABLED:
        return _LOCAL_STUDENT_ID

    if user is None:
        from deeptutor.multi_user.context import get_current_user_or_none

        user = get_current_user_or_none()

    if user is None:
        return _LOCAL_STUDENT_ID

    uid = str(getattr(user, "user_id", None) or getattr(user, "id", "") or "")
    if uid in ("local-admin", "env-admin", ""):
        return _LOCAL_STUDENT_ID

    if uid.startswith("user-"):
        return uid[5:]
    return uid


async def _db_path() -> str:
    return str(get_path_service().user_dir / "chat_history.db")


async def _session_owner_student_id(session_id: str) -> Optional[str]:
    """Look up the student_id that owns a study session."""
    try:
        async with aiosqlite.connect(await _db_path()) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT student_id FROM study_sessions WHERE id = ?",
                (session_id,),
            )
            row = await cur.fetchone()
            return str(row["student_id"]) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("Session owner lookup failed for %s: %s", session_id, exc)
        return None


async def _sitting_owner_student_id(sitting_id: str) -> Optional[str]:
    """Look up the student_id that owns an exam sitting (any part)."""
    try:
        async with aiosqlite.connect(await _db_path()) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT student_id FROM exams WHERE sitting_id = ? LIMIT 1",
                (sitting_id,),
            )
            row = await cur.fetchone()
            return str(row["student_id"]) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("Sitting owner lookup failed for %s: %s", sitting_id, exc)
        return None


async def _exam_owner_student_id(exam_id: str) -> Optional[str]:
    """Look up the student_id that owns an individual exam."""
    try:
        async with aiosqlite.connect(await _db_path()) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT student_id FROM exams WHERE id = ? LIMIT 1",
                (exam_id,),
            )
            row = await cur.fetchone()
            return str(row["student_id"]) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("Exam owner lookup failed for %s: %s", exam_id, exc)
        return None


def _is_local_admin(user: Any = None) -> bool:
    """True when running in single-user / auth-disabled mode or role is admin."""
    if not _auth.AUTH_ENABLED:
        return True
    if user is None:
        from deeptutor.multi_user.context import get_current_user_or_none

        user = get_current_user_or_none()
    if user is None:
        return True
    uid = str(getattr(user, "user_id", None) or getattr(user, "id", "") or "")
    role = str(getattr(user, "role", "") or "")
    return uid in ("local-admin", "env-admin") or role == "admin"


async def require_session_owner(
    session_id: str,
    user: TokenPayload | None = Depends(require_auth),
) -> str:
    """Verify session belongs to the authenticated user. Returns student_id.

    Raises HTTP 403 on mismatch, 404 when session doesn't exist.
    In single-user mode (AUTH_ENABLED=false) this always passes.
    """
    caller_student = resolve_student_id(user)
    if _is_local_admin(user):
        return caller_student

    owner = await _session_owner_student_id(session_id)
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Study session '{session_id}' not found",
        )
    if owner != caller_student:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this study session",
        )
    return caller_student


async def require_sitting_owner(
    sitting_id: str,
    user: TokenPayload | None = Depends(require_auth),
) -> str:
    """Verify sitting belongs to the authenticated user. Returns student_id.

    Raises HTTP 403 on mismatch, 404 when sitting doesn't exist.
    """
    caller_student = resolve_student_id(user)
    if _is_local_admin(user):
        return caller_student

    owner = await _sitting_owner_student_id(sitting_id)
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sitting '{sitting_id}' not found",
        )
    if owner != caller_student:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this exam sitting",
        )
    return caller_student


async def require_exam_owner(
    exam_id: str,
    user: TokenPayload | None = Depends(require_auth),
) -> str:
    """Verify exam belongs to the authenticated user. Returns student_id.

    Raises HTTP 403 on mismatch, 404 when exam doesn't exist.
    """
    caller_student = resolve_student_id(user)
    if _is_local_admin(user):
        return caller_student

    owner = await _exam_owner_student_id(exam_id)
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exam '{exam_id}' not found",
        )
    if owner != caller_student:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this exam",
        )
    return caller_student


async def require_student_owner(
    student_id: str,
    user: TokenPayload | None = Depends(require_auth),
) -> str:
    """Verify student_id matches the authenticated user."""
    caller_student = resolve_student_id(user)
    if _is_local_admin(user):
        return caller_student
    if student_id != caller_student:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this student's data",
        )
    return caller_student


async def check_session_owner_ws(session_id: str, user: Any = None) -> bool:
    """Check session ownership for WebSocket connections before accepting."""
    if _is_local_admin(user):
        return True
    caller_student = resolve_student_id(user)
    owner = await _session_owner_student_id(session_id)
    return owner is not None and owner == caller_student
