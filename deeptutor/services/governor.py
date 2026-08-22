"""
AI Guru Dynamic Resource Governor.
==================================

Monitors system CPU and RAM usage, provides throttling hooks, and dynamically
adjusts background task frequency and Computer Vision (CV) frame rates to prevent
system freezes or out-of-memory crashes during heavy local LLM inference or CV processing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ResourceGovernor:
    """
    Dynamic resource supervisor enforcing CPU and RAM safety limits.
    """

    def __init__(
        self,
        cpu_threshold_percent: float = 85.0,
        ram_threshold_percent: float = 90.0,
        min_throttle_sleep: float = 0.05,
        max_throttle_sleep: float = 0.5,
    ) -> None:
        self.cpu_threshold_percent = cpu_threshold_percent
        self.ram_threshold_percent = ram_threshold_percent
        self.min_throttle_sleep = min_throttle_sleep
        self.max_throttle_sleep = max_throttle_sleep
        self._last_check_time: float = 0.0
        self._cached_cpu: float = 0.0
        self._cached_ram: float = 0.0
        self._cache_ttl_seconds: float = 0.5

    def _sample_resources(self) -> tuple[float, float]:
        """Sample current CPU and RAM usage percentages, cached with short TTL."""
        now = time.monotonic()
        if now - self._last_check_time < self._cache_ttl_seconds:
            return self._cached_cpu, self._cached_ram

        cpu_val = 0.0
        ram_val = 0.0
        try:
            import psutil

            cpu_val = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            ram_val = mem.percent
        except Exception:
            cpu_val = 0.0
            ram_val = 0.0

        self._cached_cpu = cpu_val
        self._cached_ram = ram_val
        self._last_check_time = now
        return cpu_val, ram_val

    def get_metrics(self) -> dict[str, Any]:
        """Return real-time resource utilization snapshot and overload flags."""
        cpu_pct, ram_pct = self._sample_resources()
        cpu_over = cpu_pct >= self.cpu_threshold_percent
        ram_over = ram_pct >= self.ram_threshold_percent
        overloaded = cpu_over or ram_over

        return {
            "cpu_percent": round(cpu_pct, 1),
            "ram_percent": round(ram_pct, 1),
            "cpu_threshold": self.cpu_threshold_percent,
            "ram_threshold": self.ram_threshold_percent,
            "is_overloaded": overloaded,
            "cpu_overloaded": cpu_over,
            "ram_overloaded": ram_over,
            "throttle_factor": self.get_throttle_factor(),
        }

    def is_overloaded(self) -> bool:
        """Check if either CPU or RAM exceeds safety thresholds (>85% CPU or >90% RAM)."""
        cpu_pct, ram_pct = self._sample_resources()
        return cpu_pct >= self.cpu_threshold_percent or ram_pct >= self.ram_threshold_percent

    def is_cpu_overloaded(self) -> bool:
        """Check if CPU exceeds threshold (>85%)."""
        cpu_pct, _ = self._sample_resources()
        return cpu_pct >= self.cpu_threshold_percent

    def is_ram_overloaded(self) -> bool:
        """Check if RAM exceeds threshold (>90%)."""
        _, ram_pct = self._sample_resources()
        return ram_pct >= self.ram_threshold_percent

    def get_throttle_factor(self) -> float:
        """
        Calculate throttle intensity factor from 0.0 (healthy) to 1.0 (critical overload).
        """
        cpu_pct, ram_pct = self._sample_resources()
        cpu_excess = max(0.0, cpu_pct - self.cpu_threshold_percent) / max(1.0, 100.0 - self.cpu_threshold_percent)
        ram_excess = max(0.0, ram_pct - self.ram_threshold_percent) / max(1.0, 100.0 - self.ram_threshold_percent)
        return min(1.0, max(cpu_excess, ram_excess))

    async def throttle_if_needed(self, task_name: str = "task") -> float:
        """
        If system is overloaded, dynamically sleep and yield execution.
        Returns the duration slept in seconds (0.0 if not throttled).
        """
        factor = self.get_throttle_factor()
        if factor > 0.0:
            sleep_duration = self.min_throttle_sleep + factor * (self.max_throttle_sleep - self.min_throttle_sleep)
            logger.debug(
                "ResourceGovernor: Throttling %s for %.3fs (factor=%.2f, CPU=%.1f%%, RAM=%.1f%%)",
                task_name,
                sleep_duration,
                factor,
                self._cached_cpu,
                self._cached_ram,
            )
            await asyncio.sleep(sleep_duration)
            return sleep_duration
        return 0.0

    def get_recommended_cv_fps(self, base_fps: int = 10) -> int:
        """
        Dynamically scale CV sampling FPS based on system resource pressure.
        - Under normal conditions: returns base_fps (e.g. 7-10 FPS).
        - Under moderate pressure (>85% CPU): reduces FPS to ~3-5 FPS.
        - Under critical pressure (>95% CPU or >92% RAM): drops FPS to 1-2 FPS.
        """
        cpu_pct, ram_pct = self._sample_resources()
        if cpu_pct >= 95.0 or ram_pct >= 95.0:
            return 1
        if cpu_pct >= self.cpu_threshold_percent or ram_pct >= self.ram_threshold_percent:
            return max(2, base_fps // 2)
        if cpu_pct >= 70.0:
            return max(4, int(base_fps * 0.75))
        return base_fps

    async def yield_execution(self) -> None:
        """Cooperative yield to the event loop, adding brief sleep if stressed."""
        factor = self.get_throttle_factor()
        if factor > 0.1:
            await asyncio.sleep(0.02 * factor)
        else:
            await asyncio.sleep(0)


_governor_instance: Optional[ResourceGovernor] = None


def get_resource_governor() -> ResourceGovernor:
    """Return singleton instance of ResourceGovernor."""
    global _governor_instance
    if _governor_instance is None:
        _governor_instance = ResourceGovernor()
    return _governor_instance
