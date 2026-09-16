"""Unit tests for Gemini AI OCR pipeline and fallback behavior."""

from unittest.mock import patch

import pytest

from deeptutor.services.exams.engine import ExamPaper, ExamQuestion
from deeptutor.services.exams.gemini_ocr import (
    GeminiDiagram,
    GeminiExamPaper,
    GeminiQuestionItem,
    GeminiSubQuestion,
    _gemini_data_to_exam_paper,
    gemini_available,
)


def test_gemini_pydantic_schema():
    """Verify Gemini Pydantic schemas validate structured examination output."""
    diagram = GeminiDiagram(
        id="d1",
        src="images/circuit.png",
        alt="Circuit diagram",
        caption="Figure 1: Logic circuit",
    )
    subq = GeminiSubQuestion(
        sub_id="1.a",
        label="(a)",
        stem="Define boolean logic.",
        marks=2.0,
        expected_answer="Logic of true/false values",
        marking_guide="Award 2 marks for full definition.",
    )
    mcq = GeminiQuestionItem(
        id="al-2023-ict-en-p1-q1",
        number=1,
        section="mcq",
        question_type="choice",
        marks=1.0,
        stem="What is $2^3$?",
        options={"A": "6", "B": "8", "C": "9", "D": "10", "E": "16"},
        reference_answer="B",
        explanation="2 cubed is 8",
        metadata={
            "subject": "ict",
            "year": "2023",
            "grade": "13",
            "medium": "english",
            "topic": "math",
        },
    )
    structured = GeminiQuestionItem(
        id="al-2023-ict-en-p2-q1",
        number=1,
        section="structured",
        question_type="structured",
        marks=10.0,
        stem="Answer the following parts:",
        sub_questions=[subq],
        diagrams=[diagram],
        metadata={
            "subject": "ict",
            "year": "2023",
            "grade": "13",
            "medium": "english",
            "topic": "logic",
        },
    )

    paper_data = GeminiExamPaper(
        paper_metadata={
            "subject": "ict",
            "year": "2023",
            "grade": "13",
            "level": "al",
            "medium": "english",
            "paper_no": "1",
        },
        questions=[mcq, structured],
    )
    assert len(paper_data.questions) == 2
    assert paper_data.questions[0].options["B"] == "8"


def test_gemini_data_to_exam_paper():
    """Test converting Gemini JSON dictionary into an ExamPaper dataclass instance."""
    raw_data = {
        "paper_metadata": {
            "subject": "ict",
            "year": "2023",
            "grade": "13",
            "level": "al",
            "medium": "english",
            "paper_no": "1",
        },
        "questions": [
            {
                "id": "q1",
                "number": 1,
                "section": "mcq",
                "question_type": "choice",
                "marks": 1.0,
                "stem": "Which layer is IP protocol located at?",
                "options": {"A": "Application", "B": "Network", "C": "Transport", "D": "Data Link"},
                "reference_answer": "B",
                "explanation": "IP is Network layer.",
            },
            {
                "id": "q2",
                "number": 2,
                "section": "structured",
                "question_type": "structured",
                "marks": 5.0,
                "stem": "Write SQL statement.",
                "sub_questions": [
                    {
                        "sub_id": "2.a",
                        "label": "(a)",
                        "stem": "Create table Student.",
                        "marks": 5.0,
                    }
                ],
            },
        ],
    }

    paper = _gemini_data_to_exam_paper(raw_data, source_filename="sample.pdf")
    assert isinstance(paper, ExamPaper)
    assert len(paper.questions) == 2
    assert paper.questions[0].question_type == "choice"
    assert paper.questions[0].options["B"] == "Network"
    assert paper.questions[0].reference_answer == "B"
    assert paper.questions[0].section == "mcq"

    # Check sub-question composition into stem for structured questions
    assert paper.questions[1].question_type == "written"
    assert "(a) Create table Student." in paper.questions[1].text
    assert paper.questions[1].section == "essay"


def test_gemini_available_check():
    """Test availability check returns False when no API key or package absent."""
    with patch.dict("os.environ", {}, clear=True):
        # Even if google-genai were installed, with no GEMINI_API_KEY it returns False
        assert gemini_available() is False
