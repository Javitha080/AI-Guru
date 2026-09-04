"""AI Guru Past-Paper Exam API Router.

Contract (consumed by the exam-runner frontend):

- POST /api/v1/exams/parse-preview   (multipart: file)
      -> {question_count, mcq_count, essay_count, detected_types, preview[]}
- POST /api/v1/exams/upload          (multipart: file, title?, duration_seconds?)
      -> {exam_id, title, question_count, mcq_count, essay_count,
          total_marks, duration_seconds}
- GET  /api/v1/exams/list?limit=     -> [{exam_id,title,status,...}]
- GET  /api/v1/exams/{exam_id}       -> paper (NO reference answers)
- POST /api/v1/exams/{exam_id}/start -> {started_at, ends_at}
- POST /api/v1/exams/{exam_id}/submit {answers:[{question_id,option_key?,answer_text?}]}
      -> grading result (MCQ deterministic + LLM essays)
- GET  /api/v1/exams/{exam_id}/result -> stored result incl. reference answers
"""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from deeptutor.services.exams.engine import (
    AUTO_GRADABLE,
    ExamPaper,
    solve_missing_answers,
    submit_and_grade,
    templates_to_paper,
)
from deeptutor.services.exams.store import ExamStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exams", tags=["exams"])


class SubmitAnswersRequest(BaseModel):
    student_id: str = "student-primary"
    answers: List[Dict[str, Any]] = Field(default_factory=list)


def _workspace_dir() -> Path:
    from deeptutor.services.path_service import get_path_service

    d = get_path_service().user_dir / "workspace" / "exams"
    d.mkdir(parents=True, exist_ok=True)
    return d


# The extraction pipeline is PDF-only; anything else is rejected before it
# touches disk (both a size cap and an extension whitelist — the filename is
# attacker-controlled, so the suffix alone must never reach the filesystem).
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_ALLOWED_UPLOAD_SUFFIXES = {".pdf"}


async def _persist_upload(upload: UploadFile) -> Path:
    raw_suffix = Path(upload.filename or "").suffix.lower()
    if raw_suffix not in _ALLOWED_UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{raw_suffix or '(none)'}' — upload a PDF past paper.",
        )
    dest = _workspace_dir() / f"upload_{uuid.uuid4().hex[:10]}{raw_suffix}"
    written = 0
    with open(dest, "wb") as fh:
        while chunk := await upload.read(1024 * 512):
            written += len(chunk)
            if written > _MAX_UPLOAD_BYTES:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail="Past-paper PDF exceeds the 50 MB upload limit.",
                )
            fh.write(chunk)
    return dest


async def _extract_templates(pdf_path: Path, max_questions: int = 200):
    """Run the shared parse+extract pipeline; raises RuntimeError on failure."""
    from deeptutor.agents.question.mimic_source import parse_exam_paper_to_templates

    out_dir = _workspace_dir() / f"extract_{uuid.uuid4().hex[:8]}"
    templates, trace = await parse_exam_paper_to_templates(
        pdf_path,
        max_questions=max_questions,
        paper_mode="upload",
        output_dir=out_dir,
    )
    return templates, trace


@router.post("/parse-preview")
async def parse_preview(file: UploadFile = File(...)):
    """Extract questions WITHOUT creating an exam (UI progress preview)."""
    pdf_path = await _persist_upload(file)
    try:
        templates, trace = await _extract_templates(pdf_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"extraction_failed: {exc}")
    detected: Dict[str, int] = {}
    for t in templates:
        qtype = getattr(t, "question_type", "written")
        detected[qtype] = detected.get(qtype, 0) + 1

    preview = [
        {
            "number": i + 1,
            "question_type": getattr(t, "question_type", ""),
            "text": (getattr(t, "reference_question", "") or "")[:280],
        }
        for i, t in enumerate(templates[:10])
    ]
    mcq = sum(1 for t in templates if getattr(t, "question_type", "") in AUTO_GRADABLE)
    return {
        "question_count": len(templates),
        "mcq_count": mcq,
        "essay_count": len(templates) - mcq,
        "detected_types": detected,
        "preview": preview,
        "trace": trace,
    }


@router.post("/upload")
async def upload_exam(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    duration_seconds: int = Form(7200),
    student_id: str = Form("student-primary"),
    solve_answers: bool = Form(True),
):
    """Parse a past-paper PDF and create a verbatim exam."""
    pdf_path = await _persist_upload(file)
    try:
        templates, trace = await _extract_templates(pdf_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"extraction_failed: {exc}")

    if not templates:
        raise HTTPException(
            status_code=422, detail="No questions could be extracted from this PDF."
        )

    paper = templates_to_paper(
        templates,
        title=(title or Path(file.filename or "Past Paper").stem)[:120],
        source_filename=str(file.filename or ""),
        mcq_duration_seconds=max(300, int(duration_seconds)),
        student_id=student_id,
    )

    # One batched LLM pass for papers without an answer key (tolerated failure).
    if solve_answers:
        solved = await solve_missing_answers(paper)
        if solved:
            for q in paper.questions:
                entry = solved.get(q.id)
                if entry:
                    q.reference_answer = entry["correct_answer"]
                    q.explanation = entry["explanation"]

    await ExamStore.save_paper(_paper_dict(paper))
    counts = paper.counts()
    return {
        "exam_id": paper.exam_id,
        "title": paper.title,
        **counts,
        "total_marks": paper.total_marks,
        "duration_seconds": paper.mcq_duration_seconds,
        "solved_answers": len({q.id for q in paper.questions if q.reference_answer}),
        "trace": trace,
    }


def _paper_dict(paper: ExamPaper) -> Dict[str, Any]:
    import json as _json

    return _json.loads(paper.to_json())


@router.get("/list")
async def list_exams(limit: int = Query(20, le=100)):
    rows = await ExamStore.list_exams(limit=limit)
    for r in rows:
        r.pop("source_filename", None)
    return rows


@router.get("/{exam_id}")
async def get_exam(exam_id: str):
    data = await ExamStore.load_paper(exam_id)
    if not data:
        raise HTTPException(status_code=404, detail="Exam not found")
    paper = ExamPaper.from_json(_dumps(data))
    public = paper.public_dict(include_answers=False)
    return public


def _dumps(data: Dict[str, Any]) -> str:
    import json as _json

    return _json.dumps(data)


@router.post("/{exam_id}/start")
async def start_exam(exam_id: str, student_id: str = "student-primary"):
    data = await ExamStore.load_paper(exam_id)
    if not data:
        raise HTTPException(status_code=404, detail="Exam not found")
    if data.get("status") == "graded":
        raise HTTPException(status_code=409, detail="Exam already submitted")

    now = time.time()
    ends_at = now + int(data.get("mcq_duration_seconds") or 7200)
    await ExamStore.update_fields(exam_id, status="active", started_at=now, ends_at=ends_at)

    data["status"], data["started_at"], data["ends_at"] = "active", now, ends_at
    await ExamStore.update_fields(exam_id, paper_json=_dumps(data))
    return {"exam_id": exam_id, "started_at": now, "ends_at": ends_at}


@router.post("/{exam_id}/submit")
async def submit_exam(exam_id: str, req: SubmitAnswersRequest):
    data = await ExamStore.load_paper(exam_id)
    if not data:
        raise HTTPException(status_code=404, detail="Exam not found")
    if data.get("status") == "graded":
        raise HTTPException(status_code=409, detail="Exam already submitted")

    paper = ExamPaper.from_json(_dumps(data))
    result = await submit_and_grade(paper, req.answers)

    # Atomic claim of the "graded" transition: only ONE concurrent submit can
    # win, so answers/XP can never be double-written under a race.
    claimed = await ExamStore.claim_for_grading(exam_id)
    if not claimed:
        raise HTTPException(status_code=409, detail="Exam already submitted")

    now = time.time()
    for row in result["results"]:
        graded = bool(row["verdict"]) or row["question_type"] in (
            "choice",
            "concept",
            "fill_in_blank",
        )
        await ExamStore.upsert_answer(
            exam_id,
            {
                "question_id": row["question_id"],
                "option_key": next(
                    (
                        a.get("option_key", "")
                        for a in req.answers
                        if a.get("question_id") == row["question_id"]
                    ),
                    "",
                ),
                "answer_text": next(
                    (
                        a.get("answer_text", "")
                        for a in req.answers
                        if a.get("question_id") == row["question_id"]
                    ),
                    "",
                ),
                **{k: v for k, v in row.items() if k in ("awarded", "feedback", "verdict")},
                "graded": graded,
            },
            float(row["max_marks"]),
        )
    await ExamStore.update_fields(
        exam_id, status="graded", submitted_at=now, student_id=req.student_id
    )

    data["status"], data["submitted_at"] = "graded", now
    await ExamStore.update_fields(exam_id, paper_json=_dumps(data))

    try:
        pct = result["total_score"] / max(1.0, result["total_marks"])
        xp = int(20 + 80 * pct)
        from deeptutor.services.gamification.gamification_service import GamificationService

        await GamificationService.award_xp(req.student_id, xp, f"exam_completed:{paper.exam_id}")
        await GamificationService.check_and_award(req.student_id)
    except Exception as exc:  # noqa: BLE001 - gamification is best-effort
        logger.debug("Gamification award skipped: %s", exc)

    return result


@router.get("/{exam_id}/result")
async def exam_result(exam_id: str):
    data = await ExamStore.load_paper(exam_id)
    if not data:
        raise HTTPException(status_code=404, detail="Exam not found")

    paper = ExamPaper.from_json(_dumps(data))
    stored_answers = await ExamStore.get_answers(exam_id)
    by_qid = {a["question_id"]: a for a in stored_answers}

    # Anti-cheat: reference answers/explanations are only revealed once the
    # exam has actually been submitted and graded.
    reveal_answers = data.get("status") == "graded"

    results = []
    total_awarded = 0.0
    graded_count = sum(1 for a in stored_answers if a.get("graded"))
    for q in sorted(paper.questions, key=lambda x: x.number):
        ans = by_qid.get(q.id, {})
        awarded = float(ans.get("awarded", 0) or 0)
        total_awarded += awarded
        results.append(
            {
                "question_id": q.id,
                "number": q.number,
                "question_type": q.question_type,
                "text": q.text,
                "options": q.options,
                "answer_text": ans.get("answer_text", ""),
                "option_key": ans.get("option_key", ""),
                "reference_answer": q.reference_answer if reveal_answers else None,
                "explanation": q.explanation if reveal_answers else None,
                "awarded": round(awarded, 2),
                "max_marks": q.marks,
                "verdict": ans.get("verdict", ""),
                "feedback": ans.get("feedback", "") if reveal_answers else "",
                "graded": bool(ans.get("graded")),
            }
        )

    return {
        "exam_id": exam_id,
        "title": paper.title,
        "status": data.get("status"),
        "submitted_at": data.get("submitted_at"),
        "total_score": round(total_awarded, 2),
        "total_marks": paper.total_marks,
        "questions_graded": graded_count,
        "results": results,
    }
