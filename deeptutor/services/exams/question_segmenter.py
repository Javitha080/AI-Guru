"""Segment OCR'd past-paper text into structured questions + answer keys.

MCQ segmentation is OPTION-GROUP-DRIVEN: every MCQ owns a block of
``(1)…(5)`` (A/L) or ``(1)…(4)`` (O/L) option markers, so the text between
consecutive option groups is that question's stem — even when the printed
stem number got separated from its content during OCR/cleaning.

Answer keys come from two independent sources and are cross-validated:
- official ``MCQ SHEET`` PDFs (embedded numeric grids, fitz)
- Past-Paper Review books (inline ``Answer : N )`` + Key Points explanations)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

_OPTION_TOKEN_RE = re.compile(r"\((1|2|3|4|5)\)")
_OPTION_TOKEN_LOOSE_RE = re.compile(r"\((1|2|3|4|5)\)?")
_STEM_MARK_RE = re.compile(r"^\s*(\d{1,2})[\.)]\s*(.*)$")
_BARE_STEM_RE = re.compile(r"^\s*(\d{1,2})[\.)]\s*$")
_ANSWER_LINE_RE = re.compile(r"Answer\s*[:\-]?\s*(\d{1,2}|All|all)\s*\)?")
_KEYPOINT_RE = re.compile(r"Key\s*Points?\s+of\s+MCQ", re.I)
_BOOK_STEM_RE = re.compile(r"^\s*(\d{1,2})\.\s+\S")
_MARKS_RE = re.compile(r"[\[(]\s*(\d{1,2})\s*(?:marks?|ලකුණු)[\]|)|.]?", re.I)

_NUMERIC_TO_LETTER = {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"}


@dataclass
class McqQuestion:
    number: int
    stem: str
    options: Dict[str, str] = field(default_factory=dict)


@dataclass
class EssayQuestion:
    number: int
    part: str
    text: str
    marks_total: Optional[float] = None


@dataclass
class McqSegmentation:
    questions: List[McqQuestion]
    groups_found: int
    short_option_units: List[int]


def _find_option_groups(
    lines: List[str], max_option: int, min_distinct: int
) -> List[Tuple[int, int]]:
    """Return [start_line, end_line] spans of option blocks.

    Clusters consecutive/adjacent option-token lines, then merges clusters
    whose union still fits one question's option set (OCR often splits a
    single ``(1)…(5)`` block across blank-line gaps).
    """
    clusters: List[Tuple[int, int]] = []
    cur_start: Optional[int] = None
    cur_end = -1
    last_tok_line = -10
    for i, line in enumerate(lines):
        if _OPTION_TOKEN_LOOSE_RE.search(line):
            if cur_start is None:
                cur_start = i
            cur_end = i
            last_tok_line = i
        elif cur_start is not None and i - last_tok_line > 2:
            clusters.append((cur_start, cur_end))
            cur_start = None
    if cur_start is not None:
        clusters.append((cur_start, cur_end))

    def distinct_keys(a: int, b: int) -> set:
        ks: set = set()
        for i in range(max(0, a), min(b + 1, len(lines))):
            for k in _OPTION_TOKEN_LOOSE_RE.findall(lines[i]):
                ks.add(int(k))
        return ks

    # Split fused clusters where the numbering restarts at (1) mid-cluster
    # (two questions whose option blocks sat only 1-2 lines apart).
    split: List[Tuple[int, int]] = []
    for a, b in clusters:
        segs: List[List[int]] = [[a, a]]
        seen: set = set()
        for i in range(a, b + 1):
            keys = [int(k) for k in _OPTION_TOKEN_LOOSE_RE.findall(lines[i])]
            if 1 in keys and len(seen) >= 3:
                segs.append([i, i])
                seen = set()
            elif keys:
                segs[-1][1] = i
            seen.update(keys)
        split.extend((s[0], s[1]) for s in segs)
    clusters = split

    merged: List[Tuple[int, int]] = []
    for cl in clusters:
        if merged:
            pa, pb = merged[-1]
            prev_keys = distinct_keys(pa, pb)
            union = prev_keys | distinct_keys(*cl)
            gap = cl[0] - pb
            if len(prev_keys) < max_option and gap <= 8 and len(union) <= max_option:
                merged[-1] = (pa, cl[1])
                continue
        merged.append(cl)

    return [sp for sp in merged if len(distinct_keys(*sp)) >= min_distinct]


def _options_from_span(lines: List[str], start: int, end: int, max_option: int) -> Dict[str, str]:
    """Pair option markers with their text across the group span.

    Tolerates inline groups (``(1) x (2) y``), multi-line values and the
    OCR variant with a missing closing paren (``(4 value``).
    """
    options: Dict[str, str] = {}
    buf_key: Optional[str] = None
    buf_val: List[str] = []

    def flush() -> None:
        nonlocal buf_key, buf_val
        if buf_key is not None:
            options.setdefault(buf_key, " ".join(v.strip() for v in buf_val).strip(" ;,."))
        buf_key, buf_val = None, []

    for i in range(start, min(end + 3, len(lines))):
        line = lines[i]
        matches = list(_OPTION_TOKEN_LOOSE_RE.finditer(line))
        if not matches:
            if buf_key is not None and line.strip():
                buf_val.append(line.strip())
            continue
        lead = line[: matches[0].start()].strip()
        if lead and buf_key is not None:
            buf_val.append(lead)
        for idx_m, m in enumerate(matches):
            k = int(m.group(1))
            if k > max_option:
                continue
            flush()
            buf_key = _NUMERIC_TO_LETTER[str(k)]
            seg_end = matches[idx_m + 1].start() if idx_m + 1 < len(matches) else len(line)
            buf_val.append(line[m.end() : seg_end].strip())
    flush()
    return {k: v for k, v in options.items() if v}


def segment_mcqs(
    p1_text: str,
    *,
    expected_count: int,
    options_per_question: int,
    stop_after: Optional[int] = None,
) -> McqSegmentation:
    """Split Paper-I text into MCQ units via their option groups."""
    lines = p1_text.splitlines()
    lines = _strip_instructions_preamble(lines)
    min_distinct = max(3, options_per_question - 2)
    spans = _find_option_groups(lines, options_per_question, min_distinct)
    limit = stop_after or expected_count

    questions: List[McqQuestion] = []
    prev_end = -1
    pending_num: Optional[int] = None
    last_num = 0
    for counter, (start, end) in enumerate(spans[:limit], start=1):
        stem_lines: List[str] = []
        for i in range(prev_end + 1, start):
            s = lines[i].strip()
            if not s:
                continue
            bare = _BARE_STEM_RE.match(lines[i])
            if bare and i < start - 1:
                continue
            m = _STEM_MARK_RE.match(lines[i])
            if m and m.group(2).strip():
                try:
                    n = int(m.group(1))
                    if abs(n - counter) <= 2 or (last_num < n <= counter):
                        pending_num = n
                except ValueError:
                    pass
            stem_lines.append(s)
        stem = "\n".join(stem_lines).strip()
        options = _options_from_span(lines, start, end, options_per_question)
        number = pending_num if pending_num is not None else counter
        pending_num = None
        last_num = number
        questions.append(McqQuestion(number=number, stem=stem, options=options))
        prev_end = end

    short = [q.number for q in questions if len(q.options) < options_per_question]
    return McqSegmentation(questions=questions, groups_found=len(spans), short_option_units=short)


def _strip_instructions_preamble(lines: List[str]) -> List[str]:
    """Drop everything before the first real ``1.`` stem (instructions block).

    The exam instructions quote ``(1)…(5)`` and would otherwise form a fake
    option group that swallows Question 1.
    """
    for i, line in enumerate(lines[:35]):
        m = re.match(r"^\s*1\s*[\.)]\s+(\S.*)$", line)
        if m and len(m.group(1)) > 8:
            return lines[i:]
    # If no explicit '1.' in the first 35 lines, look for end of instructions
    for i, line in enumerate(lines[:35]):
        s = line.strip()
        if any(
            marker in s
            for marker in [
                "කතිරයක්",
                "කවය තුළ",
                "නොලැබේ",
                "කියවා පිළිපදින්න",
                "උපදෙස් පරිදි",
                "not allowed",
                "Follow those carefully",
                "answer sheet with a cross",
            ]
        ):
            return lines[i + 1 :]
    return lines


def segment_essays(p2_text: str, *, part_label: str = "B") -> List[EssayQuestion]:
    """Split Paper-II text into top-level essay/structured questions."""
    lines = p2_text.splitlines()
    starts: List[Tuple[int, int]] = []
    for i, line in enumerate(lines):
        m = re.match(r"^\s*(\d{1,2})\s*[\.)]\s+(\S.*)$", line)
        if not m:
            continue
        rest = m.group(2).strip()
        if rest[0] in "<${" or len(rest) < 15:
            continue
        n = int(m.group(1))
        if 1 <= n <= 12:
            starts.append((i, n))
    if not starts:
        return []
    out: List[EssayQuestion] = []
    for idx, (i, n) in enumerate(starts):
        j = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        block = "\n".join(lines[i:j]).strip()
        marks_list = [float(mv) for mv in _MARKS_RE.findall(block)]
        total = sum(marks_list) if marks_list else None
        out.append(
            EssayQuestion(number=n or idx + 1, part=part_label, text=block, marks_total=total)
        )
    return out


def extract_book_answers(book_text: str, *, mcq_count: int) -> Dict[int, str]:
    """Per-question answers from a review book: ``Answer : N )`` / ``All``."""
    lines = book_text.splitlines()
    answers: Dict[int, str] = {}
    current: Optional[int] = None
    for line in lines:
        m = _BOOK_STEM_RE.match(line)
        if m:
            n = int(m.group(1))
            if 1 <= n <= mcq_count:
                current = n
                continue
        am = _ANSWER_LINE_RE.search(line)
        if am and current is not None:
            raw = am.group(1).lower()
            answers.setdefault(current, "ALL" if raw == "all" else _NUMERIC_TO_LETTER.get(raw, ""))
            current = None
    return {k: v for k, v in answers.items() if v}


def extract_sheet_keys(pdf_path: Path, *, read_pdf_text=None) -> Dict[int, str]:
    """Numeric answer grid from an official MCQ-SHEET PDF (fitz embedded text)."""
    if read_pdf_text is None:
        from deeptutor.services.exams.bank_import import read_pdf_text as read_pdf_text_fn

        read_pdf_text = read_pdf_text_fn
    text = read_pdf_text(Path(pdf_path), max_pages=60) or ""
    keys: Dict[int, str] = {}
    for num_raw, ans in re.findall(r"(\d{1,2})\s*\.\s*\n\s*(All|all|[1-5])\b", text):
        n = int(num_raw)
        if 1 <= n <= 200:
            keys[n] = "ALL" if ans.lower() == "all" else _NUMERIC_TO_LETTER[ans]
    return keys


def merge_keys(
    *sources: Tuple[Dict[int, str], str],
) -> Tuple[Dict[int, str], List[Dict[str, object]]]:
    """Merge keyed sources in priority order; report conflicts.

    Each source is ``(keys, label)``; earlier labels win. Returns
    ``(merged, conflicts)`` where conflicts list every disagreement.
    """
    merged: Dict[int, str] = {}
    owner: Dict[int, str] = {}
    conflicts: List[Dict[str, object]] = []
    for keys, label in sources:
        for n, v in keys.items():
            if not v:
                continue
            if n in merged:
                if merged[n] != v:
                    conflicts.append(
                        {
                            "question": n,
                            "kept": merged[n],
                            "dropped": v,
                            "kept_from": owner[n],
                            "dropped_from": label,
                        }
                    )
                continue
            merged[n] = v
            owner[n] = label
    return merged, conflicts


_JUNK_BOOK_LINE_RE = re.compile(
    r"(?:bandaranayake|#ictfromabc|^\s*-{0,3}\s*\d{1,3}\s*-{0,3}\s*$)", re.I
)


def extract_keypoints(book_text: str, *, mcq_count: int) -> Dict[int, str]:
    """Explanation text following each question's ``Answer`` line.

    Most questions carry a bilingual explanation directly after the answer
    (with or without an explicit ``Key Points`` heading); capture runs from
    the answer line to the next question stem.
    """
    lines = book_text.splitlines()
    out: Dict[int, str] = {}
    current: Optional[int] = None
    capturing = False
    buf: List[str] = []

    def flush() -> None:
        nonlocal capturing, buf
        if current is not None and buf:
            text = "\n".join(buf).strip()
            if len(text) >= 30:
                out.setdefault(current, text[:4000])
        capturing = False
        buf = []

    for line in lines:
        m = _BOOK_STEM_RE.match(line)
        if m and int(m.group(1)) <= mcq_count:
            flush()
            current = int(m.group(1))
            capturing = False
            continue
        s = line.strip()
        if not s or _JUNK_BOOK_LINE_RE.search(s):
            continue
        if _ANSWER_LINE_RE.search(s):
            flush()
            capturing = True
            continue
        if _KEYPOINT_RE.search(s):
            continue
        if capturing:
            buf.append(s)
    flush()
    return out
