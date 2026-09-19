"""User-friendly tests for monitoring score accumulation.

In plain language:
- ScoreAccumulator keeps the running average of focus/engagement across
  video frames, so the parent dashboard shows real measured means.
- EpisodeTracker counts each continuous distraction only once (edge
  triggered): staring at a phone for a minute is ONE episode, and putting
  the phone away resets the trigger for next time.
"""

from __future__ import annotations

import pytest

from deeptutor.services.monitoring.session_scores import EpisodeTracker, ScoreAccumulator


class TestScoreAccumulator:
    def test_empty_accumulator_returns_honest_fallback_not_fake_data(self):
        acc = ScoreAccumulator()
        assert acc.mean_focus() == 0.0
        assert acc.mean_engagement() == 0.0
        assert acc.mean_focus(fallback=50.0) == 50.0

    def test_means_are_true_averages_of_added_frames(self):
        acc = ScoreAccumulator()
        acc.add_frame(80.0, 90.0)
        acc.add_frame(100.0, 70.0)
        assert acc.mean_focus() == pytest.approx(90.0)
        assert acc.mean_engagement() == pytest.approx(80.0)
        assert acc.ticks == 2

    def test_reset_clears_everything(self):
        acc = ScoreAccumulator()
        acc.add_frame(80.0, 80.0)
        acc.distraction_count = 3
        acc.warning_count = 1
        acc.reset()
        assert acc.ticks == 0
        assert acc.mean_focus() == 0.0
        assert acc.distraction_count == 0
        assert acc.warning_count == 0


class TestEpisodeTracker:
    def test_continuous_distraction_counts_exactly_once(self):
        tracker = EpisodeTracker()
        assert tracker.on_frame(True, "PHONE_DETECTED") is True
        assert tracker.on_frame(True, "PHONE_DETECTED") is False
        assert tracker.on_frame(True, "PHONE_DETECTED") is False
        assert tracker.distraction_count == 1

    def test_recovery_rearms_the_trigger(self):
        tracker = EpisodeTracker()
        assert tracker.on_frame(True, "LOOKING_AWAY") is True
        assert tracker.on_frame(False, None) is False  # student refocused
        assert tracker.on_frame(True, "LOOKING_AWAY") is True
        assert tracker.distraction_count == 2

    def test_different_types_count_separately(self):
        tracker = EpisodeTracker()
        assert tracker.on_frame(True, "PHONE_DETECTED") is True
        assert tracker.on_frame(True, "LOOKING_AWAY") is True
        assert tracker.distraction_count == 2

    def test_reset_clears_active_and_count(self):
        tracker = EpisodeTracker()
        tracker.on_frame(True, "PHONE_DETECTED")
        tracker.reset()
        assert tracker.distraction_count == 0
        assert tracker.on_frame(True, "PHONE_DETECTED") is True
