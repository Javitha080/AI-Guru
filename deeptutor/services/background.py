"""Strongly-referenced fire-and-forget background tasks.

``asyncio.create_task`` results that are discarded can be garbage-collected
mid-execution: the event loop keeps only *weak* references to running tasks
(CPython docs explicitly warn about this). Symptoms are intermittent — a
queued Telegram flush, an audit write, or a vault-staging capture silently
never runs.

``spawn_bg`` keeps every spawned task in a module-level set until it
completes, so a task can never be collected while still pending. Failures
are logged instead of swallowed by "Task exception was never retrieved".
"""

from __future__ import annotations

import asyncio
import logging
from typing import Coroutine, Set

logger = logging.getLogger(__name__)

_tasks: Set[asyncio.Task] = set()


def spawn_bg(coro: Coroutine, *, name: str = "bg") -> asyncio.Task | None:
    """Schedule ``coro`` fire-and-forget, holding a strong reference to it."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop (sync context): nothing sensible to schedule.
        logger.debug("spawn_bg(%s) skipped: no running loop", name)
        return None

    task = loop.create_task(coro, name=name)
    _tasks.add(task)
    task.add_done_callback(_on_done)
    return task


def _on_done(task: asyncio.Task) -> None:
    _tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("Background task %s failed: %s", task.get_name(), exc)


def pending_count() -> int:
    """Number of still-pending background tasks (test/diagnostics hook)."""
    return len(_tasks)
