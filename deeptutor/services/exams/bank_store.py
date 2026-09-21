"""SQLite persistence for the Paper Bank (tables from migration 004).

The bank holds PRISTINE past papers as JSON. Starting an exam copies a bank
row's ``paper_json`` into the ``exams`` table, so attempts never mutate the
catalog and any paper can be retaken unlimited times.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

import aiosqlite

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)


_JSON_COLUMNS = ("paper_json", "scheme_answers_json", "topic_tags_json")

# Placeholder stubs shipped in the master archive for A/L years whose real
# papers were never captured (2017-2025 A/L): stems like
# "Question N of G.C.E. (A/L) YYYY ICT Examination Paper ..." with options
# "Alternative (1..5)". They are not real past papers and must never render
# as such — detect and exclude them honestly.
_PLACEHOLDER_STEM_RE = re.compile(
    r"^Question \d+ of G\.C\.E\. .*Examination Paper", re.IGNORECASE
)


def _db_path():
    d = get_path_service().user_dir
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:  # pragma: no cover - read-only home edge
        pass
    return d / "chat_history.db"


def _deserialize(row: Dict[str, Any]) -> Dict[str, Any]:
    """JSON columns come back as real structures (mirrors ExamStore.load_paper)."""
    for col in _JSON_COLUMNS:
        val = row.get(col)
        if isinstance(val, str) and val:
            try:
                row[col] = json.loads(val)
            except json.JSONDecodeError:  # pragma: no cover - corrupt row
                logger.warning("Unparseable %s in paper_bank row %s", col, row.get("id"))
    return row


def is_placeholder_paper(paper_json: Any) -> bool:
    """True when a bank paper is an archive placeholder stub, not a real paper.

    Markers: first-question stems like "Question N of G.C.E. ... Examination
    Paper ...". Real past-paper stems are the actual question text and never
    match this pattern, so the stem gate alone is decisive for both MCQ
    (options "Alternative (1..5)") and structured stubs (no options).
    """
    try:
        questions = (paper_json or {}).get("questions", []) if isinstance(paper_json, dict) else []
        if not questions:
            return False
        sample = questions[:3]
        stub_stems = sum(
            1 for q in sample if _PLACEHOLDER_STEM_RE.match(str(q.get("stem") or q.get("text") or "").strip())
        )
        return stub_stems >= min(2, len(sample))
    except Exception:  # noqa: BLE001 - detection must never break catalog
        return False


class BankStore:
    """Thin async data-access layer over ``paper_bank``."""

    @staticmethod
    async def ensure_tables(db: aiosqlite.Connection) -> None:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_bank (
                id TEXT PRIMARY KEY,
                group_key TEXT NOT NULL,
                paper_no INTEGER NOT NULL DEFAULT 1 CHECK (paper_no IN (1, 2)),
                grade INTEGER NOT NULL CHECK (grade IN (11, 12, 13)),
                subject TEXT NOT NULL,
                year INTEGER NOT NULL,
                medium TEXT NOT NULL DEFAULT 'english'
                    CHECK (medium IN ('english', 'sinhala', 'tamil')),
                paper_type TEXT NOT NULL DEFAULT 'mcq'
                    CHECK (paper_type IN ('mcq', 'structured', 'essay', 'mixed')),
                title TEXT NOT NULL,
                source_filename TEXT DEFAULT '',
                file_hash TEXT UNIQUE,
                question_count INTEGER NOT NULL DEFAULT 0,
                mcq_count INTEGER NOT NULL DEFAULT 0,
                essay_count INTEGER NOT NULL DEFAULT 0,
                total_marks REAL NOT NULL DEFAULT 0,
                default_duration_seconds INTEGER NOT NULL DEFAULT 7200,
                paper_json TEXT NOT NULL,
                scheme_answers_json TEXT DEFAULT '{}',
                topic_tags_json TEXT DEFAULT '[]',
                created_at REAL NOT NULL,
                updated_at REAL,
                UNIQUE (group_key, paper_no)
            )
            """
        )

    @classmethod
    async def upsert_paper(cls, row: Dict[str, Any]) -> str:
        """Insert or replace one catalog entry. Returns the row id."""
        rid = str(row["id"])
        now = time.time()
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.execute(
                "INSERT OR REPLACE INTO paper_bank (id, group_key, paper_no, grade, subject,"
                " year, medium, paper_type, title, source_filename, file_hash,"
                " question_count, mcq_count, essay_count, total_marks,"
                " default_duration_seconds, paper_json, scheme_answers_json,"
                " topic_tags_json, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rid,
                    str(row["group_key"]),
                    int(row.get("paper_no") or 1),
                    int(row["grade"]),
                    str(row["subject"]),
                    int(row["year"]),
                    str(row.get("medium") or "english"),
                    str(row.get("paper_type") or "mcq"),
                    str(row["title"]),
                    str(row.get("source_filename") or ""),
                    row.get("file_hash"),
                    int(row.get("question_count") or 0),
                    int(row.get("mcq_count") or 0),
                    int(row.get("essay_count") or 0),
                    float(row.get("total_marks") or 0),
                    int(row.get("default_duration_seconds") or 7200),
                    json.dumps(row["paper_json"]),
                    json.dumps(row.get("scheme_answers") or {}),
                    json.dumps(row.get("topic_tags") or []),
                    float(row.get("created_at") or now),
                    now,
                ),
            )
            await db.commit()
        return rid

    @classmethod
    async def get_by_hash(cls, file_hash: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM paper_bank WHERE file_hash = ?", (file_hash,))
            row = await cur.fetchone()
        return _deserialize(dict(row)) if row else None

    @classmethod
    async def get_by_group(cls, group_key: str) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM paper_bank WHERE group_key = ? ORDER BY paper_no ASC",
                (group_key,),
            )
            rows = await cur.fetchall()
        return [_deserialize(dict(r)) for r in rows]

    _seeded_checked: bool = False
    _is_seeding: bool = False
    _last_missing_check: float = 0.0
    _MISSING_CHECK_INTERVAL: float = 60.0

    @classmethod
    def is_seeding(cls) -> bool:
        return cls._is_seeding

    @classmethod
    async def ensure_seeded(cls, *, block: bool = True) -> None:
        """Auto-seed paper_bank from master archive, plus top-up when missing.

        The original empty-check left existing installs stale when the archive
        grew (new folders never imported because COUNT > 0). Now a cheap
        check compares ``master-archive-<folder>`` hashes against the archive
        directory and re-runs the importer when folders are missing.
        """
        if cls._is_seeding:
            return
        import os as _os
        import time as _time

        # Pytest workspaces are throwaway (tmp_path): fixtures own their data
        # and must never trigger a real-archive import in the background.
        if _os.environ.get("PYTEST_CURRENT_TEST"):
            return

        now = _time.time()
        if cls._seeded_checked and (now - cls._last_missing_check) < cls._MISSING_CHECK_INTERVAL:
            return
        # Claim the flags BEFORE any await: concurrent first-requests must see
        # them and not spawn duplicate imports (single loop => check+set atomic).
        cls._is_seeding = True
        cls._last_missing_check = now
        try:
            async with aiosqlite.connect(_db_path()) as db:
                await cls.ensure_tables(db)
                cur = await db.execute("SELECT COUNT(*) FROM paper_bank")
                row = await cur.fetchone()
                count = row[0] if row else 0
                existing_hashes: set[str] = set()
                try:
                    cur2 = await db.execute(
                        "SELECT file_hash FROM paper_bank WHERE file_hash LIKE 'master-archive-%'"
                    )
                    existing_hashes = {r[0] for r in await cur2.fetchall() if r[0]}
                except Exception:  # noqa: BLE001 - hash check is best-effort
                    existing_hashes = set()

            missing: set[str] = set()
            try:
                from pathlib import Path as _Path

                from deeptutor.services.exams.master_archive_importer import (
                    _DEFAULT_ARCHIVE_PATH as _ARCH,
                )

                arch = _Path(_ARCH)
                if arch.is_dir():
                    for d in arch.iterdir():
                        if d.is_dir() and (d / "paper.json").is_file():
                            h = f"master-archive-{d.name}"
                            if h not in existing_hashes:
                                missing.add(h)
            except Exception:  # noqa: BLE001 - never break catalog for sync check
                missing = set()

            if count == 0:
                logger.info("Paper bank empty. Auto-seeding from master archive...")
            elif missing:
                logger.info(
                    "Paper bank missing %d archive folder(s). Top-up sync...", len(missing)
                )
            else:
                cls._seeded_checked = True
                cls._is_seeding = False
                return

            async def _seed():
                try:
                    from deeptutor.services.exams.master_archive_importer import (
                        import_master_archive,
                    )
                    await import_master_archive(copy_assets=True)
                    cls._seeded_checked = True
                    logger.info("Paper bank auto-seed complete.")
                except Exception as ex:
                    logger.error("Failed to auto-seed paper bank: %s", ex)
                finally:
                    cls._is_seeding = False

            if block:
                await _seed()
            else:
                import asyncio
                asyncio.create_task(_seed())
        except Exception as e:
            cls._is_seeding = False
            logger.error("Failed to check seed status: %s", e)

    @classmethod
    async def get_paper(cls, bank_paper_id: str) -> Optional[Dict[str, Any]]:
        await cls.ensure_seeded(block=False)
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM paper_bank WHERE id = ?", (bank_paper_id,))
            row = await cur.fetchone()
        return _deserialize(dict(row)) if row else None

    @classmethod
    async def catalog(
        cls,
        *,
        subject: Optional[str] = None,
        grade: Optional[int] = None,
        year: Optional[int] = None,
        medium: Optional[str] = None,
        group_key: Optional[str] = None,
        limit: int = 500,
        honest_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """Filtered catalog listing WITHOUT the heavy paper_json blob.

        honest_only=True drops rows that can never render honestly:
        zero questions or zero total marks (bad imports / legacy promotes),
        plus placeholder archive stubs (generic "Question N of ... /
        Alternative (1..5)" content — never real past papers).
        Papers without official keys (all P2 structured essays) are KEPT —
        they grade via the LLM essay judge — but flagged via has_scheme_keys.
        """
        await cls.ensure_seeded(block=False)
        where: List[str] = []
        vals: List[Any] = []
        if subject:
            where.append("subject = ?")
            vals.append(subject.lower())
        if grade is not None:
            where.append("grade = ?")
            vals.append(int(grade))
        if year is not None:
            where.append("year = ?")
            vals.append(int(year))
        if medium:
            where.append("medium = ?")
            vals.append(medium)
        if group_key:
            where.append("group_key = ?")
            vals.append(group_key)
        if honest_only:
            where.append("question_count > 0")
            where.append("total_marks > 0")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, group_key, paper_no, grade, subject, year, medium, paper_type,"
                " title, question_count, mcq_count, essay_count, total_marks,"
                " default_duration_seconds, created_at,"
                " (COALESCE(scheme_answers_json, '{}') NOT IN ('{}', '')) AS has_scheme_keys"
                f" FROM paper_bank {clause} ORDER BY subject, year DESC, paper_no LIMIT ?",
                (*vals, max(1, min(int(limit), 2000))),
            )
            rows = [dict(r) for r in await cur.fetchall()]
            for r in rows:
                r["has_scheme_keys"] = bool(r.get("has_scheme_keys"))
        if honest_only and rows:
            # Placeholder stubs pass the numeric gate (50Q / marks > 0) so
            # they need a content check against paper_json. Bounded to the
            # page size so the catalog stays cheap.
            try:
                async with aiosqlite.connect(_db_path()) as db2:
                    db2.row_factory = aiosqlite.Row
                    kept: List[Dict[str, Any]] = []
                    for r in rows:
                        cur2 = await db2.execute(
                            "SELECT paper_json FROM paper_bank WHERE id = ?", (r["id"],)
                        )
                        prow = await cur2.fetchone()
                        try:
                            payload = json.loads(prow["paper_json"]) if prow and prow["paper_json"] else {}
                        except (json.JSONDecodeError, TypeError, KeyError):
                            payload = {}
                        if not is_placeholder_paper(payload):
                            kept.append(r)
                        else:
                            logger.info("Paper bank hides placeholder stub %s", r["id"])
                    rows = kept
            except Exception as exc:  # noqa: BLE001 - filter is best-effort
                logger.debug("Placeholder filter skipped: %s", exc)
        return rows

    @classmethod
    async def facets(cls) -> Dict[str, Any]:
        """Distinct subjects/grades/years/mediums present in the bank."""
        await cls.ensure_seeded(block=False)
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)

            async def distinct(col: str, extra: str = "") -> List[Any]:
                cur = await db.execute(
                    f"SELECT DISTINCT {col} FROM paper_bank {extra} ORDER BY {col}"
                )
                return [r[0] for r in await cur.fetchall()]

            subjects = await distinct("subject")
            grades = await distinct("grade")
            years = await distinct("year")
            mediums = await distinct("medium")
            cur = await db.execute("SELECT COUNT(*) FROM paper_bank")
            total = (await cur.fetchone())[0]
        return {
            "subjects": subjects,
            "grades": grades,
            "years": years,
            "mediums": mediums,
            "total_papers": int(total or 0),
        }

    @classmethod
    async def delete_paper(cls, bank_paper_id: str) -> bool:
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            cur = await db.execute("DELETE FROM paper_bank WHERE id = ?", (bank_paper_id,))
            await db.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------- practice log

    @classmethod
    async def log_practice(cls, rows: List[Dict[str, Any]]) -> None:
        """Append per-question outcomes from a graded attempt (best effort)."""
        if not rows:
            return
        import time as _time

        now = _time.time()
        try:
            async with aiosqlite.connect(_db_path()) as db:
                await cls.ensure_tables(db)
                await db.execute("PRAGMA foreign_keys = ON;")
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS question_practice_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        student_id TEXT NOT NULL,
                        bank_paper_id TEXT REFERENCES paper_bank(id) ON DELETE CASCADE,
                        exam_id TEXT NOT NULL,
                        question_id TEXT NOT NULL,
                        topic TEXT DEFAULT '',
                        question_type TEXT DEFAULT '',
                        verdict TEXT DEFAULT '',
                        awarded REAL NOT NULL DEFAULT 0,
                        max_marks REAL NOT NULL DEFAULT 1,
                        practiced_at REAL NOT NULL
                    )
                    """
                )
                await db.executemany(
                    "INSERT INTO question_practice_log (student_id, bank_paper_id, exam_id,"
                    " question_id, topic, question_type, verdict, awarded, max_marks, practiced_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            str(r["student_id"]),
                            r.get("bank_paper_id"),
                            str(r["exam_id"]),
                            str(r["question_id"]),
                            str(r.get("topic") or ""),
                            str(r.get("question_type") or ""),
                            str(r.get("verdict") or ""),
                            float(r.get("awarded") or 0),
                            float(r.get("max_marks") or 1),
                            float(r.get("practiced_at") or now),
                        )
                        for r in rows
                    ],
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001 - analytics must never break grading
            logger.warning("practice log write skipped: %s", exc)

    @classmethod
    async def topic_stats(cls, student_id: str) -> List[Dict[str, Any]]:
        """Per-topic accuracy for the recommendation engine."""
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT topic, COUNT(*) AS attempts,"
                " SUM(CASE WHEN verdict = 'correct' THEN 1 ELSE 0 END) AS correct,"
                " SUM(awarded) AS awarded, SUM(max_marks) AS max_marks"
                " FROM question_practice_log WHERE student_id = ? AND topic != ''"
                " GROUP BY topic ORDER BY attempts DESC",
                (student_id,),
            )
            return [dict(r) for r in await cur.fetchall()]
