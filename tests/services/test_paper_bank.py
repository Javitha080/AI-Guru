"""Paper-Bank tests: classification, key parsing, store round-trip, and the
bulk-import job (happy path with scheme pairing, quality gate, resumability).

Runs fully offline — the MinerU parse + LLM extraction layers are monkeypatched
the same way as tests/agents/question/test_mimic_source.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.services.exams.bank_import import (
    DEFAULT_DURATION_BY_TYPE,
    PaperMeta,
    _text_quality,
    attach_mcq_keys,
    classify_filename,
    parse_mcq_keys,
)


@pytest.fixture()
def isolated_home(tmp_path: Path, monkeypatch):
    """Point the path service at a throwaway workspace (never touch user data)."""
    from deeptutor.services import path_service as ps

    svc = ps.PathService(workspace_root=tmp_path)
    monkeypatch.setattr(ps.PathService, "_instance", svc, raising=False)
    return svc


# ------------------------------------------------------------------ classify


def test_classify_full_convention() -> None:
    meta = classify_filename("2021-ICT-P1-G12-EN.pdf")
    assert (meta.subject, meta.year, meta.paper_no, meta.paper_type,
            meta.grade, meta.medium, meta.is_scheme) == (
        "ict", 2021, 1, "mcq", 12, "english", False)
    assert meta.group_key == "ict-2021-g12"


def test_classify_scheme_sinhala_paper2() -> None:
    meta = classify_filename("ICT-2020-Paper-II-Sinhala-Marking-Scheme.pdf")
    assert meta.is_scheme and meta.paper_no == 2 and meta.medium == "sinhala"


def test_classify_unknown_stays_default_subject() -> None:
    meta = classify_filename("random-file.pdf")
    assert meta.year is None and meta.grade is None and meta.subject == "ict"


def test_classify_bare_numbers_are_not_grade() -> None:
    meta = classify_filename("biology paper 2 2018.pdf")
    assert meta.grade is None and meta.paper_no == 2 and meta.year == 2018


def test_group_key_suffixes_non_english() -> None:
    meta = PaperMeta(subject="ict", year=2019, grade=13, medium="tamil")
    assert meta.group_key == "ict-2019-g13-ta"


# --------------------------------------------------------------- answer keys


def test_parse_mcq_keys_line_table_and_paren_forms() -> None:
    keys = parse_mcq_keys("1 B   2 C   03 A\n(14) D\n25-E")
    assert keys == {1: "B", 2: "C", 3: "A", 14: "D", 25: "E"}
    assert parse_mcq_keys("") == {}


def test_parse_mcq_keys_numeric_and_grid() -> None:
    # Numeric answers (1..5) common in Sri Lankan marking schemes
    keys = parse_mcq_keys("1 - 2\n2: 4\n3. (1)\n04 - (5)\n5. (3)")
    assert keys == {1: "B", 2: "D", 3: "A", 4: "E", 5: "C"}

    # Grid format
    grid_keys = parse_mcq_keys("1.\n 3\n2.\n All\n3.\n 5")
    assert grid_keys == {1: "C", 2: "ALL", 3: "E"}


def test_split_options_sinhala_and_numeric() -> None:
    from deeptutor.services.exams.engine import split_options

    # Sinhala numeral options (1)-(5)
    si_stem = "1. පරිගණකයක ප්‍රධාන මතකය කුමක්ද?\n(1) RAM\n(2) ROM\n(3) HDD\n(4) SSD\n(5) Cache"
    clean_stem, opts = split_options(si_stem)
    assert opts is not None
    assert len(opts) == 5
    assert opts["A"] == "RAM"
    assert opts["B"] == "ROM"
    assert opts["E"] == "Cache"

    # Sinhala letter options (අ)-(ඉ)
    si_letters = "ප්‍රශ්නය\n(අ) පළමු තේරීම\n(ආ) දෙවන තේරීම\n(ඇ) තෙවන තේරීම\n(ඈ) සිව්වන තේරීම\n(ඉ) පස්වන තේරීම"
    clean_stem2, opts2 = split_options(si_letters)
    assert opts2 is not None
    assert len(opts2) == 5
    assert opts2["A"] == "පළමු තේරීම"
    assert opts2["E"] == "පස්වන තේරීම"


def test_grade_mcq_interchangeable() -> None:
    from deeptutor.services.exams.engine import ExamQuestion, grade_mcq

    q = ExamQuestion(id="q1", number=1, question_type="choice", text="Q1", reference_answer="3", marks=1.0)
    # Student answered letter 'C' (3rd option)
    assert grade_mcq(q, option_key="C") is True

    # Student answered numeric '3'
    assert grade_mcq(q, option_key="3") is True

    # Wrong answer
    assert grade_mcq(q, option_key="A") is False


def test_attach_keys_leading_number_then_positional_fallback() -> None:
    from deeptutor.services.exams.engine import ExamQuestion

    qs = [
        ExamQuestion(id="q_1", number=1, question_type="choice",
                     text="1. Pick A) x B) y C) z D) w", options={"A": "x"}),
        ExamQuestion(id="q_2", number=2, question_type="choice",
                     text="Pick two A) x B) y C) z D) w", options={"A": "x"}),
    ]
    assert attach_mcq_keys(qs, {1: "C", 2: "B"}) == 2
    assert qs[0].reference_answer == "C" and qs[1].reference_answer == "B"

    qs2 = [ExamQuestion(id="q_5", number=5, question_type="written", text="Explain.")]
    assert attach_mcq_keys(qs2, {5: "A"}) == 1
    assert qs2[0].reference_answer == "A"
    assert attach_mcq_keys(qs2, {99: "D"}) == 0


# ------------------------------------------------------------ text quality


def test_text_quality_flags_mojibake_and_private_use() -> None:
    # 'amma' written in Sinhala script — must survive as sane text.
    good = "Normal Sinhala \u0d85\u0db8\u0dca\u0db8\u0dcf + english 123"
    assert _text_quality(good) > 0.95
    bad = "abc \ufffd\ufffd \ue000\ue001"
    assert _text_quality(bad) < 0.9
    assert _text_quality("") == 0.0


# ------------------------------------------------------------------- store


@pytest.mark.asyncio
async def test_bank_store_roundtrip(isolated_home) -> None:
    from deeptutor.services.exams.bank_store import BankStore

    row = {
        "id": "ict-2021-g12-p1", "group_key": "ict-2021-g12", "paper_no": 1,
        "grade": 12, "subject": "ict", "year": 2021, "medium": "english",
        "paper_type": "mcq", "title": "ICT 2021 P1", "file_hash": "h1",
        "question_count": 50, "mcq_count": 50, "essay_count": 0,
        "total_marks": 50, "default_duration_seconds": 7200,
        "paper_json": {"exam_id": "x", "questions": []},
        "scheme_answers": {"1": "B"}, "topic_tags": [],
    }
    rid = await BankStore.upsert_paper(row)
    assert rid == row["id"]
    assert (await BankStore.get_by_hash("h1"))["id"] == rid
    assert await BankStore.get_by_hash("missing") is None

    cat = await BankStore.catalog(subject="ict", grade=12, year=2021)
    assert len(cat) == 1 and "paper_json" not in cat[0]

    fac = await BankStore.facets()
    assert fac["total_papers"] == 1 and fac["subjects"] == ["ict"]

    grp = await BankStore.get_by_group("ict-2021-g12")
    assert len(grp) == 1 and grp[0]["paper_no"] == 1

    assert await BankStore.delete_paper(rid) is True
    assert await BankStore.catalog() == []


# ------------------------------------------------------------------- import


def _write_scheme_pdf(path: Path, count: int) -> None:
    """Real PDF whose embedded text carries MCQ keys (3 short lines)."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    per_line = (count + 2) // 3
    for li in range(3):
        lo, hi = li * per_line + 1, min(count, (li + 1) * per_line)
        if lo > hi:
            break
        line = " ".join(f"{i} {'ABCDEF'[i % 5]}" for i in range(lo, hi + 1))
        page.insert_text((72, 72 + li * 24), line)
    doc.save(str(path))
    doc.close()


def _questions_payload(count: int, *, kind: str = "choice") -> dict:
    if kind == "choice":
        questions = [
            {
                "question_text": f"{i}. Two's complement is used for? "
                                 f"A) signs B) negatives C) floats D) none",
                "question_type": "choice",
            }
            for i in range(1, count + 1)
        ]
    else:
        questions = [
            {"question_text": f"{i}. Explain DNS.", "question_type": "written"}
            for i in range(1, count + 1)
        ]
    return {"questions": questions}


@pytest.fixture()
def fake_extraction(monkeypatch):
    """Replace the parse+LLM-extract layers with deterministic fixtures."""
    from deeptutor.agents.question import mimic_source
    from deeptutor.services.parsing.types import ParsedDocument

    def install(folder: Path, payload: dict) -> None:
        cache_dir = folder / "_parse_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        class _FakeService:
            def parse(self, source_path, **kwargs):
                return ParsedDocument(
                    markdown="# parsed", workdir=cache_dir, engine="fake", source_hash="h"
                )

        monkeypatch.setattr(mimic_source, "get_parse_service", lambda: _FakeService())

        def _fake_extract(paper_dir, output_dir=None):
            out = Path(output_dir or paper_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / "exam_questions.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            return True

        monkeypatch.setattr(mimic_source, "extract_questions_from_paper", _fake_extract)

    return install


@pytest.mark.asyncio
async def test_import_job_happy_path_pairs_marking_scheme(
    isolated_home, tmp_path, fake_extraction
) -> None:
    folder = tmp_path / "alpapers"
    folder.mkdir()
    (folder / "2021-ICT-P1-G12-EN.pdf").write_bytes(b"%PDF-fake")
    _write_scheme_pdf(folder / "2021-ICT-P1-G12-EN-Marking-Scheme.pdf", 12)

    fake_extraction(folder, _questions_payload(12))

    from deeptutor.services.exams.bank_import import BankImportJob
    from deeptutor.services.exams.bank_store import BankStore

    job = BankImportJob(folder, solve_missing=False)
    snap = await job.run()

    by_name = {Path(i["filename"]).name: i for i in snap["items"]}
    assert by_name["2021-ICT-P1-G12-EN.pdf"]["status"] == "imported"
    assert by_name["2021-ICT-P1-G12-EN-Marking-Scheme.pdf"]["status"] == "skipped"
    assert "marking scheme" in by_name["2021-ICT-P1-G12-EN-Marking-Scheme.pdf"]["detail"]

    row = await BankStore.get_paper("ict-2021-g12-p1")
    assert row is not None
    assert row["mcq_count"] == 12 and row["question_count"] == 12
    assert row["default_duration_seconds"] == DEFAULT_DURATION_BY_TYPE["mcq"]
    paper_json = row["paper_json"]
    assert isinstance(paper_json, dict), "paper_json must be deserialized"
    answers = {q["number"]: q["reference_answer"] for q in paper_json["questions"]}
    # Scheme keys came from the paired PDF (generator maps 1->'B', 12->'C').
    stored_keys = row["scheme_answers_json"]
    assert isinstance(stored_keys, dict) and stored_keys["1"] == "B" and stored_keys["12"] == "C"
    # And the stamped reference answers match the scheme.
    assert answers[1] == stored_keys["1"] and answers[12] == stored_keys["12"]


@pytest.mark.asyncio
async def test_import_job_quality_gate_routes_to_review(
    isolated_home, tmp_path, fake_extraction
) -> None:
    folder = tmp_path / "alpapers"
    folder.mkdir()
    (folder / "2019-ICT-P2-G13-EN.pdf").write_bytes(b"%PDF-fake")

    # Only 4 essay questions (< minimum 5) -> needs_review, nothing stored.
    fake_extraction(folder, _questions_payload(4, kind="written"))

    from deeptutor.services.exams.bank_import import BankImportJob
    from deeptutor.services.exams.bank_store import BankStore

    job = BankImportJob(folder, solve_missing=False)
    snap = await job.run()

    assert snap["items"][0]["status"] == "needs_review"
    assert "only 4 questions" in snap["items"][0]["detail"]
    assert await BankStore.catalog() == []


@pytest.mark.asyncio
async def test_import_job_is_resumable_via_state(
    isolated_home, tmp_path, fake_extraction
) -> None:
    folder = tmp_path / "alpapers"
    folder.mkdir()
    (folder / "2018-ICT-P1-G12-EN.pdf").write_bytes(b"%PDF-fake")
    fake_extraction(folder, _questions_payload(12))

    from deeptutor.services.exams.bank_import import BankImportJob
    from deeptutor.services.exams.bank_store import BankStore

    first = await BankImportJob(folder, solve_missing=False).run()
    assert first["items"][0]["status"] == "imported"

    # Second run over the SAME folder: hash already recorded -> skipped,
    # extraction must never run again; no duplicate catalog rows either.
    second = await BankImportJob(folder, solve_missing=False).run()
    assert second["items"][0]["status"] == "skipped"
    assert len(await BankStore.catalog()) == 1
