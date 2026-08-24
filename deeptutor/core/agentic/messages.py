"""Canonical message builders for agentic conversations."""

from __future__ import annotations

from typing import Any

_STRUCTURAL_TC_KEYS = ("id", "index", "type", "function")
_STRUCTURAL_FN_KEYS = ("name", "arguments")


def provider_extras(obj: Any, *, known: tuple[str, ...]) -> dict[str, Any]:
    """Collect provider-specific extra fields from an SDK chunk object.

    The OpenAI SDK keeps unknown JSON fields (e.g. Gemini's
    ``thought_signature``) either as real attributes or in ``model_extra``;
    litellm-style layers expose them as ``provider_specific_fields``. Anything
    beyond the structural keys already handled is returned so tool calls can
    be replayed verbatim next round.
    """
    extras: dict[str, Any] = {}
    if obj is None:
        return extras

    candidates: dict[str, Any] = {}
    model_extra = getattr(obj, "model_extra", None)
    if isinstance(model_extra, dict):
        candidates.update(model_extra)
    psf = getattr(obj, "provider_specific_fields", None)
    if isinstance(psf, dict):
        candidates["provider_specific_fields"] = psf

    for key, value in candidates.items():
        if key in known or value is None:
            continue
        if key == "provider_specific_fields":
            if isinstance(value, dict):
                extras.update(value)
            continue
        extras[key] = value
    return extras


def accumulate_streamed_tool_call(
    acc: dict[str, Any],
    tc_delta: Any,
) -> None:
    """Fold one streaming tool-call delta into an accumulator entry.

    ``acc`` may be a bare dict (keys are seeded here); besides id/name/
    arguments this preserves provider-specific extras so the assistant turn
    can be replayed without a Gemini thought-signature 400.
    """
    acc.setdefault("id", "")
    acc.setdefault("name", "")
    acc.setdefault("arguments", "")
    acc.setdefault("extras", {})
    acc.setdefault("fn_extras", {})

    tcid = getattr(tc_delta, "id", None)
    if tcid:
        acc["id"] += str(tcid)
    for key, value in provider_extras(tc_delta, known=_STRUCTURAL_TC_KEYS).items():
        acc["extras"][key] = value

    fn = getattr(tc_delta, "function", None)
    if fn is None:
        return
    for key, value in provider_extras(fn, known=_STRUCTURAL_FN_KEYS).items():
        acc["fn_extras"][key] = value
    name = getattr(fn, "name", None)
    arguments = getattr(fn, "arguments", None)
    if name:
        acc["name"] += str(name)
    if arguments:
        acc["arguments"] += str(arguments)


def finalize_streamed_tool_calls(
    tool_acc: dict[int, dict[str, Any]],
    *,
    id_fallback: str = "call_{}",
) -> list[dict[str, Any]]:
    """Build the flat id/name/arguments(+extras) dicts from accumulated deltas."""
    calls: list[dict[str, Any]] = []
    for idx, data in sorted(tool_acc.items()):
        if not data.get("name"):
            continue
        entry: dict[str, Any] = {
            "id": data.get("id") or id_fallback.format(idx),
            "name": data.get("name", ""),
            "arguments": data.get("arguments") or "{}",
        }
        extras = data.get("extras") or {}
        fn_extras = data.get("fn_extras") or {}
        # Merge function-level signatures up when the call level has none —
        # Gemini may attach the signature at either nesting depending on SDK.
        if fn_extras and not extras:
            extras = fn_extras
            fn_extras = {}
        if extras:
            entry["provider_specific_fields"] = extras
        if fn_extras:
            entry["function_provider_specific_fields"] = fn_extras
        calls.append(entry)
    return calls


def _tool_call_payload(tool_call: dict[str, Any]) -> dict[str, Any]:
    """Serialize one tool call for an assistant message.

    Provider-specific fields (Gemini's ``thought_signature`` arrives wrapped
    in ``provider_specific_fields`` / ``function_provider_specific_fields``)
    must survive the round-trip: replaying a stripped assistant turn makes
    Gemini reject the request with 400 ``INVALID_ARGUMENT`` ("Function call
    is missing a thought_signature").
    """
    function: dict[str, Any] = {
        "name": tool_call.get("name") or "",
        "arguments": tool_call.get("arguments") or "{}",
    }
    function_psf = tool_call.get("function_provider_specific_fields")
    if isinstance(function_psf, dict) and function_psf:
        function["provider_specific_fields"] = function_psf

    payload: dict[str, Any] = {
        "id": tool_call.get("id") or "",
        "type": "function",
        "function": function,
    }
    psf = tool_call.get("provider_specific_fields")
    if isinstance(psf, dict) and psf:
        payload["provider_specific_fields"] = psf
    return payload


def assistant_message_with_tool_calls(
    content: str,
    tool_calls: list[dict[str, Any]],
    reasoning_content: str | None = None,
) -> dict[str, Any]:
    """Build the assistant message that precedes tool result messages."""
    msg: dict[str, Any] = {
        "role": "assistant",
        "content": content or None,
        "tool_calls": [_tool_call_payload(tool_call) for tool_call in tool_calls],
    }
    if reasoning_content:
        msg["reasoning_content"] = reasoning_content
    return msg


__all__ = [
    "accumulate_streamed_tool_call",
    "assistant_message_with_tool_calls",
    "finalize_streamed_tool_calls",
    "provider_extras",
]
