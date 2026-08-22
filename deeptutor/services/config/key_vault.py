"""
AI Guru Secure Local Key Storage (Key Vault).
============================================

Manages local storage of external AI API keys in `data/user/settings/keys.json`.
Keys are stored strictly on the local filesystem and are never exposed in plaintext
to client-side JavaScript bundles or unauthenticated requests.
All client-facing reads return server-side masked representations (e.g. `sk-proj...1234`).
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

KEYS_SETTINGS_FILE = "keys.json"


def mask_api_key(key: Optional[str]) -> str:
    """
    Safely mask an API key for server-side responses and logging.
    e.g. 'sk-proj-1234567890abcdef' -> 'sk-proj...cdef'
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


class KeyVaultService:
    """
    Local filesystem key storage vault.
    """

    def __init__(self, settings_dir: Optional[Path] = None) -> None:
        self._settings_dir = settings_dir
        self._cached_data: Optional[dict[str, Any]] = None

    def _get_vault_path(self) -> Path:
        if self._settings_dir:
            return self._settings_dir / KEYS_SETTINGS_FILE
        return get_path_service().get_settings_dir() / KEYS_SETTINGS_FILE

    def load_vault(self, refresh: bool = False) -> dict[str, Any]:
        """Load vault JSON structure from disk, ensuring defaults if absent."""
        if self._cached_data is not None and not refresh:
            return self._cached_data

        path = self._get_vault_path()
        if not path.exists():
            default_payload: dict[str, Any] = {
                "version": 1,
                "keys": {},
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_json(path, default_payload)
            except Exception as exc:
                logger.warning("Failed to initialize keys.json: %s", exc)
            self._cached_data = default_payload
            return default_payload

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {"version": 1, "keys": {}}
            if "keys" not in data or not isinstance(data["keys"], dict):
                data["keys"] = {}
            self._cached_data = data
            return data
        except Exception as exc:
            logger.error("Failed to read keys.json: %s", exc)
            return {"version": 1, "keys": {}}

    def get_key(self, provider_name: str = "default") -> Optional[str]:
        """
        Retrieve raw API key for provider.
        Checks local vault -> process environment variables -> global LLM config.
        """
        vault = self.load_vault()
        keys = vault.get("keys", {})
        provider_key = provider_name.strip().lower()

        # 1. Check exact provider key in vault
        if provider_key in keys and keys[provider_key]:
            return str(keys[provider_key])

        # 2. Check default key in vault (only if default is requested)
        if provider_key in {"default", "global", ""} and "default" in keys and keys["default"]:
            return str(keys["default"])

        # 3. Check environment variables
        env_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "dashscope": "DASHSCOPE_API_KEY",
            "default": "OPENAI_API_KEY",
        }
        env_var = env_map.get(provider_key)
        import os
        if env_var and os.environ.get(env_var):
            return os.environ[env_var]

        # 4. Check global config fallback (only if default is requested)
        if provider_key in {"default", "global", ""}:
            try:
                from deeptutor.services.llm.config import get_llm_config
                cfg = get_llm_config()
                if cfg.api_key and cfg.api_key != "sk-no-key-required":
                    return cfg.api_key
            except Exception:
                pass

        return None

    def set_key(self, provider_name: str, api_key: str) -> None:
        """Store API key for provider in local vault and update runtime env."""
        vault = self.load_vault(refresh=True)
        provider_key = provider_name.strip().lower()
        clean_key = api_key.strip()

        if "keys" not in vault or not isinstance(vault["keys"], dict):
            vault["keys"] = {}

        vault["keys"][provider_key] = clean_key
        vault["updated_at"] = datetime.now(timezone.utc).isoformat()

        path = self._get_vault_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, vault)
        self._cached_data = vault

        # Sync to environment variable for immediate provider readiness
        import os
        if provider_key in {"openai", "default"}:
            os.environ["OPENAI_API_KEY"] = clean_key
        elif provider_key == "anthropic":
            os.environ["ANTHROPIC_API_KEY"] = clean_key
        elif provider_key == "deepseek":
            os.environ["DEEPSEEK_API_KEY"] = clean_key
        elif provider_key == "dashscope":
            os.environ["DASHSCOPE_API_KEY"] = clean_key

    def delete_key(self, provider_name: str) -> bool:
        """Remove an API key from the local vault."""
        vault = self.load_vault(refresh=True)
        provider_key = provider_name.strip().lower()

        if "keys" in vault and provider_key in vault["keys"]:
            del vault["keys"][provider_key]
            vault["updated_at"] = datetime.now(timezone.utc).isoformat()
            path = self._get_vault_path()
            atomic_write_json(path, vault)
            self._cached_data = vault
            return True
        return False

    def get_masked_keys(self) -> dict[str, str]:
        """
        Return dictionary of all registered providers with safely masked keys.
        Suitable for sending to frontend UI.
        """
        vault = self.load_vault(refresh=True)
        raw_keys = vault.get("keys", {})
        masked: dict[str, str] = {}
        for p, key in raw_keys.items():
            masked[p] = mask_api_key(str(key))

        # Include default from config if not in vault
        if "default" not in masked:
            fallback = self.get_key("default")
            if fallback:
                masked["default"] = mask_api_key(fallback)

        return masked


_vault_instance: Optional[KeyVaultService] = None


def get_key_vault() -> KeyVaultService:
    """Return singleton instance of KeyVaultService."""
    global _vault_instance
    if _vault_instance is None:
        _vault_instance = KeyVaultService()
    return _vault_instance
