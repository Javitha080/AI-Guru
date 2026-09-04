"""Telegram tunnel-command listener tests.

Pins the pure security/parse layer of the remote tunnel-control listener:
command grammar, config parsing, and the exact-chat-id authorization gate.
Network and tunnel side effects are not exercised here (covered by e2e
gateway mocks).
"""

from __future__ import annotations

import json

from deeptutor.services.remote.telegram_command_listener import (
    is_authorized_chat,
    load_parent_telegram_config,
    parse_command,
)

CFG_JSON = json.dumps(
    {
        "bot_token": "123:ABC",
        "chat_id": "555000111",
        "enabled": True,
        "updated_at": 0.0,
    }
)


class TestParseCommand:
    def test_on_off_status(self):
        assert parse_command("/tunnel on") == "tunnel_on"
        assert parse_command("/tunnel off") == "tunnel_off"
        assert parse_command("/tunnel status") == "tunnel_status"

    def test_bare_tunnel_is_status(self):
        assert parse_command("/tunnel") == "tunnel_status"

    def test_group_chat_bot_suffix(self):
        assert parse_command("/tunnel@my_guru_bot on") == "tunnel_on"
        assert parse_command("/TUNNEL ON") == "tunnel_on"

    def test_help_and_start(self):
        assert parse_command("/help") == "help"
        assert parse_command("/start") == "help"

    def test_status_command(self):
        assert parse_command("/status") == "status"
        assert parse_command("/status@my_guru_bot") == "status"

    def test_unknown_returns_none(self):
        assert parse_command("/tunnel reboot") is None
        assert parse_command("hello") is None
        assert parse_command("") is None
        assert parse_command(None) is None


class TestConfigParsing:
    def test_valid_enabled_config(self):
        cfg = load_parent_telegram_config(CFG_JSON)
        assert cfg == {"bot_token": "123:ABC", "chat_id": "555000111"}

    def test_disabled_or_incomplete_rejected(self):
        disabled = json.loads(CFG_JSON)
        disabled["enabled"] = False
        assert load_parent_telegram_config(json.dumps(disabled)) is None
        assert load_parent_telegram_config('{"bot_token":"","chat_id":"1","enabled":true}') is None
        assert load_parent_telegram_config("not-json{") is None
        assert load_parent_telegram_config(None) is None


class TestAuthorization:
    def setup_method(self):
        self.cfg = load_parent_telegram_config(CFG_JSON)

    def test_exact_chat_matches(self):
        assert is_authorized_chat(555000111, self.cfg)
        assert is_authorized_chat("555000111", self.cfg)

    def test_any_other_chat_denied(self):
        assert not is_authorized_chat(999999999, self.cfg)
        assert not is_authorized_chat(None, self.cfg)
        # Suffix/prefix games must never match.
        assert not is_authorized_chat("1555000111", self.cfg)
