"""Unit tests for boostalert systems and exam room monitoring integration."""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deeptutor.services.monitoring.cv_pipeline import LocalCVPipeline
from deeptutor.services.monitoring.distraction_analyzer import DistractionAnalyzer
from deeptutor.services.monitoring.monitoring_config import (
    perception_profile_for,
    strictness_for,
)
from deeptutor.services.monitoring.system_monitor import (
    apply_supervision_strictness,
    update_all_monitors_strictness,
)
from deeptutor.services.monitoring.warning_manager import WarningManager
from deeptutor.services.remote.telegram_command_listener import (
    _boost_state,
    _run_boostalert_action,
    parse_command,
)


class TestPerceptionThresholdProfiles:
    def test_perception_profiles(self):
        gentle = perception_profile_for("gentle")
        assert gentle.looking_away_seconds == 15.0
        assert gentle.phone_seconds == 6.0
        assert gentle.cooldown_seconds == 90.0
        assert gentle.min_confidence == 0.85

        balanced = perception_profile_for("balanced")
        assert balanced.looking_away_seconds == 10.0
        assert balanced.phone_seconds == 4.0
        assert balanced.cooldown_seconds == 60.0
        assert balanced.min_confidence == 0.80

        strict = perception_profile_for("strict")
        assert strict.looking_away_seconds == 5.0
        assert strict.phone_seconds == 2.0
        assert strict.cooldown_seconds == 30.0
        assert strict.min_confidence == 0.75

    def test_distraction_analyzer_apply_strictness(self):
        da = DistractionAnalyzer()
        assert da.looking_away_threshold == 10.0
        assert da.phone_detected_threshold == 4.0

        da.apply_strictness("strict")
        assert da.looking_away_threshold == 5.0
        assert da.phone_detected_threshold == 2.0
        assert da.identity_mismatch_threshold == 8.0
        assert da.drowsiness_threshold == 2.5
        assert da.current_profile == "strict"

        da.apply_strictness("gentle")
        assert da.looking_away_threshold == 15.0
        assert da.phone_detected_threshold == 6.0

    def test_warning_manager_apply_strictness(self):
        wm = WarningManager()
        assert wm.cooldown_seconds == 60.0
        assert wm.min_confidence == 0.80

        wm.apply_strictness("strict")
        assert wm.cooldown_seconds == 30.0
        assert wm.min_confidence == 0.75
        assert wm.nudge_cooldown_seconds == 20.0
        assert wm.nudge_min_confidence == 0.70
        assert wm.current_profile == "strict"


@pytest.mark.asyncio
class TestSupervisionStrictnessApplication:
    async def test_apply_supervision_strictness_override(self):
        pipe = LocalCVPipeline()
        await apply_supervision_strictness(pipe, profile_override="strict")

        assert getattr(pipe, "strictness_profile", None) == "strict"
        assert pipe.warning_manager.cooldown_seconds == 30.0
        assert pipe.warning_manager.min_confidence == 0.75
        assert pipe.distraction_analyzer.looking_away_threshold == 5.0
        assert pipe.distraction_analyzer.phone_detected_threshold == 2.0

    async def test_apply_supervision_strictness_exam_session_detection(self):
        pipe = LocalCVPipeline()
        # session_id starting with exam- automatically triggers strict profile
        await apply_supervision_strictness(pipe, session_id="exam-12345")

        assert getattr(pipe, "strictness_profile", None) == "strict"
        assert pipe.warning_manager.cooldown_seconds == 30.0
        assert pipe.distraction_analyzer.looking_away_threshold == 5.0


@pytest.mark.asyncio
class TestBoostAlertCommands:
    async def test_boostalert_status(self):
        reply = await _run_boostalert_action("boostalert_status", chat_id="555000111")
        assert "Alert & Supervision Status" in reply
        assert "Looking Away:" in reply
        assert "Phone Detected:" in reply

    async def test_boostalert_strict_and_off(self):
        reply = await _run_boostalert_action("boostalert_strict:45", chat_id="555000111")
        assert "Boosted to STRICT" in reply
        assert "45 minutes" in reply
        assert _boost_state["active"] is True
        assert _boost_state["duration_minutes"] == 45

        status_reply = await _run_boostalert_action("boostalert_status", chat_id="555000111")
        assert "STRICT" in status_reply
        assert "Boosted" in status_reply

        off_reply = await _run_boostalert_action("boostalert_off", chat_id="555000111")
        assert "Reset to Balanced" in off_reply
        assert _boost_state["active"] is False

    async def test_boostalert_test_command(self):
        reply = await _run_boostalert_action("boostalert_test", chat_id="555000111")
        assert "Alert System Verification" in reply
        assert "ONLINE & VERIFIED" in reply

    async def test_boostalert_multitenancy_parent_id(self):
        # parent_id updates both supervision_rules_{parent_id} and default
        reply = await _run_boostalert_action(
            "boostalert_strict:20", chat_id="555000111", parent_id="parent-alpha"
        )
        assert "Boosted to STRICT" in reply
        from deeptutor.services.remote.telegram_command_listener import _get_current_strictness

        curr = await _get_current_strictness(parent_id="parent-alpha")
        assert curr == "strict"

        # Revert with parent_id
        off_reply = await _run_boostalert_action(
            "boostalert_off", chat_id="555000111", parent_id="parent-alpha"
        )
        assert "Reset to Balanced" in off_reply
        curr_off = await _get_current_strictness(parent_id="parent-alpha")
        assert curr_off == "balanced"


@pytest.mark.asyncio
class TestExamStrictnessInvariantAndLifecycle:
    async def test_exam_session_immune_to_strictness_demotion(self):
        """Global strictness downgrade to 'balanced' or 'gentle' must NEVER relax an exam session."""
        pipe = LocalCVPipeline()
        # Even if profile_override='balanced' or 'gentle' is passed, an exam session stays 'strict'
        await apply_supervision_strictness(
            pipe, profile_override="balanced", session_id="exam-test-session"
        )
        assert getattr(pipe, "strictness_profile", None) == "strict"
        assert pipe.warning_manager.cooldown_seconds == 30.0
        assert pipe.distraction_analyzer.looking_away_threshold == 5.0

    async def test_drowsiness_threshold_evaluates(self):
        """Verify DistractionAnalyzer activates drowsiness alert when drowsy_dur exceeds threshold."""
        from deeptutor.services.monitoring.liveness_detector import LivenessResult
        from deeptutor.services.monitoring.pose_gaze import HeadPoseResult, PostureCategory
        from deeptutor.services.monitoring.presence_state_machine import PresenceState

        da = DistractionAnalyzer()
        da.apply_strictness("strict")
        assert da.DROWSINESS_THRESHOLD == 2.5

        pose = HeadPoseResult(
            yaw=0.0,
            pitch=0.0,
            roll=0.0,
            posture=PostureCategory.HEAD_CENTER,
            is_facing_screen=True,
            is_reading_writing_pose=False,
        )
        liveness = LivenessResult(
            is_live=True,
            confidence=0.99,
            blink_detected=False,
            ear=0.25,
            ear_variance=0.01,
            motion_score=0.5,
            texture_score=0.5,
            reason="Live face verified",
        )

        # 1. First sample: eyes closed (starts drowsiness timer, no premature alert)
        t0 = 1000.0
        res0 = da.analyze(
            timestamp=t0,
            presence_state=PresenceState.PRESENT,
            pose=pose,
            liveness=liveness,
            identity_match=True,
            eye_closure=0.8,
        )
        assert res0.is_distracted is False
        assert res0.distraction_type == "NONE"

        # 2. Advanced timestamp beyond strict DROWSINESS_THRESHOLD (2.5s)
        t1 = t0 + 3.0
        res1 = da.analyze(
            timestamp=t1,
            presence_state=PresenceState.PRESENT,
            pose=pose,
            liveness=liveness,
            identity_match=True,
            eye_closure=0.8,
        )
        assert res1.is_distracted is True
        assert res1.distraction_type == "DROWSINESS"
        assert res1.duration_seconds >= 2.5

    async def test_exam_room_lifecycle_integration(self):
        """Verify exam start creates study session, get returns session_id, and submit completes session."""
        from deeptutor.api.routers.exams import (
            SubmitAnswersRequest,
            get_exam,
            start_exam,
            submit_exam,
        )
        from deeptutor.services.exams.store import ExamStore
        from deeptutor.services.study.session_manager import StudySessionManager

        exam_id = f"test-exam-{int(time.time())}"
        paper_dict = {
            "exam_id": exam_id,
            "title": "Mathematics Final Exam",
            "status": "created",
            "questions": [
                {
                    "id": "q1",
                    "number": 1,
                    "question_type": "choice",
                    "text": "What is 5 x 5?",
                    "options": {"A": "20", "B": "25", "C": "30"},
                    "marks": 5,
                    "reference_answer": "B",
                    "explanation": "5*5=25",
                }
            ],
            "mcq_duration_seconds": 1800,
            "total_marks": 5,
        }
        await ExamStore.save_paper(paper_dict)

        # 1. Start exam
        start_res = await start_exam(exam_id=exam_id, student_id="student-primary")
        assert start_res["exam_id"] == exam_id
        session_id = start_res["session_id"]
        assert session_id is not None

        # Verify linked study session created
        sess = await StudySessionManager().get_session(session_id)
        assert sess is not None
        assert sess["status"] == "in_progress"
        assert "Exam:" in sess["title"]

        # 2. Get exam returns session_id
        exam_view = await get_exam(exam_id=exam_id)
        assert exam_view["session_id"] == session_id

        # 3. Submit exam
        submit_req = SubmitAnswersRequest(
            student_id="student-primary",
            answers=[{"question_id": "q1", "option_key": "B", "answer_text": ""}],
        )
        sub_res = await submit_exam(exam_id=exam_id, req=submit_req)
        assert sub_res["total_score"] == 5

        # Verify study session completed
        sess_after = await StudySessionManager().get_session(session_id)
        assert sess_after["status"] == "completed"
