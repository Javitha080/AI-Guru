"""Shared retrieval-mode resolution for mode-aware pipelines (LightRAG, GraphRAG).

Resolution order, first valid wins:

1. an explicit ``mode`` kwarg (a one-off override on the search call),
2. the KB's own ``search_mode`` (``kb_config.json`` → ``knowledge_bases[kb]``),
3. the engine's global default mode set from the engine card
   (``kb_config.json`` → ``defaults.provider_modes[provider]``),
4. the engine's built-in default.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Sequence

_CONFIG_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def clear_kb_config_cache() -> None:
    """Clear cached kb_config.json contents (for tests or manual refresh)."""
    _CONFIG_CACHE.clear()


def load_kb_config_cached(cfg_path: str | Path) -> Optional[dict[str, Any]]:
    """Load kb_config.json with mtime caching to avoid repeated disk reads."""
    p = Path(cfg_path)
    try:
        stat_res = p.stat()
        mtime = stat_res.st_mtime
        cache_key = str(p.resolve())
        cached = _CONFIG_CACHE.get(cache_key)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        data = json.loads(p.read_text(encoding="utf-8"))
        _CONFIG_CACHE[cache_key] = (mtime, data)
        return data
    except (OSError, ValueError, TypeError):
        return None


# Backward-compatible alias
_load_kb_config_cached = load_kb_config_cached


def resolve_kb_mode(
    kb_base_dir: str | Path,
    kb_name: Optional[str],
    provider: str,
    *,
    explicit: Any = None,
    supported: Sequence[str],
    default: str,
) -> str:
    candidates: list[Any] = [explicit]
    try:
        cfg_path = Path(kb_base_dir) / "kb_config.json"
        data = load_kb_config_cached(cfg_path)
        if data:
            if kb_name:
                entry = data.get("knowledge_bases", {}).get(kb_name, {})
                candidates.append(entry.get("search_mode"))
            candidates.append(data.get("defaults", {}).get("provider_modes", {}).get(provider))
    except Exception:  # pragma: no cover - defensive
        pass

    supported_set = {m.lower() for m in supported}
    for candidate in candidates:
        norm = (str(candidate) if candidate else "").strip().lower()
        if norm in supported_set:
            return norm
    return default


__all__ = ["resolve_kb_mode", "load_kb_config_cached", "clear_kb_config_cache"]
