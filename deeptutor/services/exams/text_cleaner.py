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

import unicodedata

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
    re.compile(r"^[^,\n]{0,25}කොටස\s*[-–—]?\s*[AB1බ]?.{0,30}රචනා", re.I),
    re.compile(r"^[^,\n]{0,25}[AB12]\s*කොටස\s*[-–—]?\s*(?:ව්‍යුහගත|ව්‍යහගන)?\s*රචනා", re.I),
    re.compile(r"^[^,\n]{0,25}(?:ප්‍රශ්න\s*පත්‍රය\s*(?:II|2)|II\s*පත්‍රය|දෙවන\s*පත්‍රය)", re.I),
    re.compile(r"ව්‍යුහගත\s*රචනා|ව්‍යහගන\s*රචනා", re.I),
)

_SINHALA_WORD_REPLACEMENTS = [
    (r"\bප්‍රග්න", "ප්‍රශ්න"),
    (r"ප්‍රග්න\b", "ප්‍රශ්න"),
    (r"ප්‍රග්නය", "ප්‍රශ්නය"),
    (r"ප්‍රග්නවලට", "ප්‍රශ්නවලට"),
    (r"පිළිතුරැ", "පිළිතුරු"),
    (r"පරමිපරා", "පරම්පරා"),
    (r"අවග්‍ය", "අවශ්‍ය"),
    (r"ස්ටානයේ", "ස්ථානයේ"),
    (r"දිරථිඝ", "දීර්ඝ"),
    (r"ගාලාධිපති", "ශාලාධිපති"),
    (r"පරිගබක", "පරිගණක"),
    (r"ප්‍රකාග\b", "ප්‍රකාශ"),
    (r"ප්‍රකාගය", "ප්‍රකාශය"),
    (r"ප්‍රකාගවල", "ප්‍රකාශවල"),
    (r"යෝපනා", "යෝජනා"),
    (r"විගශාල", "විශාල"),
    (r"අතරික්සු", "අතිරික්සු"),
    (r"පයතන්\b", "පයිතන්"),
    (r"ක්‍රම\s+ලේඛ\b", "ක්‍රමලේඛ"),
    (r"ක්‍ෂ\b", "ක්ෂ"),
    (r"කාට්‍ය\b", "කාර්ය"),
    (r"කාටය\b", "කාර්ය"),
    (r"සංවට්ධන", "සංවර්ධන"),
    (r"අන්තටපාල", "අන්තර්ජාල"),
    (r"අන්තටරපාල", "අන්තර්ජාල"),
    (r"අන්තරපාල", "අන්තර්ජාල"),
    (r"ව්‍යහගන\s*රචනා", "ව්‍යුහගත රචනා"),
    (r"ව්‍යහගත\s*රචනා", "ව්‍යුහගත රචනා"),
    (r"ව්‍යහගන", "ව්‍යුහගත"),
    (r"ව්‍යහගත", "ව්‍යුහගත"),
    (r"සමිබන්ධ", "සම්බන්ධ"),
    (r"සමිඛන්ධ", "සම්බන්ධ"),
    (r"මෙහෙයුමි\b", "මෙහෙයුම්"),
    (r"මෙහෙයුමිවල", "මෙහෙයුම්වල"),
    (r"මෙහෙයුමිවලට", "මෙහෙයුම්වලට"),
    (r"යෙදුමි\b", "යෙදුම්"),
    (r"යෙදුමිවල", "යෙදුම්වල"),
    (r"යෙදුමිවලට", "යෙදුම්වලට"),
    (r"ගැලීමි\b", "ගැලීම්"),
    (r"ගැලීමිවල", "ගැලීම්වල"),
    (r"පැවරැමි\b", "පැවරුම්"),
    (r"පැවරැමිවල", "පැවරුම්වල"),
    (r"සමිප්‍රේෂ", "සම්ප්‍රේෂ"),
    (r"සමිපූර්ණ", "සම්පූර්ණ"),
    (r"සමිපත්", "සම්පත්"),
    (r"සමිමත", "සම්මත"),
    (r"සමිපාදන", "සම්පාදන"),
    (r"සමිපාදක", "සම්පාදක"),
    (r"නැඹුරැ\b", "නැඹුරු"),
    (r"නැඹුරැව", "නැඹුරුව"),
    (r"කවරැන්\b", "කවුරුන්"),
    (r"ගුරැවරු", "ගුරුවරු"),
    (r"නුදුරැ\b", "නුදුරු"),
    (r"දරැවන්\b", "දරුවන්"),
    (r"මිතුරැ\b", "මිතුරු"),
    (r"අවුරැදු\b", "අවුරුදු"),
    (r"නිරෑපන", "නිරූපණ"),
    (r"රෑපය", "රූපය"),
    (r"හස්තිය\b", "හස්තීය"),
    (r"එන්පිම", "එන්ජිම"),
    (r"පරිපටය", "පරිපථය"),
    (r"පරිපට\b", "පරිපථ"),
]

_ENGLISH_WORD_REPLACEMENTS = [
    (r"\bVaccum\b", "Vacuum"),
    (r"\bIntergrated\b", "Integrated"),
    (r"\bIntergration\b", "Integration"),
    (r"\bofa\b", "of a"),
    (r"\bSOL\b(?=\s+(?:statement|query|command|server|database|SELECT|INSERT|UPDATE|DELETE))", "SQL"),
    (r"\bcornputer\b", "computer"),
    (r"\bcornputing\b", "computing"),
    (r"\bprograrn\b", "program"),
    (r"\bsystern\b", "system"),
    (r"\bnetvvork\b", "network"),
    (r"\bbandwith\b", "bandwidth"),
    (r"\bcomplier\b", "compiler"),
    (r"\bdefualt\b", "default"),
    (r"\brecieve\b", "receive"),
    (r"\brecieved\b", "received"),
    (r"\bcommuncation\b", "communication"),
    (r"\btransmision\b", "transmission"),
    (r"\bproccessor\b", "processor"),
    (r"\bdatabse\b", "database"),
    (r"\binterpretor\b", "interpreter"),
    (r"\bartifical\b", "artificial"),
    (r"\bintellegence\b", "intelligence"),
    (r"\bneccessary\b", "necessary"),
    (r"\btransfered\b", "transferred"),
    (r"\bmemmory\b", "memory"),
    (r"\bprotocal\b", "protocol"),
    (r"\btoplogy\b", "topology"),
    (r"\balgrithm\b", "algorithm"),
    (r"\bstatment\b", "statement"),
    (r"\bvariabel\b", "variable"),
    (r"\bexecusion\b", "execution"),
    (r"\barchitechture\b", "architecture"),
    (r"\bperiferal\b", "peripheral"),
    (r"\binterupt\b", "interrupt"),
    (r"\bparrallel\b", "parallel"),
    (r"\bseriel\b", "serial"),
    (r"\bsynchronus\b", "synchronous"),
    (r"\basynchronus\b", "asynchronous"),
]


def _is_junk(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return bool(_JUNK_LINE_RE.match(s)) and len(s) <= 4


def normalize(text: str) -> str:
    """Normalize whitespace/noise, Unicode hygiene and common OCR substitutions."""
    text = unicodedata.normalize("NFC", text)
    # Replace ඞ (U+0D9E, Kantaja Na) with ඩ (U+0DA9, Murdhaja Da) in Sinhala words
    text = text.replace("\u0D9E", "\u0DA9")
    # Collapse multiple viramas (al-lakuna)
    text = re.sub(r"\u0DCA{2,}", "\u0DCA", text)
    # Remove isolated combining marks at start of line or after whitespace
    text = re.sub(r"(?:^|\s)[\u0DCA-\u0DDF]+", " ", text)

    # Word-level vocabulary / spelling replacements
    for pattern, repl in _SINHALA_WORD_REPLACEMENTS:
        text = re.sub(pattern, repl, text)
    for pattern, repl in _ENGLISH_WORD_REPLACEMENTS:
        text = re.sub(pattern, repl, text)

    out: list[str] = []
    for raw in text.splitlines():
        line = _DOT_RUN_RE.sub("……", raw.rstrip())
        line = re.sub(r"෴{2,}", "෴", line)
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
        # Check ahead up to 80 lines for the first stem (allows cover instructions)
        for j in range(i + 1, min(i + 81, len(lines))):
            m = re.match(r"^\s*(\d{1,2})[\.)]\s+\S", lines[j])
            if m and int(m.group(1)) <= 6:
                return i, text
        # Strong marker in the latter half of document
        if i >= len(lines) * 0.35 and any(w in text for w in [
            "Structured", "ව්‍යුහගත", "ව්‍යහගන", "II පත්‍රය", "දෙවන පත්‍රය", "A කොටස"
        ]):
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
            if m and len(s.strip()) < 80:
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

    # Numbering restart fallback:
    # Requires small number <= 6 after having reached at least 85% of expected MCQs,
    # and ensures no higher question numbers continue afterwards in Paper 1.
    running_max = 0
    min_split_threshold = int(mcq_count_hint * 0.85)
    for i, line in enumerate(lines):
        m = re.match(r"^\s*(\d{1,2})[\.)]\s+\S", line)
        if not m:
            continue
        n = int(m.group(1))
        if n <= 6 and running_max >= min_split_threshold:
            has_higher = False
            for j in range(i + 1, min(i + 100, len(lines))):
                sub_m = re.match(r"^\s*(\d{1,2})[\.)]\s+\S", lines[j])
                if sub_m:
                    sub_n = int(sub_m.group(1))
                    if sub_n >= running_max or sub_n >= 15:
                        has_higher = True
                        break
            if not has_higher:
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
