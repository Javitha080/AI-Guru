"""Cleaned-corpus pipeline: OCR text folder → inspectable artifacts → paper_bank rows.

Stage 1 ``build_artifacts``  — normalize + split P1/P2 + segment MCQs/essays +
        merge dual-source answer keys (official SHEET PDFs × review books) +
        harvest Key Points explanations; everything written as JSON/txt.
Stage 2 ``import_artifacts`` — read artifacts and upsert paper_bank rows via
        BankStore (deterministic ids per group+paper_no).
"""

from __future__ import annotations

from dataclasses import asdict
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from deeptutor.services.exams.bank_import import DEFAULT_DURATION_BY_TYPE
from deeptutor.services.exams.question_segmenter import (
    extract_book_answers,
    extract_keypoints,
    extract_sheet_keys,
    merge_keys,
    segment_essays,
    segment_mcqs,
)
from deeptutor.services.exams.text_cleaner import normalize, split_papers

logger = logging.getLogger(__name__)

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_GRADE12_MAX_YEAR = 2018

_MIN_MCQ_FULL_RATIO = 0.80


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _year_of(name: str, rel_parts: Tuple[str, ...]) -> Optional[int]:
    m = _YEAR_RE.search(name.lower())
    if m:
        return int(m.group(0))
    for part in reversed(rel_parts):
        m = _YEAR_RE.search(part.lower())
        if m:
            return int(m.group(0))
    return None


def _grade_for(meta_year: Optional[int], filename: str) -> Optional[int]:
    low = filename.lower()
    if "o-l" in low or re.search(r"\bol\b", low):
        return 11
    if meta_year is None:
        return None
    if meta_year <= _GRADE12_MAX_YEAR:
        return 12
    if meta_year == 2019:
        return 12 if re.search(r"\bold\b", low) else 13
    return 13


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(content, encoding="utf-8")
    except OSError:
        import time

        time.sleep(0.1)
        path.write_text(content, encoding="utf-8")


def _find_book_for_year(year: int, books_dir: Path) -> Optional[Path]:
    if not books_dir.is_dir():
        return None
    for p in sorted(books_dir.glob("*.txt")):
        m = _YEAR_RE.search(p.stem)
        if m and int(m.group(0)) == year:
            return p
    return None


def _sheet_for_year(year: int, papers_dirs: List[Path]) -> Optional[Path]:
    for d in papers_dirs:
        if not d.is_dir():
            continue
        hit = d / f"{year} AL ICT MCQ SHEET.pdf"
        if hit.exists():
            return hit
    return None


def build_artifacts(
    source_dir: str | Path,
    out_dir: str | Path,
    *,
    raw_books_dir: Optional[str | Path] = None,
    sheet_dirs: Optional[List[str | Path]] = None,
) -> Dict[str, Any]:
    """Clean + segment every past-paper txt under source_dir into out_dir."""
    src = Path(source_dir)
    dst = Path(out_dir)
    books_dir = (
        Path(raw_books_dir)
        if raw_books_dir
        else src.parent / "ictfromabc_ocr_text" / "PDFs" / "Past Paper Books"
    )
    sheet_search: List[Path] = [Path(p) for p in (sheet_dirs or [])]
    sheet_search.insert(0, src)
    sheet_search.append(src.parent)

    pdf_files = sorted(src.rglob("*.pdf"))
    txt_files = [
        p
        for p in sorted(src.rglob("*.txt"))
        if ("Past Papers" in str(p) or "past papers" in str(p))
        and not any(x in p.name for x in ["MCQ SHEET", "Review", "REVIEW", "විවරණය"])
    ]

    report: Dict[str, Any] = {"files": [], "books": 0}
    for txt in txt_files:
        rel = txt.relative_to(src)
        is_al = "A-L" in str(rel)
        expected_mcq = 50 if is_al else 40
        options_n = 5 if is_al else 4

        text = normalize(_read(txt))
        sp = split_papers(text, mcq_count_hint=expected_mcq)
        mcq = segment_mcqs(sp.p1_text, expected_count=expected_mcq, options_per_question=options_n)
        essays = segment_essays(sp.p2_text) if sp.p2_text else []

        stem_txt = txt.stem
        year = _year_of(stem_txt, tuple(rel.parts[:-1]))
        grade = _grade_for(year, str(rel))

        full = sum(1 for q in mcq.questions if len(q.options) == options_n)
        quality_ok = (
            year is not None
            and grade is not None
            and mcq.questions
            and len(mcq.questions) >= expected_mcq * 0.9
            and (full / max(1, len(mcq.questions))) >= _MIN_MCQ_FULL_RATIO
        )

        part_base = dst / rel.parent / stem_txt
        part_base.parent.mkdir(parents=True, exist_ok=True)
        _write_text(dst / rel.parent / f"{stem_txt}.p1.txt", sp.p1_text)
        _write_text(dst / rel.parent / f"{stem_txt}.p2.txt", sp.p2_text)
        _write_text(
            dst / rel.parent / f"{stem_txt}.mcq.json",
            json.dumps([asdict(q) for q in mcq.questions], ensure_ascii=False, indent=1),
        )
        _write_text(
            dst / rel.parent / f"{stem_txt}.essay.json",
            json.dumps([asdict(q) for q in essays], ensure_ascii=False, indent=1),
        )

        answers_payload: Dict[str, Any] = {"keys": {}, "conflicts": [], "sources": []}
        keypoints_path = None
        book = _find_book_for_year(year, books_dir) if year else None
        if quality_ok and book and book.exists():
            book_text = _read(book)
            book_keys = extract_book_answers(book_text, mcq_count=expected_mcq)
            keypoints = extract_keypoints(book_text, mcq_count=expected_mcq)
            keypoints_path = part_base.parent / f"Review {year}.keypoints.json"
            _write_text(
                keypoints_path,
                json.dumps(keypoints, ensure_ascii=False, indent=1),
            )

            sheet = _sheet_for_year(year, sheet_search) if year is not None else None
            sources: List[Tuple[Dict[int, str], str]] = []
            if sheet:
                sk = extract_sheet_keys(sheet)
                if sk:
                    sources.append((sk, "official-sheet"))
            if book_keys:
                sources.append((book_keys, "review-book"))
            merged, conflicts = merge_keys(*sources)
            answers_payload = {
                "keys": {str(k): v for k, v in merged.items()},
                "conflicts": conflicts,
                "sources": [label for _, label in sources],
                "book_conflict_ratio": round(len(conflicts) / max(1, len(merged)), 3),
            }
            report["books"] += 1

        _write_text(
            dst / rel.parent / f"{stem_txt}.answers.json",
            json.dumps(answers_payload, ensure_ascii=False, indent=1),
        )

        report["files"].append(
            {
                "file": str(rel),
                "year": year,
                "grade": grade,
                "mcq_found": len(mcq.questions),
                "mcq_full_options": full,
                "essay_found": len(essays),
                "answers": len(answers_payload.get("keys") or {}),
                "quality_ok": bool(quality_ok),
                "split_marker": sp.marker[:48],
            }
        )

    unused_pdfs = len(pdf_files)
    report["pdfs_present"] = unused_pdfs
    return report


# ---------------------------------------------------------------------------
# Stage 2: artifacts → paper_bank rows
# ---------------------------------------------------------------------------


def import_artifacts(artifacts_dir: str | Path) -> Dict[str, Any]:
    """Upsert paper_bank rows from a build_artifacts output tree."""
    import asyncio

    from deeptutor.services.exams.bank_store import BankStore

    root = Path(artifacts_dir)
    rows_written = 0
    skipped: List[str] = []

    async def _run() -> None:
        nonlocal rows_written
        for mcq_path in sorted(root.rglob("*.mcq.json")):
            base = mcq_path.with_suffix("")
            orig_name = base.name
            for part_suffix in (".p1", ".p2", ".mcq"):
                orig_name = orig_name.replace(part_suffix, "")
            essay_path = base.parent / f"{orig_name}.essay.json"
            answers_path = base.parent / f"{orig_name}.answers.json"

            year_m = _YEAR_RE.search(orig_name)
            year = int(year_m.group(0)) if year_m else None
            grade = _grade_for(year, orig_name)
            medium = (
                "sinhala"
                if "sinhala" in orig_name.lower()
                else ("tamil" if "tamil" in orig_name.lower() else "english")
            )
            level = "ol" if "OL" in orig_name else "al"
            subject = f"ict-{level}" if level == "ol" else "ict"

            mcqs = json.loads(_read(mcq_path))
            essays = json.loads(_read(essay_path)) if essay_path.exists() else []
            answers = json.loads(_read(answers_path)) if answers_path.exists() else {}
            keys: Dict[str, str] = answers.get("keys", {})
            keypoints_path = base.parent / f"Review {year}.keypoints.json"
            keypoints: Dict[str, str] = (
                json.loads(_read(keypoints_path)) if keypoints_path.exists() else {}
            )

            if not mcqs or not keys or year is None or grade is None:
                skipped.append(orig_name)
                continue

            group_key = f"{subject}-{year}-g{grade}"
            if medium != "english":
                group_key += f"-{medium[:2]}"

            def make_row(
                paper_no: int,
                title: str,
                questions: List[Dict[str, Any]],
                qtype: str,
                duration: int,
            ) -> Dict[str, Any]:
                is_mcq = qtype == "choice"
                paper_type = "mcq" if is_mcq else "structured"
                qs_out = []
                marks_each = 1.0 if is_mcq else None
                for i, q in enumerate(questions, start=1):
                    entry: Dict[str, Any] = {
                        "id": f"{group_key}-p{paper_no}-q{i}",
                        "number": int(q.get("number") or i),
                        "question_type": qtype,
                        "text": str(q.get("stem") or q.get("text") or "")[:6000],
                        "options": q.get("options") or None,
                        "marks": marks_each or float(q.get("marks_total") or 1),
                        "reference_answer": None,
                        "explanation": None,
                    }
                    num = str(entry["number"])
                    if is_mcq:
                        key = keys.get(num)
                        if key:
                            entry["reference_answer"] = key
                            kp = keypoints.get(num)
                            if kp:
                                entry["explanation"] = kp[:4000]
                    qs_out.append(entry)
                total_marks = sum(float(q["marks"]) for q in qs_out)
                scheme = {
                    str(q["number"]): keys[str(q["number"])]
                    for q in qs_out
                    if keys.get(str(q["number"]))
                }
                return {
                    "id": f"{group_key}-p{paper_no}",
                    "group_key": group_key,
                    "paper_no": paper_no,
                    "grade": grade,
                    "subject": subject,
                    "year": year,
                    "medium": medium,
                    "paper_type": paper_type,
                    "title": title,
                    "source_filename": orig_name + ".txt",
                    "file_hash": "cleaned-" + f"{group_key}-p{paper_no}",
                    "question_count": len(qs_out),
                    "mcq_count": len(qs_out) if is_mcq else 0,
                    "essay_count": 0 if is_mcq else len(qs_out),
                    "total_marks": total_marks,
                    "default_duration_seconds": duration,
                    "paper_json": {
                        "exam_id": f"{group_key}-p{paper_no}",
                        "title": title,
                        "source_filename": orig_name + ".txt",
                        "status": "created",
                        "total_marks": total_marks,
                        "mcq_duration_seconds": duration,
                        "essay_duration_seconds": None,
                        "questions": qs_out,
                    },
                    "scheme_answers": scheme,
                    "topic_tags": [],
                    "created_at": time.time(),
                }

            label = f"ICT {year} G{grade} ({medium.title()})"
            rows = []
            if mcqs:
                rows.append(
                    make_row(
                        1, f"{label} Paper 1 (MCQ)", mcqs, "choice", DEFAULT_DURATION_BY_TYPE["mcq"]
                    )
                )
            if essays:
                rows.append(
                    make_row(
                        2,
                        f"{label} Paper 2 (Structured)",
                        essays,
                        "structured",
                        DEFAULT_DURATION_BY_TYPE["structured"],
                    )
                )
            for row in rows:
                await BankStore.upsert_paper(row)
                rows_written += 1

    asyncio.run(_run())
    return {"rows_written": rows_written, "skipped": skipped}
