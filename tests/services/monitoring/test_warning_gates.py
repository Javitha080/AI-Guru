"""User-friendly tests for warning throttling primitives.

In plain language:
- EpisodeGate: one notification per continuous distraction episode. A new
  notification is only allowed after the student recovers (focus returns).
- RateLimiter: at most N notifications per sliding time window, so a bad
  study day can never spam parents with hundreds of alerts.

These are the building blocks WarningManager relies on — testing them here
keeps failures small and messages readable.
"""

from __future__ import annotations

from deeptutor.services.monitoring.warning_gates import EpisodeGate, RateLimiter


class TestEpisodeGate:
    def test_first_episode_may_notify_after_mark(self):
        gate = EpisodeGate()
        gate.observe(True, "PHONE_DETECTED")
        assert gate.already_notified("PHONE_DETECTED") is False
        gate.mark_notified("PHONE_DETECTED")
        assert gate.already_notified("PHONE_DETECTED") is True

    def test_recovery_clears_episode_so_next_one_may_notify(self):
        """Student puts the phone away -> the next pickup is a new episode."""
        gate = EpisodeGate()
        gate.observe(True, "PHONE_DETECTED")
        gate.mark_notified("PHONE_DETECTED")
        gate.observe(False, "PHONE_DETECTED")  # focus recovered
        assert gate.already_notified("PHONE_DETECTED") is False

    def test_none_category_never_blocks(self):
        gate = EpisodeGate()
        gate.observe(True, "NONE")
        assert gate.already_notified("NONE") is False

    def test_categories_are_independent(self):
        """A phone warning must not suppress a looking-away warning."""
        gate = EpisodeGate()
        gate.observe(True, "PHONE_DETECTED")
        gate.mark_notified("PHONE_DETECTED")
        assert gate.already_notified("LOOKING_AWAY") is False

    def test_reset_disarms_everything(self):
        gate = EpisodeGate()
        gate.observe(True, "PHONE_DETECTED")
        gate.mark_notified("PHONE_DETECTED")
        gate.reset()
        assert gate.armed is False
        assert gate.already_notified("PHONE_DETECTED") is False


class TestRateLimiter:
    def test_allows_up_to_max_then_blocks(self):
        limiter = RateLimiter(max_events=5, window_seconds=600.0)
        for i in range(5):
            assert limiter.allow(float(i * 65)) is True, f"event {i} wrongly blocked"
        assert limiter.allow(5 * 65.0) is False, "6th event in window must be blocked"

    def test_window_slides_so_old_events_expire(self):
        """After 600s pass, the budget refills — alerts resume honestly."""
        limiter = RateLimiter(max_events=2, window_seconds=600.0)
        assert limiter.allow(0.0) is True
        assert limiter.allow(10.0) is True
        assert limiter.allow(20.0) is False
        assert limiter.allow(601.0) is True, "expired events should free budget"

    def test_reset_restores_full_budget(self):
        limiter = RateLimiter(max_events=1, window_seconds=600.0)
        assert limiter.allow(0.0) is True
        assert limiter.allow(1.0) is False
        limiter.reset()
        assert limiter.allow(2.0) is True
