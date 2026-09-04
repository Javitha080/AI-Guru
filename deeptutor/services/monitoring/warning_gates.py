"""Warning throttling primitives (extracted from WarningManager)."""

from __future__ import annotations

import collections
from typing import Deque, Dict


class EpisodeGate:
    """One notification per continuous distraction episode."""

    def __init__(self) -> None:
        self._notified: Dict[str, bool] = {}
        self.armed = False

    def observe(self, is_distracted: bool, category: object = None) -> None:
        self.armed = True
        if not is_distracted or category is None:
            self._notified.clear()
            return
        cat = getattr(category, "value", str(category))
        if cat in ("NONE", "", None):
            self._notified.clear()

    def already_notified(self, category: str) -> bool:
        return bool(self.armed and self._notified.get(category))

    def mark_notified(self, category: str) -> None:
        self._notified[category] = True

    def reset(self) -> None:
        self._notified.clear()
        self.armed = False


class RateLimiter:
    """Sliding-window max-N-per-window gate."""

    def __init__(self, max_events: int = 5, window_seconds: float = 600.0) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._history: Deque[float] = collections.deque()

    def allow(self, timestamp: float) -> bool:
        while self._history and (timestamp - self._history[0] > self.window_seconds):
            self._history.popleft()
        if len(self._history) >= self.max_events:
            return False
        self._history.append(timestamp)
        return True

    def reset(self) -> None:
        self._history.clear()


__all__ = ["EpisodeGate", "RateLimiter"]
