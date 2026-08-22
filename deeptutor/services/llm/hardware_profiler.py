"""
AI Guru Hardware Profiler & Capability Detection Service.
=========================================================

Detects system GPU accelerators (NVIDIA CUDA, Apple Metal MPS, AMD ROCm,
Intel Arc, CPU-only fallback), calculates total/available VRAM and system RAM,
determines the system capability tier (LOW, MEDIUM, HIGH), and provides optimal
local AI model recommendations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import logging
import os
from pathlib import Path
import platform
import shutil
import sys
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


class HardwareTier(str, Enum):
    """System hardware capability tier for AI inference."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass
class HardwareProfile:
    """Detailed profile of system computing resources and model recommendations."""

    tier: HardwareTier = HardwareTier.LOW
    gpu_type: str = "CPU Fallback"
    gpu_name: Optional[str] = None
    gpu_count: int = 0
    vram_bytes: int = 0
    vram_gb: float = 0.0
    system_ram_bytes: int = 0
    system_ram_gb: float = 0.0
    cpu_cores_physical: int = 1
    cpu_cores_logical: int = 1
    cpu_name: str = "Generic CPU"
    recommended_models: list[str] = field(default_factory=list)
    recommended_quantization: str = "q4_k_m"
    max_context_window: int = 8192
    cv_recommended_fps: int = 5
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize profile to JSON-compatible dictionary."""
        data = asdict(self)
        data["tier"] = self.tier.value if isinstance(self.tier, HardwareTier) else str(self.tier)
        return data


# Tier-based model recommendations
RECOMMENDED_MODELS_BY_TIER: dict[HardwareTier, list[str]] = {
    HardwareTier.HIGH: [
        "qwen2.5:14b",
        "deepseek-r1:14b",
        "qwen2.5:32b",
        "deepseek-r1:32b",
        "llama3.3:70b",
    ],
    HardwareTier.MEDIUM: [
        "qwen2.5:7b",
        "deepseek-r1:7b",
        "llama3.1:8b",
        "gemma2:9b",
        "mistral:7b",
    ],
    HardwareTier.LOW: [
        "qwen2.5:1.5b",
        "deepseek-r1:1.5b",
        "llama3.2:1b",
        "llama3.2:3b",
        "qwen2.5:3b",
        "phi3:mini",
    ],
}

TIER_QUANTIZATIONS: dict[HardwareTier, str] = {
    HardwareTier.HIGH: "q5_k_m",
    HardwareTier.MEDIUM: "q4_k_m",
    HardwareTier.LOW: "q4_k_m",
}

TIER_CONTEXT_WINDOWS: dict[HardwareTier, int] = {
    HardwareTier.HIGH: 32768,
    HardwareTier.MEDIUM: 16384,
    HardwareTier.LOW: 8192,
}

TIER_CV_FPS: dict[HardwareTier, int] = {
    HardwareTier.HIGH: 10,
    HardwareTier.MEDIUM: 7,
    HardwareTier.LOW: 5,
}


class HardwareProfiler:
    """Detects and profiles system hardware for local AI tutoring execution."""

    def __init__(self) -> None:
        self._cached_profile: Optional[HardwareProfile] = None

    def get_profile(self, refresh: bool = False) -> HardwareProfile:
        """Return the system hardware profile, caching results unless refresh=True."""
        if self._cached_profile is None or refresh:
            self._cached_profile = self.detect_hardware()
        return self._cached_profile

    def detect_hardware(self) -> HardwareProfile:
        """Detect CPU, RAM, and GPU hardware and determine capability tier."""
        # 1. Detect System RAM & CPU
        ram_bytes, ram_gb = self._detect_system_ram()
        phys_cores, log_cores, cpu_name = self._detect_cpu()

        # 2. Detect GPU Accelerators
        gpu_type, gpu_name, gpu_count, vram_bytes, vram_gb = self._detect_gpu()

        # 3. Classify into HardwareTier
        tier = self._classify_tier(
            gpu_type=gpu_type,
            vram_gb=vram_gb,
            ram_gb=ram_gb,
            cpu_physical_cores=phys_cores,
        )

        # 4. Generate recommendations
        recommended_models = RECOMMENDED_MODELS_BY_TIER.get(tier, RECOMMENDED_MODELS_BY_TIER[HardwareTier.LOW])
        quantization = TIER_QUANTIZATIONS.get(tier, "q4_k_m")
        context_window = TIER_CONTEXT_WINDOWS.get(tier, 8192)
        cv_fps = TIER_CV_FPS.get(tier, 5)

        if tier == HardwareTier.HIGH:
            desc = f"High Performance ({gpu_name or gpu_type}, {vram_gb:.1f}GB VRAM, {ram_gb:.1f}GB RAM) — Optimal for 14B-32B+ models"
        elif tier == HardwareTier.MEDIUM:
            desc = f"Balanced Performance ({gpu_name or gpu_type}, {vram_gb:.1f}GB VRAM, {ram_gb:.1f}GB RAM) — Optimal for 7B-8B models"
        else:
            desc = f"Standard Performance ({gpu_name or gpu_type}, {ram_gb:.1f}GB RAM) — Optimal for lightweight 1.5B-3B models"

        return HardwareProfile(
            tier=tier,
            gpu_type=gpu_type,
            gpu_name=gpu_name,
            gpu_count=gpu_count,
            vram_bytes=vram_bytes,
            vram_gb=round(vram_gb, 2),
            system_ram_bytes=ram_bytes,
            system_ram_gb=round(ram_gb, 2),
            cpu_cores_physical=phys_cores,
            cpu_cores_logical=log_cores,
            cpu_name=cpu_name,
            recommended_models=recommended_models,
            recommended_quantization=quantization,
            max_context_window=context_window,
            cv_recommended_fps=cv_fps,
            description=desc,
        )

    def _detect_system_ram(self) -> tuple[int, float]:
        """Return (system_ram_bytes, system_ram_gb)."""
        try:
            import psutil

            mem = psutil.virtual_memory()
            return mem.total, mem.total / (1024**3)
        except Exception:
            return 8 * (1024**3), 8.0  # Fallback to 8GB default

    def _detect_cpu(self) -> tuple[int, int, str]:
        """Return (physical_cores, logical_cores, cpu_name)."""
        cpu_name = platform.processor() or platform.machine() or "Generic CPU"
        try:
            import psutil

            phys = psutil.cpu_count(logical=False) or 1
            log = psutil.cpu_count(logical=True) or phys
            return phys, log, cpu_name
        except Exception:
            cores = os.cpu_count() or 1
            return max(1, cores // 2), cores, cpu_name

    def _detect_gpu(self) -> tuple[str, Optional[str], int, int, float]:
        """
        Detect GPU device and memory.
        Returns (gpu_type, gpu_name, gpu_count, vram_bytes, vram_gb).
        """
        # A. Try PyTorch CUDA / ROCm
        try:
            import torch

            if torch.cuda.is_available():
                count = torch.cuda.device_count()
                device_name = torch.cuda.get_device_name(0)
                vram_bytes = torch.cuda.get_device_properties(0).total_memory
                vram_gb = vram_bytes / (1024**3)

                is_rocm = hasattr(torch.version, "hip") and torch.version.hip is not None
                gpu_type = "AMD ROCm" if is_rocm else "NVIDIA CUDA"

                return gpu_type, device_name, count, vram_bytes, vram_gb

            # B. Try Apple Silicon Metal (MPS)
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                # On macOS, unified memory is shared between CPU and GPU
                ram_bytes, ram_gb = self._detect_system_ram()
                # Treat ~70% of unified memory as effective VRAM
                effective_vram_bytes = int(ram_bytes * 0.7)
                effective_vram_gb = effective_vram_bytes / (1024**3)
                return (
                    "Apple Metal (MPS)",
                    "Apple Silicon Unified GPU",
                    1,
                    effective_vram_bytes,
                    effective_vram_gb,
                )
        except Exception as e:
            logger.debug("Torch GPU check failed: %s", e)

        # C. Try nvidia-smi command-line query
        nvidia_smi = shutil.which("nvidia-smi")
        if nvidia_smi:
            try:
                import subprocess

                res = subprocess.run(
                    [
                        nvidia_smi,
                        "--query-gpu=name,memory.total",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                if res.returncode == 0 and res.stdout.strip():
                    lines = [l.strip() for l in res.stdout.strip().splitlines() if l.strip()]
                    if lines:
                        parts = [p.strip() for p in lines[0].split(",")]
                        if len(parts) >= 2:
                            name = parts[0]
                            mb = float(parts[1])
                            vram_bytes = int(mb * 1024 * 1024)
                            return "NVIDIA CUDA", name, len(lines), vram_bytes, mb / 1024.0
            except Exception as e:
                logger.debug("nvidia-smi probe failed: %s", e)

        # D. Try rocm-smi command-line query
        rocm_smi = shutil.which("rocm-smi")
        if rocm_smi:
            try:
                import subprocess

                res = subprocess.run(
                    [rocm_smi, "--showmeminfo", "vram"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                if res.returncode == 0:
                    return "AMD ROCm", "AMD Radeon GPU", 1, 8 * (1024**3), 8.0
            except Exception:
                pass

        # E. macOS system profiler fallback
        if sys.platform == "darwin" and platform.machine() == "arm64":
            ram_bytes, ram_gb = self._detect_system_ram()
            effective_vram_bytes = int(ram_bytes * 0.7)
            return (
                "Apple Metal (MPS)",
                "Apple Silicon Unified Memory",
                1,
                effective_vram_bytes,
                effective_vram_bytes / (1024**3),
            )

        # F. CPU Fallback
        return "CPU Fallback", None, 0, 0, 0.0

    def _classify_tier(
        self,
        gpu_type: str,
        vram_gb: float,
        ram_gb: float,
        cpu_physical_cores: int,
    ) -> HardwareTier:
        """Determine whether system falls into LOW, MEDIUM, or HIGH tier."""
        # Dedicated GPU with >= 8GB VRAM -> HIGH
        if vram_gb >= 7.5:
            return HardwareTier.HIGH

        # Apple Silicon with >= 16GB Unified RAM -> HIGH
        if "Apple" in gpu_type and ram_gb >= 15.0:
            return HardwareTier.HIGH

        # Dedicated GPU with 3.5GB - 7.5GB VRAM -> MEDIUM
        if vram_gb >= 3.5:
            return HardwareTier.MEDIUM

        # Apple Silicon with 8GB - 16GB Unified RAM -> MEDIUM
        if "Apple" in gpu_type and ram_gb >= 7.5:
            return HardwareTier.MEDIUM

        # CPU-only with >= 32GB RAM and >= 8 physical cores -> HIGH
        if ram_gb >= 30.0 and cpu_physical_cores >= 8:
            return HardwareTier.HIGH

        # CPU-only with >= 14GB RAM and >= 4 physical cores -> MEDIUM
        if ram_gb >= 13.5 and cpu_physical_cores >= 4:
            return HardwareTier.MEDIUM

        # Otherwise -> LOW
        return HardwareTier.LOW


_profiler_instance: Optional[HardwareProfiler] = None


def get_hardware_profiler() -> HardwareProfiler:
    """Return singleton instance of HardwareProfiler."""
    global _profiler_instance
    if _profiler_instance is None:
        _profiler_instance = HardwareProfiler()
    return _profiler_instance


def get_hardware_profile(refresh: bool = False) -> HardwareProfile:
    """Convenience function returning current HardwareProfile."""
    return get_hardware_profiler().get_profile(refresh=refresh)


def get_hardware_tier() -> HardwareTier:
    """Convenience function returning current HardwareTier."""
    return get_hardware_profiler().get_profile().tier
