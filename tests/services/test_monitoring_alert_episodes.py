"""
Regression tests for the Telegram notification spam fixes (Aug 2026):

1. STUDENT_AWAY fired one identical "Study timer paused" ping per 60s cooldown
   expiry for the ENTIRE absence — now one notification per continuous episode
   (edge-triggered via WarningManager.observe_distraction_state).
2. The away distraction reported duration_seconds=0.0 on every frame — now it
   grows with the absence so warnings/reports can tell a 20s trip from a
   10-minute walkaway.
3. Session warning counts included info-severity presence pings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.monitoring.distraction_analyzer import (
    DistractionAnalysisResult,
    DistractionAnalyzer,
    DistractionType,
)
from deeptutor.services.monitoring.liveness_detector import LivenessResult
from deeptutor.services.monitoring.pose_gaze import HeadPoseResult, PostureCategory
from deeptutor.services.monitoring.presence_state_machine import PresenceState
from deeptutor.services.monitoring.warning_manager import WarningManager
from deeptutor.services.study import telemetry_logger as telemetry_module
from deeptutor.services.study.telemetry_logger import TelemetryLogger


@pytest.fixture()
def isolated_telemetry_db(tmp_path: Path):
    """Point the shared PathService at a temp user dir (repo-standard pattern)."""
    import sqlite3

    from deeptutor.services.database.schema import PRAGMAS, V1_SCHEMA_DDL
    from deeptutor.services.path_service import get_path_service

    service = get_path_service()
    original_root = service._project_root
    original_user_dir = service._user_data_dir
    service._project_root = tmp_path
    service._user_data_dir = tmp_path / "data" / "user"
    service._user_data_dir.mkdir(parents=True, exist_ok=True)
    db_path = service.user_dir / "chat_history.db"

    # Apply the real app schema so telemetry flush has its tables. FK pragma
    # stays off on this raw connection: the fixture only needs the events table.
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(PRAGMAS.split(";")[0] + ";")  # journal mode only
        conn.executescript(V1_SCHEMA_DDL)
        conn.commit()
    finally:
        conn.close()

    yield db_path
    service._project_root = original_root
    service._user_data_dir = original_user_dir


def _away_result(duration: float = 0.0) -> DistractionAnalysisResult:
    return DistractionAnalysisResult(
        is_distracted=True,
        distraction_type=DistractionType.STUDENT_AWAY,
        focus_score=0.0,
        confidence=0.98,
        duration_seconds=duration,
        reason="Student is away from study desk",
    )


def _present_pose() -> HeadPoseResult:
    return HeadPoseResult(
        yaw=0.0,
        pitch=0.0,
        roll=0.0,
        posture=PostureCategory.HEAD_CENTER,
        is_facing_screen=True,
        is_reading_writing_pose=False,
    )


def _live() -> LivenessResult:
    return LivenessResult(
        is_live=True,
        confidence=0.95,
        blink_detected=False,
        ear=0.30,
        ear_variance=0.01,
        motion_score=0.02,
        texture_score=120.0,
        reason="test fixture",
    )


class TestAwayEpisodeEdgeTriggering:
    """One notification per continuous absence, not one per cooldown expiry."""

    def test_away_pings_once_per_episode_not_every_cooldown(self):
        wm = WarningManager(cooldown_seconds=60.0, min_confidence=0.80)

        # Student leaves at t=0 and stays away for 11 minutes (~1 frame/s).
        # The old behavior produced ~11 identical Telegram pings.
        emitted = []
        for i in range(660):
            t = float(i)
            wm.observe_distraction_state(True, DistractionType.STUDENT_AWAY)
            event = wm.evaluate_and_dispatch(timestamp=t, distraction=_away_result(duration=t))
            if event is not None:
                emitted.append(event)

        assert len(emitted) == 1, f"expected exactly 1 away ping, got {len(emitted)}"
        assert emitted[0].severity == "info"

    def test_returning_student_rearms_the_away_notification(self):
        wm = WarningManager(cooldown_seconds=60.0, min_confidence=0.80)

        # First absence: 5 minutes away -> single ping.
        for i in range(300):
            wm.observe_distraction_state(True, DistractionType.STUDENT_AWAY)
            assert (
                wm.evaluate_and_dispatch(timestamp=float(i), distraction=_away_result(float(i)))
                is not None
            ) == (i == 0)

        # Student returns for 2 minutes (focused frames clear the episode)...
        for _ in range(300, 420):
            wm.observe_distraction_state(False, None)

        # ...then leaves again AFTER the cooldown has already expired. The
        # second absence must notify again despite no cooldown reset.
        t_second_absence = 420.0
        wm.observe_distraction_state(True, DistractionType.STUDENT_AWAY)
        event = wm.evaluate_and_dispatch(
            timestamp=t_second_absence, distraction=_away_result(0.0)
        )
        assert event is not None, "a NEW absence episode must notify again"

    def test_bare_evaluate_callers_keep_legacy_cooldown_semantics(self):
        """Callers that never observe() get the classic cooldown-only behaviour."""
        wm = WarningManager(cooldown_seconds=60.0, min_confidence=0.80)
        first = wm.evaluate_and_dispatch(timestamp=0.0, distraction=_away_result())
        assert first is not None
        second = wm.evaluate_and_dispatch(timestamp=65.0, distraction=_away_result())
        assert second is not None, "cooldown-only mode re-issues after expiry"
        third = wm.evaluate_and_dispatch(timestamp=130.0, distraction=_away_result())
        assert third is not None


class TestAwayDurationTracking:
    """The analyzer must report how long the student has been away."""

    def _analyze(self, analyzer: DistractionAnalyzer, timestamp: float, present: bool = False):
        return analyzer.analyze(
            timestamp=timestamp,
            presence_state=PresenceState.PRESENT if present else PresenceState.AWAY,
            pose=_present_pose(),
            liveness=_live(),
            identity_match=True,
        )

    def test_away_duration_grows_across_frames(self):
        analyzer = DistractionAnalyzer()
        first = self._analyze(analyzer, timestamp=100.0)
        assert first.distraction_type == DistractionType.STUDENT_AWAY
        assert first.duration_seconds == 0.0

        mid = self._analyze(analyzer, timestamp=190.0)
        assert mid.duration_seconds == pytest.approx(90.0, abs=0.1)

        later = self._analyze(analyzer, timestamp=700.0)
        assert later.duration_seconds == pytest.approx(600.0, abs=0.1)

    def test_returning_resets_the_away_timer(self):
        analyzer = DistractionAnalyzer()
        self._analyze(analyzer, timestamp=100.0)
        self._analyze(analyzer, timestamp=160.0)

        # Present again — resets the internal away timer.
        self._analyze(analyzer, timestamp=200.0, present=True)

        back_away = self._analyze(analyzer, timestamp=205.0)
        assert back_away.duration_seconds == 0.0, "new absence starts from zero"


class TestSeverityAwareWarningCounts:
    """Info-level presence pings must not count as session warnings."""

    @pytest.mark.asyncio
    async def test_summary_splits_actionable_warnings_from_info_pings(
        self, isolated_telemetry_db
    ):
        logger = TelemetryLogger()

        events = [
            ("WARNING_ISSUED", "info", 0.98),
            ("WARNING_ISSUED", "info", 0.98),
            ("WARNING_ISSUED", "warning", 0.88),
            ("WARNING_ISSUED", "alert", 0.92),
            ("PRESENCE_CHANGE", "info", 0.90),
        ]
        for etype, sev, conf in events:
            await logger.log_event(
                session_id="sev-test-session",
                event_type=etype,
                severity=sev,
                confidence=conf,
                duration_seconds=1.0,
                metadata={},
            )
        await telemetry_module.flush()  # drain the batched writer synchronously

        summary = await logger.get_session_summary("sev-test-session")
        assert isolated_telemetry_db.exists(), "telemetry must land in the isolated db"
        assert summary["by_type"]["WARNING_ISSUED"] == 4
        assert summary["by_severity"]["info"] == 3
        assert summary["by_severity"]["warning"] == 1
        assert summary["by_severity"]["alert"] == 1
        assert summary["actionable_warnings"] == 2, "only warning+alert count"


def test_observe_then_reset_clears_episode_state():
    wm = WarningManager(cooldown_seconds=60.0, min_confidence=0.80)
    wm.observe_distraction_state(True, DistractionType.STUDENT_AWAY)
    assert wm.evaluate_and_dispatch(timestamp=0.0, distraction=_away_result()) is not None
    assert wm.evaluate_and_dispatch(timestamp=61.0, distraction=_away_result()) is None

    wm.reset()
    # After reset the manager behaves like a fresh instance.
    assert wm.evaluate_and_dispatch(timestamp=1000.0, distraction=_away_result()) is not None
