"""SQLite-backed Telegram notification outbox.

Warnings and session summaries produced by the local monitoring engine are
queued durably and delivered with retry/backoff so a temporary internet loss
never silently drops parent notifications.

Table ``notification_outbox`` lives in the user's chat_history.db and is
created lazily by this module (additive; does not touch schema.py).
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import time
from typing import Any, Dict, Optional

import aiosqlite

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

_MAX_RETRIES = 8
_BASE_BACKOFF = 30.0
_MAX_BACKOFF = 600.0

_worker_task: Optional[asyncio.Task] = None
_worker_task_loop: Optional[asyncio.AbstractEventLoop] = None


def _db_path():
    return get_path_service().user_dir / "chat_history.db"


def _backoff_for(retries: int) -> float:
    return min(_BASE_BACKOFF * (2 ** max(0, retries - 1)), _MAX_BACKOFF)


def _compose_message(kind: str, payload: Dict[str, Any]) -> str:
    if kind == "warning":
        emoji = {"alert": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(payload.get("severity", ""), "⚠️")
        title = html.escape(str(payload.get("category", "Notice")).replace("_", " ").title())
        lines = [
            f"{emoji} <b>AI Guru — {title}</b>",
            "",
            html.escape(str(payload.get("message", "Attention needed during study session."))),
            f"<i>Confidence: {int(float(payload.get('confidence', 0)) * 100)}% · "
            f"Duration: {float(payload.get('duration_seconds', 0)):.0f}s</i>",
            f"<i>Session: {html.escape(str(payload.get('session_id', ''))[:18])}</i>",
        ]
        return "\n".join(lines)
    if kind == "session_summary":
        lines = [
            "📊 <b>AI Guru — Session Report</b>",
            "",
            f"⏱ Duration: {float(payload.get('duration_minutes', 0)):.0f} min",
            f"🎯 Focus score: {float(payload.get('focus_score', 0)):.0f}/100",
            f"⚡ Engagement: {float(payload.get('engagement_score', 0)):.0f}/100",
            f"⚠️ Warnings: {int(payload.get('warning_count', 0))}",
        ]
        if payload.get("xp_earned"):
            lines.append(f"🏅 XP earned: +{int(payload['xp_earned'])}")
        if payload.get("summary"):
            lines += ["", html.escape(str(payload["summary"])[:500])]
        return "\n".join(lines)
    if kind == "session_start":
        return (
            "▶️ <b>AI Guru — Study Session Started</b>\n\n"
            f"👤 Student: {html.escape(str(payload.get('student_name', 'Student')))}\n"
            f"📚 Subject: {html.escape(str(payload.get('subject', 'General')))}\n"
            f"⏱ Target: {float(payload.get('target_minutes', 25)):.0f} min"
        )
    return json.dumps(payload)[:800]


async def enqueue(kind: str, payload: Dict[str, Any]) -> int:
    """Queue a notification for resilient delivery."""
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                retries INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL DEFAULT 0,
                last_error TEXT,
                sent_at REAL
            )
            """
        )
        cursor = await db.execute(
            "INSERT INTO notification_outbox (created_at, kind, payload_json) VALUES (?, ?, ?)",
            (time.time(), kind, json.dumps(payload)),
        )
        await db.commit()
        row_id = int(cursor.lastrowid or 0)
    logger.info("Queued %s notification #%d", kind, row_id)
    return row_id


async def _load_telegram_config(parent_id: str = "default") -> Optional[Dict[str, str]]:
    try:
        from deeptutor.services.remote.kv_settings import ensure_kv_settings

        async with aiosqlite.connect(_db_path()) as db:
            await ensure_kv_settings(db)
            cursor = await db.execute(
                "SELECT value FROM settings WHERE key = ?", (f"telegram_{parent_id}",)
            )
            row = await cursor.fetchone()
        if not row or not row[0]:
            return None
        data = json.loads(row[0])
        if not data.get("bot_token") or not data.get("chat_id"):
            return None
        if not data.get("enabled", True):
            return None
        return {"bot_token": data["bot_token"], "chat_id": data["chat_id"]}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load telegram config: %s", exc)
        return None


async def flush_once(limit: int = 20) -> int:
    """Attempt delivery of due notifications. Returns number sent.

    Claims rows atomically (pending → sending) so a concurrent worker or an
    immediate-flush task can never deliver the same notification twice.
    """
    from deeptutor.services.remote.telegram_notifier import TelegramNotifier

    config = await _load_telegram_config()
    if not config:
        return 0

    sent = 0
    now = time.time()
    claimed: list = []
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS notification_outbox ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL,"
            "kind TEXT NOT NULL, payload_json TEXT NOT NULL,"
            "status TEXT NOT NULL DEFAULT 'pending', retries INTEGER NOT NULL DEFAULT 0,"
            "next_attempt_at REAL NOT NULL DEFAULT 0, last_error TEXT, sent_at REAL)"
        )
        # Recover rows stuck in 'sending' (crash between claim and mark).
        await db.execute(
            "UPDATE notification_outbox SET status = 'pending'"
            " WHERE status = 'sending' AND next_attempt_at < ?",
            (now - 120,),
        )
        cursor = await db.execute(
            "SELECT id FROM notification_outbox WHERE status = 'pending' AND next_attempt_at <= ?"
            " ORDER BY created_at ASC LIMIT ?",
            (now, limit),
        )
        ids = [r[0] for r in await cursor.fetchall()]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            cur2 = await db.execute(
                f"UPDATE notification_outbox SET status='sending' WHERE id IN ({placeholders})"
                " AND status='pending'",
                ids,
            )
            await db.commit()
            if cur2.rowcount != len(ids):
                # Another worker claimed some first; keep only ours.
                cur3 = await db.execute(
                    f"SELECT id FROM notification_outbox WHERE id IN ({placeholders}) AND status='sending'",
                    ids,
                )
                ids = [r[0] for r in await cur3.fetchall()]
            claimed = ids

    for row_id in claimed:
        row = await _load_row(row_id)
        if row is None:
            continue
        payload = json.loads(row["payload_json"])
        text = _compose_message(row["kind"], payload)
        ok = await TelegramNotifier.send_message(
            bot_token=config["bot_token"], chat_id=config["chat_id"], text=text
        )
        if ok:
            sent += 1
            await _mark(row_id, sent=True)
        else:
            retries = int(row["retries"]) + 1
            if retries >= _MAX_RETRIES:
                await _mark(row_id, dead=True, error="max retries exceeded")
                logger.warning("Dropped notification #%d after %d retries", row_id, retries)
            else:
                delay = _backoff_for(retries)
                await _mark(row_id, error="send failed", retries=retries,
                            next_attempt=time.time() + delay, back_to_pending=True)
    if claimed:
        logger.info("Outbox flush: %d/%d delivered", sent, len(claimed))
    return sent


async def _load_row(row_id: int):
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, kind, payload_json, retries FROM notification_outbox WHERE id = ?",
            (row_id,),
        )
        return await cursor.fetchone()


async def _mark(row_id: int, *, sent: bool = False, dead: bool = False,
                error: Optional[str] = None, retries: int = 0,
                next_attempt: float = 0.0, back_to_pending: bool = False) -> None:
    async with aiosqlite.connect(_db_path()) as db:
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


async def _worker_loop() -> None:
    while True:
        try:
            await flush_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("Outbox worker iteration failed: %s", exc)
        await asyncio.sleep(20)


def start_notification_worker() -> None:
    """Idempotently start the background delivery loop (loop-aware)."""
    global _worker_task, _worker_task_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if (
        _worker_task is not None
        and not _worker_task.done()
        and _worker_task_loop is loop
    ):
        return
    if _worker_task is not None and not _worker_task.done():
        # Task belongs to a different (likely closed) loop — drop it.
        _worker_task.cancel()
    _worker_task_loop = loop
    _worker_task = loop.create_task(_worker_loop())
    logger.info("Notification outbox worker started")
