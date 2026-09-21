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

import asyncio
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi import Path as FastApiPath
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

# P0 hardening: serialize concurrent submits per exam so two racing requests
# cannot BOTH run the expensive LLM essay grading before the DB atomic claim
# rejects the loser. The DB claim remains the authority; this lock only saves
# the wasted duplicate grading cost within one process.
_SUBMIT_LOCKS: Dict[str, asyncio.Lock] = {}
_SUBMIT_LOCKS_GUARD = asyncio.Lock()


async def _submit_lock(exam_id: str) -> asyncio.Lock:
    async with _SUBMIT_LOCKS_GUARD:
        lock = _SUBMIT_LOCKS.get(exam_id)
        if lock is None:
            lock = asyncio.Lock()
            _SUBMIT_LOCKS[exam_id] = lock
        return lock


class AnswerSubmissionItem(BaseModel):
    """Validated single question answer submission."""

    question_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_\-\.:]+$")
    option_key: Optional[str] = Field(default="", max_length=64)
    answer_text: Optional[str] = Field(default="", max_length=20000)


class SubmitAnswersRequest(BaseModel):
    student_id: str = Field(
        "student-primary", min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$"
    )
    answers: List[AnswerSubmissionItem] = Field(default_factory=list, max_length=500)


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
    header_checked = False
    with open(dest, "wb") as fh:
        while chunk := await upload.read(1024 * 512):
            if not header_checked:
                if b"%PDF-" not in chunk[:1024]:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=422,
                        detail="Uploaded file is not a valid PDF document (missing %PDF- header).",
                    )
                header_checked = True
            written += len(chunk)
            if written > _MAX_UPLOAD_BYTES:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail="Past-paper PDF exceeds the 50 MB upload limit.",
                )
            fh.write(chunk)
    if not header_checked or written == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=422,
            detail="Uploaded file is empty (0 bytes).",
        )
    return dest


async def _extract_gemini_paper(
    pdf_path: Path,
    *,
    title_hint: str | None = None,
) -> Optional["ExamPaper"]:
    """Try direct Gemini AI extraction → ExamPaper; returns None on failure.

    This path is preferred over _extract_templates because the Gemini
    structured output preserves MCQ options, sub-questions, marks, and
    metadata without the lossy QuizTemplate intermediary.
    """
    try:
        from deeptutor.services.exams.gemini_ocr import (
            extract_with_gemini,
            gemini_available,
        )

        if not gemini_available():
            return None
        return await extract_with_gemini(pdf_path, title_hint=title_hint)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gemini direct extraction failed, will use template pipeline: %s", exc)
        return None


async def _extract_templates(pdf_path: Path, max_questions: int = 200):
    """Run the shared parse+extract pipeline; raises RuntimeError on failure.

    This is the legacy path (MinerU → LLM extractor → QuizTemplates).
    The Gemini path in mimic_source will be tried first automatically.
    """
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
        logger.warning("Preview extraction failed: %s", exc)
        raise HTTPException(
            status_code=422, detail="Could not extract questions from this PDF. Try another file."
        )
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
    title: Optional[str] = Form(None, max_length=200),
    duration_seconds: int = Form(7200, ge=60, le=86400),
    student_id: str = Form(
        "student-primary", min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$"
    ),
    solve_answers: bool = Form(True),
):
    """Parse a past-paper PDF and create a verbatim exam.

    Tries the Gemini AI direct path first (structured output with options,
    sub-questions, marks). Falls back to the MinerU + template pipeline.
    """
    pdf_path = await _persist_upload(file)
    title_str = (title or Path(file.filename or "Past Paper").stem)[:120]
    trace: Dict[str, Any] = {}

    # ── Primary: direct Gemini extraction ──────────────────────────────
    paper = await _extract_gemini_paper(pdf_path, title_hint=title_str)
    if paper is not None:
        paper.student_id = student_id
        paper.mcq_duration_seconds = max(300, int(duration_seconds))
        trace = {"extraction_engine": "gemini"}
    else:
        # ── Fallback: MinerU + template pipeline ──────────────────────
        try:
            templates, trace = await _extract_templates(pdf_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Upload extraction failed: %s", exc)
            raise HTTPException(
                status_code=422,
                detail="Could not extract questions from this PDF. Try another file.",
            )

        if not templates:
            raise HTTPException(
                status_code=422, detail="No questions could be extracted from this PDF."
            )

        paper = templates_to_paper(
            templates,
            title=title_str,
            source_filename=str(file.filename or ""),
            mcq_duration_seconds=max(300, int(duration_seconds)),
            student_id=student_id,
        )

    if not paper.questions:
        raise HTTPException(
            status_code=422, detail="No questions could be extracted from this PDF."
        )

    # One batched LLM pass for papers without an answer key (tolerated failure).
    # Skip if Gemini already populated most answers.
    already_answered = sum(1 for q in paper.questions if q.reference_answer)
    if solve_answers and already_answered < len(paper.questions) * 0.8:
        solved = await solve_missing_answers(paper)
        if solved:
            for q in paper.questions:
                entry = solved.get(q.id)
                if entry and not (q.reference_answer or "").strip():
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
async def list_exams(
    limit: int = Query(20, ge=1, le=100),
    only_uploads: bool = Query(
        False,
        description="When true, return only user-uploaded papers (exclude Paper-Bank sittings).",
    ),
):
    rows = await ExamStore.list_exams(limit=limit, only_uploads=only_uploads)
    for r in rows:
        r.pop("source_filename", None)
    return rows


@router.delete("/{exam_id}")
async def delete_exam(
    exam_id: str = FastApiPath(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$"),
):
    """Delete one uploaded exam (lets users remove dummy/failed uploads)."""
    data = await ExamStore.load_paper(exam_id)
    if not data:
        raise HTTPException(status_code=404, detail="Exam not found")
    if str(data.get("status") or "") == "active":
        raise HTTPException(status_code=409, detail="Cannot delete a running exam")
    ok = await ExamStore.delete_exam(exam_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Exam not found")
    return {"ok": True, "exam_id": exam_id}


@router.get("/{exam_id}")
async def get_exam(
    exam_id: str = FastApiPath(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$"),
):
    data = await ExamStore.load_paper(exam_id)
    if not data:
        raise HTTPException(status_code=404, detail="Exam not found")
    paper = ExamPaper.from_json(_dumps(data))
    public = paper.public_dict(include_answers=False)
    if data.get("session_id"):
        public["session_id"] = data["session_id"]
    return public


def _dumps(data: Dict[str, Any]) -> str:
    import json as _json

    return _json.dumps(data)


@router.post("/{exam_id}/start")
async def start_exam(
    exam_id: str = FastApiPath(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$"),
    student_id: str = Query(
        "student-primary", min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$"
    ),
):
    data = await ExamStore.load_paper(exam_id)
    if not data:
        raise HTTPException(status_code=404, detail="Exam not found")
    if data.get("status") == "graded":
        raise HTTPException(status_code=409, detail="Exam already submitted")
    if data.get("status") == "active":
        # Duplicate Start (double-click / retry): never spawn a second study
        # session or orphan the first monitor — return the existing attempt.
        return {
            "exam_id": exam_id,
            "started_at": data.get("started_at"),
            "ends_at": data.get("ends_at"),
            "session_id": data.get("session_id"),
            "already_active": True,
        }

    now = time.time()
    ends_at = now + int(data.get("mcq_duration_seconds") or 7200)

    # 1. Ensure linked study session for supervision and telemetry
    session_id = data.get("session_id")
    session = None
    previous_session_id: str | None = None
    if session_id:
        try:
            from deeptutor.services.study.session_manager import StudySessionManager

            session = await StudySessionManager().get_session(session_id)
            if session and session.get("status") not in ("in_progress", "paused"):
                # Completed/abandoned rows are never reused — remember the old
                # id so its monitor can be torn down before we overwrite it.
                previous_session_id = str(session_id)
                session = None
        except Exception:
            session = None

    # Tear down any stale monitor for the previous session before the paper
    # row is repointed — otherwise its camera loop leaks.
    if previous_session_id:
        try:
            from deeptutor.services.monitoring.system_monitor import stop_system_monitor

            await stop_system_monitor(previous_session_id)
        except Exception as exc:  # noqa: BLE001 - teardown is best-effort
            logger.debug("Stale exam monitor teardown skipped: %s", exc)

    if not session:
        try:
            from deeptutor.services.study.session_manager import StudySessionManager

            target_duration = int(data.get("mcq_duration_seconds") or 7200)
            exam_title = str(data.get("title") or "Exam Paper")
            session = await StudySessionManager().create_session(
                student_id=student_id,
                title=f"Exam: {exam_title}",
                subject="Examination",
                target_duration_seconds=target_duration,
            )
            session_id = session["id"]
        except Exception as exc:
            logger.warning("Could not create study session for exam %s: %s", exam_id, exc)
            session_id = f"exam-{exam_id}"

    # 2. Attach study monitoring CV pipeline with strict supervision profile
    try:
        from deeptutor.services.monitoring.camera_settings import load_camera_config
        from deeptutor.services.monitoring.cv_pipeline import (
            LocalCVPipeline,
            hydrate_identity_baseline,
        )
        from deeptutor.services.monitoring.system_monitor import (
            apply_supervision_strictness,
            start_system_monitor,
        )

        camera_cfg = await load_camera_config()
        if camera_cfg.get("enabled", True):
            pipeline = LocalCVPipeline()
            try:
                await hydrate_identity_baseline(pipeline)
            except Exception:
                pass
            pipeline.reset_session()
            await apply_supervision_strictness(
                pipeline, profile_override="strict", session_id=session_id
            )
            await start_system_monitor(
                session_id, camera_cfg, pipeline=pipeline, profile_override="strict"
            )
            logger.info("Exam %s connected to strict monitoring session %s", exam_id, session_id)
    except Exception as exc:
        logger.warning("Exam monitoring startup non-fatal error for %s: %s", exam_id, exc)

    data["status"], data["started_at"], data["ends_at"], data["session_id"] = (
        "active",
        now,
        ends_at,
        session_id,
    )
    await ExamStore.update_fields(
        exam_id,
        status="active",
        started_at=now,
        ends_at=ends_at,
        paper_json=_dumps(data),
    )
    return {"exam_id": exam_id, "started_at": now, "ends_at": ends_at, "session_id": session_id}


@router.post("/{exam_id}/submit")
async def submit_exam(
    exam_id: str = FastApiPath(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$"),
    req: SubmitAnswersRequest = ...,
):
    lock = await _submit_lock(exam_id)
    async with lock:
        data = await ExamStore.load_paper(exam_id)
        if not data:
            raise HTTPException(status_code=404, detail="Exam not found")
        if data.get("status") == "graded":
            raise HTTPException(status_code=409, detail="Exam already submitted")

        # Late-submit handling: never throw away the student's work, but flag
        # it honestly so results/reports can distinguish on-time vs overtime.
        now_submit = time.time()
        ends_at = float(data.get("ends_at") or 0.0)
        late_seconds = max(0.0, now_submit - ends_at) if ends_at else 0.0
        is_late = bool(ends_at) and late_seconds > 0
        if is_late:
            logger.info(
                "Late exam submit %s: %.0fs past ends_at; accepting and flagging",
                exam_id,
                late_seconds,
            )

        paper = ExamPaper.from_json(_dumps(data))
        answers_dicts = [a.model_dump() for a in req.answers]
        result = await submit_and_grade(paper, answers_dicts)
        result["late"] = is_late
        result["late_seconds"] = round(late_seconds, 1)

        # Atomic claim of the "graded" transition: only ONE concurrent submit can
        # win, so answers/XP can never be double-written under a race.
        # (The per-exam lock above already serialized in-process racers so the
        # loser never pays for a duplicate LLM grading run; the DB claim stays
        # authoritative across processes/workers.)
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
                        for a in answers_dicts
                        if a.get("question_id") == row["question_id"]
                    ),
                    "",
                ),
                "answer_text": next(
                    (
                        a.get("answer_text", "")
                        for a in answers_dicts
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
    data["late"], data["late_seconds"] = (
        bool(result.get("late")),
        float(result.get("late_seconds") or 0.0),
    )
    await ExamStore.update_fields(exam_id, paper_json=_dumps(data))

    try:
        pct = result["total_score"] / max(1.0, result["total_marks"])
        xp = int(20 + 80 * pct)
        from deeptutor.services.gamification.gamification_service import GamificationService

        await GamificationService.award_xp(req.student_id, xp, f"exam_completed:{paper.exam_id}")
        await GamificationService.check_and_award(req.student_id)
    except Exception as exc:  # noqa: BLE001 - gamification is best-effort
        logger.debug("Gamification award skipped: %s", exc)

    # Complete linked study session and stop monitoring CV pipeline
    session_id = data.get("session_id")
    if session_id:
        try:
            from deeptutor.services.monitoring.dispatch import handle_session_completed
            from deeptutor.services.monitoring.system_monitor import stop_system_monitor
            from deeptutor.services.study.session_manager import StudySessionManager

            await stop_system_monitor(session_id)
            await StudySessionManager().stop_session(session_id)
            try:
                await asyncio.wait_for(
                    handle_session_completed(session_id, req.student_id),
                    timeout=5.0,
                )
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001 - teardown is best-effort
            logger.warning(
                "Exam session completion cleanup non-fatal error for %s: %s", session_id, exc
            )

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
