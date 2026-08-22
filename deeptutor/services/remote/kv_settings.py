"""Shared accessor for the runtime key/value ``settings`` table.

Two shapes of this table exist historically:

* migrations/V1 (schema.py): ``settings(key, value_json NOT NULL, category, updated_at)``
* the AI Guru parent/security stack: ``settings(key, value TEXT, category, updated_at)``

On a fresh install the migration shape is created first, so every
``SELECT value`` / ``INSERT … value`` from the security stack fails with
"no such column". This module guarantees a compatible shape: it creates the
kv-table when missing and ALTERs in any missing columns on legacy tables.
The ``value_json`` column is left untouched so existing rows survive.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

import aiosqlite

logger = logging.getLogger(__name__)

_KV_DDL = (
    "CREATE TABLE IF NOT EXISTS settings ("
    "key TEXT PRIMARY KEY, value TEXT, "
    "category TEXT DEFAULT 'general', updated_at REAL DEFAULT 0)"
)

_REQUIRED_COLUMNS: dict[str, str] = {
    "value": "TEXT",
    "category": "TEXT DEFAULT 'general'",
    "updated_at": "REAL DEFAULT 0",
}

# Unified rebuild: keeps BOTH writer families working. The legacy migrations
# table declares ``value_json TEXT NOT NULL`` which rejects every kv-TEXT
# insert; the security stack's original shape lacks ``value``. The rebuilt
# table carries both columns with safe defaults and copies all prior rows.
_REBUILD_DDL = (
    "CREATE TABLE settings ("
    "key TEXT PRIMARY KEY, "
    "value TEXT DEFAULT '', "
    "value_json TEXT DEFAULT '{}', "
    "category TEXT DEFAULT 'general', "
    "updated_at REAL DEFAULT 0)"
)


async def ensure_kv_settings(db: aiosqlite.Connection) -> None:
    """Idempotently make ``settings`` usable for BOTH kv-TEXT and value_json writers."""
    await db.execute(_KV_DDL)
    cursor = await db.execute("PRAGMA table_info(settings)")
    rows = await cursor.fetchall()
    existing = {row[1] for row in rows}

    if "value" not in existing and "value_json" in existing:
        # Legacy migrations shape: rebuild once into the dual-column layout.
        try:
            await db.executescript(
                """
                BEGIN;
                ALTER TABLE settings RENAME TO settings_legacy_shape;
                """
                + _REBUILD_DDL
                + """
                ;
                INSERT INTO settings (key, value, value_json, category, updated_at)
                SELECT key,
                       '',
                       COALESCE(value_json, '{}'),
                       COALESCE(category, 'general'),
                       COALESCE(updated_at, 0)
                FROM settings_legacy_shape;
                DROP TABLE settings_legacy_shape;
                CREATE INDEX IF NOT EXISTS idx_settings_category ON settings(category);
                COMMIT;
                """
            )
            logger.info("settings table rebuilt to dual-shape (kv-text + value_json)")
            return
        except Exception as exc:  # noqa: BLE001 - fall through to ALTER path
            logger.warning("settings rebuild failed (%s); trying ALTER path", exc)
            try:
                await db.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass

    altered = False
    for column, decl in _REQUIRED_COLUMNS.items():
        if column not in existing:
            try:
                await db.execute(f"ALTER TABLE settings ADD COLUMN {column} {decl}")
                altered = True
            except Exception as exc:  # noqa: BLE001 - concurrent ALTER race
                logger.debug("ALTER settings ADD %s skipped: %s", column, exc)
    if altered:
        logger.info("settings table: added missing kv columns")


async def kv_get(db: aiosqlite.Connection, key: str) -> Any:
    await ensure_kv_settings(db)
    cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row[0] if row else None


async def kv_set(
    db: aiosqlite.Connection,
    key: str,
    value: str,
    *,
    category: str = "general",
) -> None:
    await ensure_kv_settings(db)
    import time

    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, ?, ?)",
        (key, value, category, time.time()),
    )


def columns_present(row_factory_result: Iterable[Any]) -> set[str]:  # pragma: no cover - util
    return {row[1] for row in row_factory_result}
