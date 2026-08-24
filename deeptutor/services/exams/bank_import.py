"""Bulk Paper-Bank importer: a folder of past-paper PDFs → the ``paper_bank`` catalog.

Pipeline per question paper:

  1. WALK      collect PDFs, sha256 each; already-imported hashes are skipped
  2. CLASSIFY  filename (+folder names) → {subject, grade, year, paper_no,
               paper_type, medium}; marking schemes are detected for pairing
  3. PARSE     shared MinerU/docling layer (digital PDFs take the fast,
               OCR-free path) → verbatim QuizTemplates → ExamPaper
  4. ANSWERS   pair the matching marking-scheme PDF and map MCQ keys
               ("1 B", "(2) C", tables...) onto questions; optional one-shot
               LLM solve for whatever is still unanswered
  5. GATE      quality check: sane question counts + text-quality score;
               failures land in ``needs_review`` — never silently wrong data
  6. STORE     upsert into ``paper_bank`` (deterministic id per group+paper_no)

Resumable: a state file records per-file-hash outcomes so re-running the same
folder only processes new/failed files.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional
import uuid

from deeptutor.services.exams.bank_store import BankStore

logger = logging.getLogger(__name__)

# Default durations per paper type (A/L convention: P1 MCQ=2h, P2 essay=3h).
DEFAULT_DURATION_BY_TYPE = {
    "mcq": 2 * 3600,
    "structured": 3 * 3600,
    "essay": 3 * 3600,
    "mixed": 3 * 3600,
}

# Canonical subject → filename tokens (lowercased, word-boundary matched).
# 'ict' first-class per v1 scope; more subjects can be added freely.
SUBJECT_ALIASES: Dict[str, List[str]] = {
    "ict": ["ict", "information-communication-technology"],
    "physics": ["physics"],
    "chemistry": ["chemistry"],
    "biology": ["biology"],
    "combined-maths": ["combined"],
    "maths": ["maths", "mathematics"],
    "agri": ["agri"],
    "economics": ["economics", "economic"],
    "business-studies": ["business"],
    "accounting": ["accounting", "accounts"],
    "geography": ["geography"],
    "civics": ["civics"],
    "logic": ["logic"],
    "buddhism": ["buddhism"],
}

_MEDIUM_TOKENS = {
    "si": "sinhala",
    "sinhala": "sinhala",
    "ta": "tamil",
    "tamil": "tamil",
    "en": "english",
    "english": "english",
}

_P1_RE = re.compile(r"\b(p\s*-?\s*1|paper\s*[- ]?\s*(i\b|1)|mcq|part\s*[- ]?\s*i\b)\b", re.I)
_P2_RE = re.compile(r"\b(p\s*-?\s*2|paper\s*[- ]?\s*(ii\b|2)|part\s*[- ]?\s*ii\b|structured|essay)\b", re.I)
_SCHEME_RE = re.compile(r"marking|scheme|answer[\s_-]*key|answers\b", re.I)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_GRADE_RE = re.compile(r"\b(?:g|grade)[\s._-]*(12|13)\b", re.I)
_LEADING_NUM_RE = re.compile(r"^\s*\(?\s*(\d{1,3})\s*[\.\)]")

# Marking-scheme key capture: "1 B", "(2) C", "03 - A", tables of pairs.
_KEY_PAIR_RE = re.compile(
    r"(?<![\w.])(\d{1,3})\s*[\.\):\]\-–]?\s*\(?([A-Ea-e])\)?(?![\w])"
)

_MIN_MCQ_QUESTIONS = 10
_MIN_OTHER_QUESTIONS = 5
_MIN_TEXT_QUALITY = 0.70


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


@dataclass
class PaperMeta:
    subject: str = "ict"
    year: Optional[int] = None
    grade: Optional[int] = None
    paper_no: int = 1
    paper_type: str = "mixed"
    medium: str = "english"
    is_scheme: bool = False

    @property
    def group_key(self) -> str:
        base = f"{self.subject}-{self.year or 'unknown'}-g{self.grade or '?'}"
        if self.medium != "english":
            base += f"-{self.medium[:2]}"
        return base


def classify_filename(name: str) -> PaperMeta:
    """Best-effort metadata extraction from a past-paper filename."""
    meta = PaperMeta()
    low = name.lower()

    meta.is_scheme = bool(_SCHEME_RE.search(low))

    m = _YEAR_RE.search(low)
    if m:
        meta.year = int(m.group(0))

    g = _GRADE_RE.search(low)
    if g:
        meta.grade = int(g.group(1))

    for token in re.findall(r"[a-z]+", low):
        if token in _MEDIUM_TOKENS:
            meta.medium = _MEDIUM_TOKENS[token]
            break

    if _P2_RE.search(low):
        meta.paper_no, meta.paper_type = 2, "structured"
    elif _P1_RE.search(low):
        meta.paper_no, meta.paper_type = 1, "mcq"

    for canonical, aliases in SUBJECT_ALIASES.items():
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", low):
                meta.subject = canonical
                return meta
    return meta


def parse_mcq_keys(scheme_text: str) -> Dict[int, str]:
    """Extract an answer-key map {question_number: 'A'..'E'} from scheme text."""
    keys: Dict[int, str] = {}
    for num_raw, letter in _KEY_PAIR_RE.findall(scheme_text or ""):
        num = int(num_raw)
        if 1 <= num <= 200:
            keys[num] = letter.upper()
    return keys


def _text_quality(text: str) -> float:
    """Ratio of sane characters — catches mojibake/legacy-font garbage."""
    if not text:
        return 0.0
    bad = sum(
        1
        for ch in text
        if ch == "\ufffd"
        or (0xE000 <= ord(ch) <= 0xF8FF)  # private-use area
        or (not ch.isprintable() and ch not in "\n\r\t")
    )
    return 1.0 - (bad / len(text))


def attach_mcq_keys(questions: List[Any], keys: Dict[int, str]) -> int:
    """Stamp marking-scheme answer keys onto ExamQuestions; returns hit count."""
    if not keys:
        return 0
    attached = 0
    used: set[int] = set()
    # Pass 1: match by the leading question number preserved in the stem.
    for q in questions:
        m = _LEADING_NUM_RE.match(str(q.text or ""))
        if m:
            num = int(m.group(1))
            if num in keys:
                q.reference_answer = keys[num]
                used.add(num)
                attached += 1
    # Pass 2: positional fallback (q.number == extraction order).
    for q in questions:
        if q.reference_answer:
            continue
        if q.number in keys and q.number not in used:
            q.reference_answer = keys[q.number]
            used.add(q.number)
            attached += 1
    return attached


def read_pdf_text(pdf_path: Path, max_pages: int = 60) -> str:
    """Cheap embedded-text read (digital PDFs need no OCR for this)."""
    try:
        import fitz

        parts: List[str] = []
        with fitz.open(str(pdf_path)) as doc:
            for page in doc.pages(0, max_pages):
                parts.append(page.get_text())
        return "\n".join(parts)
    except Exception as exc:  # noqa: BLE001 - fitz missing/corrupt file
        logger.debug("fitz text read failed for %s: %s", pdf_path.name, exc)
        return ""


@dataclass
class ImportItem:
    filename: str
    status: str = "queued"  # queued|parsing|imported|skipped|needs_review|failed
    detail: str = ""
    bank_id: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "status": self.status,
            "detail": self.detail,
            "bank_id": self.bank_id,
        }


def _state_path() -> Path:
    from deeptutor.services.path_service import get_path_service

    d = get_path_service().user_dir / "workspace" / "paper_bank"
    d.mkdir(parents=True, exist_ok=True)
    return d / "import_state.json"


def _load_state() -> Dict[str, Any]:
    try:
        with open(_state_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    try:
        with open(_state_path(), "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=1)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not persist import state: %s", exc)


class BankImportJob:
    """One resumable bulk-import run over a folder."""

    def __init__(
        self,
        folder: str | Path,
        *,
        subject_default: str = "ict",
        grade_default: Optional[int] = None,
        medium_default: str = "english",
        solve_missing: bool = True,
        job_id: Optional[str] = None,
    ) -> None:
        self.job_id = job_id or f"imp-{uuid.uuid4().hex[:8]}"
        self.folder = Path(folder)
        self.subject_default = subject_default.lower()
        self.grade_default = grade_default
        self.medium_default = medium_default
        self.solve_missing = solve_missing
        self.items: List[ImportItem] = []
        self.status = "queued"  # queued|running|done|failed
        self.started_at: float = 0.0
        self.finished_at: float = 0.0
        self.error = ""

    # ------------------------------------------------------------- snapshot
    def snapshot(self) -> Dict[str, Any]:
        done = sum(1 for i in self.items if i.status in ("imported", "skipped"))
        return {
            "job_id": self.job_id,
            "folder": str(self.folder),
            "status": self.status,
            "total_files": len(self.items),
            "processed_files": done,
            "solve_missing": self.solve_missing,
            "error": self.error,
            "items": [i.as_dict() for i in self.items],
        }

    # ------------------------------------------------------------------ run
    async def run(self) -> Dict[str, Any]:
        from deeptutor.agents.question.mimic_source import (
            parse_exam_paper_to_templates,
        )
        from deeptutor.services.exams.engine import (
            solve_missing_answers,
            templates_to_paper,
        )

        self.status = "running"
        self.started_at = time.time()
        state = _load_state()
        try:
            pdfs = sorted(p for p in self.folder.rglob("*.pdf") if p.is_file())
        except Exception as exc:  # noqa: BLE001
            self.status = "failed"
            self.error = f"Cannot read folder: {exc}"
            return self.snapshot()

        if not pdfs:
            self.status = "failed"
            self.error = "No PDF files found in this folder."
            return self.snapshot()

        metas = {p: classify_filename(p.name) for p in pdfs}
        # Folder-name hints win when the filename lacks them
        # (e.g. papers under ...\Grade 13\2021\...).
        for p, meta in metas.items():
            rel_parts = p.relative_to(self.folder).parts[:-1]
            if meta.grade is None:
                for part in rel_parts:
                    g = _GRADE_RE.search(part.lower())
                    if g:
                        meta.grade = int(g.group(1))
                        break
                if meta.grade is None:
                    meta.grade = self.grade_default
            if meta.year is None:
                for part in reversed(rel_parts):
                    y = _YEAR_RE.search(part.lower())
                    if y:
                        meta.year = int(y.group(0))
                        break

        schemes_by_group: Dict[str, List[Path]] = {}
        for p, meta in metas.items():
            if meta.is_scheme:
                schemes_by_group.setdefault(meta.group_key, []).append(p)

        workspace_out = _state_path().parent / "sessions"
        workspace_out.mkdir(parents=True, exist_ok=True)

        for pdf_path in pdfs:
            meta = metas[pdf_path]
            item = ImportItem(filename=str(pdf_path.relative_to(self.folder)))
            self.items.append(item)

            fhash = sha256_file(pdf_path)
            existing = await BankStore.get_by_hash(fhash)
            if existing or state.get(fhash, {}).get("status") == "imported":
                item.status = "skipped"
                item.detail = "already imported"
                continue

            if meta.is_scheme:
                # Schemes are consumed via pairing below, never stored alone.
                item.status = "skipped"
                item.detail = "marking scheme (paired automatically)"
                continue

            missing_bits = [
                label
                for label, val in (("grade", meta.grade), ("year", meta.year))
                if val is None
            ]
            if missing_bits:
                item.status = "needs_review"
                item.detail = (
                    "could not determine "
                    + " and ".join(missing_bits)
                    + " — rename e.g. '2021-ICT-P1-G12-EN.pdf'"
                )
                continue

            item.status = "parsing"
            out_dir = workspace_out / f"import_{uuid.uuid4().hex[:8]}"
            try:
                templates, _trace = await parse_exam_paper_to_templates(
                    pdf_path,
                    max_questions=200,
                    paper_mode="upload",
                    output_dir=out_dir,
                )
                if not templates:
                    raise RuntimeError("no questions extracted")
                duration = DEFAULT_DURATION_BY_TYPE[meta.paper_type]
                paper = templates_to_paper(
                    templates,
                    title=f"{meta.subject.upper()} {meta.year} Grade {meta.grade}"
                    f" Paper {meta.paper_no} ({meta.medium.title()})",
                    source_filename=pdf_path.name,
                    mcq_duration_seconds=duration,
                )
            except Exception as exc:  # noqa: BLE001
                item.status = "failed"
                item.detail = f"extraction_failed: {exc}"[:300]
                state[fhash] = {"status": "failed", "error": item.detail}
                _save_state(state)
                continue

            # ---- scheme pairing + key stamping -----------------------------
            scheme_answers: Dict[int, str] = {}
            for scheme_path in schemes_by_group.get(meta.group_key, []):
                keys = parse_mcq_keys(read_pdf_text(scheme_path))
                if keys and attach_mcq_keys(paper.questions, keys):
                    scheme_answers = keys
                    break

            # ---- optional one-shot LLM solve for leftovers ------------------
            if self.solve_missing:
                try:
                    solved = await solve_missing_answers(paper)
                    if solved:
                        for q in paper.questions:
                            entry = solved.get(q.id)
                            if entry and not (q.reference_answer or "").strip():
                                q.reference_answer = entry["correct_answer"]
                                q.explanation = entry["explanation"]
                        scheme_answers.setdefault(-1, f"llm:{len(solved)}")
                except Exception as exc:  # noqa: BLE001 - tolerated
                    logger.info("LLM answer solve skipped: %s", exc)

            # ---- quality gate ----------------------------------------------
            counts = paper.counts()
            joined = " ".join(q.text for q in paper.questions)
            quality = _text_quality(joined)
            min_expected = (
                _MIN_MCQ_QUESTIONS if meta.paper_type == "mcq" else _MIN_OTHER_QUESTIONS
            )
            problems: List[str] = []
            if counts["question_count"] < min_expected:
                problems.append(
                    f"only {counts['question_count']} questions (expected ≥ {min_expected})"
                )
            if quality < _MIN_TEXT_QUALITY:
                problems.append(f"text quality {quality:.2f} below {_MIN_TEXT_QUALITY}")
            if meta.paper_type == "mcq" and counts["mcq_count"] < counts["question_count"] * 0.6:
                problems.append("MCQ options not detected on most questions")
            if problems:
                item.status = "needs_review"
                item.detail = "; ".join(problems)
                state[fhash] = {"status": "needs_review", "detail": item.detail}
                _save_state(state)
                continue

            # ---- store ------------------------------------------------------
            row = {
                "id": f"{meta.group_key}-p{meta.paper_no}",
                "group_key": meta.group_key,
                "paper_no": meta.paper_no,
                "grade": meta.grade,
                "subject": meta.subject,
                "year": meta.year,
                "medium": meta.medium,
                "paper_type": meta.paper_type,
                "title": paper.title,
                "source_filename": pdf_path.name,
                "file_hash": fhash,
                **counts,
                "total_marks": counts["question_count"],
                "default_duration_seconds": duration,
                "paper_json": json.loads(paper.to_json()),
                "scheme_answers": {str(k): v for k, v in scheme_answers.items()},
                "topic_tags": [],
                "created_at": time.time(),
            }
            await BankStore.upsert_paper(row)
            item.bank_id = row["id"]
            item.status = "imported"
            item.detail = (
                f"{counts['mcq_count']} MCQ · {counts['essay_count']} essay ·"
                f" keys={'yes' if len(scheme_answers) else 'llm/pending'}"
            )
            state[fhash] = {"status": "imported", "bank_id": row["id"]}
            _save_state(state)

        self.finished_at = time.time()
        self.status = "done"
        return self.snapshot()


# ------------------------------------------------------------------ registry
_JOBS: Dict[str, BankImportJob] = {}


def create_job(folder: str | Path, **kwargs: Any) -> BankImportJob:
    job = BankImportJob(folder, **kwargs)
    _JOBS[job.job_id] = job
    return job


def get_job(job_id: str) -> Optional[BankImportJob]:
    return _JOBS.get(job_id)


def latest_job() -> Optional[BankImportJob]:
    if not _JOBS:
        return None
    return max(_JOBS.values(), key=lambda j: j.started_at)
