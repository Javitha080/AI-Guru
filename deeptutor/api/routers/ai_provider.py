"""
AI Guru AI Provider & Tutoring Mode API Router.
===============================================

Handles AI provider switching (Auto-Mode, Cloud API, Local Ollama, Offline),
hardware capability profiling diagnostics, connection tests, Ollama model catalog,
and dynamic resource governor telemetry.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Literal, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

import aiohttp
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from deeptutor.services.config.key_vault import get_key_vault, mask_api_key
from deeptutor.services.governor import get_resource_governor
from deeptutor.services.llm.hardware_profiler import get_hardware_profile
from deeptutor.services.llm.tutor_provider import (
    TutoringMode,
    get_tutor_provider_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class ModeUpdatePayload(BaseModel):
    mode: Literal["auto", "cloud", "ollama", "offline"]


class KeySavePayload(BaseModel):
    provider: str = Field(default="openai", description="Provider identifier, e.g. 'openai', 'deepseek', 'anthropic', 'dashscope'")
    api_key: str = Field(..., description="API key to store in local vault")


class ProviderTestPayload(BaseModel):
    provider_type: Literal["cloud", "ollama"]
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    binding: Optional[str] = "openai"


class OllamaPullPayload(BaseModel):
    model: str = Field(..., description="Ollama model tag to download, e.g. 'qwen2.5:1.5b'")
    insecure: bool = False


@router.get("/status", summary="Get AI Provider Status & Diagnostics")
async def get_provider_status() -> dict[str, Any]:
    """
    Return active AI provider diagnostics, hardware tier, circuit breaker states,
    and masked API keys.
    """
    manager = get_tutor_provider_manager()
    return await manager.get_system_status()


@router.post("/mode", summary="Set AI Tutoring Mode")
async def set_tutoring_mode(payload: ModeUpdatePayload) -> dict[str, Any]:
    """
    Switch tutoring execution mode:
    - 'auto': Cloud API -> Local Ollama -> Offline Rule Engine (Recommended)
    - 'cloud': Cloud API (with fallback if enabled)
    - 'ollama': Local Ollama only
    - 'offline': Deterministic offline educational engine
    """
    manager = get_tutor_provider_manager()
    manager.set_mode(payload.mode)
    return {
        "status": "success",
        "mode": manager.mode.value,
        "message": f"Tutoring mode updated to '{payload.mode}'",
    }


@router.get("/hardware-profile", summary="Get Hardware Capability Profile")
async def get_hardware_diagnostics() -> dict[str, Any]:
    """
    Return comprehensive system hardware detection:
    - GPU device, accelerator type (CUDA/MPS/ROCm/Arc), VRAM capacity
    - System RAM & CPU core metrics
    - Assigned HardwareTier (LOW, MEDIUM, HIGH)
    - Recommended local models and quantization configs
    """
    profile = get_hardware_profile(refresh=True)
    return profile.to_dict()


@router.post("/test", summary="Test AI Provider Connection")
async def test_provider_connection(payload: ProviderTestPayload) -> dict[str, Any]:
    """
    Verify connectivity to a Cloud API or Local Ollama server.
    API keys are validated securely without leaking credentials in response.
    """
    if payload.provider_type == "ollama":
        host = (payload.base_url or "http://127.0.0.1:11434").rstrip("/")
        url = f"{host}/api/tags"
        timeout = aiohttp.ClientTimeout(total=4)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        models = [m.get("name") for m in data.get("models", [])]
                        return {
                            "success": True,
                            "provider": "ollama",
                            "status": "online",
                            "host": host,
                            "models": models,
                            "model_count": len(models),
                            "message": f"Successfully connected to Ollama ({len(models)} models available)",
                        }
                    return {
                        "success": False,
                        "provider": "ollama",
                        "status": "error",
                        "message": f"Ollama returned HTTP {resp.status}",
                    }
        except Exception as e:
            return {
                "success": False,
                "provider": "ollama",
                "status": "offline",
                "message": f"Could not connect to Ollama at {host}: {e}",
            }

    # Cloud API Test
    try:
        from deeptutor.services.llm import factory

        api_key = payload.api_key
        if not api_key:
            from deeptutor.services.llm.config import get_llm_config
            api_key = get_llm_config().api_key

        if not api_key or api_key == "sk-no-key-required":
            return {
                "success": False,
                "provider": "cloud",
                "message": "No Cloud API key provided or configured",
            }

        model = payload.model or "gpt-4o-mini"
        resp = await factory.complete(
            prompt="Respond with 'OK'",
            system_prompt="You are a health probe. Reply with OK.",
            model=model,
            api_key=api_key,
            base_url=payload.base_url,
            binding=payload.binding or "openai",
            max_tokens=10,
        )
        return {
            "success": True,
            "provider": "cloud",
            "model": model,
            "message": "Cloud API connection verified successfully",
            "sample_response": resp[:30],
        }
    except Exception as e:
        return {
            "success": False,
            "provider": "cloud",
            "message": f"Cloud API test failed: {e}",
        }


@router.get("/ollama/models", summary="List Installed & Recommended Ollama Models")
async def get_ollama_models(host: str = "http://127.0.0.1:11434") -> dict[str, Any]:
    """
    List models currently installed in local Ollama, alongside tier-recommended models.
    """
    profile = get_hardware_profile()
    host_clean = host.rstrip("/")
    installed_models: list[str] = []
    ollama_online = False

    timeout = aiohttp.ClientTimeout(total=3)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{host_clean}/api/tags") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    installed_models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                    ollama_online = True
    except Exception:
        ollama_online = False

    return {
        "ollama_online": ollama_online,
        "host": host_clean,
        "installed_models": installed_models,
        "hardware_tier": profile.tier.value,
        "recommended_models": profile.recommended_models,
        "recommended_quantization": profile.recommended_quantization,
    }


@router.post("/ollama/pull", summary="Pull / Download Ollama Model")
async def pull_ollama_model(payload: OllamaPullPayload, host: str = "http://127.0.0.1:11434") -> dict[str, Any]:
    """
    Trigger download of a model in local Ollama daemon.
    """
    host_clean = host.rstrip("/")
    url = f"{host_clean}/api/pull"
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json={"name": payload.model, "stream": False, "insecure": payload.insecure}) as resp:
                if resp.status == 200:
                    return {
                        "status": "success",
                        "model": payload.model,
                        "message": f"Successfully initiated download for '{payload.model}'",
                    }
                err = await resp.text()
                raise HTTPException(
                    status_code=resp.status,
                    detail=f"Ollama pull failed: {err}",
                )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Cannot reach Ollama at {host}: {e}",
        )


@router.get("/governor", summary="Resource Governor Status")
async def get_governor_status() -> dict[str, Any]:
    """
    Return real-time CPU and RAM utilization metrics, overload flags, and
    recommended CV frame rates.
    """
    gov = get_resource_governor()
    metrics = gov.get_metrics()
    metrics["recommended_cv_fps"] = gov.get_recommended_cv_fps(base_fps=10)
    return metrics


@router.get("/keys", summary="List Masked API Keys in Local Vault")
async def get_vault_keys() -> dict[str, Any]:
    """
    Return masked representations of all API keys stored in local vault (e.g. sk-proj...1234).
    Plaintext secrets are NEVER exposed via this endpoint.
    """
    vault = get_key_vault()
    masked_keys = vault.get_masked_keys()
    return {
        "status": "success",
        "keys": masked_keys,
        "count": len(masked_keys),
    }


@router.post("/keys", summary="Save API Key to Local Vault")
async def save_vault_key(payload: KeySavePayload) -> dict[str, Any]:
    """
    Store an API key securely into data/user/settings/keys.json on local filesystem.
    """
    if not payload.api_key or not payload.api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API key cannot be empty",
        )

    vault = get_key_vault()
    vault.set_key(payload.provider, payload.api_key)
    masked = mask_api_key(payload.api_key)

    return {
        "status": "success",
        "provider": payload.provider.strip().lower(),
        "masked_key": masked,
        "message": f"API key for '{payload.provider}' successfully stored in local secure vault",
    }


@router.delete("/keys/{provider}", summary="Delete API Key from Local Vault")
async def delete_vault_key(provider: str) -> dict[str, Any]:
    """
    Remove an API key from local vault.
    """
    vault = get_key_vault()
    deleted = vault.delete_key(provider)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Key for provider '{provider}' not found in vault",
        )
    return {
        "status": "success",
        "provider": provider,
        "message": f"Key for provider '{provider}' deleted from vault",
    }

