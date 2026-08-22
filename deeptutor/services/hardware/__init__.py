"""
AI Guru Hardware and Diagnostics Service Package.
"""

from __future__ import annotations

from deeptutor.services.hardware.health_checker import (
    check_ai_provider_health,
    check_backend_health,
    check_camera_health,
    check_cpu_health,
    check_database_health,
    check_gpu_health,
    check_mic_health,
    check_monitoring_engine_health,
    check_ollama_health,
    check_ram_health,
    check_remote_access_health,
    get_full_system_health,
    get_process_uptime,
)

__all__ = [
    "check_ai_provider_health",
    "check_backend_health",
    "check_camera_health",
    "check_cpu_health",
    "check_database_health",
    "check_gpu_health",
    "check_mic_health",
    "check_monitoring_engine_health",
    "check_ollama_health",
    "check_ram_health",
    "check_remote_access_health",
    "get_full_system_health",
    "get_process_uptime",
]
