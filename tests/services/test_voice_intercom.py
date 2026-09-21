"""Unit tests for the parent voice drop-in service (in-memory, no DB)."""

from __future__ import annotations

from deeptutor.services.monitoring import voice_intercom as voice


def setup_function(_):
    voice.reset_for_tests()


def test_valid_session_id_rejects_bad_input():
    assert voice.valid_session_id("abc-123_XY")
    assert not voice.valid_session_id("")
    assert not voice.valid_session_id("a" * 200)
    assert not voice.valid_session_id("../../etc")
    assert not voice.valid_session_id(None)  # type: ignore[arg-type]


def test_start_and_active_call():
    call = voice.start_call("sess-1", "default", "student-primary")
    assert voice.is_call_active("sess-1")
    data = voice.call_to_dict(call)
    assert data["active"] is True
    assert data["seconds_left"] > 0
    assert data["call_id"] == call.call_id


def test_cooldown_blocks_immediate_recall():
    voice.start_call("sess-2", "default")
    voice.end_call("sess-2", "parent_ended")
    ok, reason = voice.check_rate_limit("sess-2")
    assert not ok
    assert "cooldown" in reason


def test_signal_relay_parent_to_student():
    voice.start_call("sess-3", "default")
    assert voice.push_signal("sess-3", "parent", "offer", "fake-sdp")
    inbox = voice.drain_signals("sess-3", "student")
    assert len(inbox) == 1
    assert inbox[0]["type"] == "offer"
    # Drained — second read is empty.
    assert voice.drain_signals("sess-3", "student") == []


def test_signal_rejects_invalid():
    assert not voice.push_signal("sess-4", "parent", "video-offer", "x")
    assert not voice.push_signal("sess-4", "intruder", "offer", "x")
    assert not voice.push_signal("bad id!!", "parent", "offer", "x")
    assert not voice.push_signal("sess-4", "parent", "offer", "x" * 20000)


def test_announcement_roundtrip_and_empty_rejected():
    assert voice.push_announcement("sess-5", "default", "") is None
    item = voice.push_announcement("sess-5", "default", "  Dinner in 10  ")
    assert item and item["text"] == "Dinner in 10"
    items = voice.drain_announcements("sess-5")
    assert len(items) == 1
    assert voice.drain_announcements("sess-5") == []


def test_bye_ends_call():
    voice.start_call("sess-6", "default")
    voice.push_signal("sess-6", "parent", "bye", "ended")
    assert not voice.is_call_active("sess-6")


def test_rate_limit_caps_burst():
    now = voice._now()
    # 5 starts inside the window, oldest beyond cooldown so the
    # per-window cap (not cooldown) is what blocks the 6th.
    voice._call_starts["sess-7"] = [now - 500, now - 400, now - 300, now - 200, now - 100]
    ok, reason = voice.check_rate_limit("sess-7")
    assert not ok
    assert reason == "rate_limited"
