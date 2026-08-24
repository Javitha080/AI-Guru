"""SQLite persistence for the Paper Bank (tables from migration 004).

The bank holds PRISTINE past papers as JSON. Starting an exam copies a bank
row's ``paper_json`` into the ``exams`` table, so attempts never mutate the
catalog and any paper can be retaken unlimited times.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

import aiosqlite

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)


_JSON_COLUMNS = ("paper_json", "scheme_answers_json", "topic_tags_json")


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
                grade INTEGER NOT NULL CHECK (grade IN (12, 13)),
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
            cur = await db.execute(
                "SELECT * FROM paper_bank WHERE file_hash = ?", (file_hash,)
            )
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

    @classmethod
    async def get_paper(cls, bank_paper_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM paper_bank WHERE id = ?", (bank_paper_id,)
            )
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
    ) -> List[Dict[str, Any]]:
        """Filtered catalog listing WITHOUT the heavy paper_json blob."""
        where, vals = [], []
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
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, group_key, paper_no, grade, subject, year, medium, paper_type,"
                " title, question_count, mcq_count, essay_count, total_marks,"
                " default_duration_seconds, created_at"
                f" FROM paper_bank {clause} ORDER BY subject, year DESC, paper_no LIMIT ?",
                (*vals, max(1, min(int(limit), 2000))),
            )
            rows = [dict(r) for r in await cur.fetchall()]
        return rows

    @classmethod
    async def facets(cls) -> Dict[str, Any]:
        """Distinct subjects/grades/years/mediums present in the bank."""
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
            cur = await db.execute(
                "DELETE FROM paper_bank WHERE id = ?", (bank_paper_id,)
            )
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
