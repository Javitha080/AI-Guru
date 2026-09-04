"""SQLite-backed Telegram notification outbox.

Warnings and session summaries produced by the local monitoring engine are
queued durably and delivered with retry/backoff so a temporary internet loss
never silently drops parent notifications.

Table ``notification_outbox`` lives in the user's chat_history.db and is
created lazily by this module (additive; does not touch schema.py).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any, Dict, List, Optional
import uuid

import aiosqlite

from deeptutor.services.monitoring.monitoring_config import DEFAULT_THRESHOLDS
from deeptutor.services.monitoring.outbox_repo import (
    db_path as _db_path,
)
from deeptutor.services.monitoring.outbox_repo import (
    ensure_outbox as _ensure_outbox,
)
from deeptutor.services.monitoring.outbox_repo import (
    load_row as _load_row,
)
from deeptutor.services.monitoring.outbox_repo import (
    mark as _mark,
)

logger = logging.getLogger(__name__)

_MAX_RETRIES = DEFAULT_THRESHOLDS.outbox_max_retries
_BASE_BACKOFF = DEFAULT_THRESHOLDS.outbox_base_backoff
_MAX_BACKOFF = DEFAULT_THRESHOLDS.outbox_max_backoff
# How long a claimed ('sending') row's lease lasts before another flush may
# recover it as crash-orphaned. Covers any sane Telegram round-trip.
_CLAIM_LEASE_SECONDS = 300.0
# Pending rows older than this are expired instead of delivered. Without it,
# alerts accumulated while Telegram was unconfigured (or while the parent had
# notifications disabled) all flushed the moment a token was saved — stale
# "Study Session Started"/warning messages arriving hours later as if live.
_STALE_AFTER_SECONDS = DEFAULT_THRESHOLDS.outbox_stale_after
# Base64 length cap for an optional alert photo (~400 KB decoded JPEG).
_MAX_PHOTO_B64_LEN = 550_000

_worker_task: Optional[asyncio.Task] = None
_worker_task_loop: Optional[asyncio.AbstractEventLoop] = None


def _backoff_for(retries: int) -> float:
    return min(_BASE_BACKOFF * (2 ** max(0, retries - 1)), _MAX_BACKOFF)


def _portal_base_url() -> Optional[str]:
    """Public tunnel base URL when live — so every alert carries a one-tap
    link back to the Parent Portal. None when LAN-only/offline (honest)."""
    from deeptutor.services.remote.portal_urls import public_tunnel_url

    return public_tunnel_url()


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
            student_name=str(payload.get("student_name") or "Student"),
            subject=str(payload.get("subject") or "General"),
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


async def enqueue(kind: str, payload: Dict[str, Any], parent_id: str = "default") -> int:
    """Queue a notification for resilient delivery to one parent.

    Events produced while that parent's Telegram is unconfigured/disabled
    are dropped on the floor: the outbox exists to survive temporary
    *network* loss, not to replay everything that happened before the
    parent finished setup as if it were live.
    """
    from deeptutor.services.remote.telegram_config import TelegramConfigStore

    if await TelegramConfigStore.get(parent_id) is None:
        logger.debug("Dropped %s notification for %s: Telegram not configured", kind, parent_id)
        return 0
    async with aiosqlite.connect(_db_path()) as db:
        await _ensure_outbox(db)
        cursor = await db.execute(
            "INSERT INTO notification_outbox (created_at, kind, payload_json, parent_id)"
            " VALUES (?, ?, ?, ?)",
            (time.time(), kind, json.dumps(payload), parent_id or "default"),
        )
        await db.commit()
        row_id = int(cursor.lastrowid or 0)
    logger.info("Queued %s notification #%d for %s", kind, row_id, parent_id)
    return row_id


async def enqueue_for_parents(
    kind: str, payload: Dict[str, Any], parent_ids: List[str]
) -> List[int]:
    """Fan one event out to several parents; skips unconfigured ones.

    Returns the queued row ids (empty when nobody could receive it).
    """
    from deeptutor.services.remote.telegram_config import TelegramConfigStore

    row_ids: List[int] = []
    seen: set[str] = set()
    for parent_id in parent_ids or ["default"]:
        parent_id = parent_id or "default"
        if parent_id in seen:
            continue
        seen.add(parent_id)
        if await TelegramConfigStore.get(parent_id) is None:
            logger.debug(
                "Dropped %s notification for %s: Telegram not configured", kind, parent_id
            )
            continue
        async with aiosqlite.connect(_db_path()) as db:
            await _ensure_outbox(db)
            cursor = await db.execute(
                "INSERT INTO notification_outbox (created_at, kind, payload_json, parent_id)"
                " VALUES (?, ?, ?, ?)",
                (time.time(), kind, json.dumps(payload), parent_id),
            )
            await db.commit()
            row_ids.append(int(cursor.lastrowid or 0))
    if row_ids:
        logger.info("Queued %s notification for %d parent(s): %s", kind, len(row_ids), row_ids)
    return row_ids


async def enqueue_for_student(
    kind: str, payload: Dict[str, Any], student_id: str
) -> List[int]:
    """Fan one event out to every parent linked to a student.

    Falls back to the default parent when nobody linked the student yet
    (single-home setup). Failures in link resolution degrade to default
    rather than dropping the alert.
    """
    try:
        from deeptutor.services.remote.pairing import PairingService

        parent_ids = await PairingService.get_parent_ids_for_student(student_id or "student-primary")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Parent fan-out degraded to default: %s", exc)
        parent_ids = ["default"]
    return await enqueue_for_parents(kind, payload, parent_ids)


async def _load_telegram_config(parent_id: str = "default") -> Optional[Dict[str, str]]:
    """Legacy accessor — delegates to the shared TelegramConfigStore."""
    try:
        from deeptutor.services.remote.telegram_config import TelegramConfigStore

        return await TelegramConfigStore.get(parent_id)
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

    from deeptutor.services.remote.telegram_config import TelegramConfigStore
    from deeptutor.services.remote.telegram_notifier import TelegramNotifier

    sent = 0
    claimed: list = []
    async with aiosqlite.connect(_db_path()) as db:
        await _ensure_outbox(db)
        # Recover rows stuck in 'sending' (crash between claim and mark)
        # once their claim lease expires. Pre-upgrade rows have no
        # claimed_at stamp and are recovered via the NULL branch.
        await db.execute(
            "UPDATE notification_outbox SET status = 'pending'"
            " WHERE status = 'sending'"
            " AND (claimed_at IS NULL OR claimed_at < ?)",
            (now - _CLAIM_LEASE_SECONDS,),
        )
        cursor = await db.execute(
            "SELECT id FROM notification_outbox WHERE status = 'pending' AND next_attempt_at <= ?"
            " ORDER BY created_at ASC LIMIT ?",
            (now, limit),
        )
        ids = [r[0] for r in await cursor.fetchall()]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            # Stamp a per-flush claim token into the DEDICATED claimed_by
            # column during the claim (last_error stays reserved for real
            # delivery errors). The follow-up select filters on THAT token,
            # so it can never re-adopt rows another concurrent flush
            # claimed between our UPDATE and SELECT.
            claim_token = f"claim:{uuid.uuid4().hex}"
            params = [claim_token, now, now + _CLAIM_LEASE_SECONDS, *ids]
            await db.execute(
                f"UPDATE notification_outbox SET status='sending', claimed_by=?,"
                f" claimed_at=?, next_attempt_at=? WHERE id IN ({placeholders}) AND status='pending'",
                params,
            )
            await db.commit()
            cur3 = await db.execute(
                f"SELECT id FROM notification_outbox WHERE id IN ({placeholders})"
                f" AND status='sending' AND claimed_by=?",
                [*ids, claim_token],
            )
            claimed = [r[0] for r in await cur3.fetchall()]

    for row_id in claimed:
        row = await _load_row(row_id)
        if row is None:
            continue
        try:
            try:
                row_parent = str(row["parent_id"] or "default")
            except (KeyError, IndexError):
                row_parent = "default"
            config = await TelegramConfigStore.get(row_parent)
            if not config:
                # Parent disabled/revoked Telegram after enqueue: retire the
                # row instead of retrying forever against a dead config.
                await _mark(row_id, dead=True, error="telegram config removed/disabled")
                logger.info(
                    "Retired notification #%d: telegram unconfigured for %s", row_id, row_parent
                )
                continue
            payload = json.loads(row["payload_json"])
            text = _compose_message(row["kind"], payload)

            # Alert rows may carry the incident snapshot: deliver via sendPhoto with
            # the composed text as caption; fall back to a plain message when the
            # photo is absent or undecodable so the alert itself never drops.
            photo_b64 = payload.get("photo_b64")
            photo_bytes = None
            if isinstance(photo_b64, str) and photo_b64:
                if len(photo_b64) > _MAX_PHOTO_B64_LEN:
                    logger.warning(
                        "Notification #%d photo %d chars exceeds %d cap; sending text-only",
                        row_id, len(photo_b64), _MAX_PHOTO_B64_LEN,
                    )
                else:
                    try:
                        photo_bytes = base64.b64decode(photo_b64)
                    except Exception:  # noqa: BLE001
                        photo_bytes = None

            if photo_bytes:
                ok = await TelegramNotifier.send_photo(
                    bot_token=config["bot_token"],
                    chat_id=config["chat_id"],
                    photo_bytes=photo_bytes,
                    caption=text,
                )
                if not ok:
                    # Fall back to text if photo delivery failed (e.g. format, size, or caption issue)
                    logger.info("Photo send failed for notification #%d; falling back to text", row_id)
                    ok = await TelegramNotifier.send_message(
                        bot_token=config["bot_token"], chat_id=config["chat_id"], text=text
                    )
            else:
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
        except Exception as exc:  # noqa: BLE001 - isolate corrupted or failing item
            logger.warning("Error processing notification #%d: %s", row_id, exc)
            await _mark(row_id, dead=True, error=f"processing failed: {exc}")
    if claimed:
        logger.info("Outbox flush: %d/%d delivered", sent, len(claimed))
    return sent


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
