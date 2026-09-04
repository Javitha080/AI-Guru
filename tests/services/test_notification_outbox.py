"""Regression tests for the Telegram notification outbox claim protocol.

The claim step must stamp a per-flush ownership token: a concurrent flush
must never adopt (and double-deliver) rows claimed by another flush.
"""

from __future__ import annotations

from pathlib import Path
import time

import aiosqlite
import pytest

from deeptutor.services.monitoring import notification_queue as nq


@pytest.fixture()
def isolated_outbox(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "chat_history.db"

    async def _seed():
        async with aiosqlite.connect(db_path) as db:
            await nq._ensure_outbox(db)
            await db.commit()

    import asyncio

    asyncio.run(_seed())
    monkeypatch.setattr(nq, "_db_path", lambda: db_path)
    return db_path


@pytest.mark.asyncio
async def test_flush_marks_sent_and_drains_queue(isolated_outbox, monkeypatch):
    async def _ok(**kwargs):
        return True

    async def _config(parent_id="default"):
        return {"bot_token": "t", "chat_id": "c"}

    from deeptutor.services.remote import telegram_notifier as tn

    monkeypatch.setattr(tn.TelegramNotifier, "send_message", staticmethod(_ok))
    monkeypatch.setattr(nq, "_load_telegram_config", _config)

    await nq.enqueue("warning", {"session_id": "s1", "category": "PHONE", "severity": "warning"})
    sent = await nq.flush_once()
    assert sent == 1
    # A second flush has nothing left to deliver.
    assert await nq.flush_once() == 0


@pytest.mark.asyncio
async def test_foreign_claim_is_never_adopted(isolated_outbox, monkeypatch):
    """A row sitting in 'sending' under ANOTHER flush's token stays untouched."""

    async def _ok(**kwargs):
        return True

    async def _config(parent_id="default"):
        return {"bot_token": "t", "chat_id": "c"}

    # Stub the config BEFORE enqueueing: since the stale-backlog fix,
    # unconfigured events are dropped at enqueue time.
    from deeptutor.services.remote import telegram_notifier as tn

    monkeypatch.setattr(tn.TelegramNotifier, "send_message", staticmethod(_ok))
    monkeypatch.setattr(nq, "_load_telegram_config", _config)

    row_id = await nq.enqueue("warning", {"session_id": "s2", "category": "AWAY"})
    assert row_id > 0

    import sqlite3

    def _claim_as_foreign():
        conn = sqlite3.connect(isolated_outbox)
        try:
            conn.execute(
                "UPDATE notification_outbox SET status='sending', last_error='claim:foreign-worker',"
                " next_attempt_at=? WHERE id=?",
                (time.time() + nq._CLAIM_LEASE_SECONDS, row_id),
            )
            conn.commit()
        finally:
            conn.close()

    _claim_as_foreign()

    sent = await nq.flush_once()
    assert sent == 0  # not ours — never delivered twice

    conn = sqlite3.connect(isolated_outbox)
    try:
        status, owner = conn.execute(
            "SELECT status, last_error FROM notification_outbox WHERE id=?", (row_id,)
        ).fetchone()
    finally:
        conn.close()
    assert status == "sending"
    assert owner == "claim:foreign-worker"


@pytest.mark.asyncio
async def test_enqueue_drops_events_while_telegram_unconfigured(isolated_outbox):
    """No ghost delivery: events produced before setup must never be queued."""
    row_id = await nq.enqueue("session_start", {"session_id": "s3", "student_name": "Primary"})

    assert row_id == 0, "unconfigured events must not enter the outbox"
    import sqlite3

    conn = sqlite3.connect(isolated_outbox)
    try:
        count = conn.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0]
    finally:
        conn.close()
    assert count == 0


@pytest.mark.asyncio
async def test_flush_expires_stale_backlog_but_delivers_fresh(isolated_outbox, monkeypatch):
    """A token saved hours later must not resurrect stale alerts as live ones."""
    import sqlite3

    stale_created = time.time() - (nq._STALE_AFTER_SECONDS + 120)
    async with aiosqlite.connect(isolated_outbox) as db:
        await db.execute(
            "INSERT INTO notification_outbox (created_at, kind, payload_json)"
            " VALUES (?, 'warning', ?)",
            (
                stale_created,
                '{"session_id": "old", "category": "STUDENT_AWAY", "severity": "info"}',
            ),
        )
        await db.execute(
            "INSERT INTO notification_outbox (created_at, kind, payload_json)"
            " VALUES (?, 'warning', ?)",
            (time.time(), '{"session_id": "new", "category": "PHONE", "severity": "alert"}'),
        )
        await db.commit()

    async def _ok(**kwargs):
        return True

    async def _config(parent_id="default"):
        return {"bot_token": "t", "chat_id": "c"}

    from deeptutor.services.remote import telegram_notifier as tn

    monkeypatch.setattr(tn.TelegramNotifier, "send_message", staticmethod(_ok))
    monkeypatch.setattr(nq, "_load_telegram_config", _config)

    sent = await nq.flush_once()
    assert sent == 1, "the fresh event delivers"

    conn = sqlite3.connect(isolated_outbox)
    try:
        rows = conn.execute(
            "SELECT status, last_error FROM notification_outbox ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()
    assert rows[0][0] == "dead", "stale backlog is expired, never replayed"
    assert "expired" in (rows[0][1] or "")
    assert rows[1][0] == "sent"


@pytest.mark.asyncio
async def test_flush_without_config_keeps_recent_rows_deliverable(isolated_outbox, monkeypatch):
    """Recent rows stay pending through a transient unconfigured window —
    only AGE expires them, so brief config hiccups don't lose live alerts."""
    import sqlite3

    async def _config(parent_id="default"):
        return {"bot_token": "t", "chat_id": "c"}

    # Queue while configured...
    monkeypatch.setattr(nq, "_load_telegram_config", _config)
    row_id = await nq.enqueue("warning", {"session_id": "s4", "severity": "warning"})
    assert row_id > 0

    # ...then the config disappears (stub removed) before the flush.
    monkeypatch.setattr(nq, "_load_telegram_config", lambda parent_id="default": _none_async())
    sent = await nq.flush_once()
    assert sent == 0

    conn = sqlite3.connect(isolated_outbox)
    try:
        status = conn.execute(
            "SELECT status FROM notification_outbox WHERE id=?", (row_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert status == "pending", "recent row must remain deliverable after re-config"


async def _none_async(parent_id: str = "default"):
    return None
