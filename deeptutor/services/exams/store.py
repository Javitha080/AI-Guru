"""SQLite persistence for the exam engine (tables from migration 002)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

import aiosqlite

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)


def _db_path():
    return get_path_service().user_dir / "chat_history.db"


class ExamStore:
    """Thin async data-access layer over ``exams`` / ``exam_answers``."""

    @staticmethod
    async def ensure_tables(db: aiosqlite.Connection) -> None:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS exams (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source_filename TEXT DEFAULT '',
                paper_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'created',
                mcq_duration_seconds INTEGER NOT NULL DEFAULT 7200,
                essay_duration_seconds INTEGER,
                total_marks INTEGER NOT NULL DEFAULT 0,
                student_id TEXT DEFAULT 'student-primary',
                created_at REAL NOT NULL,
                started_at REAL,
                ends_at REAL,
                submitted_at REAL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS exam_answers (
                exam_id TEXT NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
                question_id TEXT NOT NULL,
                answer_text TEXT DEFAULT '',
                option_key TEXT DEFAULT '',
                awarded REAL DEFAULT 0,
                max_marks REAL NOT NULL DEFAULT 1,
                feedback TEXT DEFAULT '',
                verdict TEXT DEFAULT '',
                graded INTEGER NOT NULL DEFAULT 0,
                answered_at REAL,
                PRIMARY KEY (exam_id, question_id)
            )
            """
        )

    @classmethod
    async def save_paper(cls, paper_dict: Dict[str, Any]) -> None:
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            await db.execute(
                "INSERT OR REPLACE INTO exams (id, title, source_filename, paper_json, status,"
                " mcq_duration_seconds, essay_duration_seconds, total_marks, student_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    paper_dict["exam_id"],
                    paper_dict["title"],
                    paper_dict.get("source_filename", ""),
                    json.dumps(paper_dict),
                    paper_dict.get("status", "created"),
                    int(paper_dict.get("mcq_duration_seconds") or 7200),
                    paper_dict.get("essay_duration_seconds"),
                    float(paper_dict.get("total_marks") or 0),
                    paper_dict.get("student_id") or "student-primary",
                    time.time(),
                ),
            )
            await db.commit()

    @classmethod
    async def load_paper(cls, exam_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            cursor = await db.execute("SELECT paper_json FROM exams WHERE id = ?", (exam_id,))
            row = await cursor.fetchone()
        if not row or not row[0]:
            return None
        return json.loads(row[0])

    @classmethod
    async def update_fields(cls, exam_id: str, **fields: Any) -> bool:
        allowed = {"status", "started_at", "ends_at", "submitted_at", "paper_json"}
        sets, vals = [], []
        for key, value in fields.items():
            if key not in allowed:
                continue
            sets.append(f"{key} = ?")
            vals.append(json.dumps(value) if key == "paper_json" else value)
        if not sets:
            return False
        vals.append(exam_id)
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            cursor = await db.execute(f"UPDATE exams SET {', '.join(sets)} WHERE id = ?", vals)
            await db.commit()
            return cursor.rowcount > 0

    @classmethod
    async def list_exams(cls, limit: int = 20) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, title, status, total_marks, created_at, started_at, ends_at, source_filename"
                " FROM exams ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            )
            rows = [dict(r) for r in await cursor.fetchall()]
        out = []
        for r in rows:
            try:
                paper = json.loads(
                    (await cls._paper_json_raw(r["id"])) or "{}"
                )
                r["question_count"] = len(paper.get("questions", []))
            except Exception:  # noqa: BLE001
                r["question_count"] = 0
            out.append(r)
        return out

    @classmethod
    async def _paper_json_raw(cls, exam_id: str) -> Optional[str]:
        async with aiosqlite.connect(_db_path()) as db:
            cursor = await db.execute("SELECT paper_json FROM exams WHERE id = ?", (exam_id,))
            row = await cursor.fetchone()
        return row[0] if row else None

    @classmethod
    async def upsert_answer(cls, exam_id: str, answer: Dict[str, Any], max_marks: float) -> None:
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            await db.execute(
                "INSERT OR REPLACE INTO exam_answers (exam_id, question_id, answer_text, option_key,"
                " awarded, max_marks, feedback, verdict, graded, answered_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    exam_id,
                    str(answer.get("question_id")),
                    str(answer.get("answer_text", "") or "")[:8000],
                    str(answer.get("option_key", "") or ""),
                    float(answer.get("awarded", 0) or 0),
                    float(max_marks),
                    str(answer.get("feedback", "") or "")[:2000],
                    str(answer.get("verdict", "") or ""),
                    1 if answer.get("graded") else 0,
                    time.time(),
                ),
            )
            await db.commit()

    @classmethod
    async def get_answers(cls, exam_id: str) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM exam_answers WHERE exam_id = ? ORDER BY answered_at ASC",
                (exam_id,),
            )
            return [dict(r) for r in await cursor.fetchall()]
