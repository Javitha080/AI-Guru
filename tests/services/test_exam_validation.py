"""Unit tests for input validation in the Exam Room / Hall and Gemini OCR pipeline."""

from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, UploadFile
from pydantic import ValidationError
import pytest

from deeptutor.api.routers.exams import AnswerSubmissionItem, SubmitAnswersRequest, _persist_upload
from deeptutor.services.exams.gemini_ocr import GeminiDiagram, _convert_question


@pytest.mark.asyncio
async def test_persist_upload_rejects_missing_pdf_header(tmp_path, monkeypatch):
    """Verify upload rejects file without %PDF- magic bytes."""
    from deeptutor.api.routers import exams

    monkeypatch.setattr(exams, "_workspace_dir", lambda: tmp_path)

    # File claiming to be .pdf but actually plaintext
    fake_file = UploadFile(filename="test.pdf", file=BytesIO(b"This is not a PDF file at all."))
    with pytest.raises(HTTPException) as exc_info:
        await _persist_upload(fake_file)
    assert exc_info.value.status_code == 422
    assert "missing %PDF- header" in exc_info.value.detail


@pytest.mark.asyncio
async def test_persist_upload_rejects_empty_file(tmp_path, monkeypatch):
    """Verify upload rejects 0-byte file."""
    from deeptutor.api.routers import exams

    monkeypatch.setattr(exams, "_workspace_dir", lambda: tmp_path)

    empty_file = UploadFile(filename="empty.pdf", file=BytesIO(b""))
    with pytest.raises(HTTPException) as exc_info:
        await _persist_upload(empty_file)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_persist_upload_accepts_valid_pdf_magic_bytes(tmp_path, monkeypatch):
    """Verify upload accepts file starting with %PDF- header."""
    from deeptutor.api.routers import exams

    monkeypatch.setattr(exams, "_workspace_dir", lambda: tmp_path)

    valid_file = UploadFile(filename="sample.pdf", file=BytesIO(b"%PDF-1.7\n1 0 obj..."))
    saved_path = await _persist_upload(valid_file)
    assert saved_path.exists()
    assert saved_path.suffix == ".pdf"


def test_submit_answers_request_validation():
    """Verify input validation on SubmitAnswersRequest and AnswerSubmissionItem."""
    # Valid submission
    req = SubmitAnswersRequest(
        student_id="student-1",
        answers=[AnswerSubmissionItem(question_id="q1", option_key="B", answer_text="text")],
    )
    assert req.student_id == "student-1"
    assert len(req.answers) == 1

    # Invalid student_id with illegal characters
    with pytest.raises(ValidationError):
        SubmitAnswersRequest(student_id="student; DROP TABLE students;--")

    # Invalid question_id (empty)
    with pytest.raises(ValidationError):
        AnswerSubmissionItem(question_id="")


def test_gemini_diagram_path_traversal_sanitization():
    """Verify GeminiDiagram sanitizes path traversal characters."""
    diagram = GeminiDiagram(
        id="d1",
        src="../../etc/passwd",
        alt="diagram",
        caption="caption",
    )
    # Sanitized to safe relative images/ folder
    assert ".." not in diagram.src
    assert diagram.src == "images/passwd"

    # Absolute path sanitized
    diagram2 = GeminiDiagram(
        id="d2",
        src="/var/log/secret.png",
        alt="diagram",
        caption="caption",
    )
    assert diagram2.src == "images/secret.png"


def test_convert_question_nan_inf_marks_sanitization():
    """Verify _convert_question sanitizes NaN and Infinity marks."""
    # NaN marks on choice -> reset to safe default (1.0)
    q_nan = _convert_question(
        {
            "id": "q1",
            "stem": "Test question",
            "marks": float("nan"),
            "question_type": "choice",
            "options": {"A": "1", "B": "2"},
        },
        fallback_number=1,
    )
    assert q_nan.marks == 1.0

    # Inf marks -> reset to safe default
    q_inf = _convert_question(
        {"id": "q2", "stem": "Test essay", "marks": float("inf"), "question_type": "written"},
        fallback_number=2,
    )
    assert q_inf.marks == 0.0

    # Negative marks on choice -> reset to safe default (1.0)
    q_neg = _convert_question(
        {
            "id": "q3",
            "stem": "Test choice",
            "marks": -5.0,
            "question_type": "choice",
            "options": {"A": "1", "B": "2"},
        },
        fallback_number=3,
    )
    assert q_neg.marks == 1.0

    # Extremely high marks clamped to 1000
    q_high = _convert_question(
        {"id": "q4", "stem": "Test high", "marks": 50000.0, "question_type": "written"},
        fallback_number=4,
    )
    assert q_high.marks == 1000.0
