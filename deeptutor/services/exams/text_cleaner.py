"""Light normalization + Paper-I/Paper-II splitting for OCR'd past-paper text.

Input is the user's pre-cleaned corpus (watermarks/mastheads already removed,
Sinhala already Unicode). This layer only does structural work:

- drop residual figure-bleed noise lines (1-2 junk glyphs)
- collapse dotted/dashed answer-rule runs (incl. Sinhala ``෴``)
- locate the Paper-II section heading (EN + SI markers, fuzzy)
"""

from __future__ import annotations

from dataclasses import dataclass
import re

_JUNK_LINE_RE = re.compile(r"^(?:[^\w\u0d80-\u0dff]{1,3}|[ද෴r%*|xX]{1,4})$")
_DOT_RUN_RE = re.compile(r"(?:[.]{3,}|෴{2,}|_{3,})+")

_P2_STRICT_EN = (
    re.compile(r"^\s*Part\s*A\s*[—–-]+\s*Structured\s*Essay\s*:?\s*$", re.I),
    re.compile(r"^\s*Paper\s*(?:I{2}|II|02)\b\s*$", re.I),
)
_P2_LOOSE_EN = (
    re.compile(r"Part\s+A\b[^\n]{0,40}?Structured\s+Essay", re.I),
    re.compile(r"Part\s+(?:I{2}|2|II)\b.*(?:Three|3)\s*hours", re.I),
)
_P2_MARKERS_SI = (
    re.compile(r"^[^,\n]{0,14}කොටස\s*[-–—]?\s*[AB1බ]?.{0,24}රචනා"),
)


def _is_junk(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return bool(_JUNK_LINE_RE.match(s)) and len(s) <= 4


def normalize(text: str) -> str:
    """Normalize whitespace/noise while keeping line structure."""
    out: list[str] = []
    for raw in text.splitlines():
        line = _DOT_RUN_RE.sub("……", raw.rstrip())
        if _is_junk(line):
            out.append("")
            continue
        out.append(line)
    cleaned: list[str] = []
    blank = 0
    for line in out:
        if line.strip():
            blank = 0
            cleaned.append(line)
        else:
            blank += 1
            if blank <= 1:
                cleaned.append("")
    return "\n".join(cleaned).strip("\n")


@dataclass
class SplitResult:
    p1_text: str
    p2_text: str
    boundary_line: int
    marker: str


def _validated_heading(hits: list[tuple[int, str]], lines: list[str]) -> tuple[int, str]:
    for i, text in hits:
        for j in range(i + 1, min(i + 21, len(lines))):
            m = re.match(r"^\s*(\d{1,2})[\.)]\s+\S", lines[j])
            if m and int(m.group(1)) <= 6:
                return i, text
    return -1, ""


def _find_p2_heading(lines: list[str], start: int) -> tuple[int, str]:
    si_hits: list[tuple[int, str]] = []
    strict_hits: list[tuple[int, str]] = []
    loose_hits: list[tuple[int, str]] = []
    for i in range(start, len(lines)):
        s = lines[i]
        for rx in _P2_MARKERS_SI:
            m = rx.match(s)
            if m and len(s.strip()) < 60:
                si_hits.append((i, m.group(0).strip()))
        for rx in _P2_STRICT_EN:
            if rx.match(s):
                strict_hits.append((i, s.strip()))
        for rx in _P2_LOOSE_EN:
            m = rx.search(s)
            if m:
                loose_hits.append((i, m.group(0)))
    for source in (si_hits, strict_hits, loose_hits):
        i, text = _validated_heading(source, lines)
        if i >= 0:
            return i, text
    return -1, ""


def split_papers(
    text: str,
    *,
    mcq_count_hint: int = 50,
) -> SplitResult:
    """Split normalized text into Paper-I (MCQ) and Paper-II (structured).

    Marker headings first; falls back to a stem-numbering restart (a small
    question number appearing again well after the MCQ run).
    """
    lines = text.splitlines()
    idx, marker = _find_p2_heading(lines, 0)
    if idx >= 0:
        return SplitResult(
            p1_text="\n".join(lines[:idx]).strip(),
            p2_text="\n".join(lines[idx:]).strip(),
            boundary_line=idx,
            marker=marker.strip(),
        )

    running_max = 0
    for i, line in enumerate(lines):
        m = re.match(r"^\s*(\d{1,2})[\.)]\s+\S", line)
        if not m:
            continue
        n = int(m.group(1))
        if n < running_max - 10 and running_max >= mcq_count_hint * 0.7:
            return SplitResult(
                p1_text="\n".join(lines[:i]).strip(),
                p2_text="\n".join(lines[i:]).strip(),
                boundary_line=i,
                marker=f"numbering-restart:{n}",
            )
        running_max = max(running_max, n)
    return SplitResult(p1_text=text, p2_text="", boundary_line=-1, marker="none")


def _stem_numbers(lines: list[str], start: int, end: int) -> list[int]:
    nums = []
    for i in range(start, min(end, len(lines))):
        m = re.match(r"^\s*(\d{1,2})[\.)]\s+\S", lines[i])
        if m:
            nums.append(int(m.group(1)))
    return nums
