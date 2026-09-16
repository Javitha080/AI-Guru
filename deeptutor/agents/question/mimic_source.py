"""Exam-paper → QuizTemplate adapter for mimic mode.

Wraps the (sync, IO-heavy) MinerU parsing backend (local CLI or cloud API,
selected via ``document_parsing.json``) + the LLM question extractor so the capability
layer can hand mimic templates to :class:`QuestionPipeline` via its
``templates_override`` entry. Each extracted question carries its own
``question_type`` and ``difficulty`` (classified by the extractor), so mimic
templates preserve the source paper's format mix instead of defaulting every
item to a written question.

This module is intentionally narrow: it ONLY converts a PDF (or a
previously-parsed working directory) into a list of
:class:`QuizTemplate`. Streaming progress, prompt assembly, LLM calls,
and result emission all stay in the pipeline / capability layers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
import logging
from pathlib import Path

from deeptutor.agents.question.pipeline import (
    _VALID_DIFFICULTIES,
    _VALID_QUESTION_TYPES,
    QuizTemplate,
)
from deeptutor.services.parsing import get_parse_service
from deeptutor.tools.question.question_extractor import extract_questions_from_paper

logger = logging.getLogger(__name__)


_DEFAULT_DIFFICULTY = "medium"
_DEFAULT_QUESTION_TYPE = "written"
_TOPIC_CLIP_CHARS = 240


def _coerce_question_type(raw: object) -> str:
    """Map the extractor's per-question type onto the canonical taxonomy.

    The classification authority lives here (agents layer) rather than in the
    tools-layer extractor, which only emits a best-effort string. Anything
    outside the canonical set degrades to ``written`` (a free-text answer),
    the safest catch-all for an unrecognized format."""
    value = str(raw or "").strip().lower()
    return value if value in _VALID_QUESTION_TYPES else _DEFAULT_QUESTION_TYPE


def _coerce_difficulty(raw: object) -> str:
    """Validate the extractor's per-question difficulty; default ``medium``."""
    value = str(raw or "").strip().lower()
    return value if value in _VALID_DIFFICULTIES else _DEFAULT_DIFFICULTY


async def parse_exam_paper_to_templates(
    paper_path: str | Path,
    *,
    max_questions: int,
    paper_mode: str,
    output_dir: str | Path,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[list[QuizTemplate], dict[str, str]]:
    """Resolve an exam paper into a list of mimic-mode ``QuizTemplate``\\s.

    **Primary path (Gemini AI OCR):** When ``google-genai`` is installed and
    ``GEMINI_API_KEY`` is set, the raw PDF is sent directly to the Gemini API
    which returns fully structured questions.  This path is only tried for
    ``paper_mode="upload"`` (fresh PDF uploads); pre-parsed directories always
    use the legacy MinerU path.

    **Fallback path (MinerU + LLM extractor):** When Gemini is unavailable or
    fails, falls through to the original MinerU → question_extractor pipeline.

    ``paper_mode``:

    * ``"upload"``  — ``paper_path`` is a freshly-uploaded PDF; Gemini (or
      MinerU) parses it.
    * ``"parsed"``  — ``paper_path`` is a previously-parsed working dir
      (already contains the MinerU output); skip the parse step.

    Returns ``(templates, trace)``. ``trace`` carries paths + counts for
    inclusion in the final ``stream.result`` envelope. ``progress_callback``
    is a plain sync callable invoked from the parser worker thread with live
    parsing progress lines (upload mode only — the parsed path has nothing to
    report). Raises :class:`RuntimeError` when parsing or extraction fails —
    the caller emits a user-facing error.
    """
    # ── Gemini AI primary path (upload mode only) ─────────────────────────
    if paper_mode == "upload":
        try:
            from deeptutor.services.exams.gemini_ocr import (
                extract_with_gemini,
                gemini_available,
            )

            if gemini_available():
                logger.info(
                    "Gemini OCR available — using AI extraction for %s", Path(paper_path).name
                )
                paper = await extract_with_gemini(paper_path)
                # Convert ExamPaper questions → QuizTemplates for callers that
                # need the template list (capability.py, coordinator.py).
                templates = _exam_paper_to_templates(paper, max_questions)
                trace = {
                    "paper_dir": str(paper_path),
                    "question_file": "(gemini-structured-output)",
                    "template_count": str(len(templates)),
                    "extraction_engine": "gemini",
                }
                return templates, trace
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Gemini OCR failed for %s, falling back to MinerU pipeline: %s",
                Path(paper_path).name,
                exc,
            )

    # ── Legacy MinerU fallback path ───────────────────────────────────────
    return await asyncio.to_thread(
        _parse_sync,
        Path(paper_path),
        int(max_questions),
        str(paper_mode),
        Path(output_dir),
        progress_callback,
    )


def _exam_paper_to_templates(
    paper: "ExamPaper",  # noqa: F821 — lazy import avoids circular
    max_questions: int,
) -> list[QuizTemplate]:
    """Convert an :class:`ExamPaper` (from Gemini) into ``QuizTemplate`` list.

    This bridges the new Gemini output into the existing template-based
    pipeline so that callers in ``capability.py`` / ``coordinator.py`` see
    the same interface.
    """

    templates: list[QuizTemplate] = []
    questions = paper.questions
    if max_questions > 0:
        questions = questions[:max_questions]

    for idx, q in enumerate(questions, 1):
        q_text = (q.text or "").strip()
        if not q_text:
            continue
        templates.append(
            QuizTemplate(
                question_id=q.id or f"q_{idx}",
                topic=q_text[:_TOPIC_CLIP_CHARS],
                question_type=_coerce_question_type(q.question_type),
                difficulty=_DEFAULT_DIFFICULTY,
                source="mimic",
                reference_question=q_text,
                reference_answer=q.reference_answer,
            )
        )
    return templates


def _parse_sync(
    paper_path: Path,
    max_questions: int,
    paper_mode: str,
    output_base: Path,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[list[QuizTemplate], dict[str, str]]:
    output_base.mkdir(parents=True, exist_ok=True)

    if paper_mode == "parsed":
        # Caller already has a parsed directory; skip the parse step. Its own
        # dir doubles as the questions-output dir (legacy behavior).
        working_dir = paper_path
        questions_dir = working_dir
    else:
        # Shared parse layer: cached + engine-pluggable (the active engine is
        # selected in Settings → Document Parsing). Returns the cache dir with
        # the parsed artifacts; the questions JSON goes to the session output
        # dir so it never pollutes the shared parse cache.
        doc = get_parse_service().parse(paper_path, on_output=progress_callback)
        working_dir = doc.workdir or paper_path
        questions_dir = output_base

    json_files = list(questions_dir.glob("*_questions.json"))
    if not json_files:
        ok = extract_questions_from_paper(
            str(working_dir),
            output_dir=None if questions_dir == working_dir else str(questions_dir),
        )
        if not ok:
            raise RuntimeError("Failed to extract questions from parsed exam")
        json_files = list(questions_dir.glob("*_questions.json"))
    if not json_files:
        raise RuntimeError("Question extraction output not found")

    with json_files[0].open(encoding="utf-8") as fh:
        payload = json.load(fh)
    questions = payload.get("questions") or []
    if max_questions > 0:
        questions = questions[:max_questions]

    templates: list[QuizTemplate] = []
    for idx, item in enumerate(questions, 1):
        if not isinstance(item, dict):
            continue
        q_text = str(item.get("question_text") or "").strip()
        if not q_text:
            continue
        templates.append(
            QuizTemplate(
                question_id=f"q_{idx}",
                topic=q_text[:_TOPIC_CLIP_CHARS],
                question_type=_coerce_question_type(item.get("question_type")),
                difficulty=_coerce_difficulty(item.get("difficulty")),
                source="mimic",
                reference_question=q_text,
                reference_answer=str(item.get("answer") or "").strip() or None,
            )
        )

    trace = {
        "paper_dir": str(working_dir),
        "question_file": str(json_files[0]),
        "template_count": str(len(templates)),
    }
    return templates, trace


__all__ = ["parse_exam_paper_to_templates"]
