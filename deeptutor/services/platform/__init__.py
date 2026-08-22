"""
AI Guru Platform Integration Utilities.
"""

from __future__ import annotations

from deeptutor.services.platform.windows_startup import (
    disable_windows_startup,
    enable_windows_startup,
    get_default_startup_command,
    get_startup_status,
    is_windows,
    is_windows_startup_enabled,
)

__all__ = [
    "disable_windows_startup",
    "enable_windows_startup",
    "get_default_startup_command",
    "get_startup_status",
    "is_windows",
    "is_windows_startup_enabled",
]
