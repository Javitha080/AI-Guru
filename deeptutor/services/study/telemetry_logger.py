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
    """Flushes the current batch of events to the database.

    On DB failure the batch is re-queued at the FRONT (bounded to 2000
    events) so transient locks/full-disk never silently drop telemetry.
    """
    async with _get_lock():
        if not _batch:
            return
        batch_to_insert = _batch[:]
        _batch.clear()

    db_path = get_path_service().user_dir / "chat_history.db"
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.executemany(
                """INSERT INTO monitoring_events
                   (session_id, event_type, severity, confidence, duration_seconds, metadata_json, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                batch_to_insert,
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to flush telemetry events: {e}")
        # Re-queue for the next flusher pass instead of dropping.
        async with _get_lock():
            _batch[0:0] = batch_to_insert
            # Bound memory: drop oldest when the backlog grows unbounded
            # (sustained DB outage) rather than growing without limit.
            if len(_batch) > 2000:
                dropped = len(_batch) - 2000
                del _batch[:dropped]
                logger.warning("Telemetry backlog capped; dropped %d oldest events", dropped)


class TelemetryLogger:
    """Logs telemetry events for study sessions with batching support."""

    VALID_EVENT_TYPES = {
        "PRESENCE_CHANGE",
        "LOOKING_AWAY",
        "PHONE_DETECTED",
        "STUDENT_AWAY",
        "IDENTITY_MISMATCH",
        "DROWSINESS",
        "POSTURE_SHIFT",
        "IDENTITY_VERIFIED",
        "LIVENESS_CHECK",
        "WARNING_ISSUED",
        "NUDGE_ISSUED",
        "SESSION_PAUSED",
        "SESSION_RESUMED",
    }
    VALID_SEVERITIES = {"info", "warning", "alert"}

    def __init__(self) -> None:
        self.db_path = get_path_service().user_dir / "chat_history.db"
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Telemetry DB parent not writable: %s", exc)
        _ensure_flusher()

    # Hardening bounds: attacker- or bug-controlled telemetry must never
    # poison reports (negative durations inflated distracted_seconds; huge
    # metadata blobs grew monitoring_events without bound).
    _MAX_CONFIDENCE = 1.0
    _MAX_DURATION_SECONDS = 3600.0
    _MAX_METADATA_CHARS = 4096
    _SESSION_ID_RE = r"^[A-Za-z0-9_-]{1,128}$"

    async def log_event(
        self,
        session_id: str,
        event_type: str,
        severity: str,
        confidence: float,
        duration_seconds: float,
        metadata: Dict[str, Any],
    ) -> bool:
        """Logs a single telemetry event. Returns True when accepted.

        Invalid payloads are rejected (False) instead of persisted, so a
        misbehaving client cannot inject fake warnings or negative durations
        that would corrupt focus scores and parent incident feeds.
        """
        import re as _re

        if not isinstance(session_id, str) or not _re.match(self._SESSION_ID_RE, session_id):
            logger.warning("Rejected telemetry: bad session_id %r", session_id)
            return False
        if event_type not in self.VALID_EVENT_TYPES:
            logger.warning(f"Invalid event_type: {event_type}")
            return False
        if severity not in self.VALID_SEVERITIES:
            logger.warning(f"Invalid severity: {severity}")
            return False
        try:
            confidence_f = float(confidence)
            duration_f = float(duration_seconds)
        except (TypeError, ValueError):
            logger.warning("Rejected telemetry: non-numeric confidence/duration")
            return False
        if not (0.0 <= confidence_f <= self._MAX_CONFIDENCE):
            logger.warning("Rejected telemetry: confidence %r out of range", confidence)
            return False
        if not (0.0 <= duration_f <= self._MAX_DURATION_SECONDS):
            logger.warning("Rejected telemetry: duration %r out of range", duration_seconds)
            return False
        if not isinstance(metadata, dict):
            logger.warning("Rejected telemetry: metadata must be an object")
            return False

        now = time.time()
        try:
            metadata_str = json.dumps(metadata)
        except (TypeError, ValueError):
            logger.warning("Rejected telemetry: metadata not JSON-serializable")
            return False
        if len(metadata_str) > self._MAX_METADATA_CHARS:
            logger.warning(
                "Rejected telemetry: metadata %d chars exceeds %d cap",
                len(metadata_str),
                self._MAX_METADATA_CHARS,
            )
            return False

        _ensure_flusher()
        async with _get_lock():
            _batch.append(
                (
                    session_id,
                    event_type,
                    severity,
                    confidence_f,
                    duration_f,
                    metadata_str,
                    now,
                )
            )
        return True

    async def get_session_events(
        self, session_id: str, event_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieves events for a session, optionally filtered by type."""
        import re as _re2

        if not isinstance(session_id, str) or not _re2.match(
            self._SESSION_ID_RE, session_id
        ):
            return []
        if event_type is not None and event_type not in self.VALID_EVENT_TYPES:
            return []
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

        summary: Dict[str, Any] = {
            "total_events": len(events),
            "by_type": {},
            "by_severity": {},
            "avg_confidence": 0.0,
        }

        if not events:
            return summary

        total_conf = 0.0
        for event in events:
            etype = event["event_type"]
            summary["by_type"][etype] = summary["by_type"].get(etype, 0) + 1
            sev = event["severity"] if event["severity"] in ("info", "warning", "alert") else "info"
            summary["by_severity"][sev] = summary["by_severity"].get(sev, 0) + 1
            total_conf += event["confidence"]

        # Warnings that actually count against the student (info-level
        # presence pings like STUDENT_AWAY are deliberately excluded).
        summary["actionable_warnings"] = summary["by_severity"].get("warning", 0) + summary[
            "by_severity"
        ].get("alert", 0)
        summary["avg_confidence"] = total_conf / len(events)
        return summary
