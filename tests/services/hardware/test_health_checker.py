"""
Tests for AI Guru Comprehensive Health Check Service and Router.
"""

from __future__ import annotations

import pytest

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
)


def test_individual_subsystem_health_probes() -> None:
    # 1. Database
    db_h = check_database_health()
    assert "status" in db_h
    assert "latency_ms" in db_h

    # 2. Backend
    be_h = check_backend_health()
    assert be_h["status"] == "online"
    assert be_h["product_name"] == "AI Guru"
    assert "uptime_seconds" in be_h

    # 3. Camera
    cam_h = check_camera_health()
    assert "status" in cam_h
    assert "available" in cam_h

    # 4. Mic
    mic_h = check_mic_health()
    assert "status" in mic_h

    # 5. AI Provider
    ai_h = check_ai_provider_health()
    assert "status" in ai_h

    # 6. Ollama
    ollama_h = check_ollama_health()
    assert "status" in ollama_h
    assert "available" in ollama_h

    # 7. Monitoring Engine
    cv_h = check_monitoring_engine_health()
    assert cv_h["status"] == "ready"
    assert cv_h["local_only"] is True
    assert cv_h["sampling_fps"] in range(3, 11)

    # 8. Remote Access
    remote_h = check_remote_access_health()
    assert "status" in remote_h
    assert remote_h["relay_stores_data"] is False

    # 9. CPU
    cpu_h = check_cpu_health()
    assert "usage_percent" in cpu_h
    assert cpu_h["logical_cores"] >= 1

    # 10. RAM
    ram_h = check_ram_health()
    assert "usage_percent" in ram_h

    # 11. GPU
    gpu_h = check_gpu_health()
    assert "hardware_tier" in gpu_h
    assert gpu_h["hardware_tier"] in {"LOW", "MEDIUM", "HIGH"}


def test_get_full_system_health() -> None:
    health = get_full_system_health()
    assert health["status"] in {"healthy", "degraded", "unhealthy"}
    assert "timestamp" in health
    assert "subsystems" in health

    subsystems = health["subsystems"]
    expected_subsystems = [
        "database",
        "backend",
        "camera",
        "mic",
        "ai_provider",
        "ollama",
        "monitoring_engine",
        "remote_access",
        "cpu",
        "ram",
        "gpu",
    ]
    for sub in expected_subsystems:
        assert sub in subsystems, f"Subsystem {sub} missing from full health report"
