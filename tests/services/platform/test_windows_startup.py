"""
Tests for Windows auto-startup platform utility.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from deeptutor.services.platform.windows_startup import (
    disable_windows_startup,
    enable_windows_startup,
    get_default_startup_command,
    get_startup_status,
    is_windows,
    is_windows_startup_enabled,
)


def test_get_default_startup_command() -> None:
    cmd = get_default_startup_command()
    assert "-m deeptutor_cli.main start" in cmd
    assert sys.executable in cmd


def test_startup_status_structure() -> None:
    status = get_startup_status(app_name="AIGuruTest")
    assert "platform" in status
    assert "supported" in status
    assert "enabled" in status
    assert status["app_name"] == "AIGuruTest"


def test_windows_mock_enable_disable() -> None:
    if not is_windows():
        # Non-windows should gracefully report unsupported
        assert is_windows_startup_enabled("AIGuruTest") is False
        assert enable_windows_startup("AIGuruTest") is False
        assert disable_windows_startup("AIGuruTest") is False
    else:
        # On Windows, test with mock winreg to avoid polluting actual user registry during tests
        with patch("winreg.OpenKey") as mock_open:
            mock_key = MagicMock()
            mock_open.return_value.__enter__.return_value = mock_key
            with patch("winreg.SetValueEx") as mock_set:
                res = enable_windows_startup("AIGuruTest")
                assert res is True
                mock_set.assert_called_once()
