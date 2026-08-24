"""Unit tests for the cleaned-corpus pipeline (clean → segment → answers).

Covers the deterministic text layer only — no PDFs, no network:
- grade tagging rules (year ranges, OLD/NEW 2019 split, O/L)
- P1/P2 boundary splitting (EN heading + numbering-restart fallback)
- option-group-driven MCQ segmentation with detached stems
- numeric→letter key normalization and dual-source merging
"""

from __future__ import annotations

import pytest

from deeptutor.services.exams.cleaned_pipeline import _grade_for
from deeptutor.services.exams.question_segmenter import (
    merge_keys,
    segment_mcqs,
)
from deeptutor.services.exams.text_cleaner import normalize, split_papers

# ------------------------------------------------------------- grade rules


@pytest.mark.parametrize(
    "name,year,expected",
    [
        ("AL 2011 English Medium.txt", 2011, 12),
        ("AL 2018 Sinhala Medium.txt", 2018, 12),
        ("AL 2019 OLD English Medium.txt", 2019, 12),
        ("AL 2019 NEW English Medium.txt", 2019, 13),
        ("AL 2021 English Medium.txt", 2021, 13),
        ("AL 2025 Sinhala Medium.txt", 2025, 13),
        ("OL 2022 English Medium.txt", 2022, 11),
        ("OL 2024 Sinhala Medium.txt", 2024, 11),
    ],
)
def test_grade_for_year_rules(name: str, year: int, expected: int) -> None:
    assert _grade_for(year, name) == expected


def test_grade_for_none_year_is_none() -> None:
    assert _grade_for(None, "AL ???? English Medium.txt") is None


# ------------------------------------------------------------ P1/P2 split


EN_PAPER = """Instructions:
Answer all questions.

1. What is 2+2?
(1) 3
(2) 4
(3) 5
(4) 6
(5) 7

2. Pick the odd one.
(1) a
(2) b
(3) c
(4) d
(5) e

Part A — Structured Essay
Answer all four questions

1. (a) Write an algorithm. [05 marks]
2. (a) Explain DNS records. [10 marks]
"""


def test_split_papers_en_heading() -> None:
    sp = split_papers(normalize(EN_PAPER))
    assert "Structured Essay" in sp.marker or "heading" in sp.marker
    assert "(5) 7" in sp.p1_text
    assert sp.p2_text.startswith("Part A") or "Structured Essay" in sp.p2_text[:60]


def test_split_papers_numbering_restart_fallback() -> None:
    text = "\n".join(
        [
            f"{i}. Q{i}?\n(1) x\n(2) y\n(3) z\n(4) w\n(5) v\n"
            for i in range(1, 51)
        ]
    )
    text += "\n1. First essay question\n(a) part\n[10 marks]\n"
    sp = split_papers(normalize(text))
    assert sp.marker.startswith("numbering-restart")
    assert "50." in sp.p1_text and "essay" in sp.p2_text


# --------------------------------------------------------- MCQ segmentation


def test_segment_mcq_counts_and_option_keys() -> None:
    sp = split_papers(normalize(EN_PAPER))
    seg = segment_mcqs(sp.p1_text, expected_count=2, options_per_question=5)
    assert len(seg.questions) == 2
    q1 = seg.questions[0]
    assert set(q1.options.keys()) == {"A", "B", "C", "D", "E"}
    assert q1.options["B"] == "4"


def test_segment_mcq_detached_stems() -> None:
    """Stem numbers separated from content still yield sequential units."""
    raw = (
        "48.\n49.\n50.\n"
        "<html>code</html>\nWhich statement is correct?\n"
        "(1) one\n(2) two\n(3) three\n(4) four\n(5) five\n"
        "Another question body here.\n"
        "(1) alpha\n(2) beta\n(3) gamma\n(4) delta\n(5) epsilon\n"
        "Third question about PHP arrays.\n"
        "(1) red\n(2) green\n(3) blue\n(4) black\n(5) white\n"
    )
    seg = segment_mcqs(raw, expected_count=3, options_per_question=5)
    assert len(seg.questions) == 3
    assert all(len(q.options) == 5 for q in seg.questions)


def test_segment_mcq_inline_options() -> None:
    raw = "1. Choose binary digits.\n(1) 01 (2) 10 (3) 11 (4) 00 (5) all\n"
    seg = segment_mcqs(raw, expected_count=1, options_per_question=5)
    assert len(seg.questions) == 1
    assert sorted(seg.questions[0].options.keys()) == ["A", "B", "C", "D", "E"]


# --------------------------------------------------------------- key merge


def test_merge_keys_official_wins_and_conflicts_reported() -> None:
    official = {1: "B", 2: "C", 3: "ALL"}
    book = {1: "B", 2: "A", 3: "D", 4: "E"}
    merged, conflicts = merge_keys((official, "official-sheet"), (book, "review-book"))
    assert merged == {1: "B", 2: "C", 3: "ALL", 4: "E"}
    conflict_pairs = {(c["question"], c["kept"], c["dropped"]) for c in conflicts}
    assert (2, "C", "A") in conflict_pairs


def test_merge_keys_empty_sources() -> None:
    merged, conflicts = merge_keys()
    assert merged == {} and conflicts == []
