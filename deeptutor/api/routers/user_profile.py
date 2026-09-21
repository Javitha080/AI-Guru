"""User Profile API Router.

Provides unified endpoints for student profile and academic personalization:
- Display name and avatar marker
- Grade level, learning style, daily study goal
- Primary focus subjects and AI tutor tone
- Gamification metrics (XP, level, streak, sessions)

Bridges SQLite chat_history.db (canonical for student UI) with the auth layer,
respecting the dual-shape settings contract and foreign-key constraints.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, List, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_auth
from deeptutor.services.auth import AUTH_ENABLED, TokenPayload
from deeptutor.services.gamification.gamification_service import GamificationService
from deeptutor.services.path_service import get_path_service
from deeptutor.services.remote.kv_settings import ensure_kv_settings, kv_get, kv_set

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Allow-lists matching frontend lib/avatar.ts & personalization design
# ---------------------------------------------------------------------------

VALID_AVATAR_ICONS = frozenset(
    {
        "sparkles",
        "sprout",
        "leaf",
        "feather",
        "cloud",
        "droplet",
        "sun",
        "moon",
        "flame",
        "star",
        "heart",
        "lightbulb",
        "compass",
        "cherry",
        "cookie",
        "music",
    }
)

VALID_AVATAR_COLORS = frozenset(
    {
        "violet",
        "blue",
        "teal",
        "green",
        "amber",
        "rose",
        "slate",
        "pink",
    }
)

VALID_LEARNING_STYLES = frozenset(
    {
        "visual",
        "step_by_step",
        "socratic",
        "practical",
    }
)

VALID_TUTOR_TONES = frozenset(
    {
        "encouraging",
        "rigorous",
        "friendly",
        "socratic",
    }
)

_ICON_MARKER_RE = re.compile(r"^icon:([a-z0-9_-]+):([a-z0-9_-]+)$")
_IMG_MARKER_RE = re.compile(r"^img:\d+$")


def _is_raw_fallback_name(name: str, student_id: str) -> bool:
    """True when display_name was never set by the user (empty or auto-seed)."""
    if not name:
        return True
    if name == student_id:
        return True
    if name.startswith("student:"):
        return True
    return False


def _display_name_for_response(
    raw_name: str, *, student_id: str, is_configured: bool
) -> str:
    """Mask internal fallback IDs: '' when onboarding, 'Student' once configured."""
    if _is_raw_fallback_name(raw_name, student_id):
        return "Student" if is_configured else ""
    return raw_name


# Local single-user installs historically used these global keys. Multi-user
# installs scope them per student (suffix ":<student_id>") so one user's
# onboarding/personalization never leaks into another's. Reads try the scoped
# key first, then fall back to the legacy global for backward compatibility.
_LEGACY_CONFIGURED_KEY = "user_profile_configured"
_LEGACY_PERSONALIZATIONS_KEY = "student_personalizations_default"
_DEFAULT_STUDENT_ID = "student-primary"


def _configured_key(student_id: str) -> str:
    if student_id == _DEFAULT_STUDENT_ID:
        return _LEGACY_CONFIGURED_KEY
    return f"{_LEGACY_CONFIGURED_KEY}:{student_id}"


def _personalizations_key(student_id: str) -> str:
    if student_id == _DEFAULT_STUDENT_ID:
        return _LEGACY_PERSONALIZATIONS_KEY
    return f"{_LEGACY_PERSONALIZATIONS_KEY}:{student_id}"


async def _kv_get_scoped(db: aiosqlite.Connection, key: str, legacy_key: str) -> Any:
    """Read scoped key first, fall back to legacy global (pre-multi-user DBs)."""
    value = await kv_get(db, key)
    if value is not None:
        return value
    if key != legacy_key:
        return await kv_get(db, legacy_key)
    return None


def _auth_role_to_user_role(role: str) -> str:
    """Map auth-layer roles ('admin'/'user') onto users-table roles."""
    return "admin" if role == "admin" else "student"


def validate_avatar_marker(marker: str) -> bool:
    """Check if an avatar marker matches the allowed icon/color sets or img format."""
    if not marker:
        return True
    if _IMG_MARKER_RE.match(marker):
        return True
    match = _ICON_MARKER_RE.match(marker)
    if not match:
        return False
    icon, color = match.groups()
    return icon in VALID_AVATAR_ICONS and color in VALID_AVATAR_COLORS


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class UserProfileResponse(BaseModel):
    student_id: str
    user_id: str
    display_name: str
    username: str
    avatar: str
    role: str
    grade_level: str
    learning_style: str
    target_daily_minutes: int
    school: str
    preferred_subjects: List[str]
    tutor_tone: str
    is_configured: bool
    xp: int
    level: int
    level_title: str
    streak: int
    total_sessions: int


class UserProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=50)
    avatar: Optional[str] = Field(default=None, max_length=60)
    grade_level: Optional[str] = Field(default=None, max_length=60)
    learning_style: Optional[str] = Field(default=None, max_length=30)
    target_daily_minutes: Optional[int] = Field(default=None, ge=15, le=480)
    school: Optional[str] = Field(default=None, max_length=100)
    preferred_subjects: Optional[List[str]] = Field(default=None, max_length=10)
    tutor_tone: Optional[str] = Field(default=None, max_length=30)


class UserProfileStatusResponse(BaseModel):
    is_configured: bool
    display_name: str
    avatar: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_path():
    return get_path_service().user_dir / "chat_history.db"


def _resolve_identity(payload: TokenPayload | None) -> tuple[str, str, str, str]:
    """Resolve student_id, user_id, username, and role.

    In local mode (AUTH_ENABLED=False or payload is None), defaults to
    the standard student-primary identity used across AI Guru services.
    """
    if AUTH_ENABLED and payload is not None:
        user_id = str(payload.user_id or f"user-{payload.username}")
        student_id = str(payload.user_id or payload.username)
        username = str(payload.username)
        role = str(payload.role or "student")
        return student_id, user_id, username, role

    return "student-primary", "user-student-primary", "student:student-primary", "student"


async def _ensure_student_profile(
    db: aiosqlite.Connection,
    *,
    student_id: str,
    user_id: str,
    username: str,
    default_name: str = "",
    default_avatar: str = "",
    role: str = "student",
) -> None:
    """Ensure prerequisite users and students rows exist before any read/write.

    Fresh rows store an EMPTY display_name (never the raw student_id) so the
    API can distinguish "never set" from a real name. The users-table role
    follows the auth identity (admin stays admin).
    """
    now = time.time()
    user_role = _auth_role_to_user_role(role)
    await db.execute("PRAGMA foreign_keys = ON;")
    await db.execute(
        """
        INSERT OR IGNORE INTO users (
            id, username, password_hash, role, display_name, avatar_url, created_at, updated_at
        ) VALUES (?, ?, '', ?, ?, ?, ?, ?)
        """,
        (user_id, username, user_role, default_name or "", default_avatar, now, now),
    )
    await db.execute(
        """
        INSERT OR IGNORE INTO students (
            id, user_id, grade_level, school, learning_style, target_daily_minutes,
            streak_count, total_xp, face_embedding_json, created_at, updated_at
        ) VALUES (?, ?, '', '', 'visual', 60, 0, 0, '', ?, ?)
        """,
        (student_id, user_id, now, now),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=UserProfileResponse)
@router.get("/", response_model=UserProfileResponse)
async def get_user_profile(
    payload: TokenPayload | None = Depends(require_auth),
) -> UserProfileResponse:
    """Get complete student profile, personalizations, and gamification totals."""
    student_id, user_id, username, role = _resolve_identity(payload)
    db_file = _db_path()

    try:
        async with aiosqlite.connect(db_file) as db:
            db.row_factory = aiosqlite.Row
            await ensure_kv_settings(db)
            await _ensure_student_profile(
                db,
                student_id=student_id,
                user_id=user_id,
                username=username,
                role=role,
            )
            await db.commit()

            # Check configuration flag (scoped per student, legacy fallback)
            configured_flag = await _kv_get_scoped(
                db, _configured_key(student_id), _LEGACY_CONFIGURED_KEY
            )
            is_configured = str(configured_flag or "").strip().lower() == "true"

            # Query users table
            user_cur = await db.execute(
                "SELECT display_name, avatar_url, role FROM users WHERE id = ? OR username = ?",
                (user_id, username),
            )
            user_row = await user_cur.fetchone()
            raw_display_name = (
                str(user_row["display_name"] or "").strip() if user_row else ""
            )
            avatar = str(user_row["avatar_url"] or "").strip() if user_row else ""
            # Token identity is authoritative for role when signed in; the
            # auto-provisioned row must never downgrade an admin to student.
            if AUTH_ENABLED and payload is not None:
                user_role = _auth_role_to_user_role(role)
            else:
                user_role = str(user_row["role"] or role) if user_row else role

            display_name = _display_name_for_response(
                raw_display_name, student_id=student_id, is_configured=is_configured
            )

            # Query students table
            student_cur = await db.execute(
                "SELECT grade_level, learning_style, target_daily_minutes, school "
                "FROM students WHERE id = ?",
                (student_id,),
            )
            student_row = await student_cur.fetchone()
            grade_level = str(student_row["grade_level"] or "") if student_row else ""
            learning_style = (
                str(student_row["learning_style"] or "visual") if student_row else "visual"
            )
            target_minutes = int(student_row["target_daily_minutes"] or 60) if student_row else 60
            school = str(student_row["school"] or "") if student_row else ""

            # Query settings for personalizations (scoped, legacy fallback)
            pers_raw = await _kv_get_scoped(
                db, _personalizations_key(student_id), _LEGACY_PERSONALIZATIONS_KEY
            )
            preferred_subjects: List[str] = []
            tutor_tone = "encouraging"
            if pers_raw:
                try:
                    p_data = json.loads(pers_raw) if isinstance(pers_raw, str) else pers_raw
                    if isinstance(p_data, dict):
                        preferred_subjects = list(p_data.get("preferred_subjects") or [])
                        tutor_tone = str(p_data.get("tutor_tone") or "encouraging")
                except Exception:
                    pass

        # Gamification totals from GamificationService
        gamification = await GamificationService.get_profile(student_id)

        return UserProfileResponse(
            student_id=student_id,
            user_id=user_id,
            display_name=display_name,
            username=username,
            avatar=avatar,
            role=user_role,
            grade_level=grade_level,
            learning_style=learning_style,
            target_daily_minutes=target_minutes,
            school=school,
            preferred_subjects=preferred_subjects,
            tutor_tone=tutor_tone,
            is_configured=is_configured,
            xp=int(gamification.get("xp", 0)),
            level=int(gamification.get("level", 1)),
            level_title=str(gamification.get("level_title", "Novice")),
            streak=int(gamification.get("streak", 0)),
            total_sessions=int(gamification.get("total_sessions", 0)),
        )
    except Exception as exc:
        logger.exception("Failed to load user profile for student %s", student_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load profile: {exc}",
        ) from exc


@router.post("", response_model=UserProfileResponse)
@router.post("/", response_model=UserProfileResponse)
@router.put("", response_model=UserProfileResponse)
@router.put("/", response_model=UserProfileResponse)
async def update_user_profile(
    body: UserProfileUpdateRequest,
    payload: TokenPayload | None = Depends(require_auth),
) -> UserProfileResponse:
    """Create or update student profile; marks configured only once a name exists."""
    student_id, user_id, username, role = _resolve_identity(payload)
    db_file = _db_path()
    now = time.time()

    # Validate avatar if provided
    if body.avatar is not None and not validate_avatar_marker(body.avatar):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid avatar marker format or unrecognized icon/color name.",
        )

    # Reject empty names (whitespace-only) instead of storing them.
    if body.display_name is not None and not body.display_name.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Display name cannot be empty.",
        )

    # Strict validation (matches avatar/minutes behavior): unknown values are
    # client bugs and must surface as 422, not silent coercion.
    learning_style = body.learning_style
    if learning_style is not None:
        learning_style = learning_style.strip().lower()
        if learning_style not in VALID_LEARNING_STYLES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid learning_style. Choose one of: {sorted(VALID_LEARNING_STYLES)}.",
            )

    # Validate tutor tone if provided
    tutor_tone = body.tutor_tone
    if tutor_tone is not None:
        tutor_tone = tutor_tone.strip().lower()
        if tutor_tone not in VALID_TUTOR_TONES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid tutor_tone. Choose one of: {sorted(VALID_TUTOR_TONES)}.",
            )

    try:
        async with aiosqlite.connect(db_file) as db:
            await ensure_kv_settings(db)
            await _ensure_student_profile(
                db,
                student_id=student_id,
                user_id=user_id,
                username=username,
                role=role,
            )

            # Read existing configured flag: avatar-only or partial patches must
            # not complete onboarding on their own.
            existing_flag = await _kv_get_scoped(
                db, _configured_key(student_id), _LEGACY_CONFIGURED_KEY
            )
            already_configured = (
                str(existing_flag or "").strip().lower() == "true"
            )

            # Update users table
            display_name = (
                (body.display_name or "").strip() if body.display_name is not None else None
            )
            avatar = body.avatar.strip() if body.avatar is not None else None

            if display_name is not None and avatar is not None:
                await db.execute(
                    "UPDATE users SET display_name = ?, avatar_url = ?, updated_at = ? WHERE id = ? OR username = ?",
                    (display_name, avatar, now, user_id, username),
                )
            elif display_name is not None:
                await db.execute(
                    "UPDATE users SET display_name = ?, updated_at = ? WHERE id = ? OR username = ?",
                    (display_name, now, user_id, username),
                )
            elif avatar is not None:
                await db.execute(
                    "UPDATE users SET avatar_url = ?, updated_at = ? WHERE id = ? OR username = ?",
                    (avatar, now, user_id, username),
                )

            # Update students table
            student_updates: list[str] = []
            student_params: list[Any] = []

            if body.grade_level is not None:
                student_updates.append("grade_level = ?")
                student_params.append(body.grade_level.strip())
            if learning_style is not None:
                student_updates.append("learning_style = ?")
                student_params.append(learning_style)
            if body.target_daily_minutes is not None:
                student_updates.append("target_daily_minutes = ?")
                student_params.append(int(body.target_daily_minutes))
            if body.school is not None:
                student_updates.append("school = ?")
                student_params.append(body.school.strip())

            if student_updates:
                student_updates.append("updated_at = ?")
                student_params.append(now)
                student_params.append(student_id)
                query = f"UPDATE students SET {', '.join(student_updates)} WHERE id = ?"
                await db.execute(query, tuple(student_params))

            # Mark configured only when a real display name now exists:
            # a fresh name in this patch, or an already-configured profile.
            # Avatar-only / preference-only patches never complete onboarding.
            if display_name:
                await kv_set(
                    db,
                    _configured_key(student_id),
                    "true",
                    category="user_profile",
                )
            elif already_configured:
                await kv_set(
                    db,
                    _configured_key(student_id),
                    "true",
                    category="user_profile",
                )

            # Update personalizations in settings kv (scoped per student)
            pers_existing_raw = await _kv_get_scoped(
                db, _personalizations_key(student_id), _LEGACY_PERSONALIZATIONS_KEY
            )
            pers_dict: dict[str, Any] = {}
            if pers_existing_raw:
                try:
                    pers_dict = (
                        json.loads(pers_existing_raw)
                        if isinstance(pers_existing_raw, str)
                        else pers_existing_raw
                    )
                except Exception:
                    pers_dict = {}

            if body.preferred_subjects is not None:
                # Sanitize subjects list
                pers_dict["preferred_subjects"] = [
                    str(s).strip()[:50] for s in body.preferred_subjects if str(s).strip()
                ][:10]
            if tutor_tone is not None:
                pers_dict["tutor_tone"] = tutor_tone

            pers_dict["updated_at"] = now
            await kv_set(
                db,
                _personalizations_key(student_id),
                json.dumps(pers_dict),
                category="user_profile",
            )

            # Sync with supervision_rules_default for Parent Portal & Telegram notifications
            rules_raw = await kv_get(db, "supervision_rules_default")
            rules: dict[str, Any] = {}
            if rules_raw:
                try:
                    rules = json.loads(rules_raw) if isinstance(rules_raw, str) else rules_raw
                except Exception:
                    rules = {}
            if display_name:
                rules["student_name"] = display_name
            if body.target_daily_minutes is not None:
                rules["daily_goal_minutes"] = int(body.target_daily_minutes)
            rules["updated_at"] = now
            await kv_set(db, "supervision_rules_default", json.dumps(rules), category="supervision")

            await db.commit()

        # If auth is active and user is signed in, sync avatar to JSON identity store
        if AUTH_ENABLED and payload is not None and avatar is not None:
            try:
                from deeptutor.services.auth import set_avatar

                set_avatar(username, avatar)
            except Exception as e:
                logger.debug("Could not sync avatar to auth store: %s", e)

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update user profile for student %s", student_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update profile: {exc}",
        ) from exc

    return await get_user_profile(payload)


@router.get("/status", response_model=UserProfileStatusResponse)
async def get_user_profile_status(
    payload: TokenPayload | None = Depends(require_auth),
) -> UserProfileStatusResponse:
    """Lightweight check for onboarding gates to see if profile has been created."""
    student_id, user_id, username, _ = _resolve_identity(payload)
    db_file = _db_path()

    try:
        async with aiosqlite.connect(db_file) as db:
            db.row_factory = aiosqlite.Row
            await ensure_kv_settings(db)

            configured_flag = await _kv_get_scoped(
                db, _configured_key(student_id), _LEGACY_CONFIGURED_KEY
            )
            is_configured = str(configured_flag or "").strip().lower() == "true"

            if not is_configured:
                return UserProfileStatusResponse(
                    is_configured=False,
                    display_name="",
                    avatar="",
                )

            cur = await db.execute(
                "SELECT display_name, avatar_url FROM users WHERE id = ? OR username = ?",
                (user_id, username),
            )
            row = await cur.fetchone()
            raw_name = str(row["display_name"] or "").strip() if row else ""
            avatar = str(row["avatar_url"] or "").strip() if row else ""
            # Mask auto-seeded IDs exactly like GET (never leak student_id).
            if _is_raw_fallback_name(raw_name, student_id):
                return UserProfileStatusResponse(
                    is_configured=True,
                    display_name="Student",
                    avatar=avatar,
                )
            return UserProfileStatusResponse(
                is_configured=True,
                display_name=raw_name,
                avatar=avatar,
            )
    except Exception:
        # Fail safe: if DB is temporarily locked or booting, report unconfigured
        return UserProfileStatusResponse(
            is_configured=False,
            display_name="",
            avatar="",
        )
