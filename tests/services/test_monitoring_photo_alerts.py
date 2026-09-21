"""Tests for Telegram photo alerts: sendPhoto, outbox photo routing, tiering."""

import base64
from unittest.mock import patch

import pytest

from deeptutor.services.monitoring.dispatch import _persist_severity, handle_warning
from deeptutor.services.remote.telegram_notifier import TelegramNotifier

pytestmark = pytest.mark.asyncio


_FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"x" * 512  # JPEG SOI + payload
_FAKE_JPEG_B64 = base64.b64encode(_FAKE_JPEG).decode("ascii")


class _FakeResp:
    status = 200

    async def text(self):
        return "ok"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeSession:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def post(self, url, data=None, json=None):
        _FakeSession.calls.append({"url": url, "data": data, "json": json})
        return _FakeResp()


@pytest.fixture()
def fake_session():
    _FakeSession.calls = []
    with patch("deeptutor.services.remote.telegram_notifier.aiohttp.ClientSession", _FakeSession):
        yield _FakeSession.calls


class TestTelegramSendPhoto:
    async def test_send_photo_posts_multipart(self, fake_session):
        ok = await TelegramNotifier.send_photo(
            bot_token="TOK", chat_id="42", photo_bytes=_FAKE_JPEG, caption="<b>Alert</b>"
        )
        assert ok is True
        assert len(fake_session) == 1
        call = fake_session[0]
        assert call["url"].endswith("/sendPhoto")
        assert call["url"].startswith("https://api.telegram.org/botTOK/")
        form = call["data"]
        assert form is not None  # multipart FormData, not a JSON body

    async def test_send_photo_requires_arguments(self, fake_session):
        assert await TelegramNotifier.send_photo("TOK", "42", b"") is False
        assert await TelegramNotifier.send_photo("", "42", _FAKE_JPEG) is False
        assert len(fake_session) == 0

    async def test_send_message_still_json(self, fake_session):
        ok = await TelegramNotifier.send_message(bot_token="TOK", chat_id="42", text="hi")
        assert ok is True
        assert fake_session[0]["url"].endswith("/sendMessage")
        assert fake_session[0]["json"]["text"] == "hi"


class TestDispatchTierPolicy:
    def test_persist_severity_mapping(self):
        assert _persist_severity("nudge") == "info"
        assert _persist_severity("alert") == "alert"
        assert _persist_severity("warning") == "warning"
        assert _persist_severity("bogus") == "warning"

    async def test_nudge_skips_telegram_entirely(self, fake_session, monkeypatch, tmp_path):
        enqueued = {}

        async def fake_enqueue(kind, payload):
            enqueued["kind"] = kind
            enqueued["payload"] = payload
            return 1

        import deeptutor.services.monitoring.dispatch as dispatch_mod

        monkeypatch.setattr(
            "deeptutor.services.monitoring.notification_queue.enqueue", fake_enqueue
        )
        monkeypatch.setattr(
            "deeptutor.services.monitoring.notification_queue.start_notification_worker",
            lambda: None,
        )

        # TelemetryLogger writes to the real user DB — stub it out.
        class _FakeLogger:
            async def log_event(self, **kwargs):
                return True

        monkeypatch.setattr(
            "deeptutor.services.study.telemetry_logger.TelemetryLogger",
            _FakeLogger,
        )

        await handle_warning(
            session_id="s-nudge",
            warning={
                "category": "LOOKING_AWAY",
                "message": "Quick focus check",
                "severity": "nudge",
                "confidence": 0.9,
                "duration_seconds": 4.0,
                "warning_id": "nudge-x",
            },
            current_frame_b64=_FAKE_JPEG_B64,
            photo_jpeg_b64=_FAKE_JPEG_B64,
        )
        # Nudge must NOT reach the parent queue even though a photo was offered.
        assert "kind" not in enqueued

    async def test_alert_carries_photo_in_payload(self, fake_session, monkeypatch):
        enqueued = {}

        async def fake_enqueue(kind, payload, *args, **kwargs):
            enqueued["payload"] = payload
            return 1

        monkeypatch.setattr(
            "deeptutor.services.monitoring.notification_queue.enqueue_for_student", fake_enqueue
        )
        monkeypatch.setattr(
            "deeptutor.services.monitoring.notification_queue.enqueue", fake_enqueue
        )
        monkeypatch.setattr(
            "deeptutor.services.monitoring.notification_queue.start_notification_worker",
            lambda: None,
        )

        class _FakeLoop:
            pass

        class _FakeLogger:
            async def log_event(self, **kwargs):
                return True

        monkeypatch.setattr(
            "deeptutor.services.study.telemetry_logger.TelemetryLogger", _FakeLogger
        )

        await handle_warning(
            session_id="s-alert",
            warning={
                "category": "PHONE_DETECTED",
                "message": "Phone detected",
                "severity": "alert",
                "confidence": 0.95,
                "duration_seconds": 6.0,
                "warning_id": "warn-x",
            },
            current_frame_b64=_FAKE_JPEG_B64,
            photo_jpeg_b64=_FAKE_JPEG_B64,
        )
        assert enqueued["payload"]["photo_b64"] == _FAKE_JPEG_B64

    async def test_warning_has_no_photo(self, fake_session, monkeypatch):
        enqueued = {}

        async def fake_enqueue(kind, payload, *args, **kwargs):
            enqueued["payload"] = payload
            return 1

        monkeypatch.setattr(
            "deeptutor.services.monitoring.notification_queue.enqueue_for_student", fake_enqueue
        )
        monkeypatch.setattr(
            "deeptutor.services.monitoring.notification_queue.enqueue", fake_enqueue
        )
        monkeypatch.setattr(
            "deeptutor.services.monitoring.notification_queue.start_notification_worker",
            lambda: None,
        )

        class _FakeLogger:
            async def log_event(self, **kwargs):
                return True

        monkeypatch.setattr(
            "deeptutor.services.study.telemetry_logger.TelemetryLogger", _FakeLogger
        )

        await handle_warning(
            session_id="s-warn",
            warning={
                "category": "LOOKING_AWAY",
                "message": "Looked away",
                "severity": "warning",
                "confidence": 0.9,
                "duration_seconds": 12.0,
                "warning_id": "warn-y",
            },
            current_frame_b64=_FAKE_JPEG_B64,
            photo_jpeg_b64=_FAKE_JPEG_B64,
        )
        assert "photo_b64" not in enqueued["payload"]


class TestPhotoAlertOptIn:
    async def test_photos_disabled_by_default_sends_text_only(self, monkeypatch):
        import deeptutor.services.monitoring.notification_queue as nq
        from deeptutor.services.remote.telegram_config import TelegramConfigStore
        from deeptutor.services.remote.telegram_notifier import TelegramNotifier

        messages = []
        photos = []

        async def fake_msg(bot_token, chat_id, text, **kwargs):
            messages.append({"bot_token": bot_token, "chat_id": chat_id, "text": text})
            return True

        async def fake_photo(bot_token, chat_id, photo_bytes, caption, **kwargs):
            photos.append({"bot_token": bot_token, "chat_id": chat_id, "photo_bytes": photo_bytes})
            return True

        monkeypatch.setattr(TelegramNotifier, "send_message", fake_msg)
        monkeypatch.setattr(TelegramNotifier, "send_photo", fake_photo)
        async def fake_load_off(parent):
            return {"bot_token": "T", "chat_id": "C"}
        monkeypatch.setattr(nq, "_load_telegram_config", fake_load_off)
        async def fake_photo_opt_in_off(parent):
            return False
        monkeypatch.setattr(TelegramConfigStore, "is_photo_enabled", fake_photo_opt_in_off)

        payload = {
            "category": "PHONE_DETECTED",
            "message": "Phone in hand",
            "severity": "alert",
            "confidence": 0.95,
            "duration_seconds": 5.0,
            "photo_b64": _FAKE_JPEG_B64,
        }
        await nq.enqueue("warning", payload, parent_id="default")
        sent = await nq.flush_once(limit=1)
        assert sent == 1
        assert len(photos) == 0  # No photo sent!
        assert len(messages) == 1  # Text only!

    async def test_photos_opted_in_sends_photo(self, monkeypatch):
        import deeptutor.services.monitoring.notification_queue as nq
        from deeptutor.services.remote.telegram_config import TelegramConfigStore
        from deeptutor.services.remote.telegram_notifier import TelegramNotifier

        photos = []

        async def fake_photo(bot_token, chat_id, photo_bytes, caption, **kwargs):
            photos.append({"bot_token": bot_token, "chat_id": chat_id, "photo_bytes": photo_bytes})
            return True

        monkeypatch.setattr(TelegramNotifier, "send_photo", fake_photo)
        async def fake_load(parent):
            return {"bot_token": "T", "chat_id": "C"}
        monkeypatch.setattr(nq, "_load_telegram_config", fake_load)
        async def fake_photo_opt_in(parent):
            return True
        monkeypatch.setattr(TelegramConfigStore, "is_photo_enabled", fake_photo_opt_in)

        payload = {
            "category": "PHONE_DETECTED",
            "message": "Phone in hand",
            "severity": "alert",
            "confidence": 0.95,
            "duration_seconds": 5.0,
            "photo_b64": _FAKE_JPEG_B64,
        }
        await nq.enqueue("warning", payload, parent_id="default")
        sent = await nq.flush_once(limit=1)
        assert sent == 1
        assert len(photos) == 1  # Photo sent because parent opted in!

