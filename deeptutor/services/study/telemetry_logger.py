from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

import aiosqlite

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

class TelemetryLogger:
    """Logs telemetry events for study sessions with batching support."""

    VALID_EVENT_TYPES = {
        'PRESENCE_CHANGE', 'LOOKING_AWAY', 'PHONE_DETECTED', 
        'POSTURE_SHIFT', 'IDENTITY_VERIFIED', 'LIVENESS_CHECK', 
        'WARNING_ISSUED', 'SESSION_PAUSED', 'SESSION_RESUMED'
    }
    VALID_SEVERITIES = {'info', 'warning', 'alert'}

    def __init__(self) -> None:
        self.db_path = get_path_service().user_dir / 'chat_history.db'
        self._batch: List[Tuple[str, str, str, float, float, str, float]] = []
        self._flush_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._start_flusher()

    def _start_flusher(self) -> None:
        """Starts the background flusher task."""
        self._flush_task = asyncio.create_task(self._flusher())

    async def _flusher(self) -> None:
        """Periodically flushes accumulated events."""
        while True:
            await asyncio.sleep(5)
            await self.flush()

    async def flush(self) -> None:
        """Flushes the current batch of events to the database."""
        async with self._lock:
            if not self._batch:
                return
            batch_to_insert = self._batch[:]
            self._batch.clear()

        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.executemany(
                    """INSERT INTO monitoring_events
                       (session_id, event_type, severity, confidence, duration_seconds, metadata_json, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    batch_to_insert
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to flush telemetry events: {e}")

    async def log_event(self, session_id: str, event_type: str, severity: str, confidence: float, duration_seconds: float, metadata: Dict[str, Any]) -> None:
        """Logs a single telemetry event."""
        if event_type not in self.VALID_EVENT_TYPES:
            logger.warning(f"Invalid event_type: {event_type}")
            return
        if severity not in self.VALID_SEVERITIES:
            logger.warning(f"Invalid severity: {severity}")
            return

        event_id = uuid.uuid4().hex
        now = time.time()
        metadata_str = json.dumps(metadata)

        async with self._lock:
            self._batch.append((session_id, event_type, severity, confidence, duration_seconds, metadata_str, now))

    async def get_session_events(self, session_id: str, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves events for a session, optionally filtered by type."""
        await self.flush() # Ensure recent events are available
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
            'avg_confidence': 0.0
        }

        if not events:
            return summary

        total_conf = 0.0
        for event in events:
            etype = event['event_type']
            summary['by_type'][etype] = summary['by_type'].get(etype, 0) + 1
            total_conf += event['confidence']

        summary['avg_confidence'] = total_conf / len(events)
        return summary
