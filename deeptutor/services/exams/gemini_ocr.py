"""Gemini AI OCR pipeline: exam PDF → structured ExamPaper in one API call.

Uploads the raw PDF to the Gemini File API, then uses structured output
(``response_schema``) to extract every question into our standard
:class:`ExamQuestion` / :class:`ExamPaper` format. This replaces the
multi-stage MinerU→LLM-extractor→regex-splitter pipeline with a single
multimodal API call.

Falls back gracefully when the ``google-genai`` SDK is not installed or
``GEMINI_API_KEY`` is missing.
"""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field, field_validator

from deeptutor.services.exams.engine import ExamPaper, ExamQuestion

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic schemas for Gemini structured output
# ---------------------------------------------------------------------------

_DEFAULT_MODEL = "gemini-2.5-flash"
_MAX_PDF_BYTES = 50 * 1024 * 1024


class GeminiDiagram(BaseModel):
    """Diagram/figure reference within a question."""

    id: str = Field(description="Descriptive identifier, e.g. 'q02_circuit'")
    src: str = Field(description="Relative path, e.g. 'images/q02_circuit.png'")
    alt: str = Field(description="Alt text describing the diagram")
    caption: str = Field(description="Caption for the diagram")

    @field_validator("src")
    @classmethod
    def validate_src(cls, v: str) -> str:
        s = v.strip().replace("\\", "/")
        # Guard against directory traversal, absolute paths, and URL schemes
        if ".." in s or s.startswith("/") or ":" in s:
            # Fall back to safe basenamed path in images/
            clean_name = Path(s).name or "diagram.png"
            return f"images/{clean_name}"
        return s


class GeminiSubQuestion(BaseModel):
    """Sub-question for structured/essay questions."""

    sub_id: str = Field(description="Hierarchical id, e.g. '1.a' or '1.b.i'")
    label: str = Field(description="Printed label, e.g. '(a)' or '(i)'")
    stem: str = Field(description="Complete text of the sub-question")
    marks: float = Field(description="Allocated marks")
    expected_answer: Optional[str] = Field(
        default=None, description="Model answer or marking guideline"
    )
    marking_guide: Optional[str] = Field(
        default=None,
        description="Allocation rules, e.g. 'Award 1 mark for formula, 1 for calculation'",
    )


class GeminiQuestionItem(BaseModel):
    """A single extracted question."""

    id: str = Field(description="Format: <level>-<year>-<subject>-<lang>-p<num>-q<num>")
    number: int = Field(description="Question number as printed")
    section: str = Field(description="'mcq', 'structured', or 'essay'")
    question_type: str = Field(description="'choice', 'structured', or 'essay'")
    marks: float = Field(description="Total marks for this question")
    stem: str = Field(description="Full question text (verbatim)")
    diagrams: List[GeminiDiagram] = Field(
        default_factory=list, description="Referenced diagrams/figures"
    )
    options: Optional[Dict[str, str]] = Field(
        default=None,
        description="MCQ options keyed A-E (or A-D for O/L)",
    )
    sub_questions: Optional[List[GeminiSubQuestion]] = Field(
        default=None,
        description="Sub-questions for structured/essay",
    )
    reference_answer: Optional[str] = Field(
        default=None,
        description="Correct answer letter (MCQ) or model answer",
    )
    explanation: Optional[str] = Field(
        default=None,
        description="Step-by-step rationale",
    )
    metadata: Dict[str, str] = Field(
        default_factory=dict,
        description="Must include subject, grade, year, medium, and topic",
    )


class GeminiExamPaper(BaseModel):
    """Top-level structured output from Gemini extraction."""

    paper_metadata: Dict[str, str] = Field(
        description="Paper-level metadata: subject, year, grade, level, medium, paper_no"
    )
    questions: List[GeminiQuestionItem] = Field(description="All extracted questions")


# ---------------------------------------------------------------------------
# System instruction
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTION = """
You are an expert Educational Document Digitization and OCR Engine specialized in national examinations (such as G.C.E. A/L and O/L).

Your task is to analyze the provided examination PDF and extract all questions into a clean, structured JSON format adhering strictly to the schema provided.

### General Guidelines:
1. Complete Extraction: Extract every question and sub-question without summarizing, omitting, or truncating text.
2. Language Fidelity:
   - Preserve the exact language of the document (English, Sinhala, or Tamil).
   - Maintain correct Unicode characters for Sinhala and Tamil scripts. Do not attempt transliteration.
3. Mathematics & Logic Formatting:
   - Format all mathematical expressions, Boolean logic, formulas, and numeric notations using standard KaTeX LaTeX syntax enclosed in single dollar signs (e.g., $X + \\bar{X}Y$, $1101_2$, $2^{32}$).
4. Code and Tables:
   - Format programming code segments (Python, Pascal, PHP, HTML) within standard Markdown code blocks.
   - Format tabular data in question stems or sub-questions as Markdown tables.

### Question Specifics:

#### For Multiple-Choice Questions (Paper I):
- Set `section` to "mcq" and `question_type` to "choice".
- Map options to uppercase letters:
  - For 5-choice questions (A/L): "A", "B", "C", "D", "E" (corresponding to 1, 2, 3, 4, 5).
  - For 4-choice questions (O/L): "A", "B", "C", "D" (corresponding to 1, 2, 3, 4).
- Populate `reference_answer` with the correct option letter if a marking scheme/answer is provided or discernible; otherwise, leave null.
- Provide a step-by-step rationale in `explanation`.

#### For Structured & Essay Questions (Paper II):
- Set `section` to "structured" (typically Part A) or "essay" (typically Part B).
- Decompose multi-part questions into the `sub_questions` list.
- Each sub-question must capture:
  - `sub_id`: Unique hierarchical identifier (e.g., "1.a", "1.b.i").
  - `label`: Printed label (e.g., "(a)", "(i)").
  - `stem`: Complete text of the sub-question.
  - `marks`: Allocated marks as a float.
  - `expected_answer`: Model answer or marking guideline criteria.
  - `marking_guide`: Allocation rules (e.g., "Award 1 mark for formula, 1 mark for calculation").

#### Diagram and Image Handling:
- When a question references an external graphic, circuit, table-image, or flowchart:
  - Add an entry in the `diagrams` array.
  - Provide a descriptive `id`, relative image path `images/<suggested_name>.png`, meaningful `alt` text, and a `caption`.
  - Include an inline reference in the `stem` where appropriate: `![Caption](images/<suggested_name>.png)`.

### ID Format:
- For the question `id` field, use the format: `<level>-<year>-<subject>-<lang>-p<paper_no>-q<question_number>`
  - Example: `al-2023-ict-en-p1-q15`
- For `paper_metadata`, include: subject, year, grade, level (al/ol), medium (english/sinhala/tamil), paper_no
""".strip()

# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------


def gemini_available() -> bool:
    """Return True when the ``google-genai`` SDK is installed and an API key exists."""
    try:
        import google.genai  # noqa: F401
    except ImportError:
        return False
    return bool(_get_api_key())


def _get_api_key() -> str:
    """Resolve the Gemini API key from environment or provider registry."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return key
    # Try the provider registry (user may have configured via Settings UI)
    try:
        from deeptutor.services.provider_registry import find_by_name

        spec = find_by_name("gemini")
        if spec:
            return os.environ.get(spec.env_key, "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def _get_model() -> str:
    """Resolve the model to use; defaults to gemini-2.5-flash."""
    return os.environ.get("DEEPTUTOR_GEMINI_OCR_MODEL", _DEFAULT_MODEL)


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------


async def extract_with_gemini(
    pdf_path: str | Path,
    *,
    model: str | None = None,
    api_key: str | None = None,
    title_hint: str | None = None,
) -> ExamPaper:
    """Upload a PDF to Gemini and extract a fully structured ExamPaper.

    Parameters
    ----------
    pdf_path:
        Path to the exam PDF on disk.
    model:
        Gemini model name. Defaults to ``gemini-2.5-flash`` or
        ``DEEPTUTOR_GEMINI_OCR_MODEL`` env var.
    api_key:
        Gemini API key. Defaults to ``GEMINI_API_KEY`` env var.
    title_hint:
        Optional title for the paper (used as fallback if Gemini doesn't
        extract a title from the metadata).

    Returns
    -------
    ExamPaper
        Fully populated exam paper ready for storage.

    Raises
    ------
    RuntimeError
        On any extraction failure (caller is expected to catch and fallback).
    """
    import asyncio

    return await asyncio.to_thread(
        _extract_sync,
        Path(pdf_path),
        model=model or _get_model(),
        api_key=api_key or _get_api_key(),
        title_hint=title_hint,
    )


def _extract_sync(
    pdf_path: Path,
    *,
    model: str,
    api_key: str,
    title_hint: str | None,
) -> ExamPaper:
    """Synchronous extraction — runs in a thread pool worker."""
    if not api_key:
        raise RuntimeError("No GEMINI_API_KEY configured for Gemini OCR pipeline")

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai SDK not installed — run: pip install google-genai"
        ) from exc

    client = genai.Client(api_key=api_key)

    # 1. Validate PDF file before upload
    if not pdf_path.exists() or not pdf_path.is_file():
        raise RuntimeError(f"PDF file does not exist: {pdf_path}")
    file_size = pdf_path.stat().st_size
    if file_size == 0:
        raise RuntimeError("PDF file is empty (0 bytes)")
    if file_size > _MAX_PDF_BYTES:
        raise RuntimeError(f"PDF file exceeds 50 MB limit ({file_size} bytes)")
    with open(pdf_path, "rb") as fh:
        magic_bytes = fh.read(1024)
        if b"%PDF-" not in magic_bytes:
            raise RuntimeError(
                f"Invalid PDF file header (missing %PDF- magic bytes): {pdf_path.name}"
            )

    logger.info("Gemini OCR: uploading %s (%d KB)…", pdf_path.name, file_size // 1024)
    try:
        uploaded_file = client.files.upload(file=str(pdf_path))
    except Exception as exc:
        raise RuntimeError(f"Gemini file upload failed: {exc}") from exc

    # 2. Generate structured content
    logger.info("Gemini OCR: extracting questions with model=%s…", model)
    try:
        response = client.models.generate_content(
            model=model,
            contents=[
                uploaded_file,
                "Extract all questions from this examination document following the schema strictly. "
                "Preserve the exact language. Use KaTeX for math. Map MCQ options to A/B/C/D/E letters.",
            ],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=GeminiExamPaper,
                temperature=0.1,
            ),
        )
    except Exception as exc:
        # Clean up uploaded file on failure
        _safe_delete_file(client, uploaded_file)
        raise RuntimeError(f"Gemini content generation failed: {exc}") from exc

    # 3. Parse the response
    try:
        raw_text = response.text
        if not raw_text:
            raise RuntimeError("Gemini returned empty response")
        data = json.loads(raw_text)
    except (json.JSONDecodeError, AttributeError) as exc:
        _safe_delete_file(client, uploaded_file)
        raise RuntimeError(f"Gemini response parse failed: {exc}") from exc

    # 4. Clean up uploaded file
    _safe_delete_file(client, uploaded_file)

    # 5. Convert to ExamPaper
    paper = _gemini_data_to_exam_paper(data, title_hint=title_hint, source_filename=pdf_path.name)
    logger.info(
        "Gemini OCR: extracted %d questions (%d MCQ, %d essay) from %s",
        len(paper.questions),
        sum(1 for q in paper.questions if q.question_type == "choice"),
        sum(1 for q in paper.questions if q.question_type != "choice"),
        pdf_path.name,
    )
    return paper


def _safe_delete_file(client: Any, uploaded_file: Any) -> None:
    """Delete the uploaded file from Gemini storage; never raise."""
    try:
        client.files.delete(name=uploaded_file.name)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Gemini file cleanup failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Conversion: Gemini structured output → ExamPaper
# ---------------------------------------------------------------------------


def _gemini_data_to_exam_paper(
    data: Dict[str, Any],
    *,
    title_hint: str | None = None,
    source_filename: str = "",
) -> ExamPaper:
    """Convert the raw Gemini JSON into an ExamPaper with ExamQuestions."""
    paper_meta = data.get("paper_metadata") or {}
    questions_data = data.get("questions") or []

    if not questions_data:
        raise RuntimeError("Gemini extracted zero questions from the PDF")

    # Build title from metadata
    subject = paper_meta.get("subject", "Exam")
    year = paper_meta.get("year", "")
    grade = paper_meta.get("grade", "")
    level = paper_meta.get("level", "").upper()
    medium = paper_meta.get("medium", "english").title()
    paper_no_str = paper_meta.get("paper_no", "1")

    auto_title = f"{subject.upper()} {year}"
    if grade:
        auto_title += f" Grade {grade}"
    if level:
        auto_title += f" {level}"
    auto_title += f" Paper {paper_no_str} ({medium})"

    title = title_hint or auto_title

    # Convert questions
    exam_questions: List[ExamQuestion] = []
    for idx, q_data in enumerate(questions_data, start=1):
        q = _convert_question(q_data, idx)
        if q is not None:
            exam_questions.append(q)

    if not exam_questions:
        raise RuntimeError("All Gemini-extracted questions failed validation")

    # Determine durations from paper type
    mcq_count = sum(1 for q in exam_questions if q.question_type == "choice")
    has_essays = any(q.question_type != "choice" for q in exam_questions)
    mcq_duration = 7200  # 2h default
    essay_duration = 10800 if has_essays else None  # 3h

    paper = ExamPaper(
        exam_id=f"exam-{uuid.uuid4().hex[:12]}",
        title=title[:120],
        source_filename=source_filename,
        questions=exam_questions,
        mcq_duration_seconds=mcq_duration,
        essay_duration_seconds=essay_duration,
    )
    paper.reindex_sections()
    return paper


def _convert_question(q_data: Dict[str, Any], fallback_number: int) -> Optional[ExamQuestion]:
    """Convert a single Gemini question dict to an ExamQuestion."""
    stem = str(q_data.get("stem") or "").strip()
    if not stem:
        return None

    # Sub-questions: append their text to the main stem for display
    sub_questions = q_data.get("sub_questions") or []
    if sub_questions:
        sub_parts: List[str] = []
        for sq in sub_questions:
            label = sq.get("label", "")
            sq_stem = sq.get("stem", "")
            marks = sq.get("marks", "")
            marks_str = f" [{marks} marks]" if marks else ""
            sub_parts.append(f"{label} {sq_stem}{marks_str}")
        if sub_parts:
            stem = stem + "\n\n" + "\n\n".join(sub_parts)

    # Question type normalization
    raw_type = str(q_data.get("question_type") or "written").strip().lower()
    question_type = raw_type if raw_type in ("choice", "structured", "essay") else "written"
    # Map "structured" and "essay" to "written" for the engine's type system
    if question_type in ("structured", "essay"):
        question_type = "written"

    # Section
    raw_section = str(q_data.get("section") or "mcq").strip().lower()
    section = raw_section if raw_section in ("mcq", "structured", "essay") else "mcq"

    # Options (MCQ only)
    options = q_data.get("options")
    if options and isinstance(options, dict) and question_type == "choice":
        # Ensure keys are uppercase
        options = {k.upper(): str(v) for k, v in options.items() if v}
    elif question_type == "choice" and not options:
        # MCQ without options — demote to written
        question_type = "written"
        section = "essay"

    # Marks: ensure finite, non-negative, and sane upper limit
    try:
        raw_m = float(q_data.get("marks") or (1.0 if question_type == "choice" else 0.0))
        if math.isnan(raw_m) or math.isinf(raw_m) or raw_m < 0.0:
            marks = 1.0 if question_type == "choice" else 0.0
        else:
            marks = min(round(raw_m, 2), 1000.0)
    except (TypeError, ValueError):
        marks = 1.0 if question_type == "choice" else 0.0

    # Reference answer
    ref_answer = q_data.get("reference_answer")
    if ref_answer is not None:
        ref_answer = str(ref_answer).strip() or None

    # Explanation
    explanation = q_data.get("explanation")
    if explanation is not None:
        explanation = str(explanation).strip()[:4000] or None

    # Question number
    try:
        number = int(q_data.get("number") or fallback_number)
    except (TypeError, ValueError):
        number = fallback_number

    return ExamQuestion(
        id=str(q_data.get("id") or f"q_{fallback_number}"),
        number=number,
        question_type=question_type,
        text=stem[:6000],
        options=options if question_type == "choice" else None,
        marks=marks,
        reference_answer=ref_answer,
        explanation=explanation,
        section=section,
    )
