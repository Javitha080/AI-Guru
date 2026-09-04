"""Parent <-> Student pairing service backed by the AI Guru relational schema.

All SQL matches ``services/database/schema.py`` exactly:

``parent_student_links(id, parent_id FK parents NOT NULL, student_id FK students
NOT NULL, pairing_code, pairing_code_expires_at, status pending|active|revoked,
permissions_json, paired_at, created_at, UNIQUE(parent_id, student_id))``

Because both FK columns are NOT NULL, placeholder ``users``/``parents``/
``students`` rows are ensured for the single-student home setup
(``default`` / ``student-primary``) before any link row is written.
"""

from __future__ import annotations

import json
import random
import time
from typing import Any, Dict, List, Optional
import uuid

import aiosqlite

from deeptutor.services.path_service import get_path_service

DEFAULT_PERMISSIONS = {"can_view_live": True, "can_view_reports": True, "can_manage_goals": True}


class PairingService:
    CODE_TTL_SECONDS = 15 * 60

    @staticmethod
    def _get_db_path():
        return get_path_service().user_dir / "chat_history.db"

    # ------------------------------------------------------------- internals

    @classmethod
    async def _ensure_identity_rows(
        cls, db: aiosqlite.Connection, *, parent_id: str, student_id: str
    ) -> None:
        now = time.time()
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('student','parent','admin')),
                display_name TEXT NOT NULL, avatar_url TEXT DEFAULT '',
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            )"""
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS students (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                grade_level TEXT DEFAULT '', school TEXT DEFAULT '', learning_style TEXT DEFAULT 'visual',
                target_daily_minutes INTEGER DEFAULT 60, streak_count INTEGER DEFAULT 0,
                total_xp INTEGER DEFAULT 0, face_embedding_json TEXT DEFAULT '',
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            )"""
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS parents (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                email TEXT DEFAULT '', phone_number TEXT DEFAULT '',
                notification_preferences_json TEXT DEFAULT '{"email": false}',
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            )"""
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS parent_student_links (
                id TEXT PRIMARY KEY,
                parent_id TEXT NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
                student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                pairing_code TEXT DEFAULT '',
                pairing_code_expires_at REAL DEFAULT 0,
                status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'revoked')) DEFAULT 'pending',
                permissions_json TEXT DEFAULT '{"can_view_live": true, "can_view_reports": true, "can_manage_goals": true}',
                paired_at REAL,
                created_at REAL NOT NULL,
                UNIQUE(parent_id, student_id)
            )
            """
        )

        student_user = f"user-{student_id}"
        parent_user = f"user-{parent_id}"
        await db.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role, display_name, avatar_url, created_at, updated_at)"
            " VALUES (?, ?, '', 'student', ?, '', ?, ?)",
            (student_user, f"student:{student_id}", student_id, now, now),
        )
        await db.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role, display_name, avatar_url, created_at, updated_at)"
            " VALUES (?, ?, '', 'parent', ?, '', ?, ?)",
            (parent_user, f"parent:{parent_id}", f"Parent {parent_id}", now, now),
        )
        await db.execute(
            "INSERT OR IGNORE INTO students (id, user_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (student_id, student_user, now, now),
        )
        await db.execute(
            "INSERT OR IGNORE INTO parents (id, user_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (parent_id, parent_user, now, now),
        )

    # ---------------------------------------------------------------- public

    @classmethod
    async def generate_pairing_code(
        cls, student_id: str, parent_id: str = "default"
    ) -> Dict[str, Any]:
        code = f"GURU-{random.randint(100000, 999999)}"
        expires_at = time.time() + cls.CODE_TTL_SECONDS
        link_id = uuid.uuid4().hex

        async with aiosqlite.connect(cls._get_db_path()) as db:
            await cls._ensure_identity_rows(db, parent_id=parent_id, student_id=student_id)
            # Reuse an existing row for the pair (UNIQUE constraint), else insert.
            cursor = await db.execute(
                "SELECT id FROM parent_student_links WHERE parent_id = ? AND student_id = ?",
                (parent_id, student_id),
            )
            row = await cursor.fetchone()
            if row:
                await db.execute(
                    "UPDATE parent_student_links SET pairing_code = ?, pairing_code_expires_at = ?, status = 'pending'"
                    " WHERE id = ?",
                    (code, expires_at, row[0]),
                )
                link_id = row[0]
            else:
                await db.execute(
                    "INSERT INTO parent_student_links (id, parent_id, student_id, pairing_code,"
                    " pairing_code_expires_at, status, permissions_json, created_at)"
                    " VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                    (
                        link_id,
                        parent_id,
                        student_id,
                        code,
                        expires_at,
                        json.dumps(DEFAULT_PERMISSIONS),
                        time.time(),
                    ),
                )
            await db.commit()

        return {"code": code, "expires_in": cls.CODE_TTL_SECONDS, "student_id": student_id}

    @classmethod
    async def verify_pairing_code(cls, parent_id: str, code: str) -> Optional[Dict[str, Any]]:
        now = time.time()
        async with aiosqlite.connect(cls._get_db_path()) as db:
            await cls._ensure_identity_rows(db, parent_id=parent_id, student_id="student-primary")
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM parent_student_links WHERE pairing_code = ? AND status IN ('pending','active')"
                " AND pairing_code_expires_at > ?",
                (code, now),
            )
            link = await cursor.fetchone()
            if not link:
                return None

            await db.execute(
                "UPDATE parent_student_links SET parent_id = ?, status = 'active', paired_at = ? WHERE id = ?",
                (parent_id, now, link["id"]),
            )
            await db.commit()

            cursor = await db.execute(
                "SELECT * FROM parent_student_links WHERE id = ?", (link["id"],)
            )
            return dict(await cursor.fetchone())

    @classmethod
    async def get_linked_students(cls, parent_id: str) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(cls._get_db_path()) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT l.id AS link_id, l.student_id, l.status, l.permissions_json, l.paired_at,
                       u.display_name AS student_name
                FROM parent_student_links l
                LEFT JOIN students s ON s.id = l.student_id
                LEFT JOIN users u ON u.id = s.user_id
                WHERE l.parent_id = ? AND l.status = 'active'
                """,
                (parent_id,),
            )
            rows = [dict(r) for r in await cursor.fetchall()]
        for r in rows:
            try:
                r["permissions"] = json.loads(r.pop("permissions_json") or "{}")
            except Exception:
                r["permissions"] = dict(DEFAULT_PERMISSIONS)
        return rows

    @classmethod
    async def revoke_link(cls, link_id: str) -> bool:
        async with aiosqlite.connect(cls._get_db_path()) as db:
            cursor = await db.execute(
                "UPDATE parent_student_links SET status = 'revoked' WHERE id = ?",
                (link_id,),
            )
            await db.commit()
            return cursor.rowcount > 0
