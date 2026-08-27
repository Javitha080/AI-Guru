"""AI Guru Paper-Bank API Router.

Prebuilt local catalog of verbatim past papers (Grade 12/13 A/L, ICT first).
Starting a paper creates a SITTING: a Paper-1 (MCQ) + Paper-2 (essay) pair of
exam attempts linked by ``sitting_id``, with gamified add-on time.

Contract (consumed by the /papers frontend):

- GET  /api/v1/paper_bank/facets                  -> {subjects,grades,years,...}
- GET  /api/v1/paper_bank/catalog?subject=&grade=&year=&medium=
- GET  /api/v1/paper_bank/{bank_paper_id}         -> paper meta + questions (NO answers)
- POST /api/v1/paper_bank/{bank_paper_id}/start   -> {sitting_id, parts:[...]}  (P1 timer starts)
- GET  /api/v1/paper_bank/sittings/{sid}          -> live sitting state (server clock)
- POST /api/v1/paper_bank/sittings/{sid}/addon    {minutes: 15|30|60}
- POST /api/v1/paper_bank/sittings/{sid}/submit   {exam_id, student_id?, answers:[...]}
        -> grades this part; reveals answers; auto-starts the next part;
           awards XP (with add-on multiplier) once the LAST part is graded
- GET  /api/v1/paper_bank/sittings/{sid}/result   -> Google-Forms-style review
- GET  /api/v1/paper_bank/my-sessions?student_id= -> past sittings overview
- POST /api/v1/paper_bank/promote                 {exam_id}  (upload -> bank)
- POST /api/v1/paper_bank/import                  {folder, ...} -> background job
- GET  /api/v1/paper_bank/import/status?job_id=
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from deeptutor.services.exams.bank_import import (
    DEFAULT_DURATION_BY_TYPE,
    classify_filename,
    create_job,
    get_job,
    latest_job,
)
from deeptutor.services.exams.bank_store import BankStore
from deeptutor.services.exams.engine import ExamPaper
from deeptutor.services.exams.store import ExamStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/paper_bank", tags=["paper-bank"])

# Gamified extra-time menu: minutes → XP multiplier factor for that purchase.
ADDON_MENU: Dict[int, float] = {15: 0.90, 30: 0.75, 60: 0.60}
MAX_ADDON_PURCHASES = 2
ADDON_MIN_XP_BALANCE = 50
WELCOME_XP_GRANT = 200
REVIEW_WINDOW_SECONDS = 600


class StartRequest(BaseModel):
    student_id: str = "student-primary"


class AddonRequest(BaseModel):
    minutes: int = Field(..., description="Extra minutes to buy: 15, 30 or 60.")


class DraftRequest(BaseModel):
    exam_id: str
    answers: List[Dict[str, Any]] = Field(default_factory=list)


class ExplainRequest(BaseModel):
    exam_id: str
    question_id: str


class SubmitAnswersRequest(BaseModel):
    exam_id: str
    student_id: str = "student-primary"
    answers: List[Dict[str, Any]] = Field(default_factory=list)


class PromoteRequest(BaseModel):
    exam_id: str
    subject: str = "ict"
    grade: int = 12
    year: Optional[int] = None


class ImportRequest(BaseModel):
    folder: str
    subject_default: str = "ict"
    grade_default: Optional[int] = None
    medium_default: str = "english"
    solve_missing: bool = True


def _dumps(data: Dict[str, Any]) -> str:
    return json.dumps(data)


def _paper_from_row(row: Dict[str, Any]) -> ExamPaper:
    return ExamPaper.from_json(_dumps(row["paper_json"]))


@router.get("/facets")
async def facets():
    return await BankStore.facets()


@router.get("/catalog")
async def catalog(
    subject: Optional[str] = Query(None),
    grade: Optional[int] = Query(None, ge=11, le=13),
    year: Optional[int] = Query(None),
    medium: Optional[str] = Query(None),
    group_key: Optional[str] = Query(None),
    limit: int = Query(500, le=2000),
):
    rows = await BankStore.catalog(
        subject=subject,
        grade=grade,
        year=year,
        medium=medium,
        group_key=group_key,
        limit=limit,
    )
    return {"papers": rows, "count": len(rows)}


@router.get("/my-sessions")
async def my_sessions(student_id: str = "student-primary", limit: int = Query(50, le=200)):
    """Past bank sittings for the sessions list (grouped Paper1+Paper2)."""
    import aiosqlite

    from deeptutor.services.path_service import get_path_service

    db_path = get_path_service().user_dir / "chat_history.db"
    async with aiosqlite.connect(db_path) as db:
        await ExamStore.ensure_tables(db)
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT e.id, e.title, e.status, e.total_marks, e.created_at, e.started_at,"
            " e.ends_at, e.submitted_at, e.sitting_id, e.paper_no, e.bank_paper_id,"
            " e.addon_seconds_used, e.xp_multiplier,"
            " p.subject, p.grade, p.year, p.medium, p.paper_type"
            " FROM exams e LEFT JOIN paper_bank p ON e.bank_paper_id = p.id"
            " WHERE e.bank_paper_id IS NOT NULL AND e.student_id = ?"
            " ORDER BY e.created_at DESC LIMIT ?",
            (student_id, int(limit)),
        )
        rows = [dict(r) for r in await cur.fetchall()]

    sittings: Dict[str, Dict[str, Any]] = {}
    singles: List[Dict[str, Any]] = []
    for r in rows:
        awarded = 0.0
        max_marks = float(r.get("total_marks") or 0)
        try:
            answers = await ExamStore.get_answers(r["id"])
            awarded = sum(float(a.get("awarded") or 0) for a in answers)
        except Exception:  # noqa: BLE001 - display-only aggregation
            pass
        part = {
            **r,
            "awarded": round(awarded, 2),
            "max_marks": max_marks,
            "pct": round(100.0 * awarded / max_marks, 1) if max_marks else None,
        }
        sid = r.get("sitting_id")
        if sid:
            entry = sittings.setdefault(sid, {"sitting_id": sid, "parts": []})
            entry["parts"].append(part)
        else:
            singles.append(part)
    return {"sittings": list(sittings.values()), "single_parts": singles}


@router.post("/promote")
async def promote(req: PromoteRequest):
    """Add an uploaded exam's paper to the bank (user upload feeds the catalog)."""
    data = await ExamStore.load_paper(req.exam_id)
    if not data:
        raise HTTPException(status_code=404, detail="Exam not found")
    paper = ExamPaper.from_json(_dumps(data))

    meta = classify_filename(data.get("source_filename") or data.get("title") or "")
    meta.subject = req.subject.lower()
    meta.grade = req.grade
    if req.year:
        meta.year = req.year
    if meta.year is None:
        raise HTTPException(status_code=422, detail="year could not be determined — pass year explicitly")

    # Answers already on the paper become the stored scheme.
    scheme: Dict[str, str] = {}
    for q in paper.questions:
        if q.reference_answer:
            scheme[str(q.number)] = q.reference_answer[:40]

    counts = paper.counts()
    row_id = f"{meta.group_key}-p{meta.paper_no}"
    await BankStore.upsert_paper({
        "id": row_id,
        "group_key": meta.group_key,
        "paper_no": meta.paper_no,
        "grade": meta.grade,
        "subject": meta.subject,
        "year": meta.year,
        "medium": meta.medium,
        "paper_type": meta.paper_type if meta.paper_type != "mixed" else ("mcq" if counts["mcq_count"] > counts["essay_count"] else "structured"),
        "title": paper.title,
        "source_filename": data.get("source_filename", ""),
        # Stable content hash (no original file bytes available here).
        "file_hash": "promoted-" + hashlib.sha256(_dumps(data).encode()).hexdigest()[:16],
        **counts,
        "total_marks": counts["question_count"],
        "default_duration_seconds": paper.mcq_duration_seconds,
        "paper_json": json.loads(_dumps(data)),
        "scheme_answers": scheme,
        "topic_tags": [],
        "created_at": time.time(),
    })
    return {"bank_paper_id": row_id, "group_key": meta.group_key}


@router.get("/{bank_paper_id}")
async def get_bank_paper(bank_paper_id: str):
    row = await BankStore.get_paper(bank_paper_id)
    if not row:
        raise HTTPException(status_code=404, detail="Bank paper not found")

    paper = _paper_from_row(row)
    public = paper.public_dict(include_answers=False)
    return {
        "bank_paper_id": row["id"],
        "group_key": row["group_key"],
        "paper_no": row["paper_no"],
        "grade": row["grade"],
        "subject": row["subject"],
        "year": row["year"],
        "medium": row["medium"],
        "paper_type": row["paper_type"],
        "default_duration_seconds": row["default_duration_seconds"],
        "has_scheme_keys": bool(row.get("scheme_answers_json")),
        "paper": public,
    }


@router.post("/{bank_paper_id}/start")
async def start_sitting(bank_paper_id: str, req: StartRequest):
    """Create the P1+P2 sitting and start the Paper-1 timer immediately."""
    row = await BankStore.get_paper(bank_paper_id)
    if not row:
        raise HTTPException(status_code=404, detail="Bank paper not found")

    await _ensure_welcome_grant(req.student_id)

    group = sorted(await BankStore.get_by_group(row["group_key"]), key=lambda r: r["paper_no"])
    if not any(r["id"] == bank_paper_id for r in group):
        group.insert(0, row)

    sitting_id = f"sit-{uuid.uuid4().hex[:10]}"
    now = time.time()
    parts: List[Dict[str, Any]] = []
    for idx, part_row in enumerate(group):
        source = ExamPaper.from_json(_dumps(part_row["paper_json"]))
        exam_id = f"exam-{uuid.uuid4().hex[:12]}"
        duration = int(part_row["default_duration_seconds"] or DEFAULT_DURATION_BY_TYPE["mcq"])
        source.exam_id = exam_id
        source.title = part_row["title"]
        source.source_filename = part_row.get("source_filename", "")
        source.mcq_duration_seconds = duration
        source.status = "created"
        source.student_id = req.student_id
        paper_dict = json.loads(source.to_json())
        await ExamStore.save_paper(
            paper_dict,
            extra={
                "sitting_id": sitting_id,
                "paper_no": int(part_row["paper_no"]),
                "bank_paper_id": part_row["id"],
            },
        )
        entry = {
            "exam_id": exam_id,
            "bank_paper_id": part_row["id"],
            "paper_no": int(part_row["paper_no"]),
            "title": part_row["title"],
            "status": "created",
            "duration_seconds": duration,
            "started_at": None,
            "ends_at": None,
        }
        if idx == 0:
            ends_at = now + duration
            await ExamStore.update_fields(exam_id, status="active", started_at=now, ends_at=ends_at)
            entry.update({"status": "active", "started_at": now, "ends_at": ends_at})
        parts.append(entry)

    return {
        "sitting_id": sitting_id,
        "group_key": row["group_key"],
        "title": group[0]["title"],
        "parts": parts,
    }


@router.get("/sittings/{sitting_id}")
async def sitting_state(sitting_id: str):
    await _advance_sitting_clock(sitting_id)
    rows = await ExamStore.get_sitting(sitting_id)
    if not rows:
        raise HTTPException(status_code=404, detail="Sitting not found")
    now = time.time()
    parts = []
    for r in rows:
        meta = _bank_meta(r.get("paper_json"))
        remaining = None
        phase = r["status"]
        review_ends_at = float(meta.get("review_ends_at") or 0) or None
        if r["status"] == "active":
            remaining = max(0, int((r["ends_at"] or 0) - now))
        elif r["status"] == "review":
            remaining = max(0, int((review_ends_at or now) - now))
        parts.append({
            "exam_id": r["id"],
            "paper_no": r["paper_no"],
            "title": r["title"],
            "status": r["status"],
            "phase": phase,
            "time_up": bool(r["status"] in ("active", "review") and
                            (r["ends_at"] or 0) <= now),
            "remaining_seconds": remaining,
            "review_ends_at": review_ends_at,
            "addon_seconds_used": r["addon_seconds_used"],
            "xp_multiplier": r["xp_multiplier"],
            "duration_seconds": r["mcq_duration_seconds"],
        })
    return {
        "sitting_id": sitting_id,
        "server_now": now,
        "parts": parts,
        "all_graded": all(p["status"] == "graded" for p in parts),
    }


def _bank_meta(paper_json: Any) -> Dict[str, Any]:
    """Extract ``bank_meta`` whether paper_json arrives as dict or JSON str."""
    import json as _json

    data = paper_json
    if isinstance(data, str):
        try:
            data = _json.loads(data)
        except json.JSONDecodeError:
            return {}
    if not isinstance(data, dict):
        return {}
    meta = data.get("bank_meta")
    return meta if isinstance(meta, dict) else {}


async def _enter_review(exam_id: str, ends_at: float) -> bool:
    """Lazily move an expired active part into the 10-minute double-check window."""
    claimed = await ExamStore.claim_status(exam_id, from_status="active", to_status="review")
    if not claimed:
        return False
    data = await ExamStore.load_paper(exam_id) or {}
    meta = data.get("bank_meta") or {}
    # Never shorten a window that was already set (e.g. restored sessions).
    existing = float(meta.get("review_ends_at") or 0)
    meta.update({
        "review_ends_at": existing or (ends_at + REVIEW_WINDOW_SECONDS),
        "review_window_seconds": REVIEW_WINDOW_SECONDS,
    })
    data["bank_meta"] = meta
    await ExamStore.update_fields(exam_id, paper_json=_dumps(data))
    return True


async def _advance_sitting_clock(sitting_id: str) -> None:
    """Apply time-based transitions: active→review at time-up, then force-submit
    any review part whose double-check window has also expired."""
    rows = await ExamStore.get_sitting(sitting_id)
    now = time.time()
    for r in rows:
        if r["status"] == "active" and (r["ends_at"] or 0) <= now:
            await _enter_review(r["id"], float(r["ends_at"] or now))
    rows = await ExamStore.get_sitting(sitting_id)
    for r in rows:
        if r["status"] != "review":
            continue
        meta = _bank_meta(r.get("paper_json"))
        review_end = float(meta.get("review_ends_at") or 0)
        if review_end and now >= review_end:
            drafts = await ExamStore.get_answers(r["id"])
            answers = [
                {"question_id": a["question_id"], "option_key": a.get("option_key", ""),
                 "answer_text": a.get("answer_text", "")}
                for a in drafts
            ]
            try:
                await _finalize_part(sitting_id, r, answers,
                                     student_id=str(r.get("student_id") or "student-primary"),
                                     auto_submitted=True)
            except Exception as exc:  # noqa: BLE001 - state endpoint must survive
                logger.warning("Forced submit failed for %s: %s", r["id"], exc)

    # Clock-driven submits can complete the WHOLE sitting — award XP/notify
    # exactly as the manual submit endpoint would.
    fresh = sorted(await ExamStore.get_sitting(sitting_id), key=lambda x: x["paper_no"] or 1)
    if fresh and all(x["status"] == "graded" for x in fresh):
        student_id = str(fresh[0].get("student_id") or "student-primary")
        already = db_has_sitting_xp(sitting_id)
        if not already:
            try:
                await _maybe_complete_sitting(sitting_id, fresh, student_id)
            except Exception as exc:  # noqa: BLE001 - state endpoint must survive
                logger.warning("Sitting completion after forced submit failed: %s", exc)


async def _finalize_part(
    sitting_id: str,
    target: Dict[str, Any],
    answers: List[Dict[str, Any]],
    *,
    student_id: str,
    auto_submitted: bool = False,
) -> Dict[str, Any]:
    """Grade one part, reveal its answers, chain-start the next part.

    Shared by the manual submit endpoint and the lazy forced submit that runs
    when the double-check window expires.
    """
    exam_id = target["id"]
    data = await ExamStore.load_paper(exam_id)
    if not data:
        raise HTTPException(status_code=404, detail="Exam not found")

    from deeptutor.services.exams.engine import submit_and_grade

    paper = ExamPaper.from_json(_dumps(data))
    result = await submit_and_grade(paper, answers)

    claimed = await ExamStore.claim_for_grading(exam_id)
    if not claimed:
        raise HTTPException(status_code=409, detail="Part already submitted")

    now = time.time()
    answer_by_qid = {a.get("question_id"): a for a in answers}
    for row in result["results"]:
        graded = bool(row["verdict"]) or row["question_type"] in ("choice", "concept", "fill_in_blank")
        await ExamStore.upsert_answer(
            exam_id,
            {
                "question_id": row["question_id"],
                "option_key": (answer_by_qid.get(row["question_id"]) or {}).get("option_key", ""),
                "answer_text": (answer_by_qid.get(row["question_id"]) or {}).get("answer_text", ""),
                **{k: v for k, v in row.items() if k in ("awarded", "feedback", "verdict")},
                "graded": graded,
            },
            float(row["max_marks"]),
        )

    if auto_submitted:
        meta = data.get("bank_meta") or {}
        meta["auto_submitted"] = True
        data["bank_meta"] = meta
    await ExamStore.update_fields(exam_id, submitted_at=now, status="graded",
                                  student_id=student_id)
    data["submitted_at"] = now
    await ExamStore.update_fields(exam_id, paper_json=_dumps(data))

    # ---- practice log (best effort analytics) ---------------------------
    try:
        await BankStore.log_practice([
            {
                "student_id": student_id,
                "bank_paper_id": target["bank_paper_id"],
                "exam_id": exam_id,
                "question_id": row["question_id"],
                "topic": "",
                "question_type": row["question_type"],
                "verdict": row["verdict"],
                "awarded": row["awarded"],
                "max_marks": row["max_marks"],
                "practiced_at": now,
            }
            for row in result["results"]
        ])
    except Exception as exc:  # noqa: BLE001
        logger.debug("practice log failed: %s", exc)

    # ---- chain-start the next part ---------------------------------------
    rows = await ExamStore.get_sitting(sitting_id)
    ordered = sorted(rows, key=lambda r: r["paper_no"] or 1)
    idx = next(i for i, r in enumerate(ordered) if r["id"] == exam_id)
    next_part = None
    if idx + 1 < len(ordered) and ordered[idx + 1]["status"] == "created":
        nxt = ordered[idx + 1]
        ends_at = now + int(nxt["mcq_duration_seconds"] or 7200)
        await ExamStore.update_fields(nxt["id"], status="active", started_at=now, ends_at=ends_at)
        next_part = {"exam_id": nxt["id"], "paper_no": nxt["paper_no"],
                     "duration_seconds": nxt["mcq_duration_seconds"], "ends_at": ends_at}

    return {
        **result,
        "part": {"exam_id": exam_id, "paper_no": target.get("paper_no"), "status": "graded"},
        "next_part_started": next_part,
    }


@router.post("/sittings/{sitting_id}/submit")
async def submit_part(sitting_id: str, req: SubmitAnswersRequest):
    """Grade one sitting part, reveal its answers, chain-start the next part."""
    await _advance_sitting_clock(sitting_id)
    rows = await ExamStore.get_sitting(sitting_id)
    target = next((r for r in rows if r["id"] == req.exam_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Exam not part of this sitting")
    if target["status"] == "graded":
        raise HTTPException(status_code=409, detail="Part already submitted")

    result = await _finalize_part(
        sitting_id, target, req.answers,
        student_id=req.student_id, auto_submitted=False,
    )

    # ---- final XP once the WHOLE sitting is graded ------------------------
    ordered = sorted(await ExamStore.get_sitting(sitting_id),
                     key=lambda r: r["paper_no"] or 1)
    xp_awarded = await _maybe_complete_sitting(sitting_id, ordered, req.student_id)

    return {
        **result,
        "xp_awarded": xp_awarded,
        "sitting_complete": xp_awarded is not None,
    }


@router.put("/sittings/{sitting_id}/draft")
async def save_draft(sitting_id: str, req: DraftRequest):
    """Autosave in-progress answers while a part is active or in review."""
    rows = await ExamStore.get_sitting(sitting_id)
    target = next((r for r in rows if r["id"] == req.exam_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Exam not part of this sitting")
    if target["status"] == "graded":
        raise HTTPException(status_code=409, detail="Part already submitted")
    saved = await ExamStore.save_drafts(req.exam_id, req.answers)
    return {"ok": True, "saved": saved}


@router.post("/sittings/{sitting_id}/explain")
async def explain_question(sitting_id: str, req: ExplainRequest):
    """Grounded AI explanation for a graded question (anti-cheat gated)."""
    rows = await ExamStore.get_sitting(sitting_id)
    target = next((r for r in rows if r["id"] == req.exam_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Exam not part of this sitting")
    if target["status"] != "graded":
        raise HTTPException(status_code=403, detail="Explanations unlock after this part is graded")

    data = await ExamStore.load_paper(req.exam_id)
    paper = ExamPaper.from_json(_dumps(data or {}))
    question = next((q for q in paper.questions if q.id == req.question_id), None)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    stored = {a["question_id"]: a for a in await ExamStore.get_answers(req.exam_id)}
    ans = stored.get(req.question_id, {})

    options_text = "\n".join(f"({k}) {v}" for k, v in (question.options or {}).items())
    parts: List[str] = [f"QUESTION:\n{question.text[:4000]}"]
    if options_text:
        parts.append("OPTIONS:\n" + options_text[:2000])
    parts.append("OFFICIAL ANSWER:\n" + (question.reference_answer or "(none)")[:1500])
    if question.explanation:
        parts.append("STORED EXPLANATION CONTEXT:\n" + question.explanation[:2500])
    student_answer = ans.get("answer_text") or ans.get("option_key") or "(unanswered)"
    parts.append("STUDENT'S ANSWER:\n" + str(student_answer)[:3000])
    parts.append(f"Awarded: {ans.get('awarded', 0)} / {question.marks} marks.")
    parts.append(
        "Explain to the student why the official answer is right, where their "
        "reasoning went wrong, and one memory hook. Keep it under 220 words."
    )
    prompt = "\n\n".join(parts)
    system_prompt = (
        "You are AI Guru, a warm and encouraging Sri Lankan tutor. Teach the concept behind "
        "the mistake clearly, never just restate the answer key. If the question or student answer "
        "is in Sinhala (සිංහල), respond in clear natural Sinhala. If in English, respond in English."
    )
    try:
        from deeptutor.services.llm.factory import complete

        explanation = await complete(prompt=prompt, system_prompt=system_prompt)
    except Exception as exc:  # noqa: BLE001 - fail honest
        raise HTTPException(status_code=502, detail=f"explain_unavailable: {exc}")
    return {"explanation": (explanation or "").strip()[:4000]}


@router.post("/sittings/{sitting_id}/addon")
async def addon_time(sitting_id: str, req: AddonRequest):
    factor = ADDON_MENU.get(int(req.minutes))
    if factor is None:
        raise HTTPException(status_code=422, detail=f"minutes must be one of {sorted(ADDON_MENU)}")

    rows = await ExamStore.get_sitting(sitting_id)
    if not rows:
        raise HTTPException(status_code=404, detail="Sitting not found")
    active = [r for r in rows if r["status"] == "active"]
    if not active:
        raise HTTPException(status_code=409, detail="No active part — nothing to extend")
    if len(active) > 1:  # pragma: no cover - invariant guard
        raise HTTPException(status_code=500, detail="Sitting invariant violated: multiple active parts")

    student_id = str(active[0].get("student_id") or "student-primary")
    balance = await _xp_balance(student_id)
    if balance < ADDON_MIN_XP_BALANCE:
        raise HTTPException(
            status_code=409,
            detail=f"insufficient_xp:{balance}",
        )

    result = await ExamStore.grant_addon(
        active[0]["id"], seconds=req.minutes * 60, multiplier_factor=factor,
        max_purchases=MAX_ADDON_PURCHASES,
    )
    if not result.get("ok"):
        status = {"not_found": 404, "not_active": 409}.get(result.get("error", ""), 409)
        raise HTTPException(status_code=status, detail=result.get("error", "addon_failed"))
    return {**result, "xp_balance": balance}


def db_has_sitting_xp(sitting_id: str) -> bool:
    """True when the completion reward row for this sitting already exists."""
    import sqlite3 as _sqlite3

    from deeptutor.services.path_service import get_path_service

    db_path = get_path_service().user_dir / "chat_history.db"
    try:
        con = _sqlite3.connect(db_path)
        try:
            row = con.execute(
                "SELECT 1 FROM rewards WHERE reason = ? LIMIT 1",
                (f"sitting_completed:{sitting_id}",),
            ).fetchone()
            return row is not None
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - treat lookup failure as not-yet-awarded
        return False


async def _xp_balance(student_id: str) -> int:
    import aiosqlite as _aiosqlite

    from deeptutor.services.path_service import get_path_service

    db_path = get_path_service().user_dir / "chat_history.db"
    try:
        async with _aiosqlite.connect(db_path) as db:
            cur = await db.execute(
                "SELECT COALESCE(SUM(amount_xp), 0) FROM rewards WHERE student_id = ?",
                (student_id,),
            )
            row = await cur.fetchone()
            return int(row[0] or 0) if row else 0
    except Exception as exc:  # noqa: BLE001 - gate must not brick the flow
        logger.warning("XP balance lookup failed: %s", exc)
        return ADDON_MIN_XP_BALANCE


async def _ensure_welcome_grant(student_id: str) -> None:
    """Seed a one-time starting XP balance so add-on purchases are possible."""
    import aiosqlite as _aiosqlite

    from deeptutor.services.path_service import get_path_service

    db_path = get_path_service().user_dir / "chat_history.db"
    try:
        async with _aiosqlite.connect(db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            user_id = f"user-{student_id}"
            now = time.time()
            await db.execute(
                "INSERT OR IGNORE INTO users (id, username, password_hash, role,"
                " display_name, avatar_url, created_at, updated_at)"
                " VALUES (?, ?, '', 'student', ?, '', ?, ?)",
                (user_id, f"student:{student_id}", student_id, now, now),
            )
            await db.execute(
                "INSERT OR IGNORE INTO students (id, user_id, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                (student_id, user_id, now, now),
            )
            existing = await db.execute(
                "SELECT 1 FROM rewards WHERE student_id = ? AND reason = 'welcome_grant' LIMIT 1",
                (student_id,),
            )
            if await existing.fetchone():
                await db.commit()
                return
            await db.execute(
                "INSERT INTO rewards (id, student_id, session_id, reward_type, amount_xp,"
                " badge_id, badge_name, badge_icon, reason, unlocked_at)"
                " VALUES (?, ?, NULL, 'xp', ?, '', '', '', 'welcome_grant', ?)",
                (f"reward-{uuid.uuid4().hex[:12]}", student_id, WELCOME_XP_GRANT, now),
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 - best effort seeding
        logger.debug("Welcome grant skipped: %s", exc)


async def _maybe_complete_sitting(
    sitting_id: str,
    ordered: List[Dict[str, Any]],
    student_id: str,
) -> Optional[int]:
    """Award sitting XP exactly once when every part is graded; notify parent."""
    remaining_ungraded = [r for r in ordered if r["status"] != "graded"]
    if remaining_ungraded:
        return None
    total_awarded, total_marks = 0.0, 0.0
    combined_multiplier = 1.0
    for r in ordered:
        part_paper = ExamPaper.from_json(_dumps(await ExamStore.load_paper(r["id"]) or {}))
        answers = await ExamStore.get_answers(r["id"])
        total_awarded += sum(float(a.get("awarded") or 0) for a in answers)
        total_marks += float(part_paper.total_marks or 0)
        try:
            combined_multiplier *= float(r["xp_multiplier"] or 1.0)
        except (TypeError, ValueError):
            pass
    pct = total_awarded / max(1.0, total_marks)
    xp_awarded = int((20 + 80 * pct) * max(0.05, min(1.0, combined_multiplier)))
    try:
        await _award_sitting_xp(student_id, xp_awarded, sitting_id)
        from deeptutor.services.gamification.gamification_service import GamificationService

        await GamificationService().check_and_award(student_id)
    except Exception as exc:  # noqa: BLE001 - gamification is best-effort
        logger.debug("Gamification award skipped: %s", exc)

    # ---- parent telegram hook (best-effort, durable outbox) ---------------
    try:
        from deeptutor.services.monitoring.notification_queue import enqueue

        parts_bits: List[str] = []
        for r in ordered:
            part_paper = ExamPaper.from_json(_dumps(await ExamStore.load_paper(r["id"]) or {}))
            part_answers = await ExamStore.get_answers(r["id"])
            part_awarded = sum(float(a.get("awarded") or 0) for a in part_answers)
            part_pct = round(100 * part_awarded / max(1.0, float(part_paper.total_marks)))
            parts_bits.append(f"P{r['paper_no']}: {part_pct}%")
        await enqueue("session_summary", {
            "student_name": student_id,
            "subject": "Past-Paper Sitting",
            "duration_minutes": int(sum((r.get("mcq_duration_seconds") or 0) for r in ordered) // 60),
            "focus_score": round(pct * 100),
            "xp_earned": xp_awarded,
            "summary": "Sitting complete — " + " · ".join(parts_bits),
        })
    except Exception as exc:  # noqa: BLE001 - notifications are optional
        logger.debug("Parent sitting notification skipped: %s", exc)
    return xp_awarded


async def _award_sitting_xp(student_id: str, xp: int, sitting_id: str) -> None:
    """Persist an XP reward row for a completed sitting (FK-safe)."""
    import aiosqlite as _aiosqlite

    from deeptutor.services.path_service import get_path_service

    db_path = get_path_service().user_dir / "chat_history.db"
    now = time.time()
    async with _aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        user_id = f"user-{student_id}"
        await db.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role, display_name, avatar_url, created_at, updated_at)"
            " VALUES (?, ?, '', 'student', ?, '', ?, ?)",
            (user_id, f"student:{student_id}", student_id, now, now),
        )
        await db.execute(
            "INSERT OR IGNORE INTO students (id, user_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (student_id, user_id, now, now),
        )
        await db.execute(
            "INSERT INTO rewards (id, student_id, session_id, reward_type, amount_xp, badge_id,"
            " badge_name, badge_icon, reason, unlocked_at)"
            " VALUES (?, ?, NULL, 'xp', ?, '', '', '', ?, ?)",
            (f"reward-{uuid.uuid4().hex[:12]}", student_id, int(xp), f"sitting_completed:{sitting_id}", now),
        )
        await db.commit()


@router.get("/sittings/{sitting_id}/result")
async def sitting_result(sitting_id: str):
    """Google-Forms-style review across all parts of the sitting."""
    rows = await ExamStore.get_sitting(sitting_id)
    if not rows:
        raise HTTPException(status_code=404, detail="Sitting not found")

    parts_out, totals = [], {"score": 0.0, "marks": 0.0}
    for r in sorted(rows, key=lambda x: x["paper_no"] or 1):
        data = await ExamStore.load_paper(r["id"])
        if not data:
            continue
        paper = ExamPaper.from_json(_dumps(data))
        stored = await ExamStore.get_answers(r["id"])
        by_qid = {a["question_id"]: a for a in stored}
        reveal = r["status"] == "graded"

        results = []
        part_score = 0.0
        for q in sorted(paper.questions, key=lambda x: x.number):
            ans = by_qid.get(q.id, {})
            awarded = float(ans.get("awarded", 0) or 0)
            part_score += awarded
            results.append({
                "question_id": q.id,
                "number": q.number,
                "question_type": q.question_type,
                "text": q.text,
                "options": q.options,
                "answer_text": ans.get("answer_text", ""),
                "option_key": ans.get("option_key", ""),
                "reference_answer": q.reference_answer if reveal else None,
                "explanation": q.explanation if reveal else None,
                "awarded": round(awarded, 2),
                "max_marks": q.marks,
                "verdict": ans.get("verdict", ""),
                "feedback": ans.get("feedback", "") if reveal else "",
                "graded": bool(ans.get("graded")),
            })

        duration_taken = None
        if r["started_at"] and r["submitted_at"]:
            duration_taken = int(max(0, r["submitted_at"] - r["started_at"]))
        parts_out.append({
            "exam_id": r["id"],
            "paper_no": r["paper_no"],
            "title": r["title"],
            "status": r["status"],
            "score": round(part_score, 2),
            "max_marks": float(paper.total_marks or 0),
            "duration_taken_seconds": duration_taken,
            "addon_seconds_used": r["addon_seconds_used"],
            "xp_multiplier": r["xp_multiplier"],
            "questions": results,
        })
        totals["score"] += part_score
        totals["marks"] += float(paper.total_marks or 0)

    return {
        "sitting_id": sitting_id,
        "parts": parts_out,
        "total_score": round(totals["score"], 2),
        "total_max_marks": round(totals["marks"], 2),
        "pct": round(100.0 * totals["score"] / totals["marks"], 1) if totals["marks"] else None,
    }


@router.post("/import")
async def start_import(req: ImportRequest):
    folder = Path(req.folder).expanduser()
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"not a folder: {folder}")
    job = create_job(
        folder,
        subject_default=req.subject_default,
        grade_default=req.grade_default,
        medium_default=req.medium_default,
        solve_missing=req.solve_missing,
    )
    asyncio.create_task(job.run())  # background; poll via /import/status
    return {"job_id": job.job_id, "status": "running"}


@router.get("/import/status")
async def import_status(job_id: Optional[str] = Query(None)):
    job = get_job(job_id) if job_id else latest_job()
    if not job:
        return {"status": "idle"}
    return job.snapshot()


# ---------------------------------------------------------------------------
# NOTE: route order matters — static paths (/facets, /catalog, /my-sessions,
# /sittings/*, /import) are declared BEFORE the dynamic /{bank_paper_id}.
# FastAPI matches in declaration order, so those never get shadowed.
# ---------------------------------------------------------------------------
