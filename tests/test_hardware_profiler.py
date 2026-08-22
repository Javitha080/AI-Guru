"""
Unit tests for AI Guru Hardware Profiler and Dynamic Resource Governor.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch
import pytest

from deeptutor.services.governor import (
    ResourceGovernor,
    get_resource_governor,
)
from deeptutor.services.llm.hardware_profiler import (
    HardwareProfile,
    HardwareProfiler,
    HardwareTier,
    get_hardware_profile,
    get_hardware_profiler,
    get_hardware_tier,
)


# ---------------------------------------------------------------------------
# Hardware Profiler Tier Classification Tests
# ---------------------------------------------------------------------------

def test_hardware_profiler_high_tier_dedicated_gpu():
    """Verify system with >= 8GB VRAM is categorized as HIGH tier."""
    profiler = HardwareProfiler()
    tier = profiler._classify_tier(
        gpu_type="NVIDIA CUDA",
        vram_gb=12.0,
        ram_gb=32.0,
        cpu_physical_cores=8,
    )
    assert tier == HardwareTier.HIGH


def test_hardware_profiler_high_tier_apple_silicon():
    """Verify Apple Silicon with >= 16GB Unified RAM is categorized as HIGH tier."""
    profiler = HardwareProfiler()
    tier = profiler._classify_tier(
        gpu_type="Apple Metal (MPS)",
        vram_gb=11.2,
        ram_gb=16.0,
        cpu_physical_cores=8,
    )
    assert tier == HardwareTier.HIGH


def test_hardware_profiler_medium_tier_gpu():
    """Verify system with 4GB-7GB VRAM is categorized as MEDIUM tier."""
    profiler = HardwareProfiler()
    tier = profiler._classify_tier(
        gpu_type="NVIDIA CUDA",
        vram_gb=6.0,
        ram_gb=16.0,
        cpu_physical_cores=6,
    )
    assert tier == HardwareTier.MEDIUM


def test_hardware_profiler_medium_tier_cpu_only():
    """Verify CPU-only system with 16GB RAM and 4+ cores is categorized as MEDIUM tier."""
    profiler = HardwareProfiler()
    tier = profiler._classify_tier(
        gpu_type="CPU Fallback",
        vram_gb=0.0,
        ram_gb=16.0,
        cpu_physical_cores=4,
    )
    assert tier == HardwareTier.MEDIUM


def test_hardware_profiler_low_tier_cpu():
    """Verify low-spec CPU system (< 14GB RAM) is categorized as LOW tier."""
    profiler = HardwareProfiler()
    tier = profiler._classify_tier(
        gpu_type="CPU Fallback",
        vram_gb=0.0,
        ram_gb=8.0,
        cpu_physical_cores=2,
    )
    assert tier == HardwareTier.LOW


def test_hardware_profile_recommendations_populated():
    """Verify recommendations, quantization, and context windows are populated."""
    profiler = HardwareProfiler()
    profile = profiler.detect_hardware()

    assert isinstance(profile, HardwareProfile)
    assert profile.tier in {HardwareTier.LOW, HardwareTier.MEDIUM, HardwareTier.HIGH}
    assert len(profile.recommended_models) > 0
    assert profile.max_context_window in {8192, 16384, 32768}
    assert profile.cv_recommended_fps in {5, 7, 10}

    # Serialization test
    d = profile.to_dict()
    assert d["tier"] in {"LOW", "MEDIUM", "HIGH"}
    assert "cpu_cores_physical" in d


# ---------------------------------------------------------------------------
# Resource Governor Tests
# ---------------------------------------------------------------------------

def test_governor_normal_state():
    """Verify governor reports not overloaded under normal load."""
    gov = ResourceGovernor(cpu_threshold_percent=85.0, ram_threshold_percent=90.0)
    with patch.object(gov, "_sample_resources", return_value=(30.0, 45.0)):
        assert gov.is_overloaded() is False
        assert gov.is_cpu_overloaded() is False
        assert gov.is_ram_overloaded() is False
        assert gov.get_throttle_factor() == 0.0
        assert gov.get_recommended_cv_fps(base_fps=10) == 10

        metrics = gov.get_metrics()
        assert metrics["is_overloaded"] is False
        assert metrics["cpu_percent"] == 30.0
        assert metrics["ram_percent"] == 45.0


def test_governor_cpu_overload():
    """Verify governor detects CPU > 85% overload and throttles CV FPS."""
    gov = ResourceGovernor(cpu_threshold_percent=85.0, ram_threshold_percent=90.0)
    with patch.object(gov, "_sample_resources", return_value=(88.0, 50.0)):
        assert gov.is_overloaded() is True
        assert gov.is_cpu_overloaded() is True
        assert gov.is_ram_overloaded() is False
        assert gov.get_throttle_factor() > 0.0
        assert gov.get_recommended_cv_fps(base_fps=10) <= 5


def test_governor_ram_overload():
    """Verify governor detects RAM > 90% overload."""
    gov = ResourceGovernor(cpu_threshold_percent=85.0, ram_threshold_percent=90.0)
    with patch.object(gov, "_sample_resources", return_value=(40.0, 92.0)):
        assert gov.is_overloaded() is True
        assert gov.is_ram_overloaded() is True
        assert gov.get_throttle_factor() > 0.0


def test_governor_critical_overload_minimum_fps():
    """Verify critical overload (>=95%) drops CV FPS to minimum (1 FPS)."""
    gov = ResourceGovernor(cpu_threshold_percent=85.0, ram_threshold_percent=90.0)
    with patch.object(gov, "_sample_resources", return_value=(96.0, 70.0)):
        assert gov.get_recommended_cv_fps(base_fps=10) == 1


@pytest.mark.asyncio
async def test_governor_throttle_sleep():
    """Verify throttle_if_needed sleeps when system is overloaded."""
    gov = ResourceGovernor(
        cpu_threshold_percent=85.0,
        ram_threshold_percent=90.0,
        min_throttle_sleep=0.01,
        max_throttle_sleep=0.05,
    )
    with patch.object(gov, "_sample_resources", return_value=(90.0, 50.0)):
        slept = await gov.throttle_if_needed(task_name="cv_inference")
        assert slept >= 0.01


@pytest.mark.asyncio
async def test_governor_yield_execution():
    """Verify yield_execution executes cleanly."""
    gov = get_resource_governor()
    await gov.yield_execution()
