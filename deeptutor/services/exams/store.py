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
                status TEXT NOT NULL DEFAULT 'created'
                    CHECK (status IN ('created', 'active', 'review', 'submitted', 'graded')),
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
    async def save_paper(
        cls,
        paper_dict: Dict[str, Any],
        *,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert/replace an exam row. ``extra`` may carry sitting metadata:
        ``sitting_id``, ``paper_no``, ``bank_paper_id`` (Paper-Bank links)."""
        extra = extra or {}
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.execute(
                "INSERT OR REPLACE INTO exams (id, title, source_filename, paper_json, status,"
                " mcq_duration_seconds, essay_duration_seconds, total_marks, student_id, created_at,"
                " sitting_id, paper_no, bank_paper_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    str(extra.get("sitting_id") or ""),
                    extra.get("paper_no"),
                    extra.get("bank_paper_id"),
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
    async def claim_for_grading(cls, exam_id: str) -> bool:
        """Atomically transition status → 'graded' from an active phase.

        Accepts both 'active' (timed run) and 'review' (double-check window);
        exactly ONE concurrent caller wins; losers must not write answers or
        award XP twice.
        """
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            cursor = await db.execute(
                "UPDATE exams SET status = 'graded'"
                " WHERE id = ? AND status IN ('active', 'review')",
                (exam_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    @classmethod
    async def claim_status(cls, exam_id: str, *, from_status: str, to_status: str) -> bool:
        """Optimistic single-winner status transition."""
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            cursor = await db.execute(
                "UPDATE exams SET status = ? WHERE id = ? AND status = ?",
                (to_status, exam_id, from_status),
            )
            await db.commit()
            return cursor.rowcount > 0

    @classmethod
    async def save_drafts(cls, exam_id: str, answers: List[Dict[str, Any]]) -> int:
        """Persist draft answers (graded=0) while a part is active/review."""
        paper = await cls.load_paper(exam_id)
        if not paper:
            return 0
        marks_by_qid = {q.get("id"): float(q.get("marks") or 1) for q in paper.get("questions", [])}
        saved = 0
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            for ans in answers:
                qid = str(ans.get("question_id", ""))
                if not qid or qid not in marks_by_qid:
                    continue
                await db.execute(
                    "INSERT OR REPLACE INTO exam_answers (exam_id, question_id, answer_text,"
                    " option_key, awarded, max_marks, feedback, verdict, graded, answered_at)"
                    " VALUES (?, ?, ?, ?, 0, ?, '', '', 0, ?)",
                    (
                        exam_id,
                        qid,
                        str(ans.get("answer_text", "") or "")[:8000],
                        str(ans.get("option_key", "") or ""),
                        marks_by_qid[qid],
                        time.time(),
                    ),
                )
                saved += 1
            await db.commit()
        return saved

    # ------------------------------------------------------------- sittings

    @classmethod
    async def get_sitting(cls, sitting_id: str) -> List[Dict[str, Any]]:
        """All parts of a Paper-Bank sitting, ordered Paper 1 → Paper 2."""
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, title, status, mcq_duration_seconds, total_marks,"
                " student_id, sitting_id, paper_no, bank_paper_id, addon_seconds_used,"
                " xp_multiplier, created_at, started_at, ends_at, submitted_at, paper_json"
                " FROM exams WHERE sitting_id = ? ORDER BY COALESCE(paper_no, 1) ASC",
                (sitting_id,),
            )
            return [dict(r) for r in await cur.fetchall()]

    @classmethod
    async def grant_addon(
        cls,
        exam_id: str,
        *,
        seconds: int,
        multiplier_factor: float,
        max_purchases: int = 2,
        min_multiplier: float = 0.30,
    ) -> Dict[str, Any]:
        """Gamified extra-time purchase for the ACTIVE part of a sitting.

        Optimistic-locking on (status, ends_at): exactly one concurrent caller
        wins; losers get ``{"ok": False, "error": "conflict"}``. The purchase
        counter rides inside ``paper_json.bank_meta`` so no schema change is
        needed to enforce ``max_purchases``.
        """
        async with aiosqlite.connect(_db_path()) as db:
            await cls.ensure_tables(db)
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT status, ends_at, addon_seconds_used, xp_multiplier, paper_json"
                " FROM exams WHERE id = ?",
                (exam_id,),
            )
            row = await cur.fetchone()
            if not row:
                return {"ok": False, "error": "not_found"}

            meta: Dict[str, Any] = {}
            try:
                meta = json.loads(row["paper_json"] or "{}")
            except json.JSONDecodeError:  # pragma: no cover
                pass
            purchases = int((meta.get("bank_meta") or {}).get("purchases", 0))

            if row["status"] != "active":
                return {"ok": False, "error": "not_active"}
            if purchases >= max_purchases:
                return {"ok": False, "error": "purchase_cap", "purchases": purchases}

            new_mult = round(float(row["xp_multiplier"] or 1.0) * multiplier_factor, 4)
            if new_mult < min_multiplier:
                return {"ok": False, "error": "multiplier_floor", "multiplier": new_mult}

            new_ends = float(row["ends_at"] or 0.0) + seconds
            new_meta = dict(meta)
            new_meta["bank_meta"] = {
                **(meta.get("bank_meta") or {}),
                "purchases": purchases + 1,
            }

            cur = await db.execute(
                "UPDATE exams SET ends_at = ?, addon_seconds_used = addon_seconds_used + ?,"
                " xp_multiplier = ?, paper_json = ?"
                " WHERE id = ? AND status = 'active' AND ends_at = ?",
                (
                    new_ends,
                    int(seconds),
                    new_mult,
                    json.dumps(new_meta),
                    exam_id,
                    row["ends_at"],
                ),
            )
            await db.commit()
            if cur.rowcount == 0:
                return {"ok": False, "error": "conflict"}
            return {
                "ok": True,
                "exam_id": exam_id,
                "added_seconds": int(seconds),
                "ends_at": new_ends,
                "addon_seconds_used": int(row["addon_seconds_used"] or 0) + int(seconds),
                "xp_multiplier": new_mult,
                "purchases": purchases + 1,
            }

    @classmethod
    async def update_fields(cls, exam_id: str, **fields: Any) -> bool:
        allowed = {"status", "started_at", "ends_at", "submitted_at", "paper_json"}
        sets, vals = [], []
        for key, value in fields.items():
            if key not in allowed:
                continue
            sets.append(f"{key} = ?")
            vals.append(value)
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
                paper = json.loads((await cls._paper_json_raw(r["id"])) or "{}")
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
