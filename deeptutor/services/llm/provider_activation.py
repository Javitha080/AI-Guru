"""
One-shot AI provider activation used by the first-run wizard ("Welcome to AI
Guru Setup") and the Settings re-entry point.

Historically the wizard only flipped an in-memory mode flag and tested the
connection without saving anything: the typed API key evaporated, the chosen
mode reset on restart, and the actual tutor pipeline (which resolves its
config from the model catalog via ``resolve_llm_runtime_config``) never saw
any of it. This module wires a setup choice into *every* layer the runtime
reads, in test-first order so a bad configuration never becomes active:

1. **Verify** the candidate (cloud ``factory.complete`` probe or Ollama
   ``/api/tags``) using explicitly-passed parameters — no state mutated yet.
2. Only on success, **commit**:
   - API key -> local key vault (``data/user/settings/keys.json``)
   - LLM profile upsert + activation in the model catalog (what
     ``resolve_llm_runtime_config`` reads for every tutor turn)
   - ``tutoring_mode`` (+ optional ``ollama_base_url``) -> system settings so
     the ``TutorProviderManager`` singleton survives restarts
   - cached LLM clients/config invalidated so the change is live immediately

All storage collaborators are injectable so tests can run against temp dirs.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4

from deeptutor.services.config.key_vault import KeyVaultService, mask_api_key

logger = logging.getLogger(__name__)

VALID_MODES = frozenset({"auto", "cloud", "ollama", "offline"})

# Known cloud presets. "custom" (and unknown names) rely fully on the
# caller-supplied base_url/model/binding.
PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "binding": "openai",
        "model": "gpt-4o-mini",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "binding": "openai",
        "model": "deepseek-chat",
    },
    "anthropic": {
        "label": "Anthropic",
        "base_url": "",
        "binding": "anthropic",
        "model": "claude-sonnet-4-5",
    },
    "dashscope": {
        "label": "DashScope (Qwen)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "binding": "openai",
        "model": "qwen-plus",
    },
}

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"

# Signature of the cloud probe used by the existing POST /test route.
CloudTester = Callable[[str, Optional[str], str, Optional[str]], Awaitable[tuple[bool, str]]]
OllamaProber = Callable[[str], Awaitable[tuple[bool, str, list[str]]]]


@dataclass
class ActivationRequest:
    """A single wizard submission."""

    mode: str
    provider: str = "openai"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    binding: Optional[str] = None
    ollama_base_url: Optional[str] = None


@dataclass
class ActivationResult:
    success: bool
    message: str
    mode: str
    provider: str = ""
    model: Optional[str] = None
    masked_key: str = ""


def resolve_cloud_params(request: ActivationRequest) -> dict[str, str]:
    """Fill missing cloud fields from the provider preset."""
    defaults = PROVIDER_DEFAULTS.get((request.provider or "").strip().lower(), {})
    return {
        "provider": (request.provider or "openai").strip().lower(),
        "binding": (request.binding or defaults.get("binding") or "openai").strip().lower(),
        "model": (request.model or defaults.get("model") or "gpt-4o-mini").strip(),
        "base_url": (request.base_url or defaults.get("base_url") or "").strip(),
    }


def _existing_api_key(vault: Optional[KeyVaultService], provider: str) -> Optional[str]:
    """Best-effort lookup of previously-configured credentials."""
    if vault is not None:
        try:
            key = vault.get_key(provider) or vault.get_key("default")
            if key:
                return key
        except Exception:
            pass
    try:
        from deeptutor.services.llm.config import get_llm_config

        cfg = get_llm_config()
        if cfg.api_key and cfg.api_key != "sk-no-key-required":
            return cfg.api_key
    except Exception:
        pass
    return None


async def _probe_cloud(
    request: ActivationRequest,
    tester: Optional[CloudTester],
    vault: Optional[KeyVaultService] = None,
) -> tuple[bool, str, str]:
    """
    Test the candidate cloud config without touching any persisted state.
    Returns ``(ok, message, resolved_model)``.
    """
    params = resolve_cloud_params(request)

    async def default_tester(
        model: str, api_key: Optional[str], binding: str, base_url: Optional[str]
    ) -> tuple[bool, str]:
        from deeptutor.services.llm import factory

        await factory.complete(
            prompt="Respond with 'OK'",
            system_prompt="You are a health probe. Reply with OK.",
            model=model,
            api_key=api_key,
            base_url=base_url or None,
            binding=binding,
            max_tokens=10,
        )
        return True, ""

    probe = tester or default_tester
    api_key = (request.api_key or "").strip() or _existing_api_key(vault, params["provider"])
    if not api_key:
        return (
            False,
            "No API key provided and none is configured yet. "
            f"Enter your {params['provider']} key to continue.",
            params["model"],
        )
    try:
        ok, error = await probe(params["model"], api_key, params["binding"], params["base_url"] or None)
    except Exception as exc:  # noqa: BLE001 — surface any provider error verbatim
        logger.info("Cloud activation probe failed for %s: %s", params["provider"], exc)
        return False, f"Cloud API test failed: {exc}", params["model"]
    if not ok:
        message = error or "Connection test failed. Check the key, base URL, and model."
        return False, message, params["model"]
    return True, f"{params['provider'].capitalize()} connection verified ({params['model']}).", params["model"]


async def probe_ollama(base_url: str) -> tuple[bool, str, list[str]]:
    """Probe an Ollama daemon. Returns ``(ok, message, installed_models)``."""
    host = (base_url or DEFAULT_OLLAMA_BASE_URL).rstrip("/")
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=4)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{host}/api/tags") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [m.get("name") for m in (data or {}).get("models", []) if m.get("name")]
                    message = (
                        f"Ollama reachable at {host} ({len(models)} models available)"
                        if models
                        else f"Ollama reachable at {host}, but no models are installed yet."
                    )
                    return True, message, models
                return False, f"Ollama returned HTTP {resp.status} at {host}.", []
    except Exception as exc:  # noqa: BLE001
        return False, f"Could not reach Ollama at {host}: {exc}", []


def _upsert_catalog_llm_profile(
    catalog_service: Any,
    params: dict[str, str],
    api_key: str,
) -> None:
    """Add the verified provider as an ACTIVE llm profile in the model catalog."""

    def mutator(catalog: dict[str, Any]) -> None:
        services = catalog.setdefault("services", {})
        llm = services.get("llm")
        if not isinstance(llm, dict):
            llm = {}
            services["llm"] = llm
        profiles = llm.setdefault("profiles", [])
        if not isinstance(profiles, list):
            profiles = []
            llm["profiles"] = profiles

        profile_id = f"llm-profile-{uuid4().hex[:8]}"
        model_id = f"llm-model-{uuid4().hex[:8]}"
        label = PROVIDER_DEFAULTS.get(params["provider"], {}).get("label") or params["provider"]
        profiles.append(
            {
                "id": profile_id,
                "name": f"{label} (AI Guru Setup)",
                "binding": params["binding"],
                "base_url": params["base_url"],
                "api_key": api_key,
                "api_version": "",
                "extra_headers": {},
                "models": [
                    {"id": model_id, "name": params["model"], "model": params["model"]}
                ],
            }
        )
        llm["active_profile_id"] = profile_id
        llm["active_model_id"] = model_id

    catalog_service.update(mutator)


def _persist_system_settings(
    settings_service: Any,
    mode: str,
    ollama_base_url: Optional[str],
) -> None:
    """Read-modify-write system.json. Uses include_process_overrides=False so
    env-var deployment overrides are never baked into the file."""
    current = settings_service.load_system(include_process_overrides=False)
    current["tutoring_mode"] = mode
    if mode == "ollama":
        current["ollama_base_url"] = _ollama_base_url(ollama_base_url)
    settings_service.save_system(current)


def _ollama_base_url(value: Optional[str]) -> str:
    return (value or "").strip() or DEFAULT_OLLAMA_BASE_URL


def _reset_runtime_caches() -> None:
    try:
        from deeptutor.services.llm.client import reset_llm_client

        reset_llm_client()
    except Exception:
        pass
    try:
        from deeptutor.services.llm.config import clear_llm_config_cache

        clear_llm_config_cache()
    except Exception:
        pass


async def activate_tutor_provider(
    request: ActivationRequest,
    *,
    vault: Optional[KeyVaultService] = None,
    catalog_service: Any = None,
    settings_service: Any = None,
    tester: Optional[CloudTester] = None,
    ollama_prober: Optional[OllamaProber] = None,
) -> ActivationResult:
    """
    Verify-then-commit a wizard submission. Nothing is persisted unless the
    verification passes, so a typo'd key can never clobber a working setup.
    """
    mode = (request.mode or "").strip().lower()
    if mode not in VALID_MODES:
        return ActivationResult(
            success=False,
            message=f"Unknown tutoring mode '{request.mode}'.",
            mode=mode or "",
        )

    # ---- VERIFY -----------------------------------------------------------
    if mode == "offline":
        message = "Offline Rule Engine activated — no network or credentials needed."
    elif mode == "ollama":
        ok, message, _models = await (ollama_prober or probe_ollama)(
            _ollama_base_url(request.ollama_base_url)
        )
        if not ok:
            return ActivationResult(
                success=False, message=message, mode=mode, provider="ollama"
            )
    else:  # cloud / auto
        ok, message, model = await _probe_cloud(request, tester, vault)
        if not ok:
            return ActivationResult(
                success=False,
                message=message,
                mode=mode,
                provider=request.provider,
                model=model,
            )

    # ---- COMMIT -----------------------------------------------------------
    masked_key = ""
    if mode in {"cloud", "auto"}:
        params = resolve_cloud_params(request)
        api_key = (request.api_key or "").strip() or _existing_api_key(vault, params["provider"]) or ""
        if api_key and vault is not None:
            vault.set_key(params["provider"], api_key)
            masked_key = mask_api_key(api_key)
        if catalog_service is not None:
            _upsert_catalog_llm_profile(catalog_service, params, api_key)
        _reset_runtime_caches()

    if settings_service is not None:
        _persist_system_settings(settings_service, mode, request.ollama_base_url)

    return ActivationResult(
        success=True,
        message=message,
        mode=mode,
        provider=(request.provider if mode in {"cloud", "auto"} else mode),
        model=(resolve_cloud_params(request)["model"] if mode in {"cloud", "auto"} else None),
        masked_key=masked_key,
    )


__all__ = [
    "ActivationRequest",
    "ActivationResult",
    "DEFAULT_OLLAMA_BASE_URL",
    "PROVIDER_DEFAULTS",
    "VALID_MODES",
    "activate_tutor_provider",
    "resolve_cloud_params",
]
