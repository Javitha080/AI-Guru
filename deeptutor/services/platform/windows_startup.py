"""
Windows Registry Auto-Startup Management for AI Guru.

Manages the Run registry key under HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run.
Gracefully handles non-Windows platforms.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

# mypy cannot resolve winreg's attributes on non-Windows hosts (typeshed gates
# the winreg stub behind ``sys.platform == "win32"``), so the module is
# imported defensively and accessed through an Any-typed alias. Every caller
# is still guarded by ``is_windows()`` before touching the registry.
try:
    import winreg as _winreg
except ImportError:  # pragma: no cover - non-Windows host
    _winreg = None

_WINREG: Any = _winreg

REGISTRY_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
DEFAULT_APP_NAME = "AIGuru"


def is_windows() -> bool:
    """Check if the host platform is Windows."""
    return sys.platform == "win32" or os.name == "nt"


def is_windows_startup_enabled(app_name: str = DEFAULT_APP_NAME) -> bool:
    """Return True if auto-startup entry exists in Windows registry."""
    if not is_windows():
        return False

    try:
        with _WINREG.OpenKey(
            _WINREG.HKEY_CURRENT_USER, REGISTRY_KEY_PATH, 0, _WINREG.KEY_READ
        ) as key:
            try:
                value, _ = _WINREG.QueryValueEx(key, app_name)
                return bool(value and str(value).strip())
            except FileNotFoundError:
                return False
    except Exception as e:
        logger.debug("Failed to query Windows startup registry: %s", e)
        return False


def get_default_startup_command(executable_path: str | None = None, args: str = "start") -> str:
    """Construct command line string for auto-startup."""
    exe = executable_path or sys.executable
    # Use pythonw if python.exe is given on Windows to avoid opening console window,
    # or python executable with CLI module invocation
    return f'"{exe}" -m deeptutor_cli.main {args}'


def enable_windows_startup(
    app_name: str = DEFAULT_APP_NAME,
    executable_path: str | None = None,
    args: str = "start",
) -> bool:
    """
    Add or update AI Guru in Windows registry startup Run key.
    Returns True if successfully registered.
    """
    if not is_windows():
        logger.warning("Windows auto-startup is only supported on Windows systems.")
        return False

    command = get_default_startup_command(executable_path=executable_path, args=args)
    try:
        with _WINREG.OpenKey(
            _WINREG.HKEY_CURRENT_USER, REGISTRY_KEY_PATH, 0, _WINREG.KEY_SET_VALUE
        ) as key:
            _WINREG.SetValueEx(key, app_name, 0, _WINREG.REG_SZ, command)
            logger.info("Successfully enabled Windows startup for %s: %s", app_name, command)
            return True
    except Exception as e:
        logger.error("Failed to enable Windows startup: %s", e)
        return False


def disable_windows_startup(app_name: str = DEFAULT_APP_NAME) -> bool:
    """
    Remove AI Guru from Windows registry startup Run key.
    Returns True if successfully removed or was not present.
    """
    if not is_windows():
        return False

    try:
        with _WINREG.OpenKey(
            _WINREG.HKEY_CURRENT_USER, REGISTRY_KEY_PATH, 0, _WINREG.KEY_SET_VALUE
        ) as key:
            try:
                _WINREG.DeleteValue(key, app_name)
                logger.info("Successfully disabled Windows startup for %s", app_name)
            except FileNotFoundError:
                # Already not registered
                pass
            return True
    except Exception as e:
        logger.error("Failed to disable Windows startup: %s", e)
        return False


def get_startup_status(app_name: str = DEFAULT_APP_NAME) -> dict[str, Any]:
    """Return status dictionary of auto-startup configuration."""
    if not is_windows():
        return {
            "platform": sys.platform,
            "supported": False,
            "enabled": False,
            "app_name": app_name,
            "command": None,
            "message": "Windows auto-startup is supported on Windows OS only.",
        }

    enabled = is_windows_startup_enabled(app_name=app_name)
    current_command: str | None = None
    if enabled:
        try:
            with _WINREG.OpenKey(
                _WINREG.HKEY_CURRENT_USER, REGISTRY_KEY_PATH, 0, _WINREG.KEY_READ
            ) as key:
                val, _ = _WINREG.QueryValueEx(key, app_name)
                current_command = str(val)
        except Exception:
            pass

    return {
        "platform": "win32",
        "supported": True,
        "enabled": enabled,
        "app_name": app_name,
        "command": current_command,
        "default_command": get_default_startup_command(),
    }
