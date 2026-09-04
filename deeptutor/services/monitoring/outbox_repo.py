"""SQLite persistence for the Telegram notification outbox.

Extracted from notification_queue so SQL/DDL/claim logic lives in one place.
notification_queue remains the public facade (enqueue/flush_once/worker).
"""

from __future__ import annotations

import time
from typing import Optional

import aiosqlite

from deeptutor.services.path_service import get_path_service

_OUTBOX_DDL = (
    "CREATE TABLE IF NOT EXISTS notification_outbox ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "created_at REAL NOT NULL,"
    "kind TEXT NOT NULL,"
    "payload_json TEXT NOT NULL,"
    "parent_id TEXT NOT NULL DEFAULT 'default',"
    "status TEXT NOT NULL DEFAULT 'pending',"
    "retries INTEGER NOT NULL DEFAULT 0,"
    "next_attempt_at REAL NOT NULL DEFAULT 0,"
    "claimed_by TEXT,"
    "claimed_at REAL,"
    "last_error TEXT,"
    "sent_at REAL)"
)

# Columns added after the initial release; applied lazily so existing
# databases upgrade in place without a migration step.
_OUTBOX_LAZY_COLUMNS: dict[str, str] = {
    "parent_id": "TEXT NOT NULL DEFAULT 'default'",
    "claimed_by": "TEXT",
    "claimed_at": "REAL",
}


def db_path():
    return get_path_service().user_dir / "chat_history.db"


async def ensure_outbox(db: aiosqlite.Connection) -> None:
    await db.execute(_OUTBOX_DDL)
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_outbox_due ON notification_outbox (status, next_attempt_at)"
    )
    cursor = await db.execute("PRAGMA table_info(notification_outbox)")
    existing = {row[1] for row in await cursor.fetchall()}
    for column, decl in _OUTBOX_LAZY_COLUMNS.items():
        if column not in existing:
            try:
                await db.execute(f"ALTER TABLE notification_outbox ADD COLUMN {column} {decl}")
            except Exception:  # noqa: BLE001 - concurrent ALTER race
                pass


async def load_row(row_id: int):
    async with aiosqlite.connect(db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, kind, payload_json, parent_id, retries FROM notification_outbox WHERE id = ?",
            (row_id,),
        )
        return await cursor.fetchone()


async def mark(
    row_id: int,
    *,
    sent: bool = False,
    dead: bool = False,
    error: Optional[str] = None,
    retries: int = 0,
    next_attempt: float = 0.0,
    back_to_pending: bool = False,
) -> None:
    async with aiosqlite.connect(db_path()) as db:
        if sent:
            await db.execute(
                "UPDATE notification_outbox SET status='sent', sent_at=?, last_error=NULL WHERE id=?",
                (time.time(), row_id),
            )
        elif dead:
            await db.execute(
                "UPDATE notification_outbox SET status='dead', last_error=? WHERE id=?",
                (error, row_id),
            )
        elif back_to_pending:
            await db.execute(
                "UPDATE notification_outbox SET status='pending', retries=?, next_attempt_at=?, last_error=? WHERE id=?",
                (retries, next_attempt, error, row_id),
            )
        else:
            await db.execute(
                "UPDATE notification_outbox SET retries=?, next_attempt_at=?, last_error=? WHERE id=?",
                (retries, next_attempt, error, row_id),
            )
        await db.commit()


__all__ = ["db_path", "ensure_outbox", "load_row", "mark"]
