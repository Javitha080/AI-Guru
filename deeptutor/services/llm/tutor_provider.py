"""
AI Guru TutorProvider Abstraction & Dual-Mode Tutoring Engine.
==============================================================

Provides a polymorphic AI provider interface (`TutorProvider`) unifying:
  - Mode A: External Cloud API Providers (OpenAI, DeepSeek, DashScope, Claude, etc.)
  - Mode B: Local Ollama LLMs (http://127.0.0.1:11434)
  - Mode C: Deterministic Educational Offline Rule Engine (zero network/model dependency)

Includes:
  - `CircuitBreaker` pattern for proactive failure detection and recovery
  - `TutorProviderManager` managing the auto-fallback chain (Cloud -> Ollama -> Offline)
  - Hardware profiler integration
  - Secure local API key masking vault
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import logging
import re
import time
from typing import Any, Optional

import aiohttp

from deeptutor.services.llm.hardware_profiler import (
    HardwareProfile,
    get_hardware_profile,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Structures & Protocols
# ---------------------------------------------------------------------------

@dataclass
class StreamChunk:
    """A streamed output increment from a TutorProvider."""

    content: str = ""
    reasoning_content: str = ""
    finish_reason: Optional[str] = None
    provider: str = ""
    model: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompletionResponse:
    """A complete response from a TutorProvider."""

    content: str = ""
    reasoning_content: str = ""
    finish_reason: Optional[str] = "stop"
    usage: dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProviderHealth:
    """Health diagnostic for a TutorProvider."""

    status: str = "healthy"  # "healthy", "degraded", "unhealthy", "offline"
    available: bool = True
    provider_name: str = ""
    latency_ms: float = 0.0
    models: list[str] = field(default_factory=list)
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TutoringMode(str, Enum):
    """Supported tutoring execution modes."""

    AUTO = "auto"        # Cloud API -> Ollama -> Offline
    CLOUD = "cloud"      # External Cloud LLM only
    OLLAMA = "ollama"    # Local Ollama only
    OFFLINE = "offline"  # Rule-based offline engine only


# ---------------------------------------------------------------------------
# Security: Key Masking Utility
# ---------------------------------------------------------------------------

def mask_api_key(key: Optional[str]) -> str:
    """
    Safely mask an API key so it is never exposed in full to the frontend or logs.
    e.g. 'sk-1234567890abcdef' -> 'sk-1234...cdef'
    """
    if not key:
        return ""
    clean = key.strip()
    if not clean or clean in {"sk-no-key-required", "None", "none", ""}:
        return ""
    if len(clean) <= 8:
        return "****"
    prefix = clean[:6]
    suffix = clean[-4:]
    return f"{prefix}...{suffix}"


# ---------------------------------------------------------------------------
# Base Interface: TutorProvider
# ---------------------------------------------------------------------------

class TutorProvider(ABC):
    """
    Abstract Base Class defining the unified AI Tutor Provider interface.
    """

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    @abstractmethod
    async def stream(
        self,
        messages: list[dict[str, Any]],
        params: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream assistant response chunks asynchronously."""
        ...

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        params: Optional[dict[str, Any]] = None,
    ) -> CompletionResponse:
        """Execute a full non-streaming completion request."""
        ...

    @abstractmethod
    async def check_health(self) -> ProviderHealth:
        """Probe and return the health status and latency of this provider."""
        ...

    @abstractmethod
    async def get_models(self) -> list[str]:
        """Return available or installed models for this provider."""
        ...

    def get_hardware_profile(self) -> HardwareProfile:
        """Return the current system hardware profile and capability tier."""
        return get_hardware_profile()


# ---------------------------------------------------------------------------
# Adapter 1: CloudTutorProvider (CloudProviderAdapter)
# ---------------------------------------------------------------------------

class CloudTutorProvider(TutorProvider):
    """
    Adapter wrapping external cloud LLM providers (OpenAI, DashScope, DeepSeek, Anthropic, etc.).
    Preserves streaming deltas and thinking/reasoning blocks (<think>...</think>).
    """

    def __init__(
        self,
        provider_name: str = "cloud",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        binding: Optional[str] = None,
    ) -> None:
        super().__init__(provider_name=provider_name)
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.binding = binding or "openai"

    def _resolve_config(self, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Merge instance defaults with runtime params and global settings."""
        p = params or {}
        model = p.get("model") or self.model
        api_key = p.get("api_key") or self.api_key
        base_url = p.get("base_url") or self.base_url
        binding = p.get("binding") or self.binding or "openai"

        if not api_key:
            try:
                from deeptutor.services.config.key_vault import get_key_vault
                vault_key = get_key_vault().get_key(binding)
                if vault_key:
                    api_key = vault_key
            except Exception:
                pass

        if not model or not api_key:
            try:
                from deeptutor.services.llm.config import get_llm_config

                cfg = get_llm_config()
                if not model:
                    model = cfg.model
                if not api_key:
                    api_key = cfg.api_key
                if not base_url:
                    base_url = cfg.base_url
                if not binding:
                    binding = cfg.binding or cfg.provider_name or "openai"
            except Exception as exc:
                logger.debug("Failed to read global LLM config: %s", exc)

        return {
            "model": model or "gpt-4o-mini",
            "api_key": api_key,
            "base_url": base_url,
            "binding": binding,
            "temperature": p.get("temperature", 0.7),
            "max_tokens": p.get("max_tokens", 4096),
        }

    async def stream(
        self,
        messages: list[dict[str, Any]],
        params: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream cloud completions while isolating <think> reasoning tokens."""
        cfg = self._resolve_config(params)
        if not cfg["api_key"] or cfg["api_key"] == "sk-no-key-required":
            raise ValueError("Cloud API key is missing or not configured.")

        from deeptutor.services.llm import factory

        # Prepare kwargs for the factory stream
        prompt = ""
        system_prompt = "You are an expert AI Guru tutor."
        extracted_messages = list(messages)

        in_think = False
        async for chunk_text in factory.stream(
            prompt=prompt,
            system_prompt=system_prompt,
            model=cfg["model"],
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            binding=cfg["binding"],
            messages=extracted_messages,
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
        ):
            if chunk_text == "<think>":
                in_think = True
                continue
            if chunk_text == "</think>":
                in_think = False
                continue

            if in_think:
                yield StreamChunk(
                    reasoning_content=chunk_text,
                    provider=self.provider_name,
                    model=cfg["model"],
                )
            else:
                yield StreamChunk(
                    content=chunk_text,
                    provider=self.provider_name,
                    model=cfg["model"],
                )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        params: Optional[dict[str, Any]] = None,
    ) -> CompletionResponse:
        """Complete prompt via cloud API."""
        cfg = self._resolve_config(params)
        if not cfg["api_key"] or cfg["api_key"] == "sk-no-key-required":
            raise ValueError("Cloud API key is missing or not configured.")

        from deeptutor.services.llm import factory

        prompt = ""
        system_prompt = "You are an expert AI Guru tutor."
        extracted_messages = list(messages)

        full_content = await factory.complete(
            prompt=prompt,
            system_prompt=system_prompt,
            model=cfg["model"],
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            binding=cfg["binding"],
            messages=extracted_messages,
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
        )

        reasoning_content = ""
        # Separate <think> blocks if present
        if "<think>" in full_content and "</think>" in full_content:
            parts = re.split(r"</?think>", full_content)
            if len(parts) >= 3:
                reasoning_content = parts[1].strip()
                full_content = "".join([parts[0], parts[2]]).strip()

        return CompletionResponse(
            content=full_content,
            reasoning_content=reasoning_content,
            finish_reason="stop",
            provider=self.provider_name,
            model=cfg["model"],
        )

    async def check_health(self) -> ProviderHealth:
        """Probe cloud provider connectivity."""
        start = time.perf_counter()
        cfg = self._resolve_config()
        if not cfg.get("api_key") or cfg["api_key"] == "sk-no-key-required":
            return ProviderHealth(
                status="unhealthy",
                available=False,
                provider_name=self.provider_name,
                error="API key not configured",
            )

        try:
            from deeptutor.services.llm.client import get_llm_client

            client = get_llm_client()
            models = client.catalog.list_models() if hasattr(client, "catalog") else [cfg["model"]]
            latency = (time.perf_counter() - start) * 1000
            return ProviderHealth(
                status="healthy",
                available=True,
                provider_name=self.provider_name,
                latency_ms=round(latency, 2),
                models=models,
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            return ProviderHealth(
                status="degraded",
                available=False,
                provider_name=self.provider_name,
                latency_ms=round(latency, 2),
                error=str(e),
            )

    async def get_models(self) -> list[str]:
        """Return list of models available from cloud catalog."""
        try:
            from deeptutor.services.llm.client import get_llm_client

            client = get_llm_client()
            if hasattr(client, "catalog"):
                return client.catalog.list_models()
        except Exception:
            pass
        return [self.model or "gpt-4o-mini"]


CloudProviderAdapter = CloudTutorProvider


# ---------------------------------------------------------------------------
# Adapter 2: OllamaTutorProvider (OllamaProviderAdapter)
# ---------------------------------------------------------------------------

class OllamaTutorProvider(TutorProvider):
    """
    Adapter connecting to local Ollama daemon (http://127.0.0.1:11434).
    """

    def __init__(
        self,
        provider_name: str = "ollama",
        base_url: str = "http://127.0.0.1:11434",
        model: Optional[str] = None,
    ) -> None:
        super().__init__(provider_name=provider_name)
        self.base_url = base_url.rstrip("/")
        self.model = model

    def _resolve_model(self, params: Optional[dict[str, Any]] = None) -> str:
        if params and params.get("model"):
            return str(params["model"])
        if self.model:
            return self.model
        # Use hardware profiler recommendation
        recs = get_hardware_profile().recommended_models
        return recs[0] if recs else "qwen2.5:1.5b"

    async def fetch_installed_models(self) -> list[str]:
        """Fetch list of models currently downloaded in local Ollama."""
        url = f"{self.base_url}/api/tags"
        timeout = aiohttp.ClientTimeout(total=5)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return [m.get("name") for m in data.get("models", []) if m.get("name")]
        except Exception as exc:
            logger.debug("Failed to fetch Ollama models: %s", exc)
        return []

    async def stream(
        self,
        messages: list[dict[str, Any]],
        params: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream responses from local Ollama endpoint."""
        model = self._resolve_model(params)
        temperature = (params or {}).get("temperature", 0.7)
        url = f"{self.base_url}/api/chat"

        # Format messages for Ollama /api/chat
        formatted_messages = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            formatted_messages.append({"role": role, "content": str(content)})

        payload = {
            "model": model,
            "messages": formatted_messages,
            "stream": True,
            "options": {
                "temperature": temperature,
            },
        }

        timeout = aiohttp.ClientTimeout(total=300)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        raise RuntimeError(f"Ollama error (HTTP {resp.status}): {err_text}")

                    in_think_block = False
                    thinking_buf = ""

                    async for line in resp.content:
                        line_str = line.decode("utf-8").strip()
                        if not line_str:
                            continue

                        try:
                            chunk_json = json.loads(line_str)
                            msg = chunk_json.get("message", {})
                            content = msg.get("content", "")

                            if "<think>" in content:
                                in_think_block = True
                                parts = content.split("<think>", 1)
                                if parts[0]:
                                    yield StreamChunk(content=parts[0], provider=self.provider_name, model=model)
                                thinking_buf = parts[1]
                                if "</think>" in thinking_buf:
                                    t_parts = thinking_buf.split("</think>", 1)
                                    yield StreamChunk(reasoning_content=t_parts[0], provider=self.provider_name, model=model)
                                    if t_parts[1]:
                                        yield StreamChunk(content=t_parts[1], provider=self.provider_name, model=model)
                                    in_think_block = False
                                    thinking_buf = ""
                                continue

                            if in_think_block:
                                thinking_buf += content
                                if "</think>" in thinking_buf:
                                    t_parts = thinking_buf.split("</think>", 1)
                                    yield StreamChunk(reasoning_content=t_parts[0], provider=self.provider_name, model=model)
                                    if t_parts[1]:
                                        yield StreamChunk(content=t_parts[1], provider=self.provider_name, model=model)
                                    in_think_block = False
                                    thinking_buf = ""
                                else:
                                    yield StreamChunk(reasoning_content=content, provider=self.provider_name, model=model)
                                continue

                            if content:
                                yield StreamChunk(content=content, provider=self.provider_name, model=model)

                            if chunk_json.get("done", False):
                                yield StreamChunk(finish_reason="stop", provider=self.provider_name, model=model)
                                break
                        except json.JSONDecodeError:
                            continue
        except Exception as exc:
            raise RuntimeError(f"Failed connecting to local Ollama at {self.base_url}: {exc}") from exc

    async def complete(
        self,
        messages: list[dict[str, Any]],
        params: Optional[dict[str, Any]] = None,
    ) -> CompletionResponse:
        """Execute non-streaming completion against local Ollama."""
        chunks: list[str] = []
        reasoning_chunks: list[str] = []
        async for chunk in self.stream(messages, params):
            if chunk.content:
                chunks.append(chunk.content)
            if chunk.reasoning_content:
                reasoning_chunks.append(chunk.reasoning_content)

        model = self._resolve_model(params)
        return CompletionResponse(
            content="".join(chunks),
            reasoning_content="".join(reasoning_chunks),
            finish_reason="stop",
            provider=self.provider_name,
            model=model,
        )

    async def check_health(self) -> ProviderHealth:
        """Probe local Ollama daemon connectivity."""
        start = time.perf_counter()
        try:
            models = await self.fetch_installed_models()
            latency = (time.perf_counter() - start) * 1000
            if models or latency < 2000:
                return ProviderHealth(
                    status="healthy",
                    available=True,
                    provider_name=self.provider_name,
                    latency_ms=round(latency, 2),
                    models=models,
                )
            return ProviderHealth(
                status="degraded",
                available=True,
                provider_name=self.provider_name,
                latency_ms=round(latency, 2),
                models=models,
                error="No models downloaded in local Ollama",
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            return ProviderHealth(
                status="offline",
                available=False,
                provider_name=self.provider_name,
                latency_ms=round(latency, 2),
                error=f"Cannot reach Ollama at {self.base_url}: {e}",
            )

    async def get_models(self) -> list[str]:
        """Return list of models currently installed in local Ollama."""
        return await self.fetch_installed_models()


OllamaProviderAdapter = OllamaTutorProvider


# ---------------------------------------------------------------------------
# Adapter 3: OfflineRuleTutorProvider (OfflineRuleAdapter)
# ---------------------------------------------------------------------------

class OfflineRuleTutorProvider(TutorProvider):
    """
    Deterministic educational fallback engine providing rich Socratic tutoring,
    step-by-step solutions, concept breakdowns, and study advice when completely offline.
    """

    def __init__(self, provider_name: str = "offline_rule_engine") -> None:
        super().__init__(provider_name=provider_name)

    def _generate_response(self, user_query: str) -> str:
        """Generate pedagogical, structured tutoring responses deterministically."""
        q = user_query.strip().lower()

        # Math / Equations
        if any(w in q for w in ["solve", "equation", "formula", "derivative", "integral", "x^", "calculate", "math"]):
            return (
                "### 📐 AI Guru Offline Math Tutor\n\n"
                "**Step-by-Step Problem Solving Method:**\n"
                "1. **Identify Given Information:** Write down known variables and targets.\n"
                "2. **Select the Appropriate Formula / Rule:**\n"
                "   - Quadratic Formula: $x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$\n"
                "   - Power Rule for Derivatives: $\\frac{d}{dx}[x^n] = n x^{n-1}$\n"
                "   - Integration by Parts: $\\int u\\,dv = uv - \\int v\\,du$\n"
                "   - Pythagorean Theorem: $a^2 + b^2 = c^2$\n"
                "3. **Substitute & Simplify:** Carefully substitute terms and isolate the variable.\n"
                "4. **Sanity Check:** Check edge conditions (e.g. non-zero denominators, domain constraints).\n\n"
                "*Tip: Work through each algebraic step on paper, and double-check signs!*"
            )

        # Programming / Coding / Algorithms
        if any(w in q for w in ["code", "python", "javascript", "function", "bug", "algorithm", "loop", "array"]):
            return (
                "### 💻 AI Guru Offline Coding Tutor\n\n"
                "**Structured Problem Decomposition:**\n"
                "1. **Understand the Requirements & Edge Cases:**\n"
                "   - Empty input, single-element, large inputs, negative values.\n"
                "2. **Algorithm Strategy:**\n"
                "   - *Search/Sort:* Binary Search $O(\\log n)$, QuickSort/MergeSort $O(n \\log n)$\n"
                "   - *Optimization:* Hash maps for $O(1)$ lookups, Two Pointers, Dynamic Programming\n"
                "3. **Clean Implementation Pattern (Python):**\n"
                "```python\n"
                "def solve(problem_input):\n"
                "    # 1. Edge case handling\n"
                "    if not problem_input:\n"
                "        return None\n"
                "    # 2. Core logic execution\n"
                "    result = []\n"
                "    for item in problem_input:\n"
                "        result.append(item)\n"
                "    return result\n"
                "```\n"
                "4. **Debugging Checklist:** Verify loop bounds, variable scope, and off-by-one errors."
            )

        # Physics / Science
        if any(w in q for w in ["physics", "force", "velocity", "gravity", "energy", "chemistry", "biology", "atom"]):
            return (
                "### 🔬 AI Guru Offline Science & Physics Tutor\n\n"
                "**Fundamental Physical Laws & Concepts:**\n"
                "- **Newton's Laws of Motion:**\n"
                "  1. *Inertia:* Object stays at rest unless acted on by a net external force.\n"
                "  2. *Force & Acceleration:* $\\vec{F}_{net} = m\\vec{a}$\n"
                "  3. *Action-Reaction:* $\\vec{F}_{A\\to B} = -\\vec{F}_{B\\to A}$\n"
                "- **Conservation of Energy:** $E_{total} = E_k + E_p = \\text{constant}$\n"
                "  - Kinetic Energy: $E_k = \\frac{1}{2}mv^2$\n"
                "  - Gravitational Potential Energy: $E_p = mgh$\n"
                "- **Key Problem-Solving Technique:** Always draw a Free-Body Diagram (FBD) first!"
            )

        # General Study / Explanation
        return (
            "### 🎓 AI Guru Offline Learning Companion\n\n"
            "You are currently in **Offline Tutoring Mode**. Here is a structured breakdown for your topic:\n\n"
            "**1. Core Concept Definition:**\n"
            f"Regarding *\"{user_query}\"*: Break down complex ideas into first principles and fundamental definitions.\n\n"
            "**2. Active Recall & Guided Questions:**\n"
            "- What is the primary objective or mechanism behind this concept?\n"
            "- How does this connect with prerequisites you've previously mastered?\n"
            "- Can you formulate an everyday analogy or counter-example?\n\n"
            "**3. Recommended Next Study Action:**\n"
            "- Summarize key points in your study notebook.\n"
            "- Complete 3 practice problems to reinforce retention."
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        params: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream generated response token-by-token with realistic async delays."""
        user_query = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_query = str(m.get("content", ""))
                break

        full_text = self._generate_response(user_query)
        words = full_text.split(" ")
        for i, word in enumerate(words):
            chunk = word if i == 0 else " " + word
            yield StreamChunk(
                content=chunk,
                provider=self.provider_name,
                model="offline-rule-v1",
            )
            # Subtle delay for natural reading cadence
            if i % 4 == 0:
                await asyncio.sleep(0.01)

        yield StreamChunk(
            finish_reason="stop",
            provider=self.provider_name,
            model="offline-rule-v1",
        )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        params: Optional[dict[str, Any]] = None,
    ) -> CompletionResponse:
        """Return full offline educational response."""
        user_query = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_query = str(m.get("content", ""))
                break

        full_text = self._generate_response(user_query)
        return CompletionResponse(
            content=full_text,
            finish_reason="stop",
            provider=self.provider_name,
            model="offline-rule-v1",
        )

    async def check_health(self) -> ProviderHealth:
        """Offline engine is always 100% healthy and available."""
        return ProviderHealth(
            status="healthy",
            available=True,
            provider_name=self.provider_name,
            latency_ms=0.5,
            models=["offline-rule-v1"],
        )

    async def get_models(self) -> list[str]:
        """Return list of offline rule models."""
        return ["offline-rule-v1"]


OfflineRuleAdapter = OfflineRuleTutorProvider


# ---------------------------------------------------------------------------
# Circuit Breaker Pattern
# ---------------------------------------------------------------------------

class CircuitState(str, Enum):
    CLOSED = "CLOSED"      # Normal healthy operation
    OPEN = "OPEN"          # Failed, requests blocked/diverted
    HALF_OPEN = "HALF_OPEN"# Trialing recovery


class CircuitBreaker:
    """
    Circuit breaker tracking provider health to fail-fast and auto-recover.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 30.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.failure_count: int = 0
        self.state: CircuitState = CircuitState.CLOSED
        self.last_failure_time: float = 0.0

    def record_success(self) -> None:
        """Record successful call, resetting breaker to CLOSED."""
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def record_failure(self, exc: Optional[Exception] = None) -> None:
        """Record failed call; transition to OPEN if threshold reached."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.state == CircuitState.HALF_OPEN or self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                "CircuitBreaker OPEN: tripped after %d consecutive failures (last error: %s)",
                self.failure_count,
                exc,
            )

    def allow_request(self) -> bool:
        """Determine if a request should be attempted or bypassed."""
        if self.state == CircuitState.CLOSED:
            return True

        now = time.monotonic()
        if self.state == CircuitState.OPEN:
            if now - self.last_failure_time >= self.recovery_timeout_seconds:
                self.state = CircuitState.HALF_OPEN
                logger.info("CircuitBreaker HALF_OPEN: testing provider recovery")
                return True
            return False

        # HALF_OPEN: allow trial request
        return True


# ---------------------------------------------------------------------------
# Provider Manager & Auto-Fallback Chain
# ---------------------------------------------------------------------------

class TutorProviderManager:
    """
    Manages provider selection, dual-mode tutoring, and the auto-fallback chain.
    Chain order: Cloud Provider -> Local Ollama -> Offline Rule Engine.
    """

    def __init__(
        self,
        mode: TutoringMode = TutoringMode.AUTO,
        cloud_adapter: Optional[TutorProvider] = None,
        ollama_adapter: Optional[TutorProvider] = None,
        offline_adapter: Optional[TutorProvider] = None,
    ) -> None:
        self.mode = mode
        self.cloud_adapter = cloud_adapter or CloudTutorProvider()
        self.ollama_adapter = ollama_adapter or OllamaTutorProvider()
        self.offline_adapter = offline_adapter or OfflineRuleTutorProvider()

        self.cloud_breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=30.0)
        self.ollama_breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=20.0)

    def set_mode(self, mode: TutoringMode | str) -> None:
        """Change current tutoring mode."""
        if isinstance(mode, str):
            self.mode = TutoringMode(mode.lower())
        else:
            self.mode = mode

    async def get_active_provider(self) -> TutorProvider:
        """
        Resolve the primary active provider according to configured mode and circuit breakers.
        """
        if self.mode == TutoringMode.OFFLINE:
            return self.offline_adapter

        if self.mode == TutoringMode.OLLAMA:
            if self.ollama_breaker.allow_request():
                return self.ollama_adapter
            return self.offline_adapter

        if self.mode == TutoringMode.CLOUD:
            if self.cloud_breaker.allow_request():
                return self.cloud_adapter
            if self.ollama_breaker.allow_request():
                return self.ollama_adapter
            return self.offline_adapter

        # Mode AUTO: Try Cloud -> Ollama -> Offline
        if self.cloud_breaker.allow_request():
            # Quick check if Cloud is configured
            try:
                from deeptutor.services.llm.config import get_llm_config
                cfg = get_llm_config()
                if cfg.api_key and cfg.api_key != "sk-no-key-required":
                    return self.cloud_adapter
            except Exception:
                pass

        if self.ollama_breaker.allow_request():
            return self.ollama_adapter

        return self.offline_adapter

    async def stream(
        self,
        messages: list[dict[str, Any]],
        params: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[StreamChunk]:
        """
        Stream output with seamless automatic fallback:
        Cloud API -> Local Ollama -> Offline Rule Engine.
        """
        # Determine candidate providers in fallback order
        candidates: list[tuple[str, TutorProvider, Optional[CircuitBreaker]]] = []

        if self.mode == TutoringMode.OFFLINE:
            candidates = [("offline", self.offline_adapter, None)]
        elif self.mode == TutoringMode.OLLAMA:
            candidates = [
                ("ollama", self.ollama_adapter, self.ollama_breaker),
                ("offline", self.offline_adapter, None),
            ]
        elif self.mode == TutoringMode.CLOUD:
            candidates = [
                ("cloud", self.cloud_adapter, self.cloud_breaker),
                ("ollama", self.ollama_adapter, self.ollama_breaker),
                ("offline", self.offline_adapter, None),
            ]
        else:  # AUTO
            candidates = [
                ("cloud", self.cloud_adapter, self.cloud_breaker),
                ("ollama", self.ollama_adapter, self.ollama_breaker),
                ("offline", self.offline_adapter, None),
            ]

        last_error: Optional[Exception] = None
        for name, provider, breaker in candidates:
            if breaker is not None and not breaker.allow_request():
                continue

            try:
                yielded_any = False
                async for chunk in provider.stream(messages, params):
                    yielded_any = True
                    yield chunk

                if breaker is not None:
                    breaker.record_success()
                return  # Successful completion!
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "TutorProviderManager: Provider '%s' failed during streaming (%s). Initiating fallback.",
                    name,
                    exc,
                )
                if breaker is not None:
                    breaker.record_failure(exc)

                # If we already yielded chunks to the consumer, we cannot seamlessly restart
                if yielded_any:
                    logger.error("Provider %s failed mid-stream after emitting chunks: %s", name, exc)
                    raise exc

        # All candidates failed
        logger.error("All TutorProviders in fallback chain failed. Last error: %s", last_error)
        async for chunk in self.offline_adapter.stream(messages, params):
            yield chunk

    async def complete(
        self,
        messages: list[dict[str, Any]],
        params: Optional[dict[str, Any]] = None,
    ) -> CompletionResponse:
        """
        Execute completion with automatic fallback chain:
        Cloud -> Ollama -> Offline Rule Engine.
        """
        candidates: list[tuple[str, TutorProvider, Optional[CircuitBreaker]]] = []

        if self.mode == TutoringMode.OFFLINE:
            candidates = [("offline", self.offline_adapter, None)]
        elif self.mode == TutoringMode.OLLAMA:
            candidates = [
                ("ollama", self.ollama_adapter, self.ollama_breaker),
                ("offline", self.offline_adapter, None),
            ]
        elif self.mode == TutoringMode.CLOUD:
            candidates = [
                ("cloud", self.cloud_adapter, self.cloud_breaker),
                ("ollama", self.ollama_adapter, self.ollama_breaker),
                ("offline", self.offline_adapter, None),
            ]
        else:  # AUTO
            candidates = [
                ("cloud", self.cloud_adapter, self.cloud_breaker),
                ("ollama", self.ollama_adapter, self.ollama_breaker),
                ("offline", self.offline_adapter, None),
            ]

        for name, provider, breaker in candidates:
            if breaker is not None and not breaker.allow_request():
                continue

            try:
                resp = await provider.complete(messages, params)
                if breaker is not None:
                    breaker.record_success()
                return resp
            except Exception as exc:
                logger.warning(
                    "TutorProviderManager: Provider '%s' complete() failed (%s). Falling back.",
                    name,
                    exc,
                )
                if breaker is not None:
                    breaker.record_failure(exc)

        # Fallback to offline rule engine
        return await self.offline_adapter.complete(messages, params)

    async def get_system_status(self) -> dict[str, Any]:
        """Return diagnostic health and circuit status for all providers and hardware."""
        cloud_health = await self.cloud_adapter.check_health()
        ollama_health = await self.ollama_adapter.check_health()
        offline_health = await self.offline_adapter.check_health()
        hardware = get_hardware_profile()

        active_provider = await self.get_active_provider()

        # Mask Cloud API Key & fetch vault keys
        masked_key = ""
        masked_vault_keys: dict[str, str] = {}
        try:
            from deeptutor.services.config.key_vault import get_key_vault
            vault = get_key_vault()
            masked_vault_keys = vault.get_masked_keys()
            masked_key = masked_vault_keys.get("default") or masked_vault_keys.get("openai", "")
        except Exception:
            pass

        if not masked_key:
            try:
                from deeptutor.services.llm.config import get_llm_config
                cfg = get_llm_config()
                masked_key = mask_api_key(cfg.api_key)
            except Exception:
                pass

        # Ground-truth "is a cloud provider actually usable?" check: ask the
        # exact resolver the tutor pipeline uses (resolve_llm_runtime_config),
        # not a parallel heuristic. Local/OAuth setups intentionally report
        # False here — availability is covered by the health blocks below.
        catalog_cloud_ready = False
        try:
            from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config

            resolved = resolve_llm_runtime_config()
            catalog_cloud_ready = bool(
                resolved.api_key and resolved.api_key != "sk-no-key-required"
            )
        except Exception:
            catalog_cloud_ready = False

        persisted_mode = None
        try:
            persisted_mode, _ = _load_persisted_tutoring_mode()
        except Exception:
            persisted_mode = None

        return {
            "mode": self.mode.value,
            "persisted_tutoring_mode": persisted_mode.value if persisted_mode else None,
            "configured": bool(catalog_cloud_ready or masked_vault_keys),
            "active_provider": active_provider.provider_name,
            "hardware_profile": hardware.to_dict(),
            "cloud": {
                "health": cloud_health.to_dict(),
                "circuit_state": self.cloud_breaker.state.value,
                "masked_api_key": masked_key,
                "masked_keys": masked_vault_keys,
            },
            "ollama": {
                "health": ollama_health.to_dict(),
                "circuit_state": self.ollama_breaker.state.value,
                "base_url": getattr(self.ollama_adapter, "base_url", "http://127.0.0.1:11434"),
            },
            "offline": {
                "health": offline_health.to_dict(),
            },
        }


# ---------------------------------------------------------------------------
# Global Singleton Accessor
# ---------------------------------------------------------------------------

_tutor_manager_instance: Optional[TutorProviderManager] = None


def _load_persisted_tutoring_mode() -> tuple[Optional["TutoringMode"], Optional[str]]:
    """
    Read the tutoring mode (+ optional custom Ollama endpoint) persisted in
    system settings by the onboarding wizard / settings router.

    Returns ``(None, None)`` when settings are unavailable (CLI-only imports,
    tests with no settings dir) so callers keep their defaults.
    """
    try:
        from deeptutor.services.config.runtime_settings import load_system_settings

        system = load_system_settings()
        raw_mode = str(system.get("tutoring_mode") or "").strip().lower()
        try:
            mode: Optional[TutoringMode] = TutoringMode(raw_mode)
        except ValueError:
            mode = None
        base_url = str(system.get("ollama_base_url") or "").strip() or None
        return mode, base_url
    except Exception:
        return None, None


def get_tutor_provider_manager() -> TutorProviderManager:
    """Return singleton instance of TutorProviderManager."""
    global _tutor_manager_instance
    if _tutor_manager_instance is None:
        persisted_mode, persisted_ollama_url = _load_persisted_tutoring_mode()
        manager = TutorProviderManager()
        if persisted_mode is not None:
            manager.mode = persisted_mode
        if persisted_ollama_url:
            manager.ollama_adapter = OllamaTutorProvider(base_url=persisted_ollama_url)
        _tutor_manager_instance = manager
    return _tutor_manager_instance


__all__ = [
    "StreamChunk",
    "CompletionResponse",
    "ProviderHealth",
    "TutoringMode",
    "TutorProvider",
    "CloudTutorProvider",
    "CloudProviderAdapter",
    "OllamaTutorProvider",
    "OllamaProviderAdapter",
    "OfflineRuleTutorProvider",
    "OfflineRuleAdapter",
    "CircuitState",
    "CircuitBreaker",
    "TutorProviderManager",
    "get_tutor_provider_manager",
    "mask_api_key",
]
