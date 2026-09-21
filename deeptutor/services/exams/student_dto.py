"""Student-safe exam paper serialization (Phase 1 Answer Key Removal).

Recursively sanitizes questions and sub-questions so that reference answers,
explanations, marking guides, rubrics, and expected answers never leak
to students before grading.
"""

from __future__ import annotations

from typing import Any, Dict


def _is_banned_key(key: str) -> bool:
    """Return True if a key name suggests answer, solution, rubric, or marking content."""
    kl = str(key).lower()
    return any(b in kl for b in ("answer", "solution", "rubric", "scheme", "marking", "explanation"))


def sanitize_sub_question(sub: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively strip answer keys and marking guides from a sub-question."""
    if not isinstance(sub, dict):
        return {}

    sanitized: Dict[str, Any] = {
        "id": str(sub.get("id") or ""),
        "number": sub.get("number", 1),
        "text": str(sub.get("text") or ""),
        "marks": float(sub.get("marks") or 1.0),
        "question_type": str(sub.get("question_type") or "essay"),
    }

    if "part_label" in sub:
        sanitized["part_label"] = sub["part_label"]

    # Sanitize options if present (MCQ sub-question)
    raw_options = sub.get("options")
    if isinstance(raw_options, dict):
        sanitized["options"] = {
            str(k): str(v)
            for k, v in raw_options.items()
            if not _is_banned_key(k)
        }
    elif isinstance(raw_options, list):
        sanitized["options"] = raw_options

    if "diagrams" in sub and isinstance(sub["diagrams"], list):
        sanitized["diagrams"] = [
            {k: v for k, v in d.items() if not _is_banned_key(k)}
            for d in sub["diagrams"]
            if isinstance(d, dict)
        ]

    # Recursive sub-sub-questions if any
    raw_nested = sub.get("sub_questions")
    if isinstance(raw_nested, list):
        sanitized["sub_questions"] = [
            sanitize_sub_question(child)
            for child in raw_nested
            if isinstance(child, dict)
        ]
    else:
        sanitized["sub_questions"] = []

    return sanitized


def sanitize_question(q_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Strip all answers, explanations, and marking guidelines from a question."""
    safe: Dict[str, Any] = {
        "id": str(q_dict.get("id") or ""),
        "number": q_dict.get("number", 1),
        "question_type": str(q_dict.get("question_type") or "mcq"),
        "text": str(q_dict.get("text") or ""),
        "marks": float(q_dict.get("marks") or 1.0),
        "section": str(q_dict.get("section") or "mcq"),
        "section_number": q_dict.get("section_number", 1),
    }

    raw_options = q_dict.get("options")
    if isinstance(raw_options, dict):
        safe["options"] = {
            str(k): str(v)
            for k, v in raw_options.items()
            if not _is_banned_key(k)
        }
    else:
        safe["options"] = raw_options

    if "diagrams" in q_dict and isinstance(q_dict["diagrams"], list):
        safe["diagrams"] = [
            {k: v for k, v in d.items() if not _is_banned_key(k)}
            for d in q_dict["diagrams"]
            if isinstance(d, dict)
        ]
    else:
        safe["diagrams"] = []

    raw_subs = q_dict.get("sub_questions")
    if isinstance(raw_subs, list):
        safe["sub_questions"] = [
            sanitize_sub_question(s)
            for s in raw_subs
            if isinstance(s, dict)
        ]
    else:
        safe["sub_questions"] = []

    # Sanitize metadata: remove any answer or rubric references
    raw_meta = q_dict.get("metadata")
    if isinstance(raw_meta, dict):
        safe["metadata"] = {
            k: v for k, v in raw_meta.items()
            if not _is_banned_key(k)
        }
    else:
        safe["metadata"] = {}

    return safe


def to_student_safe_paper(paper_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an ExamPaper dict into a student-safe representation without answer keys."""
    raw_questions = paper_dict.get("questions") or []
    sanitized_questions = [
        sanitize_question(q) for q in raw_questions if isinstance(q, dict)
    ]

    safe_paper: Dict[str, Any] = {
        "exam_id": paper_dict.get("exam_id", ""),
        "title": paper_dict.get("title", ""),
        "source_filename": paper_dict.get("source_filename", ""),
        "status": paper_dict.get("status", "created"),
        "mcq_duration_seconds": paper_dict.get("mcq_duration_seconds", 7200),
        "essay_duration_seconds": paper_dict.get("essay_duration_seconds"),
        "total_marks": paper_dict.get("total_marks", 0.0),
        "question_count": len(sanitized_questions),
        "mcq_count": paper_dict.get("mcq_count", 0),
        "essay_count": paper_dict.get("essay_count", 0),
        "started_at": paper_dict.get("started_at"),
        "ends_at": paper_dict.get("ends_at"),
        "submitted_at": paper_dict.get("submitted_at"),
        "questions": sanitized_questions,
        "section_boundary": paper_dict.get("section_boundary", len(sanitized_questions)),
    }
    return safe_paper
