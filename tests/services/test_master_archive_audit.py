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

import hashlib
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
# Pinned 2026-09-21 baseline: legacy-font Sinhala in A/L P1 stems (see
# test_no_legacy_mojibake) — 28 folders / 1032 questions, never grow.
_MAX_LEGACY_QUESTIONS = 1032
_MAX_LEGACY_FOLDERS = 28


def _folders():
    return sorted(
        d for d in ARCHIVE.iterdir() if d.is_dir() and (d / "paper.json").exists()
    )


def _load(folder: Path):
    return json.loads((folder / "paper.json").read_text(encoding="utf-8"))


def test_archive_present():
    assert ARCHIVE.is_dir(), f"Master archive missing: {ARCHIVE}"
    assert len(_folders()) >= 100


# Generic O/L figures shared verbatim across years/mediums (sha256-pinned):
# attaching them to a guessed question would mislead, so they stay unlinked.
_KNOWN_SHARED_ASSETS = {
    "p1_flowchart.png": "bfc7a5d41560f2b50f16c7fb41523b89d79fb7c3d3528306d9a71acd1ee48380",
    "p2_flowchart.png": "bfc7a5d41560f2b50f16c7fb41523b89d79fb7c3d3528306d9a71acd1ee48380",
    "p1_logic_circuit.png": "f530b148530b28908699eea3d4d94d56feacc9d565b1987ba791e11dcbe2ab0b",
    "p2_logic_circuit.png": "f530b148530b28908699eea3d4d94d56feacc9d565b1987ba791e11dcbe2ab0b",
    "star_topology.png": "7a24653eb94b41c5ae6c80794f4a38b43340fcf21a4ef178803819630de4a6d0",
}


def test_every_image_accounted_for():
    """Each images/* file must be referenced, q-number matchable, or a known
    shared asset (importer links the q-numbered ones at import time).

    The five generic O/L figures below are byte-identical across every year /
    medium (shared teaching illustrations, not per-question diagrams — even
    p1_* and p2_* are the same bytes under two names). The importer
    deliberately does NOT attach them to a guessed question (wrong-question
    attachment is worse than unlinked). Any NEW unlinked filename, or changed
    bytes under a known name, fails so the linking assumption gets reviewed.
    """
    violations = []
    shared_seen: set[str] = set()
    for folder in _folders():
        img_dir = folder / "images"
        if not img_dir.is_dir():
            continue
        raw = _load(folder)
        referenced = set()
        for q in raw:
            for d in q.get("diagrams") or []:
                src = d if isinstance(d, str) else d.get("src")
                referenced.add(Path(str(src or "")).name)
        qnums = {int(q.get("number") or 0) for q in raw}
        for img in sorted(img_dir.glob("*")):
            if not img.is_file():
                continue
            if img.name in referenced:
                continue
            m = _QNUM_RE.search(img.stem)
            if m and int(m.group(1)) in qnums:
                continue
            if img.name in _KNOWN_SHARED_ASSETS:
                digest = hashlib.sha256(img.read_bytes()).hexdigest()
                assert digest == _KNOWN_SHARED_ASSETS[img.name], (
                    f"{folder.name}/{img.name}: bytes changed — re-check whether "
                    "it is still a shared figure or now question-specific"
                )
                shared_seen.add(img.name)
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
                src = d if isinstance(d, str) else d.get("src")
                fname = Path(str(src or "")).name
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
    """Legacy-font Sinhala in A/L P1 stems must never grow past the baseline.

    Pinned 2026-09-21: 28 folders / 1032 questions whose Sinhala halves were
    extracted through legacy 8-bit fonts (glyph IDs read as Latin-1, plus
    U+FFFD byte loss) and contain zero proper Unicode Sinhala (U+0D80–U+0DFF).
    The original bytes are unrecoverable — no mapping can reconstruct them
    without fabricating text — so the gate pins the count instead of
    asserting zero. Archive re-extraction with Unicode fonts is welcome:
    shrinking the count keeps this green.
    """
    bad = []
    folders = set()
    for folder in _folders():
        for q in _load(folder):
            stem = str(q.get("stem") or q.get("text") or "")
            if any(mk in stem for mk in _LEGACY_MARKERS):
                bad.append(f"{folder.name} q{q.get('number')}")
                folders.add(folder.name)
    assert len(bad) <= _MAX_LEGACY_QUESTIONS, (
        f"legacy-encoded stems grew: {len(bad)} (baseline {_MAX_LEGACY_QUESTIONS})"
    )
    assert len(folders) <= _MAX_LEGACY_FOLDERS, (
        f"legacy-encoded folders grew: {len(folders)} (baseline {_MAX_LEGACY_FOLDERS})"
    )


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
