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

    def test_boostalert_commands(self):
        assert parse_command("/boostalert") == "boostalert_status"
        assert parse_command("/boostalert status") == "boostalert_status"
        assert parse_command("/boostalert test") == "boostalert_test"
        assert parse_command("/boostalert strict") == "boostalert_strict"
        assert parse_command("/boostalert strict 30") == "boostalert_strict:30"
        assert parse_command("/boostalert strict 30m") == "boostalert_strict:30"
        assert parse_command("/boostalert strict 30mins") == "boostalert_strict:30"
        assert parse_command("/boostalert 45") == "boostalert_strict:45"
        assert parse_command("/boostalert 45m") == "boostalert_strict:45"
        assert parse_command("/boostalert off") == "boostalert_off"
        assert parse_command("/boostalert balanced") == "boostalert_off"
        assert parse_command("/boostalert@my_guru_bot strict 45") == "boostalert_strict:45"
        assert parse_command("/BOOSTALERT STRICT 15") == "boostalert_strict:15"

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


class TestParentBotMenu:
    def test_menu_commands_shape(self):
        from deeptutor.services.remote.telegram_notifier import TelegramNotifier

        names = [c["command"] for c in TelegramNotifier.PARENT_BOT_COMMANDS]
        assert names == ["status", "tunnel", "live", "boostalert", "help"]
        for cmd in TelegramNotifier.PARENT_BOT_COMMANDS:
            assert cmd["command"] and cmd["description"]

    def test_set_bot_commands_posts_menu(self, monkeypatch):
        import asyncio

        from deeptutor.services.remote.telegram_notifier import TelegramNotifier

        posted = {}

        class _FakeResp:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def text(self):
                return '{"ok": true}'

        class _FakeSession:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def post(self, url, json=None):
                posted["url"] = url
                posted["json"] = json
                return _FakeResp()

        import deeptutor.services.remote.telegram_notifier as tn

        monkeypatch.setattr(tn.aiohttp, "ClientSession", _FakeSession)
        assert asyncio.run(TelegramNotifier.set_bot_commands("123:ABC")) is True
        assert posted["url"].endswith("/setMyCommands")
        assert [c["command"] for c in posted["json"]["commands"]] == [
            "status",
            "tunnel",
            "live",
            "boostalert",
            "help",
        ]

    def test_set_bot_commands_blank_token_never_calls_api(self, monkeypatch):
        import asyncio

        from deeptutor.services.remote.telegram_notifier import TelegramNotifier

        called = []

        class _FakeSession:
            def __init__(self, *a, **k):
                called.append(True)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        import deeptutor.services.remote.telegram_notifier as tn

        monkeypatch.setattr(tn.aiohttp, "ClientSession", _FakeSession)
        assert asyncio.run(TelegramNotifier.set_bot_commands("")) is False
        assert asyncio.run(TelegramNotifier.set_bot_commands("   ")) is False
        assert called == []

    def test_ensure_menu_dedupes_per_token(self, monkeypatch):
        import asyncio

        import deeptutor.services.remote.telegram_command_listener as tcl

        calls = []

        async def _fake_set(token):
            calls.append(token)
            return True

        monkeypatch.setattr(
            tcl.TelegramNotifier, "set_bot_commands", staticmethod(_fake_set)
        )
        tcl._commands_registered.clear()
        cfg = {"bot_token": "TOK123", "chat_id": "1"}
        assert asyncio.run(tcl.ensure_parent_bot_commands(cfg)) is True
        assert asyncio.run(tcl.ensure_parent_bot_commands(cfg)) is True
        assert calls == ["TOK123"]

    def test_ensure_menu_failure_is_falsy_not_raise(self, monkeypatch):
        import asyncio

        import deeptutor.services.remote.telegram_command_listener as tcl

        async def _boom(token):
            raise RuntimeError("offline")

        monkeypatch.setattr(tcl.TelegramNotifier, "set_bot_commands", staticmethod(_boom))
        tcl._commands_registered.clear()
        assert asyncio.run(tcl.ensure_parent_bot_commands({"bot_token": "T", "chat_id": "1"})) is False

    def test_strict_minutes_capped_at_action(self):
        import asyncio

        import deeptutor.services.remote.telegram_command_listener as tcl

        # 99999m clamps to 720 instead of persisting a near-permanent boost.
        reply = asyncio.run(
            tcl._run_boostalert_action("boostalert_strict:99999", chat_id="555000111")
        )
        assert "720 minutes" in reply
        assert tcl._boost_for("default")["duration_minutes"] == 720
        asyncio.run(tcl._run_boostalert_action("boostalert_off", chat_id="555000111"))

    def test_status_idle_disclaimer(self):
        import asyncio

        import deeptutor.services.remote.telegram_command_listener as tcl

        asyncio.run(tcl._run_boostalert_action("boostalert_off", chat_id="555000111"))
        reply = asyncio.run(tcl._run_boostalert_action("boostalert_status", chat_id="555000111"))
        assert "Alert & Supervision Status" in reply
        # No live session/monitors in test env → must say thresholds are configured, not live.
        assert "No live session" in reply

    def test_status_reply_is_status_only(self):
        import asyncio

        from deeptutor.services.remote import tunnel_gateway as tg_mod
        import deeptutor.services.remote.telegram_command_listener as tcl

        tg_mod.TunnelGateway._tunnel_url = None
        tg_mod.TunnelGateway._status = "inactive"
        tg_mod.TunnelGateway._url_is_public = False
        reply = asyncio.run(tcl._status_reply())
        assert "not running" in reply
        assert "/tunnel on" in reply


class TestTunnelStartReplies:
    def test_local_only_is_explicit(self, monkeypatch):
        import asyncio

        from deeptutor.services.remote import tunnel_gateway as tg_mod
        import deeptutor.services.remote.telegram_command_listener as tcl

        async def _local_only(**kwargs):
            return {
                "status": "local_only",
                "url": "http://127.0.0.1:3782",
                "provider": "local",
                "url_is_public": False,
                "message": "Tunnel gateway not available on this machine.",
            }

        monkeypatch.setattr(
            tg_mod.TunnelGateway, "start_tunnel", classmethod(lambda cls, **k: _local_only(**k))
        )
        reply = asyncio.run(tcl._run_tunnel_action("tunnel_on", chat_id="1"))
        assert "local-only" in reply
        assert "cloudflared" in reply

    def test_error_surfaces_provider_and_port(self, monkeypatch):
        import asyncio

        from deeptutor.services.remote import tunnel_gateway as tg_mod
        import deeptutor.services.remote.telegram_command_listener as tcl

        async def _err(**kwargs):
            return {
                "status": "error",
                "url": None,
                "provider": "cloudflare",
                "url_is_public": False,
                "message": "Download failed: HTTP 403",
            }

        monkeypatch.setattr(
            tg_mod.TunnelGateway, "start_tunnel", classmethod(lambda cls, **k: _err(**k))
        )
        reply = asyncio.run(tcl._run_tunnel_action("tunnel_on", chat_id="1"))
        assert "Could not start the tunnel" in reply
        assert "HTTP 403" in reply

    def test_slow_start_backgrounds_and_notifies(self, monkeypatch):
        import asyncio

        from deeptutor.services.remote import tunnel_gateway as tg_mod
        import deeptutor.services.remote.telegram_command_listener as tcl

        async def _slow(**kwargs):
            await asyncio.sleep(0.3)
            return {
                "status": "active",
                "url": "https://demo.trycloudflare.com",
                "provider": "cloudflare",
                "url_is_public": True,
            }

        monkeypatch.setattr(
            tg_mod.TunnelGateway, "start_tunnel", classmethod(lambda cls, **k: _slow(**k))
        )
        monkeypatch.setattr(tcl, "_TUNNEL_START_WAIT_S", 0.01)
        sent = []

        async def _fake_send(chat_id, text):
            sent.append((chat_id, text))

        monkeypatch.setattr(tcl, "_send_to_chat", _fake_send)

        async def _scenario():
            reply = await tcl._run_tunnel_action("tunnel_on", chat_id="1")
            await asyncio.sleep(0.6)
            return reply

        reply = asyncio.run(_scenario())
        assert "background" in reply.lower()
        assert sent and "demo.trycloudflare.com/parent" in sent[0][1]


class TestLivePairingGuard:
    def test_no_session_idle(self):
        import asyncio

        import deeptutor.services.remote.telegram_command_listener as tcl

        reply = asyncio.run(tcl._run_live_action("live_stream", chat_id="1", parent_id="default"))
        assert "No active study session" in reply

    def test_resolve_empty_is_none(self):
        import asyncio

        import deeptutor.services.remote.telegram_command_listener as tcl

        assert asyncio.run(tcl._resolve_allowed_session([], "default")) is None

    def test_resolve_no_links_picks_first(self):
        import asyncio

        import deeptutor.services.remote.telegram_command_listener as tcl

        assert asyncio.run(tcl._resolve_allowed_session(["s1", "s2"], "default")) == "s1"


class TestSameTokenWarning:
    def test_detects_partner_token_clash(self, tmp_path):
        from deeptutor.api.routers.parent import _find_partner_using_token

        partner_dir = tmp_path / "guru"
        partner_dir.mkdir()
        (partner_dir / "config.yaml").write_text(
            "name: Guru\nchannels:\n  telegram:\n    enabled: true\n    token: SECRET123\n",
            encoding="utf-8",
        )
        assert _find_partner_using_token("SECRET123", base_dir=tmp_path) == "Guru"
        assert _find_partner_using_token("OTHER", base_dir=tmp_path) == ""

    def test_disabled_partner_ignored(self, tmp_path):
        from deeptutor.api.routers.parent import _find_partner_using_token

        partner_dir = tmp_path / "guru"
        partner_dir.mkdir()
        (partner_dir / "config.yaml").write_text(
            "name: Guru\nchannels:\n  telegram:\n    enabled: false\n    token: SECRET123\n",
            encoding="utf-8",
        )
        assert _find_partner_using_token("SECRET123", base_dir=tmp_path) == ""
        assert _find_partner_using_token("", base_dir=tmp_path) == ""
