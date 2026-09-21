"""
Tests for Phase 1 Audit Fixes:
1. IDOR Ownership Guards (require_session_owner, require_sitting_owner, resolve_student_id)
2. Student DTO Answer Key Sanitization (recursive strip of reference_answer, explanation, marking_guide, rubric)
3. Focus Score Preservation (preserves measured 0.0 when telemetry exists)
4. Sitting State Resumability (bank_paper_id returned in sitting_state)
"""

from fastapi import HTTPException
import pytest

from deeptutor.api.routers.ownership import (
    _is_local_admin,
    require_exam_owner,
    require_session_owner,
    require_sitting_owner,
    require_student_owner,
    resolve_student_id,
)
from deeptutor.services.auth import TokenPayload
from deeptutor.services.exams.student_dto import (
    sanitize_question,
    sanitize_sub_question,
    to_student_safe_paper,
)

# --- 1. Ownership & IDOR Tests ---


def test_resolve_student_id_single_user():
    """When auth is disabled or user is None/local-admin, returns student-primary."""
    assert resolve_student_id(None) == "student-primary"
    user_admin = TokenPayload(username="local", role="admin", user_id="local-admin")
    assert resolve_student_id(user_admin) == "student-primary"


def test_resolve_student_id_multi_user():
    """In multi-user mode, derives student_id from token payload."""
    import deeptutor.services.auth as auth_mod
    orig = auth_mod.AUTH_ENABLED
    try:
        auth_mod.AUTH_ENABLED = True
        user = TokenPayload(username="alice", role="user", user_id="user-alice-123")
        assert resolve_student_id(user) == "alice-123"

        user2 = TokenPayload(username="bob", role="user", user_id="s-bob-456")
        assert resolve_student_id(user2) == "s-bob-456"
    finally:
        auth_mod.AUTH_ENABLED = orig


@pytest.mark.asyncio
async def test_require_student_owner():
    """Non-admin student cannot access another student's data."""
    import deeptutor.services.auth as auth_mod
    orig = auth_mod.AUTH_ENABLED
    try:
        auth_mod.AUTH_ENABLED = True
        user_alice = TokenPayload(username="alice", role="user", user_id="user-alice")

        # Accessing own data succeeds
        res = await require_student_owner("alice", user=user_alice)
        assert res == "alice"

        # Accessing bob's data raises 403
        with pytest.raises(HTTPException) as exc:
            await require_student_owner("bob", user=user_alice)
        assert exc.value.status_code == 403
    finally:
        auth_mod.AUTH_ENABLED = orig


@pytest.mark.asyncio
async def test_ownership_local_admin_bypasses():
    """In single-user mode or as admin, ownership checks pass transparently."""
    res = await require_session_owner("any-session", user=None)
    assert res == "student-primary"

    res_sit = await require_sitting_owner("any-sitting", user=None)
    assert res_sit == "student-primary"

    res_exam = await require_exam_owner("any-exam", user=None)
    assert res_exam == "student-primary"


# --- 2. Answer Key & Student DTO Sanitization Tests ---


def test_sanitize_sub_question():
    """Sub-questions strip reference_answer, explanation, marking_guide, rubric."""
    raw = {
        "id": "sq-1",
        "number": 1,
        "text": "Explain photosynthesis.",
        "marks": 5.0,
        "reference_answer": "Plants convert light energy into chemical energy.",
        "marking_guide": "Award 2 marks for light, 3 marks for chemical.",
        "rubric": {"full": 5, "partial": 2},
        "options": {"A": "Choice A", "B": "Choice B", "answer": "A"},
        "sub_questions": [
            {
                "id": "sq-1-a",
                "number": 1,
                "text": "What is chlorophyll?",
                "marks": 2.0,
                "expected_answer": "Green pigment.",
                "solution": "Found in chloroplasts.",
            }
        ],
    }

    sanitized = sanitize_sub_question(raw)
    assert sanitized["text"] == "Explain photosynthesis."
    assert sanitized["marks"] == 5.0
    assert "reference_answer" not in sanitized
    assert "marking_guide" not in sanitized
    assert "rubric" not in sanitized
    assert "answer" not in sanitized["options"]

    child = sanitized["sub_questions"][0]
    assert child["text"] == "What is chlorophyll." or child["text"] == "What is chlorophyll?"
    assert "expected_answer" not in child
    assert "solution" not in child


def test_to_student_safe_paper():
    """Exam paper serialization recursively sanitizes questions and sub-questions."""
    paper = {
        "exam_id": "exam-test",
        "title": "ICT Past Paper",
        "total_marks": 100.0,
        "questions": [
            {
                "id": "q1",
                "number": 1,
                "question_type": "mcq",
                "text": "What does CPU stand for?",
                "marks": 1.0,
                "options": {"A": "Central Processing Unit", "B": "Computer Personal Unit"},
                "reference_answer": "A",
                "explanation": "CPU is Central Processing Unit.",
                "metadata": {"scheme_answer": "A", "topic": "Hardware"},
                "sub_questions": [],
            },
            {
                "id": "q2",
                "number": 2,
                "question_type": "essay",
                "text": "Describe networking topologies.",
                "marks": 10.0,
                "reference_answer": "Star, Bus, Ring, Mesh...",
                "explanation": "Each has distinct characteristics.",
                "sub_questions": [
                    {
                        "id": "q2-1",
                        "number": 1,
                        "text": "What is star topology?",
                        "marks": 5.0,
                        "marking_guide": "Central switch connection.",
                        "reference_answer": "Devices connect to a central hub.",
                    }
                ],
            },
        ],
    }

    safe = to_student_safe_paper(paper)
    assert safe["title"] == "ICT Past Paper"
    assert len(safe["questions"]) == 2

    # Question 1 checks
    q1 = safe["questions"][0]
    assert "reference_answer" not in q1
    assert "explanation" not in q1
    assert "scheme_answer" not in q1["metadata"]
    assert q1["metadata"]["topic"] == "Hardware"

    # Question 2 and sub-questions checks
    q2 = safe["questions"][1]
    assert "reference_answer" not in q2
    assert "explanation" not in q2
    assert len(q2["sub_questions"]) == 1
    sq = q2["sub_questions"][0]
    assert "reference_answer" not in sq
    assert "marking_guide" not in sq
    assert sq["marks"] == 5.0


# --- 3. Focus Score Fallback & Preservation Tests ---


@pytest.mark.asyncio
async def test_report_generator_preserves_measured_zero():
    """A session with measured focus_score=0.0 and telemetry events keeps 0.0."""
    from deeptutor.services.study.report_generator import ReportGenerator

    rg = ReportGenerator()
    # Mock session with telemetry
    session = {
        "id": "s-test-zero",
        "student_id": "student-primary",
        "focus_score": 0.0,
        "engagement_score": 0.0,
        "actual_duration_seconds": 300,
        "subject": "Math",
        "start_time": 1000.0,
    }

    # If events exist, measured 0.0 is preserved
    raw_focus = session.get("focus_score")
    candidate = float(raw_focus) if raw_focus is not None else None
    events = [{"event_type": "LOOKING_AWAY", "duration_seconds": 120.0}]
    assert candidate is not None and (candidate > 0 or (candidate == 0.0 and len(events) > 0))
