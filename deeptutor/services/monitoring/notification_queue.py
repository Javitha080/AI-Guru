"""SQLite-backed Telegram notification outbox.

Warnings and session summaries produced by the local monitoring engine are
queued durably and delivered with retry/backoff so a temporary internet loss
never silently drops parent notifications.

Table ``notification_outbox`` lives in the user's chat_history.db and is
created lazily by this module (additive; does not touch schema.py).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional
import uuid

import aiosqlite

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

_MAX_RETRIES = 8
_BASE_BACKOFF = 30.0
_MAX_BACKOFF = 600.0
# How long a claimed ('sending') row's lease lasts before another flush may
# recover it as crash-orphaned. Covers any sane Telegram round-trip.
_CLAIM_LEASE_SECONDS = 300.0
# Pending rows older than this are expired instead of delivered. Without it,
# alerts accumulated while Telegram was unconfigured (or while the parent had
# notifications disabled) all flushed the moment a token was saved — stale
# "Study Session Started"/warning messages arriving hours later as if live.
_STALE_AFTER_SECONDS = 3600.0

_worker_task: Optional[asyncio.Task] = None
_worker_task_loop: Optional[asyncio.AbstractEventLoop] = None


def _db_path():
    return get_path_service().user_dir / "chat_history.db"


def _backoff_for(retries: int) -> float:
    return min(_BASE_BACKOFF * (2 ** max(0, retries - 1)), _MAX_BACKOFF)


def _portal_base_url() -> Optional[str]:
    """Public tunnel base URL when live — so every alert carries a one-tap
    link back to the Parent Portal. None when LAN-only/offline (honest)."""
    try:
        from deeptutor.services.remote.tunnel_gateway import TunnelGateway

        base = TunnelGateway.get_tunnel_url()
        if base and TunnelGateway.is_url_public():
            return str(base)
    except Exception:  # noqa: BLE001 - link is an enhancement, never a failure
        pass
    return None


def _compose_message(kind: str, payload: Dict[str, Any]) -> str:
    # Single source of formatting truth: the TelegramNotifier composers.
    # The outbox only maps its durable payload onto them and injects the
    # live portal link when the tunnel is actually public.
    from deeptutor.services.remote.telegram_notifier import TelegramNotifier

    portal = _portal_base_url()

    if kind == "warning":
        severity = str(payload.get("severity", ""))
        category = str(payload.get("category", "NOTICE"))
        message = str(payload.get("message", "") or "Attention needed during study session.")
        if category in ("NOTICE", "", "None"):
            # Non-distraction notices keep the old generic framing.
            emoji = {"alert": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(severity, "⚠️")
            lines = [
                f"{emoji} <b>AI Guru — {TelegramNotifier._esc(category.replace('_', ' ').title())}</b>",
                "",
                TelegramNotifier._esc(message),
                f"<i>Confidence: {int(float(payload.get('confidence', 0)) * 100)}% · "
                f"Duration: {float(payload.get('duration_seconds', 0)):.0f}s</i>",
            ]
            portal_section = TelegramNotifier._portal_section(portal)
            if portal_section:
                lines.append(portal_section.lstrip("\n"))
            return "\n".join(lines)
        return TelegramNotifier.compose_distraction_alert(
            event_type=category,
            details=message,
            tunnel_url=portal,
            confidence=payload.get("confidence"),
            duration_seconds=payload.get("duration_seconds"),
            session_id=str(payload.get("session_id", "")),
            severity=severity,
        )
    if kind == "session_summary":
        return TelegramNotifier.compose_session_summary(
            student_name=str(payload.get("student_name") or payload.get("student_id") or "Student"),
            subject=str(payload.get("subject") or "Study Session"),
            duration_minutes=float(payload.get("duration_minutes", 0)),
            focus_score=float(payload.get("focus_score", 0)),
            xp_earned=int(payload.get("xp_earned", 0) or 0),
            ai_summary=str(payload.get("summary") or ""),
            engagement_score=payload.get("engagement_score"),
            warning_count=payload.get("warning_count"),
            tunnel_url=portal,
        )
    if kind == "session_start":
        return TelegramNotifier.compose_session_start(
            student_name=str(payload.get("student_name", "Student")),
            subject=str(payload.get("subject", "General")),
            target_minutes=int(float(payload.get("target_minutes", 25))),
            tunnel_url=portal,
        )
    return json.dumps(payload)[:800]


_OUTBOX_DDL = (
    "CREATE TABLE IF NOT EXISTS notification_outbox ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "created_at REAL NOT NULL,"
    "kind TEXT NOT NULL,"
    "payload_json TEXT NOT NULL,"
    "status TEXT NOT NULL DEFAULT 'pending',"
    "retries INTEGER NOT NULL DEFAULT 0,"
    "next_attempt_at REAL NOT NULL DEFAULT 0,"
    "last_error TEXT,"
    "sent_at REAL)"
)


async def _ensure_outbox(db: aiosqlite.Connection) -> None:
    await db.execute(_OUTBOX_DDL)


async def enqueue(kind: str, payload: Dict[str, Any]) -> int:
    """Queue a notification for resilient delivery.

    Events produced while Telegram is unconfigured/disabled are dropped on
    the floor: the outbox exists to survive temporary *network* loss, not to
    replay everything that happened before the parent finished setup as if
    it were live.
    """
    if await _load_telegram_config() is None:
        logger.debug("Dropped %s notification: Telegram not configured", kind)
        return 0
    async with aiosqlite.connect(_db_path()) as db:
        await _ensure_outbox(db)
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
    now = time.time()
    # Expire stale pendings BEFORE anything else — including the config
    # check — so an hours-old backlog drains even while Telegram is
    # unconfigured instead of resurrecting on a future setup.
    async with aiosqlite.connect(_db_path()) as db:
        await _ensure_outbox(db)
        await db.execute(
            "UPDATE notification_outbox SET status='dead', last_error=?"
            " WHERE status='pending' AND created_at < ?",
            (f"expired: pending longer than {_STALE_AFTER_SECONDS:.0f}s", now - _STALE_AFTER_SECONDS),
        )
        await db.commit()

    from deeptutor.services.remote.telegram_notifier import TelegramNotifier

    config = await _load_telegram_config()
    if not config:
        return 0

    sent = 0
    claimed: list = []
    async with aiosqlite.connect(_db_path()) as db:
        await _ensure_outbox(db)
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
            # Stamp a per-flush claim token into last_error during the claim.
            # The follow-up select filters on THAT token, so it can never
            # re-adopt rows another concurrent flush claimed between our
            # UPDATE and SELECT (the old status-only filter could not tell
            # the two apart and double-delivered).
            claim_token = f"claim:{uuid.uuid4().hex}"
            params = [claim_token, now + _CLAIM_LEASE_SECONDS, *ids]
            await db.execute(
                f"UPDATE notification_outbox SET status='sending', last_error=?,"
                f" next_attempt_at=? WHERE id IN ({placeholders}) AND status='pending'",
                params,
            )
            await db.commit()
            # NOTE binding order: the IN-list placeholders come FIRST in the
            # SQL text, then last_error=?
            cur3 = await db.execute(
                f"SELECT id FROM notification_outbox WHERE id IN ({placeholders})"
                f" AND status='sending' AND last_error=?",
                [*ids, claim_token],
            )
            claimed = [r[0] for r in await cur3.fetchall()]

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
