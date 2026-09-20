"""Read-only audit of the Sri Lanka ICT Master Archive + importer linking.

Guards (without ever writing to the archive):
- every ``images/*`` file is either referenced by a question's ``diagrams[]``
  or filename-matchable to a question (``q{N}`` convention — the importer
  links these at import time);
- every ``diagrams[].src`` resolves to a real file on disk;
- no template-filler stems or legacy-font mojibake (regression gate for the
  2026-09 degraded-tree incident: 600 filler stems + 626 mojibake questions);
- generic-shell question count never grows past the pinned baseline;
- the importer actually performs the loose-image linking (synthetic archive).

Pure stdlib for the archive scans; DB isolation mirrors test_paper_bank_api.py.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from deeptutor.services.exams.master_archive_importer import _DEFAULT_ARCHIVE_PATH

ARCHIVE = _DEFAULT_ARCHIVE_PATH

_QNUM_RE = re.compile(r"q(\d+)", re.IGNORECASE)
_FILLER_RES = (
    re.compile(r"Official syllabus curriculum problem"),
    re.compile(r"Comprehensive question testing syllabus mastery"),
    re.compile(r"Rigorous past-paper standard question"),
    re.compile(r"In-depth technical analysis problem"),
    re.compile(r"State the governing principles and definitions"),
    re.compile(r"Provide the program implementation or schema definition"),
    re.compile(r"Assessment Item \d+:"),
)
_LEGACY_MARKERS = ("¾", "ß", "Í", "Ñ", "õ", "è", "ï", "ÿ")
_GEN_SHELL_RE = re.compile(r"^Question \d+ of G\.C\.E\.")
_GEN_ALT_RE = re.compile(r"^Alternative \(\d+\)$")
# Pinned 2026-09-19 baseline: 30 all-generic P1 folders (2017-2025), 1380 questions.
_MAX_GENERIC_QUESTIONS = 1380
_MAX_GENERIC_FOLDERS = 30


def _folders():
    return sorted(
        d for d in ARCHIVE.iterdir() if d.is_dir() and (d / "paper.json").exists()
    )


def _load(folder: Path):
    return json.loads((folder / "paper.json").read_text(encoding="utf-8"))


def test_archive_present():
    assert ARCHIVE.is_dir(), f"Master archive missing: {ARCHIVE}"
    assert len(_folders()) >= 100


def test_every_image_accounted_for():
    """Each images/* file must be referenced or q-number matchable (importer links those)."""
    violations = []
    for folder in _folders():
        img_dir = folder / "images"
        if not img_dir.is_dir():
            continue
        raw = _load(folder)
        referenced = set()
        for q in raw:
            for d in q.get("diagrams") or []:
                referenced.add(Path(str(d.get("src") or "")).name)
        qnums = {int(q.get("number") or 0) for q in raw}
        for img in sorted(img_dir.glob("*")):
            if not img.is_file():
                continue
            if img.name in referenced:
                continue
            m = _QNUM_RE.search(img.stem)
            if m and int(m.group(1)) in qnums:
                continue
            violations.append(f"{folder.name}/{img.name}")
    assert not violations, "Unaccounted images:\n" + "\n".join(violations)


_KNOWN_DANGLING = frozenset(
    {
        # Referenced in paper.json but absent from images/; the importer skips
        # these at import time (DB-only) so viewers never render broken images.
        "ict-2012-g13-en-p1/q37_timetable.png",
        "ict-2012-g13-si-p1/q37_timetable.png",
    }
)


def test_diagram_srcs_resolve():
    missing = set()
    for folder in _folders():
        img_dir = folder / "images"
        for q in _load(folder):
            for d in q.get("diagrams") or []:
                fname = Path(str(d.get("src") or "")).name
                if fname and not (img_dir / fname).is_file():
                    missing.add(f"{folder.name}/{fname}")
    new_dangling = missing - _KNOWN_DANGLING
    assert not new_dangling, "NEW dangling diagram refs:\n" + "\n".join(sorted(new_dangling)[:20])
    assert missing <= _KNOWN_DANGLING, (
        "Dangling set changed (archive fixes welcome — update _KNOWN_DANGLING):\n"
        + "\n".join(sorted(missing)[:20])
    )


def test_no_filler_stems():
    bad = []
    for folder in _folders():
        for q in _load(folder):
            blob = " ".join(
                str(q.get(k) or "") for k in ("stem", "text", "explanation")
            )
            for rx in _FILLER_RES:
                if rx.search(blob):
                    bad.append(f"{folder.name} q{q.get('number')}: {rx.pattern}")
                    break
    assert not bad, "Filler stems:\n" + "\n".join(bad[:20])


def test_no_legacy_mojibake():
    bad = []
    for folder in _folders():
        for q in _load(folder):
            stem = str(q.get("stem") or q.get("text") or "")
            if any(mk in stem for mk in _LEGACY_MARKERS):
                bad.append(f"{folder.name} q{q.get('number')}")
    assert not bad, "Legacy-encoded stems:\n" + "\n".join(bad[:20])


def test_generic_shells_pinned():
    """Thin generic-shell P1s (2017-2025) are the known baseline — never grow."""
    gen_q = gen_folders = 0
    for folder in _folders():
        raw = _load(folder)
        n = sum(
            1
            for q in raw
            if _GEN_SHELL_RE.match(str(q.get("stem") or ""))
            and (q.get("options") or {})
            and all(
                _GEN_ALT_RE.match(str(v)) for v in (q.get("options") or {}).values()
            )
        )
        if n:
            gen_q += n
            if n == len(raw):
                gen_folders += 1
    assert gen_q <= _MAX_GENERIC_QUESTIONS, f"generic shells grew: {gen_q}"
    assert gen_folders <= _MAX_GENERIC_FOLDERS, f"generic folders grew: {gen_folders}"


# ------------------------------------------------- importer linking (isolated)

_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture()
def isolated_workspace(monkeypatch, tmp_path):
    from deeptutor.services import path_service as ps

    svc = ps.PathService(workspace_root=tmp_path)
    monkeypatch.setattr(ps.PathService, "_instance", svc, raising=False)
    from deeptutor.services.exams.bank_store import BankStore

    old_flag = BankStore._seeded_checked
    BankStore._seeded_checked = True  # never touch the real archive in tests
    try:
        yield tmp_path
    finally:
        BankStore._seeded_checked = old_flag


def test_importer_links_loose_images(isolated_workspace, tmp_path):
    """q{N}_*.png with empty diagrams[] must land on question N in the DB row."""
    from deeptutor.services.exams.bank_store import BankStore
    from deeptutor.services.exams.master_archive_importer import import_master_archive

    src = tmp_path / "archive" / "ut-2023-g13-en-p1"
    (src / "images").mkdir(parents=True)
    (src / "images" / "q2_circuit.png").write_bytes(_MINI_PNG)
    (src / "paper.json").write_text(
        json.dumps(
            [
                {
                    "id": "ut-q1",
                    "number": 1,
                    "question_type": "choice",
                    "stem": "Plain question one?",
                    "options": {"A": "Yes", "B": "No"},
                    "marks": 1,
                    "reference_answer": "A",
                    "explanation": "Because.",
                    "diagrams": [],
                    "metadata": {},
                },
                {
                    "id": "ut-q2",
                    "number": 2,
                    "question_type": "choice",
                    "stem": "Circuit question?",
                    "options": {"A": "X", "B": "Y"},
                    "marks": 1,
                    "reference_answer": "B",
                    "explanation": "See diagram.",
                    "diagrams": [],
                    "metadata": {},
                },
            ]
        ),
        encoding="utf-8",
    )

    import asyncio

    res = asyncio.run(import_master_archive(src.parent, copy_assets=True))
    assert res["success"] and res["imported_papers"] == 1

    row = asyncio.run(BankStore.get_by_hash("master-archive-ut-2023-g13-en-p1"))
    assert row is not None
    import json as _json

    paper = row["paper_json"]
    if isinstance(paper, str):
        paper = _json.loads(paper)
    by_num = {q["number"]: q for q in paper["questions"]}
    assert by_num[1]["diagrams"] == []
    assert [d["src"] for d in by_num[2]["diagrams"]] == ["images/q2_circuit.png"]

    from deeptutor.services.exams.master_archive_importer import (
        get_paper_bank_assets_dir,
    )

    assert (get_paper_bank_assets_dir() / row["id"] / "images" / "q2_circuit.png").is_file()
