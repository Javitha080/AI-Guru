"""Per-parent Telegram configuration store (SQLite kv-settings backed).

Single home for every ``telegram_{parent_id}`` settings-row access. Before
this module, five call sites (parent router x3, notification outbox, command
listener) each hand-rolled ``ensure_kv_settings + SELECT value`` with
slightly different enabled/blank semantics — including the outbox, which
only ever read ``telegram_default`` and therefore could never deliver to a
non-default parent.

Semantics (shared by UI save, outbox enqueue/flush, command listener):
- A config is *usable* only when ``bot_token`` + ``chat_id`` are non-blank
  AND ``enabled`` is truthy. Anything else behaves as "not configured".
- A blank ``bot_token`` on save means "keep the saved credential" so a
  Chat-ID-only edit can never silently kill alert delivery.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite

from deeptutor.services.path_service import get_path_service
from deeptutor.services.remote.kv_settings import ensure_kv_settings

logger = logging.getLogger(__name__)


def _db_path():
    return get_path_service().user_dir / "chat_history.db"


class TelegramConfigStore:
    """CRUD + resolution for ``telegram_{parent_id}`` settings rows."""

    @staticmethod
    def key_for(parent_id: str) -> str:
        return f"telegram_{parent_id or 'default'}"

    @staticmethod
    def parse(config_json: Any) -> Optional[Dict[str, str]]:
        """Usable (bot_token, chat_id) pair or None when not configured."""
        if not config_json:
            return None
        try:
            cfg = json.loads(config_json)
        except Exception:  # noqa: BLE001 - corrupted row behaves like absent
            return None
        if not isinstance(cfg, dict):
            return None
        bot_token = str(cfg.get("bot_token") or "").strip()
        chat_id = str(cfg.get("chat_id") or "").strip()
        if not bot_token or not chat_id:
            return None
        if not cfg.get("enabled", True):
            return None
        return {"bot_token": bot_token, "chat_id": chat_id}

    @classmethod
    async def get(cls, parent_id: str = "default") -> Optional[Dict[str, str]]:
        """Usable credentials for one parent, or None."""
        async with aiosqlite.connect(_db_path()) as db:
            await ensure_kv_settings(db)
            cursor = await db.execute(
                "SELECT value FROM settings WHERE key = ?", (cls.key_for(parent_id),)
            )
            row = await cursor.fetchone()
        return cls.parse(row[0] if row else None)

    @classmethod
    async def is_photo_enabled(cls, parent_id: str = "default") -> bool:
        """Whether Telegram photo alerts are enabled (default: True)."""
        async with aiosqlite.connect(_db_path()) as db:
            await ensure_kv_settings(db)
            cursor = await db.execute(
                "SELECT value FROM settings WHERE key = ?", (cls.key_for(parent_id),)
            )
            row = await cursor.fetchone()
        if not row or not row[0]:
            return True
        try:
            cfg = json.loads(row[0])
            return bool(cfg.get("send_photos", True))
        except Exception:
            return True

    @classmethod
    async def get_masked(cls, parent_id: str = "default") -> Dict[str, Any]:
        """UI-safe view: masked token + chat id + flags, never the secret."""
        async with aiosqlite.connect(_db_path()) as db:
            await ensure_kv_settings(db)
            cursor = await db.execute(
                "SELECT value FROM settings WHERE key = ?", (cls.key_for(parent_id),)
            )
            row = await cursor.fetchone()
        if not row or not row[0]:
            return {
                "configured": False,
                "bot_token_masked": "",
                "chat_id": "",
                "enabled": False,
                "send_photos": True,
            }
        try:
            data = json.loads(row[0])
        except Exception:  # noqa: BLE001
            logger.debug("Telegram config row for %s is corrupt", parent_id)
            return {
                "configured": False,
                "bot_token_masked": "",
                "chat_id": "",
                "enabled": False,
                "send_photos": True,
                "corrupt": True,
            }
        token = str(data.get("bot_token") or "")
        if not token or not str(data.get("chat_id") or ""):
            return {
                "configured": False,
                "bot_token_masked": "",
                "chat_id": "",
                "enabled": bool(data.get("enabled", False)),
                "send_photos": bool(data.get("send_photos", True)),
            }
        masked = f"{token[:6]}...{token[-4:]}" if len(token) > 10 else "****"
        return {
            "configured": True,
            "bot_token_masked": masked,
            "chat_id": str(data.get("chat_id") or ""),
            "enabled": bool(data.get("enabled", True)),
            "send_photos": bool(data.get("send_photos", True)),
            "last_verified_at": data.get("last_verified_at"),
            "last_verified_ok": data.get("last_verified_ok"),
            "last_verified_detail": data.get("last_verified_detail") or "",
            "bot_username": data.get("bot_username") or "",
        }

    @classmethod
    async def save(
        cls,
        parent_id: str = "default",
        *,
        bot_token: str,
        chat_id: str,
        enabled: bool = True,
        send_photos: Optional[bool] = None,
    ) -> None:
        """Persist credentials; blank token keeps the previously saved one.

        Raises ``ValueError`` when there is no usable token after the keep
        rule (first-time setup with an empty token field).
        """
        parent_id = parent_id or "default"
        token = (bot_token or "").strip()
        if not token:
            existing = await cls.get(parent_id)
            # NOTE: get() hides disabled rows; a disabled row's token must
            # still be keepable, so read the raw row here instead.
            if existing is None:
                async with aiosqlite.connect(_db_path()) as db:
                    await ensure_kv_settings(db)
                    cursor = await db.execute(
                        "SELECT value FROM settings WHERE key = ?", (cls.key_for(parent_id),)
                    )
                    row = await cursor.fetchone()
                raw_token = ""
                if row and row[0]:
                    try:
                        raw_token = str((json.loads(row[0]) or {}).get("bot_token") or "")
                    except Exception:  # noqa: BLE001
                        raw_token = ""
                token = raw_token.strip()
            else:
                token = existing["bot_token"]
            if not token:
                raise ValueError("Bot Token is required for first-time setup.")
        payload_dict: Dict[str, Any] = {
            "bot_token": token,
            "chat_id": (chat_id or "").strip(),
            "enabled": bool(enabled),
            "updated_at": time.time(),
        }
        if send_photos is not None:
            payload_dict["send_photos"] = bool(send_photos)
        payload = json.dumps(payload_dict)
        async with aiosqlite.connect(_db_path()) as db:
            await ensure_kv_settings(db)
            # Preserve prior verification stamp across Chat-ID-only edits so
            # the UI doesn't flip to "never verified" when the token is kept.
            try:
                cur = await db.execute(
                    "SELECT value FROM settings WHERE key = ?", (cls.key_for(parent_id),)
                )
                prow = await cur.fetchone()
                if prow and prow[0]:
                    try:
                        prev = json.loads(prow[0]) or {}
                    except Exception:
                        prev = {}
                    if isinstance(prev, dict):
                        merged = json.loads(payload)
                        for k in (
                            "last_verified_at",
                            "last_verified_ok",
                            "last_verified_detail",
                            "bot_username",
                        ):
                            if prev.get(k) is not None and merged.get(k) is None:
                                merged[k] = prev.get(k)
                        if "send_photos" not in merged and "send_photos" in prev:
                            merged["send_photos"] = bool(prev["send_photos"])
                        payload = json.dumps(merged)
            except Exception:  # noqa: BLE001 - verification stamp is best-effort
                pass
            merged = json.loads(payload)
            if "send_photos" not in merged:
                merged["send_photos"] = True
            payload = json.dumps(merged)
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, category, updated_at)"
                " VALUES (?, ?, 'telegram', ?)",
                (cls.key_for(parent_id), payload, time.time()),
            )
            await db.commit()

    @classmethod
    async def record_verification(
        cls,
        parent_id: str,
        *,
        ok: bool,
        detail: str = "",
        bot_username: str = "",
    ) -> None:
        """Stamp the last ``getMe`` result onto the stored row (best-effort)."""
        try:
            async with aiosqlite.connect(_db_path()) as db:
                await ensure_kv_settings(db)
                cur = await db.execute(
                    "SELECT value FROM settings WHERE key = ?", (cls.key_for(parent_id),)
                )
                row = await cur.fetchone()
                if not row or not row[0]:
                    return
                try:
                    data = json.loads(row[0]) or {}
                except Exception:
                    return
                if not isinstance(data, dict):
                    return
                data["last_verified_at"] = time.time()
                data["last_verified_ok"] = bool(ok)
                data["last_verified_detail"] = str(detail or "")[:200]
                data["bot_username"] = str(bot_username or "")[:64]
                await db.execute(
                    "INSERT OR REPLACE INTO settings (key, value, category, updated_at)"
                    " VALUES (?, ?, 'telegram', ?)",
                    (cls.key_for(parent_id), json.dumps(data), time.time()),
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Verification stamp skipped for %s: %s", parent_id, exc)

    @classmethod
    async def list_enabled(cls) -> List[Tuple[str, Dict[str, str]]]:
        """All (parent_id, credentials) pairs currently usable for delivery.

        Backs the notification flush and the Telegram command listener so a
        second parent's alerts/commands work without any `default` special
        case. Malformed or disabled rows are skipped (debug-logged).
        """
        async with aiosqlite.connect(_db_path()) as db:
            await ensure_kv_settings(db)
            cursor = await db.execute(
                "SELECT key, value FROM settings WHERE key LIKE 'telegram\\_%' ESCAPE '\\'"
            )
            rows = await cursor.fetchall()
        enabled: List[Tuple[str, Dict[str, str]]] = []
        for key, value in rows:
            parent_id = str(key)[len("telegram_") :]
            if not parent_id:
                continue
            parsed = cls.parse(value)
            if parsed is None:
                logger.debug("Skipping unusable telegram config for %s", parent_id)
                continue
            enabled.append((parent_id, parsed))
        return enabled


__all__ = ["TelegramConfigStore"]
