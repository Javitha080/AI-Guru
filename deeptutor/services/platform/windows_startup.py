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
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY_PATH, 0, winreg.KEY_READ) as key:
            try:
                value, _ = winreg.QueryValueEx(key, app_name)
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
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REGISTRY_KEY_PATH, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, command)
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
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REGISTRY_KEY_PATH, 0, winreg.KEY_SET_VALUE
        ) as key:
            try:
                winreg.DeleteValue(key, app_name)
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
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_KEY_PATH, 0, winreg.KEY_READ
            ) as key:
                val, _ = winreg.QueryValueEx(key, app_name)
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
