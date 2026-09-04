"""Shared score accumulation + episode tracking for monitoring loops.

Extracts the ~80 duplicated lines previously living in both
``browser_session.browser_driven_monitoring_loop`` and
``SystemMonitorSession``: running-mean focus/engagement, warning/
distraction counters, and edge-triggered distraction episodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Set


@dataclass
class ScoreAccumulator:
    """Running-mean focus/engagement over analyzed frames."""

    focus_sum: float = 0.0
    engagement_sum: float = 0.0
    ticks: int = 0
    distraction_count: int = 0
    warning_count: int = 0

    def add_frame(self, focus: float, engagement: float) -> None:
        self.focus_sum += float(focus or 0.0)
        self.engagement_sum += float(engagement or 0.0)
        self.ticks += 1

    def mean_focus(self, fallback: float = 0.0) -> float:
        if self.ticks > 0:
            return self.focus_sum / self.ticks
        return float(fallback or 0.0)

    def mean_engagement(self, fallback: float = 0.0) -> float:
        if self.ticks > 0:
            return self.engagement_sum / self.ticks
        return float(fallback or 0.0)

    def reset(self) -> None:
        self.focus_sum = 0.0
        self.engagement_sum = 0.0
        self.ticks = 0
        self.distraction_count = 0
        self.warning_count = 0


@dataclass
class EpisodeTracker:
    """Edge-triggered distraction episodes (one count per continuous type)."""

    active: Set[str] = field(default_factory=set)
    distraction_count: int = 0

    def on_frame(self, is_distracted: bool, dtype: str | None) -> bool:
        """Return True when a NEW distraction episode starts this frame."""
        if not is_distracted or not dtype:
            self.active.clear()
            return False
        if dtype not in self.active:
            self.active.add(dtype)
            self.distraction_count += 1
            return True
        return False

    def reset(self) -> None:
        self.active.clear()
        self.distraction_count = 0


__all__ = ["ScoreAccumulator", "EpisodeTracker"]
