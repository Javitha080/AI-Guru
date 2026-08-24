"""Exam engine core: models, verbatim conversion, grading, answer solving.

Verbatim guarantee: question text comes straight from the extractor's
``*_questions.json`` (which already preserves original wording). The only
transformations applied are:

* splitting merged ``A) ... B) ...`` option blocks back into an options dict
* an optional ONE-shot LLM batch pass that (a) splits options the regex
  splitter could not handle and (b) derives ``correct_answer`` for papers
  shipped without an answer key.

No LLM rewriting of stems ever happens here.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from dataclasses import fields as dataclass_fields
import json
import logging
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import uuid

logger = logging.getLogger(__name__)

MCQ_TYPES = ("choice",)
AUTO_GRADABLE = ("choice", "concept", "fill_in_blank")
# Ordering: MCQ-style questions first (exam convention), written last.
_TYPE_ORDER = {"choice": 0, "concept": 1, "fill_in_blank": 2, "short_answer": 3,
               "written": 4, "coding": 5}
_ESSAY_TYPES = ("short_answer", "written", "coding")

_OPTION_BLOCK_RE = re.compile(r"(?:^|(?<=\s))\(?([A-Ea-e])[\)\].](?:\s+)")


@dataclass
class ExamQuestion:
    id: str
    number: int
    question_type: str
    text: str
    options: Optional[Dict[str, str]] = None
    marks: float = 1.0
    reference_answer: Optional[str] = None
    explanation: Optional[str] = None

    def to_dict(self, *, include_answers: bool = False) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "number": self.number,
            "question_type": self.question_type,
            "text": self.text,
            "options": self.options,
            "marks": self.marks,
        }
        if include_answers:
            d["reference_answer"] = self.reference_answer
            d["explanation"] = self.explanation
        return d


@dataclass
class ExamPaper:
    exam_id: str
    title: str
    source_filename: str = ""
    questions: List[ExamQuestion] = field(default_factory=list)
    mcq_duration_seconds: int = 7200
    essay_duration_seconds: Optional[int] = None
    status: str = "created"
    student_id: str = "student-primary"
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    ends_at: Optional[float] = None
    submitted_at: Optional[float] = None

    @property
    def total_marks(self) -> float:
        return round(sum(q.marks for q in self.questions), 2)

    def counts(self) -> Dict[str, int]:
        mcq = sum(1 for q in self.questions if q.question_type in AUTO_GRADABLE)
        essay = len(self.questions) - mcq
        return {
            "question_count": len(self.questions),
            "mcq_count": mcq,
            "essay_count": essay,
        }

    def to_json(self) -> str:
        payload = asdict(self)
        return json.dumps(payload)

    @classmethod
    def from_json(cls, raw: str) -> "ExamPaper":
        data = json.loads(raw)
        questions = [ExamQuestion(**q) for q in data.pop("questions", [])]
        # Tolerate stored extras (bank_meta, cached totals) that are not
        # constructor fields — only real fields are forwarded.
        known = {f.name for f in dataclass_fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        return cls(questions=questions, **kwargs)

    def public_dict(self, *, include_answers: bool = False) -> Dict[str, Any]:
        """Serialized paper for API responses."""
        ordered = sorted(self.questions, key=lambda q: (_TYPE_ORDER.get(q.question_type, 9), q.number))
        section_boundary = next((i for i, q in enumerate(ordered) if q.question_type not in AUTO_GRADABLE), len(ordered))
        out_questions = []
        for idx, q in enumerate(ordered):
            entry = q.to_dict(include_answers=include_answers)
            entry["section"] = "mcq" if idx < section_boundary else "essay"
            entry["section_number"] = idx + 1
            out_questions.append(entry)
        return {
            "exam_id": self.exam_id,
            "title": self.title,
            "source_filename": self.source_filename,
            "status": self.status,
            "mcq_duration_seconds": self.mcq_duration_seconds,
            "essay_duration_seconds": self.essay_duration_seconds,
            "total_marks": self.total_marks,
            **self.counts(),
            "started_at": self.started_at,
            "ends_at": self.ends_at,
            "submitted_at": self.submitted_at,
            "questions": out_questions,
            "section_boundary": section_boundary,
        }


# --------------------------------------------------------------- option split

def split_options(text: str) -> Tuple[str, Optional[Dict[str, str]]]:
    """Split a merged stem like ``What is 2+2? A) 3 B) 4`` into stem + options.

    Returns ``(stem, options_or_None)``. Never raises.
    """
    try:
        matches = list(_OPTION_BLOCK_RE.finditer(text))
        # Require a well-formed option block: starts at 'A' with at least 3 options
        # (typical MCQ) to avoid matching stray lettered fragments in prose.
        if len(matches) >= 2 and matches[0].group(1).upper() == "A":
            stem = text[: matches[0].start()].strip()
            options: Dict[str, str] = {}
            for i, m in enumerate(matches):
                key = m.group(1).upper()
                start = m.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                value = text[start:end].strip().rstrip(";")
                if value:
                    options[key] = value
            if stem and len(options) >= 2:
                return stem, options
        return text.strip(), None
    except Exception:  # noqa: BLE001 - defensive: never fail extraction on format quirks
        return text.strip(), None


# ------------------------------------------------------------------ conversion

def templates_to_paper(
    templates: Sequence[Any],
    *,
    title: str,
    source_filename: str = "",
    mcq_duration_seconds: int = 7200,
    essay_duration_seconds: Optional[int] = None,
    student_id: str = "student-primary",
) -> ExamPaper:
    """Convert verbatim QuizTemplates into an ordered ExamPaper.

    Templates come from ``mimic_source.parse_exam_paper_to_templates`` whose
    ``reference_question`` holds the ORIGINAL extracted wording.
    """
    questions: List[ExamQuestion] = []
    counter = 0
    for tpl in templates:
        raw_text = str(getattr(tpl, "reference_question", "") or "").strip()
        if not raw_text:
            continue
        qtype = str(getattr(tpl, "question_type", "") or "written")
        ref_answer = getattr(tpl, "reference_answer", None)
        stem, options = (raw_text, None)
        if qtype in ("choice",):
            stem, options = split_options(raw_text)
        counter += 1
        questions.append(
            ExamQuestion(
                id=str(getattr(tpl, "question_id", f"q_{counter}")),
                number=counter,
                question_type=qtype,
                text=stem,
                options=options,
                marks=1.0,
                reference_answer=(str(ref_answer).strip() or None) if ref_answer else None,
            )
        )

    return ExamPaper(
        exam_id=f"exam-{uuid.uuid4().hex[:12]}",
        title=title,
        source_filename=source_filename,
        questions=questions,
        mcq_duration_seconds=int(mcq_duration_seconds),
        essay_duration_seconds=essay_duration_seconds,
        student_id=student_id,
    )


# -------------------------------------------------------------------- grading

_TRUE_WORDS = {"true", "t", "yes", "y", "correct", "✓"}
_FALSE_WORDS = {"false", "f", "no", "n", "incorrect", "✗"}


def _coerce_bool(value: str) -> Optional[bool]:
    v = (value or "").strip().lower()
    if v in _TRUE_WORDS:
        return True
    if v in _FALSE_WORDS:
        return False
    return None


def grade_mcq(question: ExamQuestion, *, option_key: str = "", answer_text: str = "") -> bool:
    """Deterministic grading mirroring QuizViewer.isAnswerCorrect semantics."""
    qtype = question.question_type
    expected = (question.reference_answer or "").strip()

    if qtype == "choice":
        if not expected:
            return False
        # Expected may be a bare key ("B") or the literal option text.
        if question.options:
            expected_key = expected.upper() if expected.upper() in {k.upper() for k in question.options} else None
            if expected_key is None:
                for k, v in question.options.items():
                    if v.strip().lower() == expected.lower():
                        expected_key = k.upper()
                        break
            user_key = (option_key or "").strip().upper()
            if expected_key is not None:
                return bool(user_key) and user_key == expected_key
            # Fall through to text comparison below.
        user_raw = (option_key or answer_text or "").strip()
        if not user_raw:
            return False
        user_val = question.options.get(user_raw.upper(), user_raw) if question.options else user_raw
        return user_val.strip().lower() == expected.lower()

    if qtype == "concept":
        expected_bool = _coerce_bool(expected)
        user_bool = _coerce_bool(option_key or answer_text)
        return expected_bool is not None and user_bool is not None and expected_bool == user_bool

    if qtype == "fill_in_blank":
        user = (answer_text or option_key or "").strip().lower()
        return bool(expected) and user == expected.strip().lower()

    return False


_ESSAY_JUDGE_SYSTEM = (
    "You are a strict but fair exam grader. Compare the student's answer against "
    "the reference answer for this exam question. Award partial credit where "
    "justified. Respond with ONLY a JSON object, no other text:\n"
    '{"verdict": "correct|partial|incorrect", "score": <0.0-1.0>, '
    '"feedback": "<one or two sentences of constructive feedback>"}'
)


async def grade_essay(
    question: ExamQuestion,
    answer_text: str,
    *,
    timeout_seconds: float = 120.0,
) -> Dict[str, Any]:
    """LLM-judge one essay answer. Returns {'verdict','score','feedback','graded'}."""
    result: Dict[str, Any] = {"verdict": "", "score": None, "feedback": "grading_unavailable", "graded": False}
    if not (answer_text or "").strip():
        result.update({"verdict": "incorrect", "score": 0.0, "feedback": "No answer provided.", "graded": True})
        return result
    prompt = (
        f"QUESTION:\n{question.text[:4000]}\n\n"
        f"REFERENCE ANSWER / MARKING GUIDE:\n{(question.reference_answer or '(none provided - judge on subject merit)')[:4000]}\n\n"
        f"STUDENT ANSWER:\n{answer_text[:6000]}"
    )
    try:
        from deeptutor.services.llm.factory import complete

        raw = await asyncio.wait_for(
            complete(prompt=prompt, system_prompt=_ESSAY_JUDGE_SYSTEM),
            timeout=timeout_seconds,
        )
        parsed = _extract_json_object(raw or "")
        if parsed and "verdict" in parsed:
            verdict = str(parsed.get("verdict", "")).lower()
            if verdict not in ("correct", "partial", "incorrect"):
                verdict = "partial"
            try:
                score = max(0.0, min(1.0, float(parsed.get("score", 0))))
            except (TypeError, ValueError):
                score = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}.get(verdict, 0.5)
            result.update({
                "verdict": verdict,
                "score": score,
                "feedback": str(parsed.get("feedback", ""))[:1000],
                "graded": True,
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning("Essay grading failed for %s: %s", question.id, exc)
    return result


def _extract_json_object(raw: str) -> Optional[Dict[str, Any]]:
    """Pull the first JSON object out of an LLM response."""
    if not raw:
        return None
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(raw)):
        ch = raw[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# ------------------------------------------------------------- answer solving

_SOLVE_SYSTEM = (
    "You are given exam questions extracted from a past paper. For each, provide "
    "the correct answer (as it would appear in an official marking scheme) and a "
    "brief explanation. For multiple-choice questions the answer MUST be just the "
    "option letter (A, B, C, D or E). Respond with ONLY a JSON object mapping each "
    "question id to {\"correct_answer\": ..., \"explanation\": ...}.\n"
    'Example: {"q_1": {"correct_answer": "B", "explanation": "..."}, "q_2": {...}}'
)


async def solve_missing_answers(
    paper: ExamPaper,
    *,
    timeout_seconds: float = 180.0,
) -> Dict[str, Dict[str, str]]:
    """One batched LLM pass deriving answers for questions lacking them.

    Returns ``{question_id: {"correct_answer","explanation"}}`` for the items
    it managed to solve; unsolved items stay untouched (tolerated).
    """
    pending = [
        q for q in paper.questions
        if not (q.reference_answer or "").strip()
    ]
    if not pending:
        return {}

    listing = []
    for q in pending:
        opts = ""
        if q.options:
            opts = "\n".join(f"{k}) {v}" for k, v in sorted(q.options.items()))
        listing.append(f"[{q.id}] ({q.question_type}) {q.text}\n{opts}".strip())

    prompt = "\n\n".join(listing)
    solved: Dict[str, Dict[str, str]] = {}
    try:
        from deeptutor.services.llm.factory import complete

        raw = await asyncio.wait_for(
            complete(prompt=prompt, system_prompt=_SOLVE_SYSTEM),
            timeout=timeout_seconds,
        )
        parsed = _extract_json_object(raw or "")
        if isinstance(parsed, dict):
            for q in pending:
                entry = parsed.get(q.id)
                if isinstance(entry, dict) and str(entry.get("correct_answer", "")).strip():
                    solved[q.id] = {
                        "correct_answer": str(entry["correct_answer"]).strip(),
                        "explanation": str(entry.get("explanation", "")).strip()[:800],
                    }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Answer solving failed (%d pending): %s", len(pending), exc)
    return solved


async def submit_and_grade(
    paper: ExamPaper,
    answers: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Grade all answered questions; persist handled by the caller/store layer."""
    by_id = {a.get("question_id"): a for a in answers if a.get("question_id")}
    results: List[Dict[str, Any]] = []
    mcq_correct = 0
    mcq_total_marks = 0.0
    mcq_awarded = 0.0
    essays_graded = 0
    essays_total = 0
    total_score = 0.0

    ordered = sorted(paper.questions, key=lambda q: (_TYPE_ORDER.get(q.question_type, 9), q.number))

    for q in ordered:
        ans = by_id.get(q.id, {})
        option_key = str(ans.get("option_key", "") or "")
        answer_text = str(ans.get("answer_text", "") or "")
        is_mcq = q.question_type in AUTO_GRADABLE

        if is_mcq:
            mcq_total_marks += q.marks
            if not (option_key or answer_text).strip():
                results.append(_result_row(q, 0.0, "", "skipped", True))
                continue
            if grade_mcq(q, option_key=option_key, answer_text=answer_text):
                mcq_correct += 1
                mcq_awarded += q.marks
                total_score += q.marks
                results.append(_result_row(q, q.marks, "", "correct", True))
            else:
                results.append(_result_row(q, 0.0, "", "incorrect", True))
        else:
            essays_total += 1
            judgment = await grade_essay(q, answer_text)
            if judgment["graded"]:
                essays_graded += 1
                awarded = round(q.marks * float(judgment["score"]), 2)
                total_score += awarded
                results.append(_result_row(q, awarded, judgment["feedback"], judgment["verdict"], True))
            else:
                results.append(_result_row(q, 0.0, judgment["feedback"], "", False))

    return {
        "exam_id": paper.exam_id,
        "mcq": {"correct": mcq_correct, "awarded": round(mcq_awarded, 2), "total": round(mcq_total_marks, 2)},
        "essays_graded": essays_graded,
        "essays_total": essays_total,
        "total_score": round(total_score, 2),
        "total_marks": paper.total_marks,
        "results": results,
    }


def _result_row(q: ExamQuestion, awarded: float, feedback: str, verdict: str, graded: bool) -> Dict[str, Any]:
    return {
        "question_id": q.id,
        "number": q.number,
        "question_type": q.question_type,
        "awarded": round(awarded, 2),
        "max_marks": q.marks,
        "verdict": verdict,
        "feedback": feedback,
        "reference_answer": q.reference_answer,
        "options": q.options,
    }
