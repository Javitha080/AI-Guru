from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

# --- process-wide batching state ---------------------------------------------
# One shared queue + one background flusher for every TelemetryLogger instance.
# (Previously each instance spawned its own infinite flusher task — a leak.)
_batch: List[Tuple[str, str, str, float, float, str, float]] = []
_lock: Optional[asyncio.Lock] = None
_flush_task: Optional[asyncio.Task] = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _ensure_flusher() -> None:
    """Starts (or restarts) the background flusher inside a running loop."""
    global _flush_task
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        return  # sync context: events stay queued until next async flush
    if _flush_task is None or _flush_task.done():
        _flush_task = running.create_task(_flusher())


async def _flusher() -> None:
    """Periodically flushes accumulated events."""
    while True:
        await asyncio.sleep(5)
        await flush()


async def flush() -> None:
    """Flushes the current batch of events to the database."""
    async with _get_lock():
        if not _batch:
            return
        batch_to_insert = _batch[:]
        _batch.clear()

    db_path = get_path_service().user_dir / 'chat_history.db'
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.executemany(
                """INSERT INTO monitoring_events
                   (session_id, event_type, severity, confidence, duration_seconds, metadata_json, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                batch_to_insert
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to flush telemetry events: {e}")


class TelemetryLogger:
    """Logs telemetry events for study sessions with batching support."""

    VALID_EVENT_TYPES = {
        'PRESENCE_CHANGE', 'LOOKING_AWAY', 'PHONE_DETECTED',
        'POSTURE_SHIFT', 'IDENTITY_VERIFIED', 'LIVENESS_CHECK',
        'WARNING_ISSUED', 'NUDGE_ISSUED', 'SESSION_PAUSED', 'SESSION_RESUMED'
    }
    VALID_SEVERITIES = {'info', 'warning', 'alert'}

    def __init__(self) -> None:
        self.db_path = get_path_service().user_dir / 'chat_history.db'
        _ensure_flusher()

    async def log_event(self, session_id: str, event_type: str, severity: str, confidence: float, duration_seconds: float, metadata: Dict[str, Any]) -> None:
        """Logs a single telemetry event."""
        if event_type not in self.VALID_EVENT_TYPES:
            logger.warning(f"Invalid event_type: {event_type}")
            return
        if severity not in self.VALID_SEVERITIES:
            logger.warning(f"Invalid severity: {severity}")
            return

        now = time.time()
        metadata_str = json.dumps(metadata)

        _ensure_flusher()
        async with _get_lock():
            _batch.append((session_id, event_type, severity, confidence, duration_seconds, metadata_str, now))

    async def get_session_events(self, session_id: str, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves events for a session, optionally filtered by type."""
        await flush()  # Ensure recent events are available
        events = []
        query = "SELECT * FROM monitoring_events WHERE session_id = ?"
        params = [session_id]

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        query += " ORDER BY timestamp ASC"

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                async for row in cursor:
                    events.append(dict(row))
        return events

    async def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """Gets an aggregated summary of events for a session."""
        events = await self.get_session_events(session_id)
        
        summary = {
            'total_events': len(events),
            'by_type': {},
            'by_severity': {},
            'avg_confidence': 0.0
        }

        if not events:
            return summary

        total_conf = 0.0
        for event in events:
            etype = event['event_type']
            summary['by_type'][etype] = summary['by_type'].get(etype, 0) + 1
            sev = event['severity'] if event['severity'] in ('info', 'warning', 'alert') else 'info'
            summary['by_severity'][sev] = summary['by_severity'].get(sev, 0) + 1
            total_conf += event['confidence']

        # Warnings that actually count against the student (info-level
        # presence pings like STUDENT_AWAY are deliberately excluded).
        summary['actionable_warnings'] = (
            summary['by_severity'].get('warning', 0) + summary['by_severity'].get('alert', 0)
        )
        summary['avg_confidence'] = total_conf / len(events)
        return summary
