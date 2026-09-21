"""Supervision-rules resolution — single home for student-name / strictness fallback.

Three copies of this logic drifted (parent router, study-session router,
system monitor, telegram listener) with subtly different fallbacks:

- ``supervision_rules_{parent_id}`` is the per-parent override (wizard step-4).
- ``supervision_rules_default`` is the canonical single-home row written by
  the student-side name/profile flows.

Resolution order everywhere:
1. ``supervision_rules_{parent_id}`` when non-empty,
2. ``supervision_rules_default``,
3. hardcoded honest default.

Student-name resolution for notifications adds pairing fan-out:
linked parents' rules first, then default, then users.display_name.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import aiosqlite

logger = logging.getLogger(__name__)

DEFAULTS: Dict[str, Any] = {
    "student_name": "Student",
    "daily_goal_minutes": 60,
    "alert_strictness": "balanced",
    "allow_parent_voice": True,
}


def rules_key(parent_id: str) -> str:
    return f"supervision_rules_{parent_id or 'default'}"


async def load_rules(parent_id: str = "default") -> Dict[str, Any]:
    """Load merged supervision rules with parent→default fallback.

    Returns at least DEFAULTS; never raises (dashboard/naming is best-effort).
    """
    from deeptutor.services.path_service import get_path_service
    from deeptutor.services.remote.kv_settings import ensure_kv_settings

    db_path = get_path_service().user_dir / "chat_history.db"
    merged: Dict[str, Any] = dict(DEFAULTS)
    try:
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)
            # Default first, then parent-specific override wins field-by-field.
            for key in ("supervision_rules_default", rules_key(parent_id)):
                try:
                    cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
                    row = await cur.fetchone()
                except Exception:
                    continue
                if row and row[0]:
                    try:
                        data = json.loads(row[0])
                    except Exception:
                        continue
                    if isinstance(data, dict):
                        for field in ("student_name", "daily_goal_minutes", "alert_strictness", "allow_parent_voice"):
                            val = data.get(field)
                            if field == "allow_parent_voice":
                                if isinstance(val, bool):
                                    merged[field] = val
                                continue
                            if isinstance(val, str):
                                if val.strip():
                                    merged[field] = val.strip() if field == "student_name" else val
                            elif val is not None and field != "student_name":
                                merged[field] = val
    except Exception as exc:  # noqa: BLE001
        logger.debug("Supervision rules unavailable for %s: %s", parent_id, exc)
    return merged


async def resolve_student_name(
    student_id: str,
    *,
    db_path: Any = None,
) -> str:
    """Display name for notifications/reports with pairing fan-out.

    Order: linked parents' ``student_name`` → ``supervision_rules_default``
    → ``users.display_name`` → capitalized id tail. Never raises.
    """
    sid = (student_id or "student-primary").strip() or "student-primary"
    try:
        from deeptutor.services.path_service import get_path_service
        from deeptutor.services.remote.kv_settings import ensure_kv_settings

        db_file = db_path or (get_path_service().user_dir / "chat_history.db")

        parent_ids: List[str] = []
        try:
            from deeptutor.services.remote.pairing import PairingService

            parent_ids = await PairingService.get_parent_ids_for_student(sid)
        except Exception:  # noqa: BLE001
            parent_ids = []

        # Linked parents first (skip the synthetic "default" fallback entry —
        # it is checked explicitly below as the canonical row).
        seen: set[str] = set()
        async with aiosqlite.connect(db_file) as db:
            await ensure_kv_settings(db)
            for pid in parent_ids or []:
                if not pid or pid == "default" or pid in seen:
                    continue
                seen.add(pid)
                try:
                    cur = await db.execute(
                        "SELECT value FROM settings WHERE key = ?", (rules_key(pid),)
                    )
                    row = await cur.fetchone()
                except Exception:
                    continue
                if row and row[0]:
                    try:
                        rules = json.loads(row[0])
                    except Exception:
                        continue
                    name = str((rules or {}).get("student_name") or "").strip()
                    if name:
                        return name

            # Canonical default row.
            try:
                cur = await db.execute(
                    "SELECT value FROM settings WHERE key = ?",
                    ("supervision_rules_default",),
                )
                row = await cur.fetchone()
                if row and row[0]:
                    rules = json.loads(row[0])
                    name = str((rules or {}).get("student_name") or "").strip()
                    if name:
                        return name
            except Exception:  # noqa: BLE001
                pass

            # Fallback to users table display_name.
            try:
                user_id = f"user-{sid}"
                cur2 = await db.execute(
                    "SELECT display_name FROM users WHERE id = ? OR username = ?",
                    (user_id, f"student:{sid}"),
                )
                user_row = await cur2.fetchone()
                if user_row and user_row[0]:
                    u_name = str(user_row[0]).strip()
                    if u_name and u_name != sid and not u_name.startswith("student:"):
                        return u_name
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    return sid.split("-")[-1].capitalize() or "Student"


def live_duration_seconds(session: Dict[str, Any], now: Optional[float] = None) -> float:
    """Pause-aware live duration for in-progress/paused rows.

    Mirrors ``StudySessionManager.stop_session`` banking: banked
    ``worked_seconds`` plus the open stretch (``now - last_resume_time``)
    when actively studying. Never counts paused wall-clock or the idle gap
    between row creation and explicit start (``last_resume_time`` NULL).
    """
    import time as _time

    now = now if now is not None else _time.time()
    try:
        worked = float(session.get("worked_seconds") or 0.0)
    except (TypeError, ValueError):
        worked = 0.0
    status = str(session.get("status") or "")
    if status == "in_progress":
        last_resume = session.get("last_resume_time")
        try:
            if last_resume:
                worked += max(0.0, float(now) - float(last_resume))
        except (TypeError, ValueError):
            pass
        # Defensive ceiling: never exceed wall-clock from start_time.
        try:
            start_time = session.get("start_time")
            if start_time:
                wall = float(now) - float(start_time)
                worked = min(worked, max(0.0, wall))
        except (TypeError, ValueError):
            pass
        return max(0.0, worked)
    if status == "paused":
        return max(0.0, worked)
    try:
        return max(0.0, float(session.get("actual_duration_seconds") or 0))
    except (TypeError, ValueError):
        return 0.0


__all__ = ["DEFAULTS", "rules_key", "load_rules", "resolve_student_name", "live_duration_seconds"]
