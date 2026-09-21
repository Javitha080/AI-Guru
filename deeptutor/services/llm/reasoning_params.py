"""Reasoning/thinking parameters for OpenAI-compatible provider calls."""

from __future__ import annotations

from typing import Any

_THINKING_STYLE_MAP = {
    "thinking_type": lambda enabled: {"thinking": {"type": "enabled" if enabled else "disabled"}},
    "enable_thinking": lambda enabled: {"enable_thinking": enabled},
    "reasoning_split": lambda enabled: {"reasoning_split": enabled},
    # Gemini (OpenAI-compat): thought summaries are opt-in per request. The
    # top-level ``reasoning_effort`` (sent separately below) selects the
    # thinking level/budget; ``include_thoughts`` controls whether the
    # thoughts stream back inline as <think> blocks.
    "google_thinking": lambda enabled: {
        "google": {"thinking_config": {"include_thoughts": enabled}}
    },
    # OpenRouter: unified ``reasoning`` control (also accepted top-level, but
    # extra_body is the documented OpenAI-SDK path). Reasoning is returned
    # by default; the flag is only needed to set effort or exclude it.
    "openrouter_reasoning": lambda enabled: (
        {"reasoning": {"enabled": True, "exclude": False}}
        if enabled
        else {"reasoning": {"exclude": True}}
    ),
}
_PROVIDER_THINKING_STYLES = {
    "deepseek": "thinking_type",
    "volcengine": "thinking_type",
    "volcengine_coding_plan": "thinking_type",
    "byteplus": "thinking_type",
    "byteplus_coding_plan": "thinking_type",
    "dashscope": "enable_thinking",
    "minimax": "reasoning_split",
    "gemini": "google_thinking",
    "openrouter": "openrouter_reasoning",
    # Groq is intentionally absent: its reasoning knobs are model-specific
    # (reasoning_format is rejected by gpt-oss, reasoning_effort only exists
    # on gpt-oss/qwen3.6) and are resolved per model in
    # build_openai_compatible_reasoning_kwargs below. Groq includes reasoning
    # by default, so no flag is needed to turn thinking on.
}
_PROVIDER_REASONING_PATTERNS = {
    "deepseek": ("deepseek-v4-pro", "deepseek-reasoner"),
    "dashscope": ("qwen3", "qwen-3", "qwq", "qwen-plus"),
}
# Models that ship with thinking enabled by default and burn the entire
# `max_tokens` budget on reasoning unless we explicitly turn it off via the
# top-level ``reasoning_effort`` field. Substring match — also catches the
# ``models/``-prefixed Gemini aliases and is case-insensitive (see
# :func:`_matches`).
#
# NOTE: intentionally empty. Gemini 2.5/3.x used to live here ("none" on
# Auto) to save output tokens, but that hid model thinking entirely while
# vendor sites show it. Thinking now defaults ON at the model-default
# budget via the ``google_thinking`` style (include_thoughts); users opt
# out per model with reasoning_effort=none.
_PROVIDER_DEFAULT_OFF_PATTERNS: dict[str, tuple[str, ...]] = {}
_CUSTOM_MODEL_THINKING_STYLES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("qwen3", "qwen-3", "qwq", "qwen-plus"), "enable_thinking"),
    (("deepseek-v4-pro", "deepseek-reasoner"), "thinking_type"),
)
_THINKING_DISABLED_BY_DEFAULT: tuple[tuple[str, str], ...] = (("deepseek", "deepseek-v4-flash"),)

# Gemini families with native thinking (thought summaries). Legacy 1.5/2.0
# models neither think nor accept thinking flags.
_GEMINI_THINKING_PATTERNS = ("gemini-2.5", "gemini-3")


def _spec_name(spec: Any, binding: str | None) -> str:
    return str(getattr(spec, "name", None) or binding or "").strip().lower()


def _matches(model_name: str, patterns: tuple[str, ...]) -> bool:
    model_lower = model_name.lower()
    return any(pattern.lower() in model_lower for pattern in patterns)


def _custom_thinking_style(model_name: str) -> tuple[str, tuple[str, ...]]:
    for patterns, style in _CUSTOM_MODEL_THINKING_STYLES:
        if _matches(model_name, patterns):
            return style, patterns
    return "", ()


def _disable_thinking_by_default(provider_name: str, model_name: str) -> bool:
    normalized = model_name.strip().lower()
    return any(
        provider_name == provider and pattern in normalized
        for provider, pattern in _THINKING_DISABLED_BY_DEFAULT
    )


def default_reasoning_effort_for(provider: str | None, model: str | None) -> str | None:
    """Return the implicit ``reasoning_effort`` for ``provider``/``model``, if any.

    Used by callers that don't go through :func:`build_openai_compatible_reasoning_kwargs`
    (currently the openai-SDK path in ``executors.py`` and the aiohttp fallback
    in ``cloud_provider.py``). Returns ``None`` when no default applies — the
    caller should leave the field unset in that case.

    The single source of truth is :data:`_PROVIDER_DEFAULT_OFF_PATTERNS` so all
    three execution paths agree on which models need thinking disabled by default.
    """
    provider_name = (provider or "").strip().lower()
    off_patterns = _PROVIDER_DEFAULT_OFF_PATTERNS.get(provider_name)
    if off_patterns and _matches(model or "", off_patterns):
        return "none"
    return None


def build_openai_compatible_reasoning_kwargs(
    *,
    spec: Any,
    binding: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> dict[str, Any]:
    """Return reasoning kwargs for OpenAI-compatible Chat Completions calls.

    Some OpenAI-compatible providers expose thinking controls through
    ``extra_body`` instead of the top-level ``reasoning_effort`` field.  Direct
    ``custom`` bindings need model-family inference because their endpoint is
    user supplied and therefore cannot be identified by provider name alone.
    """
    provider_name = _spec_name(spec, binding)
    model_name = model or ""
    thinking_style = str(getattr(spec, "thinking_style", "") or "")
    patterns = tuple(getattr(spec, "reasoning_model_patterns", ()) or ())

    if not thinking_style:
        thinking_style = _PROVIDER_THINKING_STYLES.get(provider_name, "")
    if not patterns:
        patterns = _PROVIDER_REASONING_PATTERNS.get(provider_name, ())
    if provider_name == "custom":
        custom_style, custom_patterns = _custom_thinking_style(model_name)
        if custom_style:
            thinking_style = custom_style
            patterns = custom_patterns

    resolved_effort = reasoning_effort
    if resolved_effort is None:
        if patterns and _matches(model_name, patterns):
            resolved_effort = "high"
        else:
            resolved_effort = default_reasoning_effort_for(provider_name, model_name)

    semantic_effort: str | None = None
    if isinstance(resolved_effort, str):
        semantic_effort = resolved_effort.lower()
        if semantic_effort == "minimum":
            semantic_effort = "minimal"

    kwargs: dict[str, Any] = {}
    if resolved_effort:
        suppress_top_level = bool(
            thinking_style and (semantic_effort == "minimal" or thinking_style == "enable_thinking")
        )
        if thinking_style in ("google_thinking", "openrouter_reasoning"):
            # Effort values map 1:1 onto Gemini thinking levels and
            # OpenRouter gateway efforts — never suppress them.
            suppress_top_level = False
        if thinking_style == "groq_reasoning":
            # Placeholder: the real groq branch below decides. Top-level
            # reasoning_effort only exists on gpt-oss / qwen3.6.
            suppress_top_level = True
        if not suppress_top_level:
            kwargs["reasoning_effort"] = resolved_effort

    if provider_name == "groq":
        _apply_groq_reasoning_kwargs(
            kwargs, model_name=model_name, resolved_effort=resolved_effort
        )
        return kwargs

    if thinking_style and resolved_effort is not None:
        if thinking_style == "openrouter_reasoning":
            # Effort-aware: the gateway normalizes these onto the target
            # model (effort none disables; minimal is a real 10% level).
            if semantic_effort == "none":
                extra: dict[str, Any] | None = {"reasoning": {"effort": "none"}}
            else:
                extra = {
                    "reasoning": {"effort": resolved_effort, "exclude": False}
                }
        else:
            thinking_enabled = semantic_effort not in ("minimal", "none")
            extra = _THINKING_STYLE_MAP.get(thinking_style, lambda _enabled: None)(
                thinking_enabled
            )
        if extra:
            kwargs.setdefault("extra_body", {}).update(extra)
    elif thinking_style and _disable_thinking_by_default(provider_name, model_name):
        extra = _THINKING_STYLE_MAP.get(thinking_style, lambda _enabled: None)(False)
        if extra:
            kwargs.setdefault("extra_body", {}).update(extra)
    elif thinking_style == "google_thinking":
        # Auto (no explicit effort): thinking stays at the model-default
        # budget, but thought summaries must be requested or nothing streams
        # back to the trace. Only for thinking-capable families — legacy
        # models (1.5/2.0) neither think nor accept the flag.
        if _matches(model_name, _GEMINI_THINKING_PATTERNS):
            extra = _THINKING_STYLE_MAP["google_thinking"](True)
            kwargs.setdefault("extra_body", {}).update(extra)

    return kwargs


# Groq models that accept a top-level ``reasoning_effort`` (per Groq docs).
_GROQ_EFFORT_MODELS = ("gpt-oss", "qwen3.6", "qwen3-6")
# Groq Qwen models that document ``reasoning_format``. Other Groq reasoning
# models (deepseek distills, llama) must NOT receive it — unknown params risk
# a 400 — they already include reasoning by default.
_GROQ_REASONING_FORMAT_MODELS = ("qwen",)


def _apply_groq_reasoning_kwargs(
    kwargs: dict[str, Any],
    *,
    model_name: str,
    resolved_effort: str | None,
) -> None:
    """Fill ``kwargs`` with Groq's model-specific reasoning controls.

    Groq includes reasoning by default (``include_reasoning`` defaults true),
    so Auto sends nothing except ``reasoning_format: parsed`` for the Qwen
    family — required there once tools/JSON mode enter the request, and it is
    what separates thinking into the ``reasoning`` delta field our trace
    reads instead of inline tags.
    """
    if resolved_effort is None:
        if _matches(model_name, _GROQ_REASONING_FORMAT_MODELS) and not _matches(
            model_name, ("gpt-oss",)
        ):
            kwargs.setdefault("extra_body", {}).update(
                {"reasoning_format": "parsed", "include_reasoning": True}
            )
        return
    semantic = resolved_effort.lower()
    if semantic == "none":
        kwargs.setdefault("extra_body", {}).update({"include_reasoning": False})
        return
    if _matches(model_name, _GROQ_EFFORT_MODELS):
        kwargs["reasoning_effort"] = resolved_effort
    if _matches(model_name, _GROQ_REASONING_FORMAT_MODELS) and not _matches(
        model_name, ("gpt-oss",)
    ):
        kwargs.setdefault("extra_body", {}).update(
            {"reasoning_format": "parsed", "include_reasoning": True}
        )


def _coerce_reasoning_text(value: Any) -> str:
    """Best-effort stringify of a provider reasoning payload.

    Handles plain strings (DeepSeek ``reasoning_content``, Groq/OpenRouter
    ``reasoning``), Ollama-style ``thinking``/``thought`` strings, and
    block lists (Anthropic-style ``[{type, text}]``) by joining text parts.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("thinking") or item.get("summary")
                if isinstance(text, str):
                    parts.append(text)
            else:
                text = getattr(item, "text", None) or getattr(item, "thinking", None)
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def extract_delta_reasoning_text(delta: Any) -> str:
    """Return the thinking text carried by one streaming delta, if any.

    Field order mirrors provider conventions: DeepSeek/vLLM
    ``reasoning_content`` first, then Groq/OpenRouter/Cerebras ``reasoning``,
    then Ollama-compat ``thinking`` / ``thought``. Works for both SDK
    objects and plain dicts.
    """
    if delta is None:
        return ""
    if isinstance(delta, dict):
        for key in ("reasoning_content", "reasoning", "thinking", "thought"):
            text = _coerce_reasoning_text(delta.get(key))
            if text:
                return text
        return ""
    for attr in ("reasoning_content", "reasoning", "thinking", "thought"):
        try:
            value = getattr(delta, attr, None)
        except Exception:
            continue
        text = _coerce_reasoning_text(value)
        if text:
            return text
    return ""


__all__ = [
    "build_openai_compatible_reasoning_kwargs",
    "default_reasoning_effort_for",
    "extract_delta_reasoning_text",
]
