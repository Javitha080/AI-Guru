"""Persisted system-camera configuration (kv-settings backed)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict

import aiosqlite

logger = logging.getLogger(__name__)

CAMERA_SETTINGS_KEY = "monitoring_camera"
_DEFAULT_CAMERA_CONFIG = {"enabled": True, "camera_index": 0, "target_fps": 10}


async def load_camera_config() -> Dict[str, Any]:
    """Read the persisted ``monitoring_camera`` kv-settings (defaults enabled)."""
    try:
        from deeptutor.services.path_service import get_path_service
        from deeptutor.services.remote.kv_settings import ensure_kv_settings

        db_path = get_path_service().user_dir / "chat_history.db"
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)
            cur = await db.execute(
                "SELECT value FROM settings WHERE key = ?", (CAMERA_SETTINGS_KEY,)
            )
            row = await cur.fetchone()
        if row and row[0]:
            data = json.loads(row[0])
            if isinstance(data, dict):
                merged = dict(_DEFAULT_CAMERA_CONFIG)
                merged.update({k: v for k, v in data.items() if k in _DEFAULT_CAMERA_CONFIG})
                return merged
    except Exception as exc:  # noqa: BLE001 - config is optional, defaults are safe
        logger.debug("Camera config load skipped: %s", exc)
    return dict(_DEFAULT_CAMERA_CONFIG)


async def save_camera_config(config: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(_DEFAULT_CAMERA_CONFIG)
    merged.update({k: v for k, v in config.items() if k in _DEFAULT_CAMERA_CONFIG})
    try:
        from deeptutor.services.path_service import get_path_service
        from deeptutor.services.remote.kv_settings import ensure_kv_settings

        db_path = get_path_service().user_dir / "chat_history.db"
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)
            await db.execute(
                "INSERT INTO settings (key, value, category, updated_at) VALUES (?, ?, 'monitoring', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (CAMERA_SETTINGS_KEY, json.dumps(merged), time.time()),
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Camera config save failed: %s", exc)
    return merged


__all__ = ["CAMERA_SETTINGS_KEY", "load_camera_config", "save_camera_config"]
