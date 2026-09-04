"""Telegram message-composition tests.

The outbox composes every parent notification through TelegramNotifier's
compose_* builders so alerts carry the live Parent Portal link (one-tap
access from the phone) plus real confidence/duration metrics. These tests
pin that contract: link present ONLY when the tunnel URL is actually
public, honest fallbacks otherwise, hostile text escaped.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.services.monitoring import notification_queue as nq
from deeptutor.services.remote.telegram_notifier import TelegramNotifier


@pytest.fixture()
def _gateway(monkeypatch):
    """Force TunnelGateway state without touching process/singletons."""
    from deeptutor.services.remote import tunnel_gateway as tg_mod

    state = {"url": None, "public": False}

    monkeypatch.setattr(
        tg_mod.TunnelGateway,
        "get_tunnel_url",
        classmethod(lambda cls: state["url"]),
    )
    monkeypatch.setattr(
        tg_mod.TunnelGateway,
        "is_url_public",
        classmethod(lambda cls: state["public"]),
    )
    return state


def _set_public(state, url="https://demo.trycloudflare.com"):
    state["url"] = url
    state["public"] = True


# ------------------------------------------------------------ portal links


class TestPortalLinksInComposedMessages:
    def test_warning_includes_link_when_tunnel_public(self, _gateway):
        _set_public(_gateway)
        msg = nq._compose_message(
            "warning",
            {
                "session_id": "sess-1",
                "category": "PHONE_DETECTED",
                "message": "Please put your phone aside to maintain deep focus! 📱",
                "severity": "alert",
                "confidence": 0.91,
                "duration_seconds": 4.2,
            },
        )
        assert "https://demo.trycloudflare.com/parent" in msg
        assert "Open Parent Portal" in msg
        assert "Confidence 91%" in msg
        assert "4s" in msg
        assert "Mobile Phone Detected" in msg

    def test_warning_has_no_link_when_local_only(self, _gateway):
        """LAN-only mode must never fabricate a public link."""
        msg = nq._compose_message(
            "warning",
            {
                "session_id": "sess-2",
                "category": "LOOKING_AWAY",
                "message": "refocus",
                "severity": "warning",
            },
        )
        assert "trycloudflare.com" not in msg
        assert "/parent" not in msg

    def test_notice_category_keeps_legacy_framing_plus_link(self, _gateway):
        _set_public(_gateway)
        msg = nq._compose_message(
            "warning",
            {
                "session_id": "sess-3",
                "category": "NOTICE",
                "message": "Session paused by student.",
                "severity": "info",
                "confidence": 0.5,
                "duration_seconds": 0,
            },
        )
        assert "AI Guru — Notice" in msg
        assert "Open Parent Portal" in msg

    def test_session_start_includes_link(self, _gateway):
        _set_public(_gateway)
        msg = nq._compose_message(
            "session_start",
            {
                "session_id": "sess-4",
                "student_name": "Aisha",
                "subject": "Mathematics",
                "target_minutes": 25,
            },
        )
        assert "Study Session Started" in msg
        assert "Aisha" in msg
        assert "https://demo.trycloudflare.com/parent" in msg

    def test_session_summary_includes_metrics_and_link(self, _gateway):
        _set_public(_gateway)
        msg = nq._compose_message(
            "session_summary",
            {
                "session_id": "sess-5",
                "student_id": "student-primary",
                "duration_minutes": 42.0,
                "focus_score": 87.3,
                "engagement_score": 81.0,
                "warning_count": 2,
                "summary": "Great persistence today.",
                "xp_earned": 95,
            },
        )
        assert "Study Session Completed" in msg
        assert "+95 XP" in msg
        assert "Engagement" in msg
        assert "Warnings" in msg
        assert "https://demo.trycloudflare.com/parent" in msg

    def test_hostile_details_are_escaped(self, _gateway):
        _set_public(_gateway)
        msg = nq._compose_message(
            "warning",
            {
                "session_id": "sess-6",
                "category": "PHONE_DETECTED",
                "message": "<script>alert(1)</script>",
                "severity": "alert",
            },
        )
        assert "<script>" not in msg
        assert "&lt;script&gt;" in msg


# ------------------------------------------------------------ composers


class TestComposerUnits:
    def test_alert_title_map_covers_dispatch_categories(self):
        for category in (
            "PHONE_DETECTED",
            "STUDENT_AWAY",
            "LOOKING_AWAY",
            "IDENTITY_MISMATCH",
            "DROWSINESS",
        ):
            title = TelegramNotifier._alert_title(category)
            assert "Study Alert:" not in title, f"{category} should map to a friendly title"

    def test_severity_picks_emoji(self):
        loud = TelegramNotifier.compose_distraction_alert("PHONE_DETECTED", severity="alert")
        soft = TelegramNotifier.compose_distraction_alert("STUDENT_AWAY", severity="info")
        assert loud.startswith("🚨")
        assert soft.startswith("ℹ️")

    def test_no_link_section_without_tunnel(self):
        msg = TelegramNotifier.compose_session_start("A", "B", 25, tunnel_url=None)
        assert "Open Parent Portal" not in msg

    def test_send_wrappers_still_send_composed_text(self, monkeypatch):
        captured = {}

        async def _fake_send(cls, bot_token, chat_id, text, **kwargs):
            captured["text"] = text
            return True

        monkeypatch.setattr(TelegramNotifier, "send_message", classmethod(_fake_send))

        import asyncio

        ok = asyncio.run(
            TelegramNotifier.send_session_start(
                "tok", "chat", "Aisha", "Physics", 30, "https://t.example"
            )
        )
        assert ok is True
        assert "Study Session Started" in captured["text"]
        assert "https://t.example/parent" in captured["text"]


# ------------------------------------------------------------ name resolver


class TestResolveStudentName:
    @pytest.mark.asyncio
    async def test_prefers_supervision_rules_name(self, tmp_path: Path):
        import aiosqlite

        from deeptutor.api.routers.study_session import _resolve_student_name
        from deeptutor.services.remote.kv_settings import ensure_kv_settings

        db_path = tmp_path / "chat_history.db"
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, category, updated_at)"
                " VALUES ('supervision_rules_default', ?, 'supervision', 0)",
                (json.dumps({"student_name": "Aisha"}),),
            )
            await db.commit()

        name = await _resolve_student_name("student-primary", db_path=db_path)
        assert name == "Aisha"

    @pytest.mark.asyncio
    async def test_falls_back_to_capitalized_id_tail(self, tmp_path: Path):
        import aiosqlite

        from deeptutor.api.routers.study_session import _resolve_student_name
        from deeptutor.services.remote.kv_settings import ensure_kv_settings

        db_path = tmp_path / "chat_history.db"
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)

        name = await _resolve_student_name("student-primary", db_path=db_path)
        assert name == "Primary"
