"""
Unit tests for AI Guru TutorProvider Abstraction, Dual-Mode Adapters,
Circuit Breaker, and Auto-Fallback Chain.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deeptutor.services.config.key_vault import KeyVaultService, get_key_vault
from deeptutor.services.llm.tutor_provider import (
    CircuitBreaker,
    CircuitState,
    CloudProviderAdapter,
    CloudTutorProvider,
    CompletionResponse,
    OfflineRuleAdapter,
    OfflineRuleTutorProvider,
    OllamaProviderAdapter,
    OllamaTutorProvider,
    ProviderHealth,
    StreamChunk,
    TutoringMode,
    TutorProvider,
    TutorProviderManager,
    get_tutor_provider_manager,
    mask_api_key,
)

# ---------------------------------------------------------------------------
# Key Masking Vault Tests
# ---------------------------------------------------------------------------


def test_mask_api_key_security():
    """Verify API keys are safely masked and never exposed in full."""
    assert mask_api_key(None) == ""
    assert mask_api_key("") == ""
    assert mask_api_key("sk-no-key-required") == ""
    assert mask_api_key("12345") == "****"

    masked = mask_api_key("sk-proj-1234567890abcdef1234567890")
    assert masked.startswith("sk-pro")
    assert masked.endswith("7890")
    assert "..." in masked
    assert "1234567890abcdef" not in masked


def test_key_vault_service_crud(tmp_path):
    """Test KeyVaultService storing, retrieving, masking, and deleting API keys."""
    vault = KeyVaultService(settings_dir=tmp_path)
    assert vault.get_key("custom_test_provider") is None

    vault.set_key("custom_test_provider", "sk-proj-supersecretkey1234567890")
    assert vault.get_key("custom_test_provider") == "sk-proj-supersecretkey1234567890"

    masked = vault.get_masked_keys()
    assert "custom_test_provider" in masked
    assert masked["custom_test_provider"].startswith("sk-pro")
    assert masked["custom_test_provider"].endswith("7890")
    assert "supersecretkey" not in masked["custom_test_provider"]

    assert vault.delete_key("custom_test_provider") is True
    assert vault.get_key("custom_test_provider") is None
    assert vault.delete_key("custom_test_provider") is False


# ---------------------------------------------------------------------------
# OfflineRuleAdapter Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_offline_rule_adapter_math_completion():
    """Test OfflineRuleAdapter generates structured math responses."""
    adapter = OfflineRuleAdapter()
    messages = [{"role": "user", "content": "How do I solve quadratic equation x^2 + 5x + 6 = 0?"}]
    resp = await adapter.complete(messages)

    assert isinstance(resp, CompletionResponse)
    assert resp.finish_reason == "stop"
    assert resp.provider == "offline_rule_engine"
    assert "Math Tutor" in resp.content
    assert "Quadratic Formula" in resp.content


@pytest.mark.asyncio
async def test_offline_rule_adapter_coding_completion():
    """Test OfflineRuleAdapter generates structured coding responses."""
    adapter = OfflineRuleAdapter()
    messages = [{"role": "user", "content": "Write python function for binary search algorithm"}]
    resp = await adapter.complete(messages)

    assert "Coding Tutor" in resp.content
    assert "```python" in resp.content


@pytest.mark.asyncio
async def test_offline_rule_adapter_streaming():
    """Test OfflineRuleAdapter streams tokens asynchronously."""
    adapter = OfflineRuleAdapter()
    messages = [{"role": "user", "content": "Explain Newton's second law of physics"}]
    chunks = []
    async for chunk in adapter.stream(messages):
        assert isinstance(chunk, StreamChunk)
        if chunk.content:
            chunks.append(chunk.content)

    full_output = "".join(chunks)
    assert "Science & Physics Tutor" in full_output
    assert "F_{net}" in full_output or "Force" in full_output


@pytest.mark.asyncio
async def test_offline_rule_adapter_health():
    """Verify OfflineRuleAdapter reports 100% healthy status."""
    adapter = OfflineRuleAdapter()
    health = await adapter.check_health()
    assert health.status == "healthy"
    assert health.available is True


# ---------------------------------------------------------------------------
# CloudProviderAdapter Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cloud_adapter_missing_api_key_raises():
    """Verify CloudProviderAdapter raises error when API key is missing."""
    adapter = CloudProviderAdapter(api_key="")
    with patch.object(
        adapter,
        "_resolve_config",
        return_value={
            "model": "gpt-4o",
            "api_key": "",
            "base_url": "",
            "binding": "openai",
            "temperature": 0.7,
            "max_tokens": 4096,
        },
    ):
        with pytest.raises(ValueError, match="API key is missing"):
            await adapter.complete([{"role": "user", "content": "Hello"}])


@pytest.mark.asyncio
async def test_cloud_adapter_complete_success():
    """Test CloudProviderAdapter completion with mocked LLM factory."""
    adapter = CloudProviderAdapter(api_key="sk-test-key", model="gpt-4o")
    with patch("deeptutor.services.llm.factory.complete", new_callable=AsyncMock) as mock_complete:
        mock_complete.return_value = (
            "<think>Analyzing student question</think>Here is the solution."
        )
        resp = await adapter.complete([{"role": "user", "content": "Help me with homework"}])

        assert resp.content == "Here is the solution."
        assert resp.reasoning_content == "Analyzing student question"
        assert resp.provider == "cloud"


@pytest.mark.asyncio
async def test_cloud_adapter_stream_success():
    """Test CloudProviderAdapter streaming."""
    adapter = CloudProviderAdapter(api_key="sk-test-key", model="gpt-4o")

    async def mock_stream_gen(*args, **kwargs):
        yield "<think>"
        yield "Step 1"
        yield "</think>"
        yield "Hello"
        yield " student!"

    with patch("deeptutor.services.llm.factory.stream", side_effect=mock_stream_gen):
        chunks = []
        async for chunk in adapter.stream([{"role": "user", "content": "Hello"}]):
            if chunk.content:
                chunks.append(chunk.content)

        assert "".join(chunks) == "Hello student!"


# ---------------------------------------------------------------------------
# OllamaProviderAdapter Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_adapter_fetch_models():
    """Test OllamaProviderAdapter model catalog fetching."""
    adapter = OllamaProviderAdapter(base_url="http://127.0.0.1:11434")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={"models": [{"name": "qwen2.5:7b"}, {"name": "llama3.1:8b"}]}
    )

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_ctx):
        models = await adapter.fetch_installed_models()
        assert models == ["qwen2.5:7b", "llama3.1:8b"]


@pytest.mark.asyncio
async def test_ollama_adapter_complete_stream():
    """Test OllamaProviderAdapter streaming and thinking tags separation."""
    adapter = OllamaProviderAdapter(base_url="http://127.0.0.1:11434", model="qwen2.5:7b")

    mock_resp = MagicMock()
    mock_resp.status = 200

    async def mock_content_gen():
        yield b'{"message": {"content": "<think>Thinking deeply"}, "done": false}\n'
        yield b'{"message": {"content": "</think>Here is the concept."}, "done": false}\n'
        yield b'{"message": {"content": ""}, "done": true}\n'

    mock_resp.content = mock_content_gen()

    mock_session = MagicMock()
    mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session.post.return_value.__aexit__ = AsyncMock(return_value=None)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_ctx):
        resp = await adapter.complete([{"role": "user", "content": "Explain gravity"}])
        assert "Here is the concept." in resp.content
        assert "Thinking deeply" in resp.reasoning_content


# ---------------------------------------------------------------------------
# CircuitBreaker Tests
# ---------------------------------------------------------------------------


def test_circuit_breaker_lifecycle():
    """Test CircuitBreaker state transitions: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=0.3)
    assert breaker.state == CircuitState.CLOSED
    assert breaker.allow_request() is True

    # 1st failure
    breaker.record_failure(RuntimeError("Network error 1"))
    assert breaker.state == CircuitState.CLOSED
    assert breaker.allow_request() is True

    # 2nd failure -> Tripped to OPEN
    breaker.record_failure(RuntimeError("Network error 2"))
    assert breaker.state == CircuitState.OPEN
    assert breaker.allow_request() is False

    # Wait for cooldown to expire
    import time

    time.sleep(0.4)

    # Cooldown passed -> HALF_OPEN (allows probe request)
    assert breaker.allow_request() is True
    assert breaker.state == CircuitState.HALF_OPEN

    # Successful call resets to CLOSED
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0


# ---------------------------------------------------------------------------
# TutorProviderManager & Fallback Chain Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_chain_cloud_to_ollama():
    """Verify TutorProviderManager falls back from Cloud to Ollama when Cloud fails."""
    mock_cloud = MagicMock(spec=CloudProviderAdapter)
    mock_cloud.provider_name = "cloud"
    mock_cloud.complete = AsyncMock(side_effect=RuntimeError("Cloud API 500 Connection Refused"))

    mock_ollama = MagicMock(spec=OllamaProviderAdapter)
    mock_ollama.provider_name = "ollama"
    mock_ollama.complete = AsyncMock(
        return_value=CompletionResponse(
            content="Response from Local Ollama", provider="ollama", model="qwen2.5:7b"
        )
    )

    offline = OfflineRuleAdapter()

    manager = TutorProviderManager(
        mode=TutoringMode.AUTO,
        cloud_adapter=mock_cloud,
        ollama_adapter=mock_ollama,
        offline_adapter=offline,
    )

    resp = await manager.complete([{"role": "user", "content": "Help me study"}])
    assert resp.content == "Response from Local Ollama"
    assert resp.provider == "ollama"
    assert manager.cloud_breaker.failure_count == 1


@pytest.mark.asyncio
async def test_fallback_chain_all_fail_to_offline_engine():
    """Verify fallback to OfflineRuleAdapter when both Cloud and Ollama fail."""
    mock_cloud = MagicMock(spec=CloudProviderAdapter)
    mock_cloud.provider_name = "cloud"
    mock_cloud.complete = AsyncMock(side_effect=RuntimeError("Cloud 503"))

    mock_ollama = MagicMock(spec=OllamaProviderAdapter)
    mock_ollama.provider_name = "ollama"
    mock_ollama.complete = AsyncMock(side_effect=RuntimeError("Ollama daemon not running"))

    offline = OfflineRuleAdapter()

    manager = TutorProviderManager(
        mode=TutoringMode.AUTO,
        cloud_adapter=mock_cloud,
        ollama_adapter=mock_ollama,
        offline_adapter=offline,
    )

    resp = await manager.complete([{"role": "user", "content": "Calculate derivative of x^2"}])
    assert "Math Tutor" in resp.content
    assert resp.provider == "offline_rule_engine"


@pytest.mark.asyncio
async def test_fallback_chain_streaming_fallback():
    """Verify streaming falls back to Ollama or Offline when primary fails immediately."""
    mock_cloud = MagicMock(spec=CloudProviderAdapter)
    mock_cloud.provider_name = "cloud"

    async def failing_stream(*args, **kwargs):
        raise ConnectionError("Network down")
        yield  # make it an async generator

    mock_cloud.stream = failing_stream

    offline = OfflineRuleAdapter()

    manager = TutorProviderManager(
        mode=TutoringMode.CLOUD,
        cloud_adapter=mock_cloud,
        offline_adapter=offline,
    )

    chunks = []
    async for chunk in manager.stream([{"role": "user", "content": "Python loop tutorial"}]):
        if chunk.content:
            chunks.append(chunk.content)

    full_output = "".join(chunks)
    assert "Coding Tutor" in full_output or "Learning Companion" in full_output


@pytest.mark.asyncio
async def test_manager_system_status():
    """Test get_system_status returns comprehensive diagnostic dictionary."""
    manager = get_tutor_provider_manager()
    status = await manager.get_system_status()

    assert "mode" in status
    assert "active_provider" in status
    assert "hardware_profile" in status
    assert "cloud" in status
    assert "ollama" in status
    assert "offline" in status
    assert status["hardware_profile"]["tier"] in {"LOW", "MEDIUM", "HIGH"}


@pytest.mark.asyncio
async def test_providers_get_models():
    """Test get_models() implementation across all TutorProvider types."""
    # 1. Cloud provider
    cloud = CloudTutorProvider(model="gpt-4o")
    cloud_models = await cloud.get_models()
    assert isinstance(cloud_models, list)
    assert len(cloud_models) >= 1

    # 2. Offline provider
    offline = OfflineRuleTutorProvider()
    offline_models = await offline.get_models()
    assert offline_models == ["offline-rule-v1"]

    # 3. Ollama provider
    ollama = OllamaTutorProvider()
    with patch.object(ollama, "fetch_installed_models", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = ["qwen2.5:7b", "deepseek-r1:7b"]
        models = await ollama.get_models()
        assert models == ["qwen2.5:7b", "deepseek-r1:7b"]


def test_tutor_provider_aliases_and_subclasses():
    """Verify class aliases match primary classes."""
    assert CloudProviderAdapter is CloudTutorProvider
    assert OllamaProviderAdapter is OllamaTutorProvider
    assert OfflineRuleAdapter is OfflineRuleTutorProvider
    assert issubclass(CloudTutorProvider, TutorProvider)
    assert issubclass(OllamaTutorProvider, TutorProvider)
    assert issubclass(OfflineRuleTutorProvider, TutorProvider)


@pytest.mark.asyncio
async def test_tutor_provider_manager_mode_switching():
    """Verify dynamic mode switching and active provider resolution."""
    cloud = CloudTutorProvider(api_key="sk-valid-test-key")
    ollama = OllamaTutorProvider()
    offline = OfflineRuleTutorProvider()

    manager = TutorProviderManager(
        mode=TutoringMode.AUTO,
        cloud_adapter=cloud,
        ollama_adapter=ollama,
        offline_adapter=offline,
    )

    # Switch to OFFLINE
    manager.set_mode("offline")
    assert manager.mode == TutoringMode.OFFLINE
    active = await manager.get_active_provider()
    assert active.provider_name == "offline_rule_engine"

    # Switch to OLLAMA
    manager.set_mode("ollama")
    assert manager.mode == TutoringMode.OLLAMA
    active = await manager.get_active_provider()
    assert active.provider_name == "ollama"

    # Switch to CLOUD
    manager.set_mode("cloud")
    assert manager.mode == TutoringMode.CLOUD
    active = await manager.get_active_provider()
    assert active.provider_name == "cloud"
