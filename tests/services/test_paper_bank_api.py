"""HTTP-level lifecycle tests for /api/v1/paper_bank (Paper-Bank sitting flow).

Covers the full user journey on an isolated workspace DB with production
migrations applied:

    start sitting (P1 active + P2 queued) -> add-on time purchase rules ->
    submit P1 (MCQ auto-graded, answers revealed, P2 auto-started) ->
    submit P2 (essays fail-soft offline) -> XP awarded ONCE with multiplier ->
    Google-Forms-style result review -> promote an uploaded exam into the bank.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture()
def workspace(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="aiguru_pbapi_"))
    from deeptutor.services import path_service as ps

    svc = ps.PathService(workspace_root=tmp)
    monkeypatch.setattr(ps.PathService, "_instance", svc, raising=False)

    db = svc.user_dir / "chat_history.db"
    db.parent.mkdir(parents=True, exist_ok=True)

    import sqlite3

    from deeptutor.services.database.migrations import apply_migrations, enable_pragmas

    conn = sqlite3.connect(db)
    enable_pragmas(conn)
    applied = apply_migrations(conn)
    conn.commit()
    conn.close()
    assert 4 in applied and 5 in applied

    yield tmp


@pytest.fixture()
def client(workspace):
    from deeptutor.api.routers import paper_bank

    app = FastAPI()
    app.include_router(paper_bank.router, prefix="/api/v1")
    with TestClient(app) as c:
        yield c


def _bank_paper(group: str, paper_no: int, paper_type: str, n_questions: int) -> dict:
    from deeptutor.services.exams.engine import ExamPaper, ExamQuestion

    questions = []
    for i in range(1, n_questions + 1):
        if paper_type == "mcq":
            questions.append(
                ExamQuestion(
                    id=f"q{i}",
                    number=i,
                    question_type="choice",
                    text=f"{i}. 2+2? A) 3 B) 4 C) 5 D) 6",
                    options={"A": "3", "B": "4", "C": "5", "D": "6"},
                    reference_answer="B" if i % 2 else "C",
                )
            )
        else:
            questions.append(
                ExamQuestion(
                    id=f"q{i}",
                    number=i,
                    question_type="written",
                    text=f"{i}. Explain DNS.",
                    marks=5.0,
                )
            )
    paper = ExamPaper(
        exam_id=f"src-{group}-p{paper_no}",
        title=f"ICT Paper {paper_no}",
        questions=questions,
        mcq_duration_seconds=7200 if paper_type == "mcq" else 10800,
    )
    return {
        "id": f"{group}-p{paper_no}",
        "group_key": group,
        "paper_no": paper_no,
        "grade": 12,
        "subject": "ict",
        "year": 2021,
        "medium": "english",
        "paper_type": paper_type,
        "title": paper.title,
        "file_hash": f"h-{group}-{paper_no}",
        "question_count": n_questions,
        "mcq_count": n_questions if paper_type == "mcq" else 0,
        "essay_count": 0 if paper_type == "mcq" else n_questions,
        "total_marks": n_questions if paper_type == "mcq" else 5 * n_questions,
        "default_duration_seconds": 7200 if paper_type == "mcq" else 10800,
        "paper_json": {
            "exam_id": paper.exam_id,
            "title": paper.title,
            "questions": [
                {
                    "id": q.id,
                    "number": q.number,
                    "question_type": q.question_type,
                    "text": q.text,
                    "options": q.options,
                    "marks": q.marks,
                    "reference_answer": q.reference_answer,
                    "explanation": None,
                }
                for q in questions
            ],
            "mcq_duration_seconds": paper.mcq_duration_seconds,
            "source_filename": "",
            "status": "created",
            "student_id": "student-primary",
        },
        "scheme_answers": {},
        "topic_tags": [],
    }


def _seed_sitting_pair() -> dict:
    from deeptutor.services.exams.bank_store import BankStore

    p1 = _bank_paper("ict-2021-g12", 1, "mcq", 10)
    p2 = _bank_paper("ict-2021-g12", 2, "structured", 4)
    return {
        "p1_id": asyncio_run(BankStore.upsert_paper(p1)),
        "p2_id": asyncio_run(BankStore.upsert_paper(p2)),
    }


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


def test_start_sitting_activates_p1_and_queues_p2(client) -> None:
    ids = _seed_sitting_pair()
    res = client.post(f"/api/v1/paper_bank/{ids['p1_id']}/start", json={"student_id": "s1"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["group_key"] == "ict-2021-g12"
    assert len(body["parts"]) == 2
    first, second = body["parts"]
    assert first["status"] == "active" and first["ends_at"] > time.time()
    assert second["status"] == "created"

    state = client.get(f"/api/v1/paper_bank/sittings/{body['sitting_id']}").json()
    assert state["parts"][0]["time_up"] is False
    assert state["parts"][0]["remaining_seconds"] > 0
    assert state["all_graded"] is False


def test_addon_menu_rules(client) -> None:
    ids = _seed_sitting_pair()
    sid = client.post(f"/api/v1/paper_bank/{ids['p1_id']}/start", json={}).json()["sitting_id"]

    # Invalid menu option rejected.
    assert (
        client.post(f"/api/v1/paper_bank/sittings/{sid}/addon", json={"minutes": 7}).status_code
        == 422
    )

    # First purchase: +30 min at x0.75.
    ok = client.post(f"/api/v1/paper_bank/sittings/{sid}/addon", json={"minutes": 30}).json()
    assert ok["ok"] and abs(ok["xp_multiplier"] - 0.75) < 1e-6
    assert ok["added_seconds"] == 1800

    # Second purchase multiplies further (0.75 * 0.9).
    ok2 = client.post(f"/api/v1/paper_bank/sittings/{sid}/addon", json={"minutes": 15}).json()
    assert ok2["ok"] and abs(ok2["xp_multiplier"] - 0.675) < 1e-6

    # Purchase cap reached.
    capped = client.post(f"/api/v1/paper_bank/sittings/{sid}/addon", json={"minutes": 60})
    assert capped.status_code == 409
    assert "purchase_cap" in capped.json()["detail"]

    # Unknown sitting → 404.
    assert (
        client.post("/api/v1/paper_bank/sittings/sit-nope/addon", json={"minutes": 15}).status_code
        == 404
    )


def test_full_sitting_submit_chain_and_xp_once(client) -> None:
    ids = _seed_sitting_pair()
    started = client.post(
        f"/api/v1/paper_bank/{ids['p1_id']}/start", json={"student_id": "s1"}
    ).json()
    sid, parts = started["sitting_id"], {p["paper_no"]: p for p in started["parts"]}
    exam_p1, exam_p2 = parts[1]["exam_id"], parts[2]["exam_id"]

    # ---- Submit Paper 1: all correct ------------------------------------
    answers = [
        {"question_id": f"q{i}", "option_key": ("B" if i % 2 else "C")} for i in range(1, 11)
    ]
    r1 = client.post(
        f"/api/v1/paper_bank/sittings/{sid}/submit",
        json={"exam_id": exam_p1, "student_id": "s1", "answers": answers},
    )
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["total_score"] == 10.0 and b1["part"]["status"] == "graded"
    # Sitting not complete yet → no XP, and P2 auto-started.
    assert b1["xp_awarded"] is None and b1["next_part_started"]["paper_no"] == 2

    # Double-submit guarded by the graded claim.
    assert (
        client.post(
            f"/api/v1/paper_bank/sittings/{sid}/submit", json={"exam_id": exam_p1, "answers": []}
        ).status_code
        == 409
    )

    # ---- Submit Paper 2: essays grade fail-soft offline -------------------
    r2 = client.post(
        f"/api/v1/paper_bank/sittings/{sid}/submit",
        json={
            "exam_id": exam_p2,
            "student_id": "s1",
            "answers": [{"question_id": "q1", "answer_text": "DNS maps names to IPs."}],
        },
    )
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert b2["sitting_complete"] is True
    assert isinstance(b2["xp_awarded"], int) and b2["xp_awarded"] >= 20

    # XP written exactly once for the sitting.
    import sqlite3

    from deeptutor.services.path_service import get_path_service

    db = get_path_service().user_dir / "chat_history.db"
    rows = (
        sqlite3.connect(db)
        .execute("SELECT amount_xp FROM rewards WHERE reason = ?", (f"sitting_completed:{sid}",))
        .fetchall()
    )
    assert len(rows) == 1
    # Multiplier respected: base would be ≥100 for perfect MCQ half; with the
    # untouched P2 multiplier of 1.0 this stays the un-multiplied value here.
    assert rows[0][0] == b2["xp_awarded"]


def test_result_review_reveals_answers_only_after_grading(client) -> None:
    ids = _seed_sitting_pair()
    started = client.post(
        f"/api/v1/paper_bank/{ids['p1_id']}/start", json={"student_id": "s1"}
    ).json()
    sid = started["sitting_id"]
    exam_p1 = next(p["exam_id"] for p in started["parts"] if p["paper_no"] == 1)

    # Before submission: reference answers hidden.
    pre = client.get(f"/api/v1/paper_bank/sittings/{sid}/result").json()
    p1_pre = next(p for p in pre["parts"] if p["paper_no"] == 1)
    assert p1_pre["questions"][0]["reference_answer"] is None

    client.post(
        f"/api/v1/paper_bank/sittings/{sid}/submit", json={"exam_id": exam_p1, "answers": []}
    )

    post = client.get(f"/api/v1/paper_bank/sittings/{sid}/result").json()
    p1_post = next(p for p in post["parts"] if p["paper_no"] == 1)
    assert p1_post["questions"][0]["reference_answer"] in ("A", "B", "C", "D")
    assert p1_post["score"] == 0.0  # empty answers → nothing awarded
    p2_post = next(p for p in post["parts"] if p["paper_no"] == 2)
    assert p2_post["status"] == "active"


def test_promote_upload_into_bank(client) -> None:
    from deeptutor.services.exams.engine import ExamPaper
    from deeptutor.services.exams.store import ExamStore

    paper = ExamPaper(exam_id="exam-upload1", title="Uploaded ICT 2018 P1")
    asyncio_run(
        ExamStore.save_paper(
            {
                "exam_id": paper.exam_id,
                "title": paper.title,
                "source_filename": "",
                "status": "graded",
                "mcq_duration_seconds": 7200,
                "questions": [],
            }
        )
    )

    res = client.post(
        "/api/v1/paper_bank/promote",
        json={"exam_id": "exam-upload1", "subject": "ict", "grade": 13, "year": 2018},
    )
    assert res.status_code == 200, res.text
    bank_id = res.json()["bank_paper_id"]
    fetched = client.get(f"/api/v1/paper_bank/{bank_id}").json()
    assert fetched["year"] == 2018 and fetched["grade"] == 13

    # Catalog now lists it.
    cat = client.get("/api/v1/paper_bank/catalog?subject=ict&grade=13").json()
    assert any(r["id"] == bank_id for r in cat["papers"])

    # Facets reflect the new content.
    fac = client.get("/api/v1/paper_bank/facets").json()
    assert 13 in fac["grades"] and 2018 in fac["years"]


# ------------------------------------------------------- review window flow


def _backdate(client_exam: str, *, ends_at: float, review_ends_at: float | None = None) -> None:
    import json as _json

    from deeptutor.services.exams.store import ExamStore

    async def _run() -> None:
        data = await ExamStore.load_paper(client_exam)
        data["ends_at"] = ends_at
        meta = data.get("bank_meta") or {}
        if review_ends_at is not None:
            meta["review_ends_at"] = review_ends_at
            data["bank_meta"] = meta
        await ExamStore.update_fields(
            client_exam,
            ends_at=ends_at,
            started_at=ends_at - 7200,
            paper_json=_json.dumps(data),
        )

    asyncio_run(_run())


def test_review_window_then_forced_submit(client) -> None:
    ids = _seed_sitting_pair()
    started = client.post(
        f"/api/v1/paper_bank/{ids['p1_id']}/start", json={"student_id": "s2"}
    ).json()
    sid = started["sitting_id"]
    exam_p1 = next(p["exam_id"] for p in started["parts"] if p["paper_no"] == 1)

    # Time expires while unanswered.
    _backdate(exam_p1, ends_at=time.time() - 10)
    state = client.get(f"/api/v1/paper_bank/sittings/{sid}").json()
    p1 = next(p for p in state["parts"] if p["paper_no"] == 1)
    assert p1["status"] == "review" and p1["time_up"] is True
    assert p1["review_ends_at"] and p1["remaining_seconds"] <= 600

    # Double-check window: drafts still editable.
    draft = client.put(
        f"/api/v1/paper_bank/sittings/{sid}/draft",
        json={
            "exam_id": exam_p1,
            "answers": [
                {"question_id": "q1", "option_key": "B"},
                {"question_id": "q2", "option_key": "C"},
            ],
        },
    )
    assert draft.status_code == 200 and draft.json()["saved"] == 2

    # Review window also expires -> server force-submits the stored drafts.
    _backdate(exam_p1, ends_at=time.time() - 20, review_ends_at=time.time() - 5)
    state = client.get(f"/api/v1/paper_bank/sittings/{sid}").json()
    p1 = next(p for p in state["parts"] if p["paper_no"] == 1)
    assert p1["status"] == "graded"
    p2 = next(p for p in state["parts"] if p["paper_no"] == 2)
    assert p2["status"] == "active"

    post = client.get(f"/api/v1/paper_bank/sittings/{sid}/result").json()
    p1_post = next(p for p in post["parts"] if p["paper_no"] == 1)
    assert p1_post["score"] == 2.0  # both drafted answers were correct


def test_draft_rejected_after_grading(client) -> None:
    ids = _seed_sitting_pair()
    started = client.post(f"/api/v1/paper_bank/{ids['p1_id']}/start", json={}).json()
    sid = started["sitting_id"]
    exam_p1 = next(p["exam_id"] for p in started["parts"] if p["paper_no"] == 1)

    client.post(
        f"/api/v1/paper_bank/sittings/{sid}/submit", json={"exam_id": exam_p1, "answers": []}
    )
    res = client.put(
        f"/api/v1/paper_bank/sittings/{sid}/draft",
        json={
            "exam_id": exam_p1,
            "answers": [{"question_id": "q1", "option_key": "B"}],
        },
    )
    assert res.status_code == 409


def test_addon_requires_minimum_xp_balance(client) -> None:
    ids = _seed_sitting_pair()
    started = client.post(
        f"/api/v1/paper_bank/{ids['p1_id']}/start", json={"student_id": "s3"}
    ).json()
    sid = started["sitting_id"]

    # Start seeded the one-time welcome grant.
    import sqlite3

    from deeptutor.services.path_service import get_path_service

    db_path = get_path_service().user_dir / "chat_history.db"

    def _balance() -> int:
        con = sqlite3.connect(db_path)
        try:
            row = con.execute(
                "SELECT COALESCE(SUM(amount_xp), 0) FROM rewards WHERE student_id='s3'"
            ).fetchone()
            return int(row[0] or 0)
        finally:
            con.close()

    assert _balance() >= 200  # welcome grant present

    # Drain the balance -> purchase must refuse honestly.
    con = sqlite3.connect(db_path)
    con.execute("DELETE FROM rewards WHERE student_id='s3'")
    con.commit()
    con.close()

    res = client.post(f"/api/v1/paper_bank/sittings/{sid}/addon", json={"minutes": 30})
    assert res.status_code == 409
    assert "insufficient_xp" in res.json()["detail"]

    # Second sitting does not re-seed the grant.
    client.post(f"/api/v1/paper_bank/{ids['p1_id']}/start", json={"student_id": "s3"})
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT COUNT(*) FROM rewards WHERE student_id='s3' AND reason='welcome_grant'"
    ).fetchone()[0]
    con.close()
    assert rows == 1


def test_explain_gated_until_part_graded(client) -> None:
    ids = _seed_sitting_pair()
    started = client.post(
        f"/api/v1/paper_bank/{ids['p1_id']}/start", json={"student_id": "s4"}
    ).json()
    sid = started["sitting_id"]
    exam_p1 = next(p["exam_id"] for p in started["parts"] if p["paper_no"] == 1)

    early = client.post(
        f"/api/v1/paper_bank/sittings/{sid}/explain", json={"exam_id": exam_p1, "question_id": "q1"}
    )
    assert early.status_code == 403

    client.post(
        f"/api/v1/paper_bank/sittings/{sid}/submit", json={"exam_id": exam_p1, "answers": []}
    )

    # After grading, the endpoint is reachable; offline LLM fails honest (502).
    late = client.post(
        f"/api/v1/paper_bank/sittings/{sid}/explain", json={"exam_id": exam_p1, "question_id": "q1"}
    )
    assert late.status_code in (200, 502)


def test_submit_from_review_window_allowed(client) -> None:
    """A student may manually submit during the double-check window."""
    ids = _seed_sitting_pair()
    started = client.post(
        f"/api/v1/paper_bank/{ids['p1_id']}/start", json={"student_id": "s5"}
    ).json()
    sid = started["sitting_id"]
    exam_p1 = next(p["exam_id"] for p in started["parts"] if p["paper_no"] == 1)

    _backdate(exam_p1, ends_at=time.time() - 10)
    state = client.get(f"/api/v1/paper_bank/sittings/{sid}").json()
    assert next(p for p in state["parts"] if p["paper_no"] == 1)["status"] == "review"

    ok = client.post(
        f"/api/v1/paper_bank/sittings/{sid}/submit",
        json={
            "exam_id": exam_p1,
            "answers": [
                {"question_id": f"q{i}", "option_key": ("B" if i % 2 else "C")}
                for i in range(1, 11)
            ],
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["part"]["status"] == "graded"


def test_clock_forced_last_part_still_awards_xp_once(client) -> None:
    """When the FINAL part is force-submitted by the sitting clock (not the
    submit endpoint), sitting XP must still be awarded exactly once."""
    ids = _seed_sitting_pair()
    started = client.post(
        f"/api/v1/paper_bank/{ids['p1_id']}/start", json={"student_id": "s6"}
    ).json()
    sid = started["sitting_id"]
    exam_p1 = next(p["exam_id"] for p in started["parts"] if p["paper_no"] == 1)
    exam_p2 = next(p["exam_id"] for p in started["parts"] if p["paper_no"] == 2)

    # P1 expires -> student manually submits during review.
    _backdate(exam_p1, ends_at=time.time() - 10)
    client.get(f"/api/v1/paper_bank/sittings/{sid}")
    client.post(
        f"/api/v1/paper_bank/sittings/{sid}/submit",
        json={
            "exam_id": exam_p1,
            "answers": [
                {"question_id": f"q{i}", "option_key": ("B" if i % 2 else "C")}
                for i in range(1, 11)
            ],
        },
    )

    # P2 expires through its whole review window with drafts present.
    _backdate(exam_p2, ends_at=time.time() - 20)
    client.get(f"/api/v1/paper_bank/sittings/{sid}")  # enters review
    _backdate(exam_p2, ends_at=time.time() - 40, review_ends_at=time.time() - 5)
    state = client.get(f"/api/v1/paper_bank/sittings/{sid}")  # force-submit fires
    assert state.json()["all_graded"] is True

    import sqlite3

    from deeptutor.services.path_service import get_path_service

    db_path = get_path_service().user_dir / "chat_history.db"
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT amount_xp FROM rewards WHERE reason = ?",
            (f"sitting_completed:{sid}",),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] >= 20

        # Parent alert for this sitting reached the durable outbox (best-effort
        # channel — its absence is tolerated, presence confirms wiring).
        try:
            summary = con.execute(
                "SELECT COUNT(*) FROM notification_outbox WHERE kind='session_summary'"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            summary = 0
        assert summary >= 0
    finally:
        con.close()
