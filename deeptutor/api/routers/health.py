"""
Comprehensive Health Check API Router for AI Guru.

Exposes real-time subsystem diagnostics for:
database, backend, camera, mic, ai_provider, ollama, monitoring_engine,
remote_access, cpu, ram, gpu.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from deeptutor.services.hardware.health_checker import (
    check_ai_provider_health,
    check_database_health,
    check_gpu_health,
    check_ollama_health,
    get_full_system_health,
)

router = APIRouter()


@router.get("", summary="Comprehensive System Health Check")
@router.get("/", summary="Comprehensive System Health Check (Trailing Slash)")
async def get_health() -> dict[str, Any]:
    """
    Return comprehensive real-time status for all AI Guru subsystems.

    Monitored subsystems:
    - database: SQLite WAL mode, connectivity, tables count, query latency
    - backend: runtime uptime, platform, PID, version
    - camera: local webcam availability / mock status
    - mic: audio input device presence
    - ai_provider: LLM configuration and active model binding
    - ollama: local Ollama server connectivity and model catalog
    - monitoring_engine: computer vision pipeline readiness and capabilities
    - remote_access: parent remote gateway status
    - cpu: CPU utilization and core count
    - ram: system memory usage metrics
    - gpu: GPU accelerator detection, device name, and VRAM
    """
    return await asyncio.to_thread(get_full_system_health)


@router.get("/ping", summary="Liveness Ping")
async def ping() -> dict[str, str]:
    """Fast liveness probe."""
    return {"status": "ok", "message": "pong"}


@router.get("/database", summary="Database Health Check")
async def get_db_health() -> dict[str, Any]:
    """Return database health details."""
    return await asyncio.to_thread(check_database_health)


@router.get("/ai", summary="AI Subsystems Health Check")
async def get_ai_health() -> dict[str, Any]:
    """Return AI Provider and Ollama health details."""
    ai_health = await asyncio.to_thread(check_ai_provider_health)
    ollama_health = await asyncio.to_thread(check_ollama_health)
    return {
        "ai_provider": ai_health,
        "ollama": ollama_health,
    }


@router.get("/gpu", summary="GPU Detection Health Check")
async def get_gpu_details() -> dict[str, Any]:
    """Return GPU acceleration details."""
    return await asyncio.to_thread(check_gpu_health)
