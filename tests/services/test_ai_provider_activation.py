"""
Tests for the first-run wizard activation flow
(deeptutor/services/llm/provider_activation.py + related persistence).

Contract under test:
- Cloud/Ollama candidates are verified BEFORE any state is written.
- On success the API key reaches the local vault, an ACTIVE llm profile lands
  in the model catalog (what resolve_llm_runtime_config reads), and the chosen
  tutoring mode persists to system settings.
- On failure nothing is mutated — a typo'd key can never clobber a working
  setup, and the tutoring mode survives restarts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from deeptutor.services.config.key_vault import KeyVaultService
from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.config.runtime_settings import RuntimeSettingsService
from deeptutor.services.llm.provider_activation import (
    ActivationRequest,
    activate_tutor_provider,
)

_PROVIDER_ENV_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
)


class _NoGlobalConfig:
    """Stand-in for an unconfigured global LLM config."""

    api_key = "sk-no-key-required"


@pytest.fixture(autouse=True)
def isolated_provider_env(monkeypatch: pytest.MonkeyPatch):
    """
    Vault lookups fall back to env vars and the global LLM config. Without
    isolation, a developer machine holding real credentials leaks them into
    these assertions (and set_key can leak test keys back out via os.environ).
    """
    import deeptutor.services.llm.config as llm_config

    saved = {name: os.environ.get(name) for name in _PROVIDER_ENV_VARS}
    for name in _PROVIDER_ENV_VARS:
        os.environ.pop(name, None)
    monkeypatch.setattr(llm_config, "get_llm_config", lambda: _NoGlobalConfig())
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


class Harness:
    """All three stores rooted at one temp dir."""

    def __init__(self, tmp_path: Path):
        self.vault = KeyVaultService(settings_dir=tmp_path)
        self.catalog = ModelCatalogService(path=tmp_path / "model_catalog.json")
        self.settings = RuntimeSettingsService(tmp_path)

    def load_catalog(self) -> dict[str, Any]:
        path = self.catalog.path
        if not path.exists():
            return {"services": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def load_system(self) -> dict[str, Any]:
        path = self.settings.path_for("system")
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def active_llm_profile(self) -> dict[str, Any] | None:
        llm = self.load_catalog().get("services", {}).get("llm", {})
        active_id = llm.get("active_profile_id")
        return next(
            (p for p in llm.get("profiles", []) if p.get("id") == active_id),
            None,
        )


def make_ok_tester():
    async def tester(model, api_key, binding, base_url):
        assert api_key, "tester must receive the candidate api key"
        return True, ""

    return tester


def make_fail_tester(message="Cloud API test failed: 401"):
    async def tester(model, api_key, binding, base_url):
        return False, message

    return tester


@pytest.mark.asyncio
async def test_cloud_activation_success_commits_every_layer(tmp_path: Path):
    store = Harness(tmp_path)
    result = await activate_tutor_provider(
        ActivationRequest(
            mode="cloud",
            provider="deepseek",
            api_key="sk-test-deepseek-key",
            model="deepseek-chat",
            base_url="https://api.deepseek.com/v1",
            binding="openai",
        ),
        vault=store.vault,
        catalog_service=store.catalog,
        settings_service=store.settings,
        tester=make_ok_tester(),
    )

    assert result.success is True
    assert result.masked_key, "masked key must be returned"

    # 1. Vault holds the raw key under the provider name.
    assert store.vault.get_key("deepseek") == "sk-test-deepseek-key"

    # 2. Catalog has an ACTIVE profile carrying the verified config.
    profile = store.active_llm_profile()
    assert profile is not None, "activation must create an active llm profile"
    assert profile["binding"] == "openai"
    assert profile["base_url"] == "https://api.deepseek.com/v1"
    assert profile["api_key"] == "sk-test-deepseek-key"
    llm = store.load_catalog()["services"]["llm"]
    active_model = next(m for m in profile["models"] if m["id"] == llm.get("active_model_id"))
    assert active_model["model"] == "deepseek-chat"

    # 3. Tutoring mode persisted for restart survival.
    assert store.load_system()["tutoring_mode"] == "cloud"


@pytest.mark.asyncio
async def test_failed_verification_mutates_nothing(tmp_path: Path):
    store = Harness(tmp_path)
    store.settings.save_system({"tutoring_mode": "offline"})

    result = await activate_tutor_provider(
        ActivationRequest(mode="cloud", provider="openai", api_key="sk-wrong"),
        vault=store.vault,
        catalog_service=store.catalog,
        settings_service=store.settings,
        tester=make_fail_tester(),
    )

    assert result.success is False
    assert "401" in result.message
    assert store.active_llm_profile() is None, "failed probe must not write the catalog"
    assert store.vault.get_key("openai") is None, "failed probe must not write the vault"
    assert store.load_system().get("tutoring_mode") == "offline", (
        "failed probe must not flip the persisted mode"
    )


@pytest.mark.asyncio
async def test_offline_activation_persists_without_credentials(tmp_path: Path):
    store = Harness(tmp_path)
    result = await activate_tutor_provider(
        ActivationRequest(mode="offline"),
        vault=store.vault,
        catalog_service=store.catalog,
        settings_service=store.settings,
    )

    assert result.success is True
    assert store.load_system()["tutoring_mode"] == "offline"
    assert store.active_llm_profile() is None
    assert store.vault.get_key("default") is None


@pytest.mark.asyncio
async def test_ollama_activation_gates_on_daemon_probe(tmp_path: Path):
    store = Harness(tmp_path)

    async def unreachable(host: str):
        return False, f"Could not reach Ollama at {host}", []

    result = await activate_tutor_provider(
        ActivationRequest(mode="ollama", ollama_base_url="http://127.0.0.1:11500"),
        vault=store.vault,
        catalog_service=store.catalog,
        settings_service=store.settings,
        ollama_prober=unreachable,
    )
    assert result.success is False
    assert store.load_system().get("tutoring_mode") != "ollama"

    async def reachable(host: str):
        assert host == "http://127.0.0.1:11500"
        return True, "Ollama online", ["qwen2.5:1.5b"]

    result = await activate_tutor_provider(
        ActivationRequest(mode="ollama", ollama_base_url="http://127.0.0.1:11500"),
        vault=store.vault,
        catalog_service=store.catalog,
        settings_service=store.settings,
        ollama_prober=reachable,
    )
    assert result.success is True
    system = store.load_system()
    assert system["tutoring_mode"] == "ollama"
    assert system["ollama_base_url"] == "http://127.0.0.1:11500"


@pytest.mark.asyncio
async def test_unknown_mode_is_rejected(tmp_path: Path):
    store = Harness(tmp_path)
    result = await activate_tutor_provider(
        ActivationRequest(mode="telepathy"),  # type: ignore[arg-type]
        settings_service=store.settings,
    )
    assert result.success is False
    assert "Unknown tutoring mode" in result.message


def test_manager_singleton_honours_persisted_mode(monkeypatch, tmp_path: Path):
    import deeptutor.services.llm.tutor_provider as tp

    def fake_load_system(*_args, **_kwargs):
        return {"tutoring_mode": "cloud", "ollama_base_url": "http://127.0.0.1:11500"}

    from deeptutor.services.config import runtime_settings

    monkeypatch.setattr(runtime_settings, "load_system_settings", fake_load_system)

    original = tp._tutor_manager_instance
    tp._tutor_manager_instance = None
    try:
        manager = tp.get_tutor_provider_manager()
        assert manager.mode.value == "cloud"
        assert getattr(manager.ollama_adapter, "base_url", None) == "http://127.0.0.1:11500"
    finally:
        tp._tutor_manager_instance = original


def test_normalize_system_round_trips_new_keys_and_keeps_lan_flag(tmp_path: Path):
    service = RuntimeSettingsService(tmp_path)
    payload = service.save_system(
        {
            "lan_access_enabled": True,
            "tutoring_mode": "ollama",
            "ollama_base_url": "http://192.168.1.10:11434/",
        }
    )

    assert payload["lan_access_enabled"] is True
    assert payload["tutoring_mode"] == "ollama"
    assert payload["ollama_base_url"] == "http://192.168.1.10:11434"

    reloaded = service.load_system()
    assert reloaded["tutoring_mode"] == "ollama"
    assert reloaded["ollama_base_url"] == "http://192.168.1.10:11434"

    # save_system is a FULL replace against defaults (not a merge), so callers
    # must read-modify-write — exactly what provider activation does. Assert
    # an RMW save keeps every key, including ones absent from the update:
    # historically this normalizer silently dropped lan_access_enabled.
    current = service.load_system(include_process_overrides=False)
    current["tutoring_mode"] = "auto"
    after_rmw_save = service.save_system(current)
    assert after_rmw_save["ollama_base_url"] == "http://192.168.1.10:11434"
    assert after_rmw_save["lan_access_enabled"] is True

    # Garbage mode falls back to auto instead of poisoning the file.
    bad = service.save_system({"tutoring_mode": "holographic"})
    assert bad["tutoring_mode"] == "auto"


def test_resolve_cloud_params_fills_from_provider_defaults():
    from deeptutor.services.llm.provider_activation import resolve_cloud_params

    filled = resolve_cloud_params(ActivationRequest(mode="cloud", provider="dashscope"))
    assert filled["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert filled["binding"] == "openai"
    assert filled["model"] == "qwen-plus"

    custom = resolve_cloud_params(
        ActivationRequest(
            mode="cloud",
            provider="custom",
            base_url="https://my.host/v1",
            model="my-model",
        )
    )
    assert custom == {
        "provider": "custom",
        "binding": "openai",
        "model": "my-model",
        "base_url": "https://my.host/v1",
    }
