"""AI Guru Past-Paper Exam Engine.

Verbatim past-paper exams: upload a PDF -> OCR/parse -> extract the ORIGINAL
questions (never paraphrased) -> serve as a timed exam (MCQ first, essays
after) -> grade deterministically where possible, LLM-judge essays.
"""

from deeptutor.services.exams.engine import (
    ExamPaper,
    ExamQuestion,
    grade_mcq,
    split_options,
    templates_to_paper,
)

__all__ = [
    "ExamPaper",
    "ExamQuestion",
    "grade_mcq",
    "split_options",
    "templates_to_paper",
]
