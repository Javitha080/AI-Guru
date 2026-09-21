"""Tests for the centralized reasoning-effort registry."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.services.llm.reasoning_params import (
    build_openai_compatible_reasoning_kwargs,
    default_reasoning_effort_for,
    extract_delta_reasoning_text,
)


class TestDefaultReasoningEffortFor:
    """Single source of truth for the implicit per-provider/model effort."""

    @pytest.mark.parametrize(
        "model",
        [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.5-flash-lite",
            "GEMINI-2.5-FLASH",
            "models/gemini-2.5-flash",
            "gemini-3.0-pro",
            "gemini-3.6-flash",
        ],
    )
    def test_gemini_thinking_models_have_no_forced_default(self, model: str) -> None:
        # Thinking stays at the model-default budget; the google_thinking
        # style requests thought summaries via extra_body instead.
        assert default_reasoning_effort_for("gemini", model) is None

    @pytest.mark.parametrize(
        "model",
        ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"],
    )
    def test_gemini_legacy_models_unaffected(self, model: str) -> None:
        assert default_reasoning_effort_for("gemini", model) is None

    def test_other_providers_unaffected(self) -> None:
        assert default_reasoning_effort_for("openai", "gpt-5") is None
        assert default_reasoning_effort_for("deepseek", "deepseek-v4") is None
        assert default_reasoning_effort_for("dashscope", "qwen3-max") is None
        assert default_reasoning_effort_for("groq", "llama-3.3-70b-versatile") is None
        assert default_reasoning_effort_for("openrouter", "x/y:free") is None

    def test_missing_provider_or_model(self) -> None:
        assert default_reasoning_effort_for(None, "gemini-2.5-flash") is None
        assert default_reasoning_effort_for("gemini", None) is None
        assert default_reasoning_effort_for("", "") is None

    def test_provider_name_case_insensitive(self) -> None:
        assert default_reasoning_effort_for("Gemini", "gemini-2.5-flash") is None
        assert default_reasoning_effort_for("GEMINI", "gemini-2.5-flash") is None


class TestBuildOpenAICompatibleReasoningKwargsForGemini:
    """The OpenAI-compat helper consults the same registry."""

    def test_gemini_25_auto_requests_thoughts_at_default_budget(self) -> None:
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None, binding="gemini", model="gemini-2.5-flash", reasoning_effort=None
        )
        assert kwargs == {
            "extra_body": {"google": {"thinking_config": {"include_thoughts": True}}}
        }

    def test_models_prefix_still_matches(self) -> None:
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None,
            binding="gemini",
            model="models/gemini-2.5-flash",
            reasoning_effort=None,
        )
        assert kwargs == {
            "extra_body": {"google": {"thinking_config": {"include_thoughts": True}}}
        }

    def test_explicit_effort_takes_precedence(self) -> None:
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None,
            binding="gemini",
            model="gemini-2.5-flash",
            reasoning_effort="high",
        )
        assert kwargs == {
            "reasoning_effort": "high",
            "extra_body": {"google": {"thinking_config": {"include_thoughts": True}}},
        }

    def test_explicit_none_disables_thinking(self) -> None:
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None,
            binding="gemini",
            model="gemini-2.5-flash",
            reasoning_effort="none",
        )
        assert kwargs == {
            "reasoning_effort": "none",
            "extra_body": {"google": {"thinking_config": {"include_thoughts": False}}},
        }

    def test_gemini_15_left_untouched(self) -> None:
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None,
            binding="gemini",
            model="gemini-1.5-flash",
            reasoning_effort=None,
        )
        assert kwargs == {}

    def test_openai_left_untouched(self) -> None:
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None, binding="openai", model="gpt-4o", reasoning_effort=None
        )
        assert kwargs == {}


class TestBuildOpenAICompatibleReasoningKwargsForGateways:
    def test_openrouter_auto_is_passthrough(self) -> None:
        # Reasoning is returned by default; no flag needed.
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None,
            binding="openrouter",
            model="deepseek/deepseek-r1:free",
            reasoning_effort=None,
        )
        assert kwargs == {}

    def test_openrouter_explicit_effort(self) -> None:
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None,
            binding="openrouter",
            model="deepseek/deepseek-r1:free",
            reasoning_effort="high",
        )
        assert kwargs["reasoning_effort"] == "high"
        assert kwargs["extra_body"] == {
            "reasoning": {"effort": "high", "exclude": False}
        }

    def test_groq_auto_sends_nothing_for_plain_models(self) -> None:
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None,
            binding="groq",
            model="llama-3.3-70b-versatile",
            reasoning_effort=None,
        )
        assert kwargs == {}

    def test_groq_auto_parses_qwen_reasoning(self) -> None:
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None, binding="groq", model="qwen/qwen3-32b", reasoning_effort=None
        )
        assert kwargs["extra_body"] == {
            "reasoning_format": "parsed",
            "include_reasoning": True,
        }
        assert "reasoning_effort" not in kwargs

    def test_groq_gpt_oss_effort_passes_through(self) -> None:
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None,
            binding="groq",
            model="openai/gpt-oss-20b",
            reasoning_effort="medium",
        )
        assert kwargs["reasoning_effort"] == "medium"

    def test_groq_gpt_oss_never_gets_reasoning_format(self) -> None:
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None,
            binding="groq",
            model="openai/gpt-oss-20b",
            reasoning_effort="medium",
        )
        assert "reasoning_format" not in kwargs.get("extra_body", {})

    def test_groq_none_disables_reasoning(self) -> None:
        kwargs = build_openai_compatible_reasoning_kwargs(
            spec=None,
            binding="groq",
            model="openai/gpt-oss-20b",
            reasoning_effort="none",
        )
        assert kwargs["extra_body"] == {"include_reasoning": False}


class TestExtractDeltaReasoningText:
    def test_reasoning_content_first(self) -> None:
        delta = SimpleNamespace(content="hi", reasoning_content="deep thought")
        assert extract_delta_reasoning_text(delta) == "deep thought"

    def test_groq_openrouter_reasoning_field(self) -> None:
        delta = SimpleNamespace(content="hi", reasoning="groq thought")
        assert extract_delta_reasoning_text(delta) == "groq thought"

    def test_ollama_thinking_field(self) -> None:
        delta = SimpleNamespace(content="hi", thinking="ollama thought")
        assert extract_delta_reasoning_text(delta) == "ollama thought"

    def test_dict_deltas(self) -> None:
        assert (
            extract_delta_reasoning_text({"content": "x", "reasoning": "r"}) == "r"
        )

    def test_block_lists_joined(self) -> None:
        delta = SimpleNamespace(
            reasoning=[{"type": "thinking", "text": "a"}, {"type": "x", "text": "b"}]
        )
        assert extract_delta_reasoning_text(delta) == "ab"

    def test_empty_and_none(self) -> None:
        assert extract_delta_reasoning_text(None) == ""
        assert extract_delta_reasoning_text(SimpleNamespace(content="x")) == ""
        assert extract_delta_reasoning_text({}) == ""
