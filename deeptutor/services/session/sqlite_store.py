"""
SQLite-backed unified chat session store.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any
import uuid

from deeptutor.services.path_service import get_path_service


def _json_dumps(value: Any) -> str:
    # default=str: a single non-serializable object inside an event payload
    # (e.g. a dataclass smuggled into tool args) must degrade to its repr,
    # never kill message/event persistence for the whole turn.
    return json.dumps(value, ensure_ascii=False, default=str)


# Sentinel so ``add_message`` can distinguish "caller wants the legacy
# auto-pick-latest-message default" from "caller explicitly wants the
# message attached at the session root (parent = NULL)". Both surface as
# ``None`` in the public ``parent_message_id`` arg, which is why we need
# a sentinel separate from None.
class _Unset:
    pass


_PARENT_AUTO = _Unset()


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


# Imported conversations share the session tables with native chats but carry
# this id prefix as their discriminator (see ``SQLiteSessionStore._WHERE_*``).
_IMPORTED_ID_PREFIX = "imported_"
_ID_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def make_imported_session_id(source: str, external_id: str) -> str:
    """Build a deterministic, dedup-friendly id for an imported conversation.

    ``source`` (e.g. ``claude_code``/``codex``) namespaces the original
    session uuid so two tools that happen to reuse an id never collide; the
    determinism is what makes re-importing the same folder idempotent.
    """
    src = _ID_SAFE.sub("-", (source or "external").strip()) or "external"
    ext = _ID_SAFE.sub("-", (external_id or "").strip()) or uuid.uuid4().hex
    return f"{_IMPORTED_ID_PREFIX}{src}_{ext}"


@dataclass
class TurnRecord:
    id: str
    session_id: str
    capability: str
    status: str
    error: str
    created_at: float
    updated_at: float
    finished_at: float | None
    last_seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "turn_id": self.id,
            "session_id": self.session_id,
            "capability": self.capability,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "last_seq": self.last_seq,
        }


class SQLiteSessionStore:
    """Persist unified chat sessions and messages in a SQLite database."""

    def __init__(self, db_path: Path | None = None) -> None:
        path_service = get_path_service()
        self.db_path = db_path or path_service.get_chat_history_db()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_db(path_service)
        self._lock = asyncio.Lock()
        self._initialize()

    def _migrate_legacy_db(self, path_service) -> None:
        """Move the legacy ``data/chat_history.db`` into ``data/user/`` once."""
        legacy_path = path_service.project_root / "data" / "chat_history.db"
        if self.db_path.exists() or not legacy_path.exists() or legacy_path == self.db_path:
            return
        try:
            os.replace(legacy_path, self.db_path)
        except OSError:
            # Fall back to leaving the legacy DB in place if an OS-level move
            # is not possible; the new DB path will be initialized empty.
            pass

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT 'New conversation',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    compressed_summary TEXT DEFAULT '',
                    summary_up_to_msg_id INTEGER DEFAULT 0,
                    preferences_json TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    capability TEXT DEFAULT '',
                    events_json TEXT DEFAULT '',
                    attachments_json TEXT DEFAULT '',
                    metadata_json TEXT DEFAULT '{}',
                    created_at REAL NOT NULL,
                    -- Edit-branching: NULL for the first message in a session;
                    -- otherwise the immediately preceding message on the path
                    -- this row continues. Siblings (same parent) are alternate
                    -- branches the user can switch between.
                    parent_message_id INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session_created
                    ON messages(session_id, created_at, id);
                -- ``idx_messages_parent`` is created after the
                -- parent_message_id migration runs (see below). Putting it
                -- in this script would fail on legacy DBs where the column
                -- gets added by ALTER TABLE further down.

                CREATE INDEX IF NOT EXISTS idx_sessions_updated_at
                    ON sessions(updated_at DESC);

                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    capability TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'running',
                    error TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    finished_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_turns_session_updated
                    ON turns(session_id, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_turns_session_status
                    ON turns(session_id, status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS turn_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                    seq INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    stage TEXT DEFAULT '',
                    content TEXT DEFAULT '',
                    metadata_json TEXT DEFAULT '',
                    timestamp REAL NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(turn_id, seq)
                );

                CREATE INDEX IF NOT EXISTS idx_turn_events_turn_seq
                    ON turn_events(turn_id, seq);

                CREATE TABLE IF NOT EXISTS notebook_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    turn_id TEXT NOT NULL DEFAULT '',
                    question_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    question_type TEXT DEFAULT '',
                    options_json TEXT DEFAULT '{}',
                    correct_answer TEXT DEFAULT '',
                    explanation TEXT DEFAULT '',
                    difficulty TEXT DEFAULT '',
                    user_answer TEXT DEFAULT '',
                    user_answer_images_json TEXT DEFAULT '[]',
                    is_correct INTEGER DEFAULT 0,
                    bookmarked INTEGER DEFAULT 0,
                    followup_session_id TEXT DEFAULT '',
                    ai_judgment TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(session_id, turn_id, question_id)
                );

                CREATE INDEX IF NOT EXISTS idx_notebook_entries_session
                    ON notebook_entries(session_id, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_notebook_entries_bookmarked
                    ON notebook_entries(bookmarked, created_at DESC);

                CREATE TABLE IF NOT EXISTS notebook_categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS notebook_entry_categories (
                    entry_id INTEGER NOT NULL REFERENCES notebook_entries(id) ON DELETE CASCADE,
                    category_id INTEGER NOT NULL REFERENCES notebook_categories(id) ON DELETE CASCADE,
                    PRIMARY KEY (entry_id, category_id)
                );
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
            if "preferences_json" not in columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN preferences_json TEXT DEFAULT '{}'")
            if "kind" in columns:
                try:
                    conn.execute("ALTER TABLE sessions DROP COLUMN kind")
                except sqlite3.OperationalError:
                    # Older SQLite builds may not support DROP COLUMN. The
                    # application no longer reads or writes this legacy field.
                    pass
            message_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "metadata_json" not in message_columns:
                conn.execute("ALTER TABLE messages ADD COLUMN metadata_json TEXT DEFAULT '{}'")
            if "parent_message_id" not in message_columns:
                conn.execute("ALTER TABLE messages ADD COLUMN parent_message_id INTEGER")
                # Backfill: for every existing session, treat the message stream
                # as a single linear path — each row's parent is the previous
                # row (by id) in the same session. Rows with no predecessor stay
                # NULL. We do this per session in pure Python to avoid relying
                # on window functions, which older SQLite builds may not have.
                sessions_rows = conn.execute("SELECT id FROM sessions").fetchall()
                for srow in sessions_rows:
                    prev_id: int | None = None
                    msg_rows = conn.execute(
                        "SELECT id FROM messages WHERE session_id = ? ORDER BY id ASC",
                        (srow[0],),
                    ).fetchall()
                    for mrow in msg_rows:
                        if prev_id is not None:
                            conn.execute(
                                "UPDATE messages SET parent_message_id = ? WHERE id = ?",
                                (prev_id, mrow[0]),
                            )
                        prev_id = mrow[0]
            # Always ensure the parent-lookup index exists — covers both
            # the legacy-migration case (just added the column) and the
            # fresh-DB case (created above without the index inline).
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_parent "
                "ON messages(session_id, parent_message_id)"
            )
            self._migrate_notebook_entries_add_turn_id(conn)
            self._migrate_notebook_entries_add_user_answer_images(conn)
            self._migrate_notebook_entries_add_ai_judgment(conn)
            # Run AI Guru core relational migrations
            from deeptutor.services.database.migrations import apply_migrations

            apply_migrations(conn)
            conn.commit()

    @staticmethod
    def _migrate_notebook_entries_add_turn_id(conn: sqlite3.Connection) -> None:
        """Add ``turn_id`` to legacy notebook_entries and re-scope the UNIQUE
        constraint to ``(session_id, turn_id, question_id)``.

        The old unique constraint conflated quizzes generated in the same chat
        (issue #487): regenerating a quiz with the same positional
        ``question_id`` (e.g. ``q_1``) would collide with the previous quiz's
        notebook entries and the UI hydrated stale answers. Scoping by
        ``turn_id`` keeps each quiz isolated.
        """
        notebook_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(notebook_entries)").fetchall()
        }
        if not notebook_cols:
            return
        if "turn_id" not in notebook_cols:
            conn.execute("ALTER TABLE notebook_entries ADD COLUMN turn_id TEXT NOT NULL DEFAULT ''")
        # SQLite stores table-level UNIQUE constraints as auto-indexes whose
        # names start with ``sqlite_autoindex_notebook_entries_``; the columns
        # they cover live in PRAGMA index_info. Detect whether any existing
        # auto-index still covers only (session_id, question_id) and, if so,
        # rebuild the table to swap in the new scope.
        needs_rebuild = False
        for idx_row in conn.execute("PRAGMA index_list(notebook_entries)").fetchall():
            idx_name = idx_row[1]
            if not idx_name.startswith("sqlite_autoindex_notebook_entries_"):
                continue
            cols = [r[2] for r in conn.execute(f"PRAGMA index_info({idx_name})").fetchall()]
            if cols == ["session_id", "question_id"]:
                needs_rebuild = True
                break
        if not needs_rebuild:
            return
        conn.executescript(
            """
            CREATE TABLE notebook_entries_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                turn_id TEXT NOT NULL DEFAULT '',
                question_id TEXT NOT NULL,
                question TEXT NOT NULL,
                question_type TEXT DEFAULT '',
                options_json TEXT DEFAULT '{}',
                correct_answer TEXT DEFAULT '',
                explanation TEXT DEFAULT '',
                difficulty TEXT DEFAULT '',
                user_answer TEXT DEFAULT '',
                is_correct INTEGER DEFAULT 0,
                bookmarked INTEGER DEFAULT 0,
                followup_session_id TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(session_id, turn_id, question_id)
            );

            INSERT INTO notebook_entries_new (
                id, session_id, turn_id, question_id, question, question_type,
                options_json, correct_answer, explanation, difficulty,
                user_answer, is_correct, bookmarked, followup_session_id,
                created_at, updated_at
            )
            SELECT
                id, session_id, COALESCE(turn_id, ''), question_id, question,
                question_type, options_json, correct_answer, explanation,
                difficulty, user_answer, is_correct, bookmarked,
                followup_session_id, created_at, updated_at
            FROM notebook_entries;

            DROP TABLE notebook_entries;
            ALTER TABLE notebook_entries_new RENAME TO notebook_entries;

            CREATE INDEX IF NOT EXISTS idx_notebook_entries_session
                ON notebook_entries(session_id, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_notebook_entries_bookmarked
                ON notebook_entries(bookmarked, created_at DESC);
            """
        )

    @staticmethod
    def _migrate_notebook_entries_add_user_answer_images(
        conn: sqlite3.Connection,
    ) -> None:
        """Back-fill ``user_answer_images_json`` on legacy DBs.

        The column stores a JSON array of ``{id, url, filename, mime_type}``
        records for image attachments uploaded as part of the learner's
        answer. The bytes themselves live in the AttachmentStore; we only
        keep references in the row so notebook_entries stays lean.
        """
        cols = {row[1] for row in conn.execute("PRAGMA table_info(notebook_entries)").fetchall()}
        if not cols:
            return
        if "user_answer_images_json" not in cols:
            conn.execute(
                "ALTER TABLE notebook_entries ADD COLUMN user_answer_images_json TEXT DEFAULT '[]'"
            )

    @staticmethod
    def _migrate_notebook_entries_add_ai_judgment(
        conn: sqlite3.Connection,
    ) -> None:
        """Back-fill ``ai_judgment`` on legacy DBs.

        Stores the latest AI-judge text per entry as plain markdown. Empty
        string means the learner has not run the AI judge for this entry
        yet.
        """
        cols = {row[1] for row in conn.execute("PRAGMA table_info(notebook_entries)").fetchall()}
        if not cols:
            return
        if "ai_judgment" not in cols:
            conn.execute("ALTER TABLE notebook_entries ADD COLUMN ai_judgment TEXT DEFAULT ''")

    async def _run(self, fn, *args):
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # sqlite3.Connection's own context manager commits/rolls back but does
        # NOT close the connection — so naked `with sqlite3.connect(...)` leaks
        # one FD per call until GC. Wrap it so each call site gets both
        # transaction semantics and deterministic close. The inner `with conn`
        # commits on clean exit and rolls back on exception, so call sites do
        # NOT need an explicit conn.commit() (any remaining ones are no-ops).
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError:
            pass
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _create_session_sync(
        self,
        title: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        resolved_id = session_id or f"unified_{int(now * 1000)}_{uuid.uuid4().hex[:8]}"
        resolved_title = (title or "New conversation").strip() or "New conversation"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    id, title, created_at, updated_at,
                    compressed_summary, summary_up_to_msg_id
                )
                VALUES (?, ?, ?, ?, '', 0)
                """,
                (resolved_id, resolved_title[:100], now, now),
            )
            conn.commit()
        return {
            "id": resolved_id,
            "session_id": resolved_id,
            "title": resolved_title[:100],
            "created_at": now,
            "updated_at": now,
            "compressed_summary": "",
            "summary_up_to_msg_id": 0,
        }

    async def create_session(
        self,
        title: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._run(self._create_session_sync, title, session_id)

    def _get_session_sync(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    s.id,
                    s.title,
                    s.created_at,
                    s.updated_at,
                    s.compressed_summary,
                    s.summary_up_to_msg_id,
                    s.preferences_json,
                    COALESCE(
                        (
                            SELECT t.status
                            FROM turns t
                            WHERE t.session_id = s.id
                            ORDER BY t.updated_at DESC
                            LIMIT 1
                        ),
                        'idle'
                    ) AS status,
                    COALESCE(
                        (
                            SELECT t.id
                            FROM turns t
                            WHERE t.session_id = s.id AND t.status = 'running'
                            ORDER BY t.updated_at DESC
                            LIMIT 1
                        ),
                        ''
                    ) AS active_turn_id,
                    COALESCE(
                        (
                            SELECT t.capability
                            FROM turns t
                            WHERE t.session_id = s.id
                            ORDER BY t.updated_at DESC
                            LIMIT 1
                        ),
                        ''
                    ) AS capability
                FROM sessions
                s
                WHERE s.id = ?
                """,
                (session_id,),
            ).fetchone()
        if not row:
            return None
        payload = dict(row)
        payload["session_id"] = payload["id"]
        payload["preferences"] = _json_loads(payload.pop("preferences_json", ""), {})
        return payload

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        return await self._run(self._get_session_sync, session_id)

    async def ensure_session(
        self,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if session_id:
            session = await self.get_session(session_id)
            if session is not None:
                return session
        return await self.create_session()

    @staticmethod
    def _serialize_turn(row: sqlite3.Row) -> dict[str, Any]:
        return TurnRecord(
            id=row["id"],
            session_id=row["session_id"],
            capability=row["capability"] or "",
            status=row["status"] or "running",
            error=row["error"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            finished_at=row["finished_at"],
            last_seq=row["last_seq"] if "last_seq" in row.keys() else 0,
        ).to_dict()

    def _create_turn_sync(self, session_id: str, capability: str = "") -> dict[str, Any]:
        now = time.time()
        turn_id = f"turn_{int(now * 1000)}_{uuid.uuid4().hex[:10]}"
        with self._connect() as conn:
            session = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                raise ValueError(f"Session not found: {session_id}")
            active = conn.execute(
                """
                SELECT id
                FROM turns
                WHERE session_id = ? AND status = 'running'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            if active is not None:
                raise RuntimeError(f"Session already has an active turn: {active['id']}")
            conn.execute(
                """
                INSERT INTO turns (id, session_id, capability, status, error, created_at, updated_at, finished_at)
                VALUES (?, ?, ?, 'running', '', ?, ?, NULL)
                """,
                (turn_id, session_id, capability or "", now, now),
            )
            conn.commit()
        return {
            "id": turn_id,
            "turn_id": turn_id,
            "session_id": session_id,
            "capability": capability or "",
            "status": "running",
            "error": "",
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
            "last_seq": 0,
        }

    async def create_turn(self, session_id: str, capability: str = "") -> dict[str, Any]:
        return await self._run(self._create_turn_sync, session_id, capability)

    def _get_turn_sync(self, turn_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    t.*,
                    COALESCE((SELECT MAX(seq) FROM turn_events te WHERE te.turn_id = t.id), 0) AS last_seq
                FROM turns t
                WHERE t.id = ?
                """,
                (turn_id,),
            ).fetchone()
        if row is None:
            return None
        return self._serialize_turn(row)

    async def get_turn(self, turn_id: str) -> dict[str, Any] | None:
        return await self._run(self._get_turn_sync, turn_id)

    def _get_active_turn_sync(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    t.*,
                    COALESCE((SELECT MAX(seq) FROM turn_events te WHERE te.turn_id = t.id), 0) AS last_seq
                FROM turns t
                WHERE t.session_id = ? AND t.status = 'running'
                ORDER BY t.updated_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return self._serialize_turn(row)

    async def get_active_turn(self, session_id: str) -> dict[str, Any] | None:
        return await self._run(self._get_active_turn_sync, session_id)

    def _list_active_turns_sync(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    t.*,
                    COALESCE((SELECT MAX(seq) FROM turn_events te WHERE te.turn_id = t.id), 0) AS last_seq
                FROM turns t
                WHERE t.session_id = ? AND t.status = 'running'
                ORDER BY t.updated_at DESC
                """,
                (session_id,),
            ).fetchall()
        return [self._serialize_turn(row) for row in rows]

    async def list_active_turns(self, session_id: str) -> list[dict[str, Any]]:
        return await self._run(self._list_active_turns_sync, session_id)

    def _update_turn_status_sync(self, turn_id: str, status: str, error: str = "") -> bool:
        now = time.time()
        finished_at = now if status in {"completed", "failed", "cancelled"} else None
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE turns
                SET status = ?, error = ?, updated_at = ?, finished_at = ?
                WHERE id = ?
                """,
                (status, error or "", now, finished_at, turn_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def update_turn_status(self, turn_id: str, status: str, error: str = "") -> bool:
        return await self._run(self._update_turn_status_sync, turn_id, status, error)

    def _append_turn_event_sync(self, turn_id: str, event: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            turn = conn.execute(
                "SELECT id, session_id FROM turns WHERE id = ?", (turn_id,)
            ).fetchone()
            if turn is None:
                raise ValueError(f"Turn not found: {turn_id}")
            provided_seq = int(event.get("seq") or 0)
            if provided_seq > 0:
                seq = provided_seq
            else:
                row = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) AS last_seq FROM turn_events WHERE turn_id = ?",
                    (turn_id,),
                ).fetchone()
                seq = int(row["last_seq"]) + 1 if row else 1
            payload = dict(event)
            payload["seq"] = seq
            payload["turn_id"] = payload.get("turn_id") or turn_id
            payload["session_id"] = payload.get("session_id") or turn["session_id"]
            conn.execute(
                """
                INSERT OR REPLACE INTO turn_events (
                    turn_id, seq, type, source, stage, content, metadata_json, timestamp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    seq,
                    payload.get("type", ""),
                    payload.get("source", ""),
                    payload.get("stage", ""),
                    payload.get("content", "") or "",
                    _json_dumps(payload.get("metadata", {})),
                    float(payload.get("timestamp") or now),
                    now,
                ),
            )
            conn.execute(
                "UPDATE turns SET updated_at = ? WHERE id = ?",
                (now, turn_id),
            )
            conn.commit()
        return payload

    async def append_turn_event(self, turn_id: str, event: dict[str, Any]) -> dict[str, Any]:
        return await self._run(self._append_turn_event_sync, turn_id, event)

    def _append_turn_events_sync(
        self, turn_id: str, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        # Batch variant of _append_turn_event_sync: one transaction for the whole
        # post-stream flush instead of one fsync'd commit per event. On slow
        # storage (e.g. NAS spinning disks) per-event commits stretch a turn's
        # finalisation to minutes while the client spinner keeps running.
        now = time.time()
        with self._connect() as conn:
            turn = conn.execute(
                "SELECT id, session_id FROM turns WHERE id = ?", (turn_id,)
            ).fetchone()
            if turn is None:
                raise ValueError(f"Turn not found: {turn_id}")
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS last_seq FROM turn_events WHERE turn_id = ?",
                (turn_id,),
            ).fetchone()
            next_seq = (int(row["last_seq"]) if row else 0) + 1
            payloads: list[dict[str, Any]] = []
            rows: list[tuple[Any, ...]] = []
            for event in events:
                provided_seq = int(event.get("seq") or 0)
                if provided_seq > 0:
                    seq = provided_seq
                    next_seq = max(next_seq, provided_seq + 1)
                else:
                    seq = next_seq
                    next_seq += 1
                payload = dict(event)
                payload["seq"] = seq
                payload["turn_id"] = payload.get("turn_id") or turn_id
                payload["session_id"] = payload.get("session_id") or turn["session_id"]
                payloads.append(payload)
                rows.append(
                    (
                        turn_id,
                        seq,
                        payload.get("type", ""),
                        payload.get("source", ""),
                        payload.get("stage", ""),
                        payload.get("content", "") or "",
                        _json_dumps(payload.get("metadata", {})),
                        float(payload.get("timestamp") or now),
                        now,
                    )
                )
            conn.executemany(
                """
                INSERT OR REPLACE INTO turn_events (
                    turn_id, seq, type, source, stage, content, metadata_json, timestamp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.execute(
                "UPDATE turns SET updated_at = ? WHERE id = ?",
                (now, turn_id),
            )
            conn.commit()
        return payloads

    async def append_turn_events(
        self, turn_id: str, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return await self._run(self._append_turn_events_sync, turn_id, events)

    def _get_turn_events_sync(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT turn_id, seq, type, source, stage, content, metadata_json, timestamp
                FROM turn_events
                WHERE turn_id = ? AND seq > ?
                ORDER BY seq ASC
                """,
                (turn_id, max(0, int(after_seq))),
            ).fetchall()
            turn = conn.execute("SELECT session_id FROM turns WHERE id = ?", (turn_id,)).fetchone()
        session_id = turn["session_id"] if turn else ""
        return [
            {
                "type": row["type"],
                "source": row["source"] or "",
                "stage": row["stage"] or "",
                "content": row["content"] or "",
                "metadata": _json_loads(row["metadata_json"], {}),
                "session_id": session_id,
                "turn_id": row["turn_id"],
                "seq": row["seq"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]

    async def get_turn_events(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        return await self._run(self._get_turn_events_sync, turn_id, after_seq)

    def _update_session_title_sync(self, session_id: str, title: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE sessions
                SET title = ?, updated_at = ?
                WHERE id = ?
                """,
                ((title.strip() or "New conversation")[:100], time.time(), session_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def update_session_title(self, session_id: str, title: str) -> bool:
        return await self._run(self._update_session_title_sync, session_id, title)

    def _delete_session_sync(self, session_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
        return cur.rowcount > 0

    async def delete_session(self, session_id: str) -> bool:
        return await self._run(self._delete_session_sync, session_id)

    def _add_message_sync(
        self,
        session_id: str,
        role: str,
        content: str,
        capability: str = "",
        events: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        parent_message_id: int | str | None | _Unset = _PARENT_AUTO,
    ) -> int:
        now = time.time()
        with self._connect() as conn:
            session = conn.execute(
                "SELECT id, title FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if session is None:
                raise ValueError(f"Session not found: {session_id}")

            resolved_parent_id: int | None
            if isinstance(parent_message_id, _Unset):
                # Legacy auto-append path: chain off the latest row in the
                # session so the linear thread stays connected.
                last_row = conn.execute(
                    "SELECT id FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT 1",
                    (session_id,),
                ).fetchone()
                resolved_parent_id = int(last_row["id"]) if last_row is not None else None
            else:
                # Caller pinned a parent explicitly — including ``None``,
                # which means "attach at the session root" (used by edits
                # of the very first message in a session).
                resolved_parent_id = (
                    int(parent_message_id) if parent_message_id is not None else None
                )

            cur = conn.execute(
                """
                INSERT INTO messages (
                    session_id, role, content, capability, events_json,
                    attachments_json, metadata_json, created_at, parent_message_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    content or "",
                    capability or "",
                    _json_dumps(events or []),
                    _json_dumps(attachments or []),
                    _json_dumps(metadata or {}),
                    now,
                    resolved_parent_id,
                ),
            )

            # Title is no longer derived from the first user message — the
            # turn runtime calls an LLM to generate a real summary title
            # once the first user+assistant pair is complete. Until then
            # the session keeps the default sentinel ``New conversation``
            # which the frontend renders as a breathing "New chat" chip.
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            conn.commit()
            return int(cur.lastrowid)

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        capability: str = "",
        events: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        # ``str`` satisfies SessionStoreProtocol (PocketBase parents are string
        # record ids); on the SQLite backend a non-None parent is always the
        # integer rowid this store itself returned.
        parent_message_id: int | str | None | _Unset = _PARENT_AUTO,
    ) -> int:
        return await self._run(
            self._add_message_sync,
            session_id,
            role,
            content,
            capability,
            events,
            attachments,
            metadata,
            parent_message_id,
        )

    @staticmethod
    def _backfill_import_meta_sync(
        conn: sqlite3.Connection,
        session_id: str,
        current_prefs_json: str | None,
        incoming_prefs: dict[str, Any],
    ) -> bool:
        """Merge agent attribution from a re-import into an existing session's
        ``preferences.import`` block, leaving everything else untouched. Returns
        whether anything changed (so the caller can skip a needless write)."""
        incoming_import = (incoming_prefs or {}).get("import") or {}
        if not incoming_import:
            return False
        prefs = _json_loads(current_prefs_json, {})
        if not isinstance(prefs, dict):
            prefs = {}
        meta = dict(prefs.get("import") or {})
        changed = False
        # Only attribution fields propagate on re-import; source/external_id are
        # part of the dedup identity and never change for a given session.
        for key in ("agent_id", "agent_name", "source_cwd"):
            value = incoming_import.get(key)
            if value and meta.get(key) != value:
                meta[key] = value
                changed = True
        if not changed:
            return False
        prefs["import"] = meta
        conn.execute(
            "UPDATE sessions SET preferences_json = ? WHERE id = ?",
            (_json_dumps(prefs), session_id),
        )
        return True

    def _import_session_sync(
        self,
        session_id: str,
        title: str,
        created_at: float,
        updated_at: float,
        preferences: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT preferences_json FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if existing is not None:
                # Idempotent on content: a session imported before keeps its
                # (possibly already-continued) state — re-importing the same
                # folder never duplicates rows or clobbers the user's edits.
                # We do, however, backfill agent attribution (agent_id /
                # agent_name) so re-syncing re-tags conversations that were
                # imported before the agent model existed, and an agent rename
                # propagates. This only touches the ``import`` metadata block.
                updated = self._backfill_import_meta_sync(
                    conn, session_id, existing["preferences_json"], preferences
                )
                if updated:
                    conn.commit()
                return {
                    "session_id": session_id,
                    "imported": False,
                    "updated": updated,
                    "message_count": 0,
                }
            safe_title = (title or "").strip()[:100] or "Imported conversation"
            conn.execute(
                """
                INSERT INTO sessions (
                    id, title, created_at, updated_at,
                    compressed_summary, summary_up_to_msg_id, preferences_json
                ) VALUES (?, ?, ?, ?, '', 0, ?)
                """,
                (session_id, safe_title, created_at, updated_at, _json_dumps(preferences or {})),
            )
            prev_id: int | None = None
            count = 0
            for msg in messages:
                cur = conn.execute(
                    """
                    INSERT INTO messages (
                        session_id, role, content, capability, events_json,
                        attachments_json, metadata_json, created_at, parent_message_id
                    ) VALUES (?, ?, ?, '', '[]', '[]', ?, ?, ?)
                    """,
                    (
                        session_id,
                        msg.get("role") or "user",
                        msg.get("content") or "",
                        _json_dumps(msg.get("metadata") or {}),
                        float(msg.get("created_at") or created_at),
                        prev_id,
                    ),
                )
                prev_id = int(cur.lastrowid)
                count += 1
            conn.commit()
        return {"session_id": session_id, "imported": True, "message_count": count}

    async def import_session(
        self,
        session_id: str,
        title: str,
        created_at: float,
        updated_at: float,
        preferences: dict[str, Any] | None,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Persist a pre-existing conversation (imported from an external CLI
        such as Claude Code or Codex) as a normal session, so the chat loop can
        re-open and continue it. ``session_id`` must carry the ``imported_``
        prefix (see :data:`_IMPORTED_ID_PREFIX`). Idempotent by id: a session
        already present is left untouched.
        """
        return await self._run(
            self._import_session_sync,
            session_id,
            title,
            created_at,
            updated_at,
            preferences or {},
            messages,
        )

    def _delete_message_sync(self, message_id: int | str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM messages WHERE id = ?", (int(message_id),))
            conn.commit()
        return cur.rowcount > 0

    async def delete_message(self, message_id: int | str) -> bool:
        return await self._run(self._delete_message_sync, message_id)

    def _delete_turn_by_message_sync(self, session_id: str, message_id: int) -> dict[str, Any]:
        with self._connect() as conn:
            msg = conn.execute(
                """
                SELECT id, session_id, role, attachments_json, created_at
                FROM messages
                WHERE id = ?
                """,
                (int(message_id),),
            ).fetchone()
            if msg is None or msg["session_id"] != session_id:
                return {
                    "deleted": False,
                    "attachment_ids": [],
                    "turn_id": None,
                    "was_running": False,
                }

            role = msg["role"]
            paired_msg = None
            if role == "user":
                paired_msg = conn.execute(
                    """
                    SELECT id, session_id, role, attachments_json, created_at
                    FROM messages
                    WHERE session_id = ? AND role = 'assistant' AND id > ?
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (session_id, int(message_id)),
                ).fetchone()
            elif role == "assistant":
                paired_msg = conn.execute(
                    """
                    SELECT id, session_id, role, attachments_json, created_at
                    FROM messages
                    WHERE session_id = ? AND role = 'user' AND id < ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (session_id, int(message_id)),
                ).fetchone()

            user_msg = msg if role == "user" else paired_msg
            turn_id = None
            was_running = False
            if user_msg is not None:
                user_created_at = user_msg["created_at"]
                turn_row = conn.execute(
                    """
                    SELECT id, status
                    FROM turns
                    WHERE session_id = ? AND created_at >= ?
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (session_id, user_created_at),
                ).fetchone()
                if turn_row is not None:
                    turn_id = turn_row["id"]
                    was_running = turn_row["status"] == "running"

            if was_running:
                return {
                    "deleted": False,
                    "attachment_ids": [],
                    "turn_id": turn_id,
                    "was_running": True,
                }

            attachment_ids: list[str] = []
            for m in [msg, paired_msg]:
                if m is not None:
                    atts = _json_loads(m["attachments_json"], [])
                    for att in atts:
                        aid = att.get("id") or att.get("attachment_id")
                        if aid:
                            attachment_ids.append(aid)

            if turn_id is not None:
                conn.execute("DELETE FROM turn_events WHERE turn_id = ?", (turn_id,))
                conn.execute("DELETE FROM turns WHERE id = ?", (turn_id,))

            ids_to_delete = [int(message_id)]
            if paired_msg is not None:
                ids_to_delete.append(int(paired_msg["id"]))
            conn.execute(
                f"DELETE FROM messages WHERE id IN ({','.join('?' * len(ids_to_delete))})",  # nosec B608
                tuple(ids_to_delete),
            )

            session_row = conn.execute(
                "SELECT summary_up_to_msg_id FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if session_row is not None:
                summary_up_to = int(session_row["summary_up_to_msg_id"])
                if any(mid <= summary_up_to for mid in ids_to_delete):
                    conn.execute(
                        "UPDATE sessions SET summary_up_to_msg_id = 0 WHERE id = ?",
                        (session_id,),
                    )

            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (time.time(), session_id),
            )
            conn.commit()

        return {
            "deleted": True,
            "attachment_ids": attachment_ids,
            "turn_id": turn_id,
            "was_running": was_running,
        }

    async def delete_turn_by_message(self, session_id: str, message_id: int) -> dict[str, Any]:
        return await self._run(self._delete_turn_by_message_sync, session_id, message_id)

    def _get_last_message_sync(
        self, session_id: str, role: str | None = None
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            if role is None:
                row = conn.execute(
                    """
                    SELECT id, session_id, role, content, capability, events_json,
                           attachments_json, metadata_json, created_at, parent_message_id
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (session_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT id, session_id, role, content, capability, events_json,
                           attachments_json, metadata_json, created_at, parent_message_id
                    FROM messages
                    WHERE session_id = ? AND role = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (session_id, role),
                ).fetchone()
        if row is None:
            return None
        return self._serialize_message(row)

    async def get_last_message(
        self, session_id: str, role: str | None = None
    ) -> dict[str, Any] | None:
        return await self._run(self._get_last_message_sync, session_id, role)

    def _serialize_message(self, row: sqlite3.Row) -> dict[str, Any]:
        row_keys = row.keys()
        parent_id = row["parent_message_id"] if "parent_message_id" in row_keys else None
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "role": row["role"],
            "content": row["content"],
            "capability": row["capability"] or "",
            "events": _json_loads(row["events_json"], []),
            "attachments": _json_loads(row["attachments_json"], []),
            "metadata": _json_loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "parent_message_id": int(parent_id) if parent_id is not None else None,
        }

    def _get_messages_sync(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, role, content, capability, events_json,
                       attachments_json, metadata_json, created_at, parent_message_id
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
        return [self._serialize_message(row) for row in rows]

    def _get_message_path_sync(self, session_id: str, leaf_message_id: int) -> list[dict[str, Any]]:
        """Return the chain of messages from the session root down to
        ``leaf_message_id`` (inclusive), in chronological order.

        Used by the turn runtime to build LLM context for a branched
        re-run: only ancestors of the new user message are included, so
        sibling branches at any depth are excluded.
        """
        with self._connect() as conn:
            chain: list[dict[str, Any]] = []
            current: int | None = int(leaf_message_id)
            # Bound the walk defensively in case of corrupted parent pointers.
            safety = 10_000
            while current is not None and safety > 0:
                row = conn.execute(
                    """
                    SELECT id, session_id, role, content, capability, events_json,
                           attachments_json, metadata_json, created_at, parent_message_id
                    FROM messages
                    WHERE id = ? AND session_id = ?
                    """,
                    (current, session_id),
                ).fetchone()
                if row is None:
                    break
                chain.append(self._serialize_message(row))
                parent = row["parent_message_id"]
                current = int(parent) if parent is not None else None
                safety -= 1
        chain.reverse()
        return chain

    async def get_message_path(self, session_id: str, leaf_message_id: int) -> list[dict[str, Any]]:
        return await self._run(self._get_message_path_sync, session_id, int(leaf_message_id))

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        return await self._run(self._get_messages_sync, session_id)

    def _get_messages_for_context_sync(
        self, session_id: str, leaf_message_id: int | None = None
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if leaf_message_id is None:
                rows = conn.execute(
                    """
                    SELECT id, role, content
                    FROM messages
                    WHERE session_id = ?
                      AND role IN ('user', 'assistant', 'system')
                    ORDER BY id ASC
                    """,
                    (session_id,),
                ).fetchall()
                return [
                    {
                        "id": row["id"],
                        "role": row["role"],
                        "content": row["content"] or "",
                    }
                    for row in rows
                ]
            # Branch-aware path walk: include only ancestors (+ leaf) so
            # sibling branches at any depth are excluded from LLM context.
            chain: list[dict[str, Any]] = []
            current: int | None = int(leaf_message_id)
            safety = 10_000
            while current is not None and safety > 0:
                row = conn.execute(
                    """
                    SELECT id, role, content, parent_message_id
                    FROM messages
                    WHERE id = ? AND session_id = ?
                      AND role IN ('user', 'assistant', 'system')
                    """,
                    (current, session_id),
                ).fetchone()
                if row is None:
                    break
                chain.append(
                    {
                        "id": row["id"],
                        "role": row["role"],
                        "content": row["content"] or "",
                    }
                )
                parent = row["parent_message_id"]
                current = int(parent) if parent is not None else None
                safety -= 1
        chain.reverse()
        return chain

    async def get_messages_for_context(
        self, session_id: str, leaf_message_id: int | None = None
    ) -> list[dict[str, Any]]:
        return await self._run(self._get_messages_for_context_sync, session_id, leaf_message_id)

    # Imported conversations live in the same tables as native chats (so the
    # chat loop can re-open and continue them) but carry an ``imported_`` id
    # prefix. That prefix is the discriminator — it travels with the primary
    # key, so we filter on it instead of adding a column + migration.
    _SESSION_SUMMARY_SQL = """
        SELECT
            s.id,
            s.title,
            s.created_at,
            s.updated_at,
            s.compressed_summary,
            s.summary_up_to_msg_id,
            s.preferences_json,
            COUNT(m.id) AS message_count,
            COALESCE(
                (SELECT t.status FROM turns t WHERE t.session_id = s.id
                 ORDER BY t.updated_at DESC LIMIT 1),
                'idle'
            ) AS status,
            COALESCE(
                (SELECT t.id FROM turns t WHERE t.session_id = s.id AND t.status = 'running'
                 ORDER BY t.updated_at DESC LIMIT 1),
                ''
            ) AS active_turn_id,
            COALESCE(
                (SELECT t.capability FROM turns t WHERE t.session_id = s.id
                 ORDER BY t.updated_at DESC LIMIT 1),
                ''
            ) AS capability,
            COALESCE(
                (SELECT m2.content FROM messages m2
                 WHERE m2.session_id = s.id AND TRIM(COALESCE(m2.content, '')) != ''
                 ORDER BY m2.id DESC LIMIT 1),
                ''
            ) AS last_message
        FROM sessions s
        LEFT JOIN messages m ON m.session_id = s.id
        {where}
        GROUP BY s.id
        ORDER BY s.updated_at DESC
        LIMIT ? OFFSET ?
    """

    # ``ESCAPE '\'`` makes the underscore in ``imported_`` literal rather than
    # the LIKE single-char wildcard.
    _WHERE_NATIVE = r"WHERE s.id NOT LIKE 'imported\_%' ESCAPE '\'"
    _WHERE_IMPORTED = r"WHERE s.id LIKE 'imported\_%' ESCAPE '\'"

    def _list_session_summaries_sync(
        self, where_sql: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                self._SESSION_SUMMARY_SQL.format(where=where_sql),
                (limit, offset),
            ).fetchall()
        sessions = []
        for row in rows:
            payload = dict(row)
            payload["session_id"] = payload["id"]
            payload["preferences"] = _json_loads(payload.pop("preferences_json", ""), {})
            sessions.append(payload)
        return sessions

    def _list_sessions_sync(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        # Native chats only — imported histories surface under their own
        # Space category, not the regular history list.
        return self._list_session_summaries_sync(self._WHERE_NATIVE, limit, offset)

    def _list_imported_sessions_sync(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self._list_session_summaries_sync(self._WHERE_IMPORTED, limit, offset)

    async def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self._run(self._list_sessions_sync, limit, offset)

    async def list_imported_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self._run(self._list_imported_sessions_sync, limit, offset)

    def _update_summary_sync(self, session_id: str, summary: str, up_to_msg_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE sessions
                SET compressed_summary = ?, summary_up_to_msg_id = ?, updated_at = updated_at
                WHERE id = ?
                """,
                (summary, max(0, int(up_to_msg_id)), session_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def update_summary(self, session_id: str, summary: str, up_to_msg_id: int) -> bool:
        return await self._run(self._update_summary_sync, session_id, summary, up_to_msg_id)

    def _update_session_preferences_sync(
        self, session_id: str, preferences: dict[str, Any]
    ) -> bool:
        with self._connect() as conn:
            current = conn.execute(
                "SELECT preferences_json FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if current is None:
                return False
            merged = {
                **_json_loads(current["preferences_json"], {}),
                **(preferences or {}),
            }
            cur = conn.execute(
                """
                UPDATE sessions
                SET preferences_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (_json_dumps(merged), time.time(), session_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def update_session_preferences(
        self, session_id: str, preferences: dict[str, Any]
    ) -> bool:
        return await self._run(self._update_session_preferences_sync, session_id, preferences)

    async def get_session_with_messages(self, session_id: str) -> dict[str, Any] | None:
        session = await self.get_session(session_id)
        if session is None:
            return None
        session["messages"] = await self.get_messages(session_id)
        session["active_turns"] = await self.list_active_turns(session_id)
        return session

    # ── Notebook entries ──────────────────────────────────────────────

    def _upsert_notebook_entries_sync(self, session_id: str, items: list[dict[str, Any]]) -> int:
        if not items:
            return 0
        now = time.time()
        with self._connect() as conn:
            if (
                conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
                is None
            ):
                raise ValueError(f"Session not found: {session_id}")
            upserted = 0
            for item in items:
                question = (item.get("question") or "").strip()
                question_id = (item.get("question_id") or "").strip()
                if not question or not question_id:
                    continue
                turn_id = (item.get("turn_id") or "").strip()
                # ``user_answer_images`` is an optional list of records
                # ``[{id, url, filename, mime_type}, …]``. We serialise it
                # here so callers that only know about text don't need to
                # know JSON. ``None`` keeps the existing column value on
                # UPDATE (avoid clobbering stored images on a partial
                # upsert that only changes ``is_correct``).
                images_value = item.get("user_answer_images")
                images_json = _json_dumps(images_value) if isinstance(images_value, list) else None
                if images_json is None:
                    conn.execute(
                        """
                        INSERT INTO notebook_entries (
                            session_id, turn_id, question_id, question, question_type,
                            options_json, correct_answer, explanation, difficulty,
                            user_answer, user_answer_images_json, is_correct,
                            bookmarked, followup_session_id, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, 0, '', ?, ?)
                        ON CONFLICT(session_id, turn_id, question_id) DO UPDATE SET
                            user_answer = excluded.user_answer,
                            is_correct = excluded.is_correct,
                            updated_at = excluded.updated_at
                        """,
                        (
                            session_id,
                            turn_id,
                            question_id,
                            question,
                            item.get("question_type") or "",
                            _json_dumps(item.get("options") or {}),
                            item.get("correct_answer") or "",
                            item.get("explanation") or "",
                            item.get("difficulty") or "",
                            item.get("user_answer") or "",
                            1 if item.get("is_correct") else 0,
                            now,
                            now,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO notebook_entries (
                            session_id, turn_id, question_id, question, question_type,
                            options_json, correct_answer, explanation, difficulty,
                            user_answer, user_answer_images_json, is_correct,
                            bookmarked, followup_session_id, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?, ?)
                        ON CONFLICT(session_id, turn_id, question_id) DO UPDATE SET
                            user_answer = excluded.user_answer,
                            user_answer_images_json = excluded.user_answer_images_json,
                            is_correct = excluded.is_correct,
                            updated_at = excluded.updated_at
                        """,
                        (
                            session_id,
                            turn_id,
                            question_id,
                            question,
                            item.get("question_type") or "",
                            _json_dumps(item.get("options") or {}),
                            item.get("correct_answer") or "",
                            item.get("explanation") or "",
                            item.get("difficulty") or "",
                            item.get("user_answer") or "",
                            images_json,
                            1 if item.get("is_correct") else 0,
                            now,
                            now,
                        ),
                    )
                upserted += 1
            conn.commit()
        return upserted

    async def upsert_notebook_entries(self, session_id: str, items: list[dict[str, Any]]) -> int:
        return await self._run(self._upsert_notebook_entries_sync, session_id, items)

    @staticmethod
    def _serialize_notebook_entry(row: sqlite3.Row) -> dict[str, Any]:
        keys = set(row.keys())
        images: list[dict[str, Any]] = []
        if "user_answer_images_json" in keys:
            raw_images = _json_loads(row["user_answer_images_json"], [])
            if isinstance(raw_images, list):
                images = [r for r in raw_images if isinstance(r, dict)]
        return {
            "id": int(row["id"]),
            "session_id": row["session_id"],
            "session_title": row["session_title"] or "" if "session_title" in keys else "",
            "turn_id": (row["turn_id"] or "") if "turn_id" in keys else "",
            "question_id": row["question_id"] or "",
            "question": row["question"],
            "question_type": row["question_type"] or "",
            "options": _json_loads(row["options_json"], {}),
            "correct_answer": row["correct_answer"] or "",
            "explanation": row["explanation"] or "",
            "difficulty": row["difficulty"] or "",
            "user_answer": row["user_answer"] or "",
            "user_answer_images": images,
            "is_correct": bool(row["is_correct"]),
            "bookmarked": bool(row["bookmarked"]),
            "followup_session_id": row["followup_session_id"] or "",
            "ai_judgment": (row["ai_judgment"] or "") if "ai_judgment" in keys else "",
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    def _list_notebook_entries_sync(
        self,
        category_id: int | None,
        bookmarked: bool | None,
        is_correct: bool | None,
        limit: int,
        offset: int,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        base = """
            SELECT
                n.id, n.session_id, COALESCE(s.title, '') AS session_title,
                n.turn_id, n.question_id, n.question, n.question_type, n.options_json,
                n.correct_answer, n.explanation, n.difficulty,
                n.user_answer, n.user_answer_images_json, n.is_correct, n.bookmarked,
                n.followup_session_id, n.ai_judgment, n.created_at, n.updated_at
            FROM notebook_entries n
            LEFT JOIN sessions s ON s.id = n.session_id
        """
        count_base = "SELECT COUNT(*) AS cnt FROM notebook_entries n"
        conditions: list[str] = []
        params: list[Any] = []
        if category_id is not None:
            join = " INNER JOIN notebook_entry_categories ec ON ec.entry_id = n.id"
            base += join
            count_base += join
            conditions.append("ec.category_id = ?")
            params.append(category_id)
        if bookmarked is not None:
            conditions.append("n.bookmarked = ?")
            params.append(1 if bookmarked else 0)
        if is_correct is not None:
            conditions.append("n.is_correct = ?")
            params.append(1 if is_correct else 0)
        if session_id is not None:
            conditions.append("n.session_id = ?")
            params.append(session_id)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        with self._connect() as conn:
            total_row = conn.execute(count_base + where, tuple(params)).fetchone()
            total = int(total_row["cnt"]) if total_row else 0
            rows = conn.execute(
                base + where + " ORDER BY n.created_at DESC LIMIT ? OFFSET ?",
                tuple(params) + (limit, offset),
            ).fetchall()
        items = [self._serialize_notebook_entry(r) for r in rows]
        return {"items": items, "total": total}

    async def list_notebook_entries(
        self,
        category_id: int | None = None,
        bookmarked: bool | None = None,
        is_correct: bool | None = None,
        limit: int = 50,
        offset: int = 0,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._run(
            self._list_notebook_entries_sync,
            category_id,
            bookmarked,
            is_correct,
            limit,
            offset,
            session_id,
        )

    def _get_notebook_entry_sync(self, entry_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    n.*, COALESCE(s.title, '') AS session_title
                FROM notebook_entries n
                LEFT JOIN sessions s ON s.id = n.session_id
                WHERE n.id = ?
                """,
                (entry_id,),
            ).fetchone()
            if row is None:
                return None
            entry = self._serialize_notebook_entry(row)
            cats = conn.execute(
                """
                SELECT c.id, c.name
                FROM notebook_categories c
                INNER JOIN notebook_entry_categories ec ON ec.category_id = c.id
                WHERE ec.entry_id = ?
                ORDER BY c.name
                """,
                (entry_id,),
            ).fetchall()
            entry["categories"] = [{"id": c["id"], "name": c["name"]} for c in cats]
        return entry

    async def get_notebook_entry(self, entry_id: int) -> dict[str, Any] | None:
        return await self._run(self._get_notebook_entry_sync, entry_id)

    def _find_notebook_entry_sync(
        self,
        session_id: str,
        question_id: str,
        turn_id: str | None = None,
    ) -> dict[str, Any] | None:
        # A missing turn_id only ever matches the legacy namespace (rows
        # persisted before turn scoping, migrated with turn_id=''). It must
        # never fall back to other turns' rows: positional question ids
        # (``q_1``..``q_N``) repeat across quizzes in one session, so a
        # cross-turn match would leak a previous quiz's answers into a new
        # quiz (issues #487 / #677).
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT n.*, COALESCE(s.title, '') AS session_title
                FROM notebook_entries n
                LEFT JOIN sessions s ON s.id = n.session_id
                WHERE n.session_id = ?
                  AND n.turn_id = ?
                  AND n.question_id = ?
                """,
                (session_id, turn_id if turn_id is not None else "", question_id),
            ).fetchone()
        if row is None:
            return None
        return self._serialize_notebook_entry(row)

    async def find_notebook_entry(
        self,
        session_id: str,
        question_id: str,
        turn_id: str | None = None,
    ) -> dict[str, Any] | None:
        return await self._run(self._find_notebook_entry_sync, session_id, question_id, turn_id)

    def _update_notebook_entry_sync(self, entry_id: int, updates: dict[str, Any]) -> bool:
        allowed = {
            "bookmarked",
            "followup_session_id",
            "user_answer",
            "is_correct",
            "ai_judgment",
        }
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return False
        fields["updated_at"] = time.time()
        if "bookmarked" in fields:
            fields["bookmarked"] = 1 if fields["bookmarked"] else 0
        if "is_correct" in fields:
            fields["is_correct"] = 1 if fields["is_correct"] else 0
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [entry_id]
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE notebook_entries SET {set_clause} WHERE id = ?",  # nosec B608
                tuple(values),
            )
            conn.commit()
        return cur.rowcount > 0

    async def update_notebook_entry(self, entry_id: int, updates: dict[str, Any]) -> bool:
        return await self._run(self._update_notebook_entry_sync, entry_id, updates)

    def _delete_notebook_entry_sync(self, entry_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM notebook_entries WHERE id = ?", (entry_id,))
            conn.commit()
        return cur.rowcount > 0

    async def delete_notebook_entry(self, entry_id: int) -> bool:
        return await self._run(self._delete_notebook_entry_sync, entry_id)

    # ── Notebook categories ────────────────────────────────────────

    def _create_category_sync(self, name: str) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO notebook_categories (name, created_at) VALUES (?, ?)",
                (name.strip(), now),
            )
            conn.commit()
        return {"id": int(cur.lastrowid), "name": name.strip(), "created_at": now}

    async def create_category(self, name: str) -> dict[str, Any]:
        return await self._run(self._create_category_sync, name)

    def _list_categories_sync(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.name, c.created_at,
                       COUNT(ec.entry_id) AS entry_count
                FROM notebook_categories c
                LEFT JOIN notebook_entry_categories ec ON ec.category_id = c.id
                GROUP BY c.id
                ORDER BY c.name
                """,
            ).fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "created_at": float(r["created_at"]),
                "entry_count": int(r["entry_count"]),
            }
            for r in rows
        ]

    async def list_categories(self) -> list[dict[str, Any]]:
        return await self._run(self._list_categories_sync)

    def _rename_category_sync(self, category_id: int, name: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE notebook_categories SET name = ? WHERE id = ?",
                (name.strip(), category_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def rename_category(self, category_id: int, name: str) -> bool:
        return await self._run(self._rename_category_sync, category_id, name)

    def _delete_category_sync(self, category_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM notebook_categories WHERE id = ?", (category_id,))
            conn.commit()
        return cur.rowcount > 0

    async def delete_category(self, category_id: int) -> bool:
        return await self._run(self._delete_category_sync, category_id)

    def _add_entry_to_category_sync(self, entry_id: int, category_id: int) -> bool:
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO notebook_entry_categories (entry_id, category_id) VALUES (?, ?)",
                    (entry_id, category_id),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return False
        return True

    async def add_entry_to_category(self, entry_id: int, category_id: int) -> bool:
        return await self._run(self._add_entry_to_category_sync, entry_id, category_id)

    def _remove_entry_from_category_sync(self, entry_id: int, category_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM notebook_entry_categories WHERE entry_id = ? AND category_id = ?",
                (entry_id, category_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def remove_entry_from_category(self, entry_id: int, category_id: int) -> bool:
        return await self._run(self._remove_entry_from_category_sync, entry_id, category_id)

    def _get_entry_categories_sync(self, entry_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.name FROM notebook_categories c
                INNER JOIN notebook_entry_categories ec ON ec.category_id = c.id
                WHERE ec.entry_id = ?
                ORDER BY c.name
                """,
                (entry_id,),
            ).fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]

    async def get_entry_categories(self, entry_id: int) -> list[dict[str, Any]]:
        return await self._run(self._get_entry_categories_sync, entry_id)

    # ── Users ─────────────────────────────────────────────────────────

    def _create_user_sync(
        self,
        username: str,
        password_hash: str,
        role: str,
        display_name: str,
        avatar_url: str = "",
        user_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        uid = user_id or f"user_{int(now * 1000)}_{uuid.uuid4().hex[:8]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (id, username, password_hash, role, display_name, avatar_url, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (uid, username, password_hash, role, display_name, avatar_url or "", now, now),
            )
            conn.commit()
        return {
            "id": uid,
            "username": username,
            "role": role,
            "display_name": display_name,
            "avatar_url": avatar_url or "",
            "created_at": now,
            "updated_at": now,
        }

    async def create_user(
        self,
        username: str,
        password_hash: str,
        role: str,
        display_name: str,
        avatar_url: str = "",
        user_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._run(
            self._create_user_sync, username, password_hash, role, display_name, avatar_url, user_id
        )

    def _get_user_sync(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        return dict(row)

    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        return await self._run(self._get_user_sync, user_id)

    def _get_user_by_username_sync(self, username: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            return None
        return dict(row)

    async def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        return await self._run(self._get_user_by_username_sync, username)

    def _list_users_sync(self, role: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if role:
                rows = conn.execute(
                    "SELECT * FROM users WHERE role = ? ORDER BY created_at ASC", (role,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM users ORDER BY created_at ASC").fetchall()
        return [dict(r) for r in rows]

    async def list_users(self, role: str | None = None) -> list[dict[str, Any]]:
        return await self._run(self._list_users_sync, role)

    def _update_user_sync(self, user_id: str, updates: dict[str, Any]) -> bool:
        allowed = {"password_hash", "role", "display_name", "avatar_url"}
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return False
        fields["updated_at"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [user_id]
        with self._connect() as conn:
            cur = conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", tuple(values))
            conn.commit()
        return cur.rowcount > 0

    async def update_user(self, user_id: str, updates: dict[str, Any]) -> bool:
        return await self._run(self._update_user_sync, user_id, updates)

    def _delete_user_sync(self, user_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
        return cur.rowcount > 0

    async def delete_user(self, user_id: str) -> bool:
        return await self._run(self._delete_user_sync, user_id)

    # ── Students ──────────────────────────────────────────────────────

    def _create_student_sync(
        self,
        user_id: str,
        grade_level: str = "",
        school: str = "",
        learning_style: str = "visual",
        target_daily_minutes: int = 60,
        student_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        sid = student_id or f"student_{int(now * 1000)}_{uuid.uuid4().hex[:8]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO students (
                    id, user_id, grade_level, school, learning_style,
                    target_daily_minutes, streak_count, total_xp, face_embedding_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, '', ?, ?)
                """,
                (sid, user_id, grade_level, school, learning_style, target_daily_minutes, now, now),
            )
            conn.commit()
        return {
            "id": sid,
            "user_id": user_id,
            "grade_level": grade_level,
            "school": school,
            "learning_style": learning_style,
            "target_daily_minutes": target_daily_minutes,
            "streak_count": 0,
            "total_xp": 0,
            "face_embedding": None,
            "created_at": now,
            "updated_at": now,
        }

    async def create_student(
        self,
        user_id: str,
        grade_level: str = "",
        school: str = "",
        learning_style: str = "visual",
        target_daily_minutes: int = 60,
        student_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._run(
            self._create_student_sync,
            user_id,
            grade_level,
            school,
            learning_style,
            target_daily_minutes,
            student_id,
        )

    def _get_student_sync(self, student_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if row is None:
            return None
        res = dict(row)
        res["face_embedding"] = _json_loads(res.pop("face_embedding_json", ""), None)
        return res

    async def get_student(self, student_id: str) -> dict[str, Any] | None:
        return await self._run(self._get_student_sync, student_id)

    def _get_student_by_user_id_sync(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM students WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        res = dict(row)
        res["face_embedding"] = _json_loads(res.pop("face_embedding_json", ""), None)
        return res

    async def get_student_by_user_id(self, user_id: str) -> dict[str, Any] | None:
        return await self._run(self._get_student_by_user_id_sync, user_id)

    def _update_student_sync(self, student_id: str, updates: dict[str, Any]) -> bool:
        allowed = {
            "grade_level",
            "school",
            "learning_style",
            "target_daily_minutes",
            "streak_count",
            "total_xp",
        }
        fields = {k: v for k, v in updates.items() if k in allowed}
        if "face_embedding" in updates:
            emb = updates["face_embedding"]
            fields["face_embedding_json"] = _json_dumps(emb) if emb is not None else ""
        if not fields:
            return False
        fields["updated_at"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [student_id]
        with self._connect() as conn:
            cur = conn.execute(f"UPDATE students SET {set_clause} WHERE id = ?", tuple(values))
            conn.commit()
        return cur.rowcount > 0

    async def update_student(self, student_id: str, updates: dict[str, Any]) -> bool:
        return await self._run(self._update_student_sync, student_id, updates)

    def _update_student_xp_sync(self, student_id: str, xp_delta: int) -> int:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "UPDATE students SET total_xp = MAX(0, total_xp + ?), updated_at = ? WHERE id = ?",
                (int(xp_delta), now, student_id),
            )
            row = conn.execute(
                "SELECT total_xp FROM students WHERE id = ?", (student_id,)
            ).fetchone()
            conn.commit()
        return int(row["total_xp"]) if row else 0

    async def update_student_xp(self, student_id: str, xp_delta: int) -> int:
        return await self._run(self._update_student_xp_sync, student_id, xp_delta)

    def _update_student_streak_sync(self, student_id: str, streak_count: int) -> bool:
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE students SET streak_count = ?, updated_at = ? WHERE id = ?",
                (max(0, int(streak_count)), now, student_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def update_student_streak(self, student_id: str, streak_count: int) -> bool:
        return await self._run(self._update_student_streak_sync, student_id, streak_count)

    def _set_student_face_embedding_sync(
        self, student_id: str, embedding: list[float] | None
    ) -> bool:
        now = time.time()
        emb_json = _json_dumps(embedding) if embedding is not None else ""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE students SET face_embedding_json = ?, updated_at = ? WHERE id = ?",
                (emb_json, now, student_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def set_student_face_embedding(
        self, student_id: str, embedding: list[float] | None
    ) -> bool:
        return await self._run(self._set_student_face_embedding_sync, student_id, embedding)

    # ── Parents ───────────────────────────────────────────────────────

    def _create_parent_sync(
        self,
        user_id: str,
        email: str = "",
        phone_number: str = "",
        notification_preferences: dict[str, Any] | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        pid = parent_id or f"parent_{int(now * 1000)}_{uuid.uuid4().hex[:8]}"
        prefs = notification_preferences or {
            "email": False,
            "warnings": True,
            "daily_summary": True,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO parents (
                    id, user_id, email, phone_number, notification_preferences_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (pid, user_id, email, phone_number, _json_dumps(prefs), now, now),
            )
            conn.commit()
        return {
            "id": pid,
            "user_id": user_id,
            "email": email,
            "phone_number": phone_number,
            "notification_preferences": prefs,
            "created_at": now,
            "updated_at": now,
        }

    async def create_parent(
        self,
        user_id: str,
        email: str = "",
        phone_number: str = "",
        notification_preferences: dict[str, Any] | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._run(
            self._create_parent_sync,
            user_id,
            email,
            phone_number,
            notification_preferences,
            parent_id,
        )

    def _get_parent_sync(self, parent_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM parents WHERE id = ?", (parent_id,)).fetchone()
        if row is None:
            return None
        res = dict(row)
        res["notification_preferences"] = _json_loads(
            res.pop("notification_preferences_json", ""), {}
        )
        return res

    async def get_parent(self, parent_id: str) -> dict[str, Any] | None:
        return await self._run(self._get_parent_sync, parent_id)

    def _get_parent_by_user_id_sync(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM parents WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        res = dict(row)
        res["notification_preferences"] = _json_loads(
            res.pop("notification_preferences_json", ""), {}
        )
        return res

    async def get_parent_by_user_id(self, user_id: str) -> dict[str, Any] | None:
        return await self._run(self._get_parent_by_user_id_sync, user_id)

    # ── Parent-Student Pairing Links ──────────────────────────────────

    def _create_pairing_code_sync(self, student_id: str, expires_in_seconds: int = 600) -> str:
        now = time.time()
        import random
        import string

        code_suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        code = f"GURU-{code_suffix}"
        expires_at = now + expires_in_seconds
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO settings (key, value_json, category, updated_at)
                VALUES (?, ?, 'pairing', ?)
                """,
                (
                    f"pairing_code:{code}",
                    _json_dumps({"student_id": student_id, "code": code, "expires_at": expires_at}),
                    now,
                ),
            )
            conn.commit()
        return code

    async def create_pairing_code(self, student_id: str, expires_in_seconds: int = 600) -> str:
        return await self._run(self._create_pairing_code_sync, student_id, expires_in_seconds)

    def _verify_pairing_code_sync(
        self, parent_id: str, code: str, permissions: dict[str, Any] | None = None
    ) -> bool:
        now = time.time()
        code_key = f"pairing_code:{code.strip()}"
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM settings WHERE key = ?", (code_key,)
            ).fetchone()
            if not row:
                return False
            data = _json_loads(row["value_json"], {})
            if not data or float(data.get("expires_at", 0)) < now:
                conn.execute("DELETE FROM settings WHERE key = ?", (code_key,))
                conn.commit()
                return False
            student_id = data.get("student_id")
            if not student_id:
                return False
            link_id = f"link_{int(now * 1000)}_{uuid.uuid4().hex[:8]}"
            perms = permissions or {
                "can_view_live": True,
                "can_view_reports": True,
                "can_manage_goals": True,
            }
            conn.execute(
                """
                INSERT INTO parent_student_links (
                    id, parent_id, student_id, pairing_code, pairing_code_expires_at,
                    status, permissions_json, paired_at, created_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
                ON CONFLICT(parent_id, student_id) DO UPDATE SET
                    status = 'active',
                    pairing_code = excluded.pairing_code,
                    permissions_json = excluded.permissions_json,
                    paired_at = excluded.paired_at
                """,
                (
                    link_id,
                    parent_id,
                    student_id,
                    code,
                    data["expires_at"],
                    _json_dumps(perms),
                    now,
                    now,
                ),
            )
            conn.execute("DELETE FROM settings WHERE key = ?", (code_key,))
            conn.commit()
        return True

    async def verify_pairing_code(
        self, parent_id: str, code: str, permissions: dict[str, Any] | None = None
    ) -> bool:
        return await self._run(self._verify_pairing_code_sync, parent_id, code, permissions)

    def _get_linked_students_sync(self, parent_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT l.*, s.user_id, s.grade_level, s.school, s.streak_count, s.total_xp,
                       u.display_name, u.username, u.avatar_url
                FROM parent_student_links l
                INNER JOIN students s ON s.id = l.student_id
                INNER JOIN users u ON u.id = s.user_id
                WHERE l.parent_id = ? AND l.status = 'active'
                ORDER BY l.paired_at DESC
                """,
                (parent_id,),
            ).fetchall()
        results = []
        for r in rows:
            item = dict(r)
            item["permissions"] = _json_loads(item.pop("permissions_json", ""), {})
            results.append(item)
        return results

    async def get_linked_students(self, parent_id: str) -> list[dict[str, Any]]:
        return await self._run(self._get_linked_students_sync, parent_id)

    def _get_linked_parents_sync(self, student_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT l.*, p.user_id, p.email, p.phone_number,
                       u.display_name, u.username, u.avatar_url
                FROM parent_student_links l
                INNER JOIN parents p ON p.id = l.parent_id
                INNER JOIN users u ON u.id = p.user_id
                WHERE l.student_id = ? AND l.status = 'active'
                ORDER BY l.paired_at DESC
                """,
                (student_id,),
            ).fetchall()
        results = []
        for r in rows:
            item = dict(r)
            item["permissions"] = _json_loads(item.pop("permissions_json", ""), {})
            results.append(item)
        return results

    async def get_linked_parents(self, student_id: str) -> list[dict[str, Any]]:
        return await self._run(self._get_linked_parents_sync, student_id)

    def _revoke_parent_student_link_sync(self, parent_id: str, student_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE parent_student_links SET status = 'revoked' WHERE parent_id = ? AND student_id = ?",
                (parent_id, student_id),
            )
            conn.commit()
        return cur.rowcount > 0

    async def revoke_parent_student_link(self, parent_id: str, student_id: str) -> bool:
        return await self._run(self._revoke_parent_student_link_sync, parent_id, student_id)

    # ── Study Sessions ────────────────────────────────────────────────

    def _create_study_session_sync(
        self,
        student_id: str,
        title: str = "Study Session",
        subject: str = "General",
        target_duration_seconds: int = 1800,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        sid = session_id or f"studysess_{int(now * 1000)}_{uuid.uuid4().hex[:8]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO study_sessions (
                    id, student_id, title, subject, target_duration_seconds,
                    actual_duration_seconds, start_time, end_time, status,
                    focus_score, engagement_score, distraction_count, warning_count,
                    ai_summary, created_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?, NULL, 'in_progress', 100.0, 100.0, 0, 0, '', ?)
                """,
                (
                    sid,
                    student_id,
                    title or "Study Session",
                    subject or "General",
                    target_duration_seconds,
                    now,
                    now,
                ),
            )
            conn.commit()
        return {
            "id": sid,
            "session_id": sid,
            "student_id": student_id,
            "title": title or "Study Session",
            "subject": subject or "General",
            "target_duration_seconds": target_duration_seconds,
            "actual_duration_seconds": 0,
            "start_time": now,
            "end_time": None,
            "status": "in_progress",
            "focus_score": 100.0,
            "engagement_score": 100.0,
            "distraction_count": 0,
            "warning_count": 0,
            "ai_summary": "",
            "created_at": now,
        }

    async def create_study_session(
        self,
        student_id: str,
        title: str = "Study Session",
        subject: str = "General",
        target_duration_seconds: int = 1800,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._run(
            self._create_study_session_sync,
            student_id,
            title,
            subject,
            target_duration_seconds,
            session_id,
        )

    def _get_study_session_sync(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM study_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        res = dict(row)
        res["session_id"] = res["id"]
        return res

    async def get_study_session(self, session_id: str) -> dict[str, Any] | None:
        return await self._run(self._get_study_session_sync, session_id)

    def _list_study_sessions_sync(
        self,
        student_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conditions = []
        params = []
        if student_id:
            conditions.append("student_id = ?")
            params.append(student_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM study_sessions{where} ORDER BY start_time DESC LIMIT ? OFFSET ?",
                tuple(params) + (limit, offset),
            ).fetchall()
        results = []
        for r in rows:
            item = dict(r)
            item["session_id"] = item["id"]
            results.append(item)
        return results

    async def list_study_sessions(
        self,
        student_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self._run(self._list_study_sessions_sync, student_id, status, limit, offset)

    def _update_study_session_sync(self, session_id: str, **kwargs: Any) -> bool:
        allowed = {
            "title",
            "subject",
            "actual_duration_seconds",
            "end_time",
            "status",
            "focus_score",
            "engagement_score",
            "distraction_count",
            "warning_count",
            "ai_summary",
        }
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [session_id]
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE study_sessions SET {set_clause} WHERE id = ?", tuple(values)
            )
            conn.commit()
        return cur.rowcount > 0

    async def update_study_session(self, session_id: str, **kwargs: Any) -> bool:
        return await self._run(self._update_study_session_sync, session_id, **kwargs)

    def _finish_study_session_sync(
        self, session_id: str, stats: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM study_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            current = dict(row)
            start_time = float(current["start_time"])
            actual_duration = int(now - start_time)
            stats = stats or {}
            focus_score = float(stats.get("focus_score", current["focus_score"]))
            engagement_score = float(stats.get("engagement_score", current["engagement_score"]))
            distraction_count = int(stats.get("distraction_count", current["distraction_count"]))
            warning_count = int(stats.get("warning_count", current["warning_count"]))
            ai_summary = str(stats.get("ai_summary", current["ai_summary"]))
            duration = int(stats.get("actual_duration_seconds", actual_duration))

            conn.execute(
                """
                UPDATE study_sessions SET
                    status = 'completed',
                    end_time = ?,
                    actual_duration_seconds = ?,
                    focus_score = ?,
                    engagement_score = ?,
                    distraction_count = ?,
                    warning_count = ?,
                    ai_summary = ?
                WHERE id = ?
                """,
                (
                    now,
                    duration,
                    focus_score,
                    engagement_score,
                    distraction_count,
                    warning_count,
                    ai_summary,
                    session_id,
                ),
            )
            conn.commit()
            updated = conn.execute(
                "SELECT * FROM study_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if updated is None:
                return None
            res = dict(updated)
            res["session_id"] = res["id"]
            return res

    async def finish_study_session(
        self, session_id: str, stats: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        return await self._run(self._finish_study_session_sync, session_id, stats)

    # ── Monitoring Events ─────────────────────────────────────────────

    def _record_monitoring_event_sync(
        self,
        session_id: str,
        event_type: str,
        severity: str = "info",
        confidence: float = 1.0,
        duration_seconds: float = 0.0,
        metadata: dict[str, Any] | None = None,
        timestamp: float | None = None,
    ) -> int:
        now = time.time()
        ts = float(timestamp if timestamp is not None else now)
        meta_json = _json_dumps(metadata or {})
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO monitoring_events (
                    session_id, timestamp, event_type, severity, confidence, duration_seconds, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    ts,
                    event_type,
                    severity,
                    float(confidence),
                    float(duration_seconds),
                    meta_json,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    async def record_monitoring_event(
        self,
        session_id: str,
        event_type: str,
        severity: str = "info",
        confidence: float = 1.0,
        duration_seconds: float = 0.0,
        metadata: dict[str, Any] | None = None,
        timestamp: float | None = None,
    ) -> int:
        return await self._run(
            self._record_monitoring_event_sync,
            session_id,
            event_type,
            severity,
            confidence,
            duration_seconds,
            metadata,
            timestamp,
        )

    def _get_monitoring_events_sync(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions = ["session_id = ?"]
        params: list[Any] = [session_id]
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        where = " WHERE " + " AND ".join(conditions)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM monitoring_events{where} ORDER BY timestamp ASC LIMIT ? OFFSET ?",
                tuple(params) + (limit, offset),
            ).fetchall()
        results = []
        for r in rows:
            item = dict(r)
            item["metadata"] = _json_loads(item.pop("metadata_json", ""), {})
            results.append(item)
        return results

    async def get_monitoring_events(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self._run(
            self._get_monitoring_events_sync, session_id, limit, offset, event_type
        )

    # ── Session Reports ───────────────────────────────────────────────

    def _create_session_report_sync(
        self,
        session_id: str,
        student_id: str,
        focus_score: float,
        engagement_score: float,
        total_study_seconds: int,
        productive_seconds: int,
        distracted_seconds: int,
        topics_covered: list[str] | None = None,
        key_strengths: str = "",
        areas_for_improvement: str = "",
        ai_tutor_feedback: str = "",
        parent_notes: str = "",
        report_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        rid = report_id or f"report_{int(now * 1000)}_{uuid.uuid4().hex[:8]}"
        topics_json = _json_dumps(topics_covered or [])
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO session_reports (
                    id, session_id, student_id, focus_score, engagement_score,
                    total_study_seconds, productive_seconds, distracted_seconds,
                    topics_covered_json, key_strengths, areas_for_improvement,
                    ai_tutor_feedback, parent_notes, generated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    focus_score = excluded.focus_score,
                    engagement_score = excluded.engagement_score,
                    total_study_seconds = excluded.total_study_seconds,
                    productive_seconds = excluded.productive_seconds,
                    distracted_seconds = excluded.distracted_seconds,
                    topics_covered_json = excluded.topics_covered_json,
                    key_strengths = excluded.key_strengths,
                    areas_for_improvement = excluded.areas_for_improvement,
                    ai_tutor_feedback = excluded.ai_tutor_feedback,
                    parent_notes = excluded.parent_notes,
                    generated_at = excluded.generated_at
                """,
                (
                    rid,
                    session_id,
                    student_id,
                    float(focus_score),
                    float(engagement_score),
                    int(total_study_seconds),
                    int(productive_seconds),
                    int(distracted_seconds),
                    topics_json,
                    key_strengths,
                    areas_for_improvement,
                    ai_tutor_feedback,
                    parent_notes,
                    now,
                ),
            )
            conn.commit()
        return {
            "id": rid,
            "session_id": session_id,
            "student_id": student_id,
            "focus_score": float(focus_score),
            "engagement_score": float(engagement_score),
            "total_study_seconds": int(total_study_seconds),
            "productive_seconds": int(productive_seconds),
            "distracted_seconds": int(distracted_seconds),
            "topics_covered": topics_covered or [],
            "key_strengths": key_strengths,
            "areas_for_improvement": areas_for_improvement,
            "ai_tutor_feedback": ai_tutor_feedback,
            "parent_notes": parent_notes,
            "generated_at": now,
        }

    async def create_session_report(
        self,
        session_id: str,
        student_id: str,
        focus_score: float,
        engagement_score: float,
        total_study_seconds: int,
        productive_seconds: int,
        distracted_seconds: int,
        topics_covered: list[str] | None = None,
        key_strengths: str = "",
        areas_for_improvement: str = "",
        ai_tutor_feedback: str = "",
        parent_notes: str = "",
        report_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._run(
            self._create_session_report_sync,
            session_id,
            student_id,
            focus_score,
            engagement_score,
            total_study_seconds,
            productive_seconds,
            distracted_seconds,
            topics_covered,
            key_strengths,
            areas_for_improvement,
            ai_tutor_feedback,
            parent_notes,
            report_id,
        )

    def _get_session_report_sync(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM session_reports WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        res = dict(row)
        res["topics_covered"] = _json_loads(res.pop("topics_covered_json", ""), [])
        return res

    async def get_session_report(self, session_id: str) -> dict[str, Any] | None:
        return await self._run(self._get_session_report_sync, session_id)

    def _list_session_reports_sync(
        self, student_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM session_reports WHERE student_id = ? ORDER BY generated_at DESC LIMIT ? OFFSET ?",
                (student_id, limit, offset),
            ).fetchall()
        results = []
        for r in rows:
            item = dict(r)
            item["topics_covered"] = _json_loads(item.pop("topics_covered_json", ""), [])
            results.append(item)
        return results

    async def list_session_reports(
        self, student_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        return await self._run(self._list_session_reports_sync, student_id, limit, offset)

    # ── Rewards & Gamification ────────────────────────────────────────

    def _award_reward_sync(
        self,
        student_id: str,
        reward_type: str,
        amount_xp: int = 0,
        badge_id: str = "",
        badge_name: str = "",
        badge_icon: str = "",
        reason: str = "",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        rid = f"reward_{int(now * 1000)}_{uuid.uuid4().hex[:8]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO rewards (
                    id, student_id, session_id, reward_type, amount_xp,
                    badge_id, badge_name, badge_icon, reason, unlocked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rid,
                    student_id,
                    session_id,
                    reward_type,
                    int(amount_xp),
                    badge_id,
                    badge_name,
                    badge_icon,
                    reason,
                    now,
                ),
            )
            if amount_xp > 0:
                conn.execute(
                    "UPDATE students SET total_xp = total_xp + ?, updated_at = ? WHERE id = ?",
                    (int(amount_xp), now, student_id),
                )
            conn.commit()
        return {
            "id": rid,
            "student_id": student_id,
            "session_id": session_id,
            "reward_type": reward_type,
            "amount_xp": int(amount_xp),
            "badge_id": badge_id,
            "badge_name": badge_name,
            "badge_icon": badge_icon,
            "reason": reason,
            "unlocked_at": now,
        }

    async def award_reward(
        self,
        student_id: str,
        reward_type: str,
        amount_xp: int = 0,
        badge_id: str = "",
        badge_name: str = "",
        badge_icon: str = "",
        reason: str = "",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._run(
            self._award_reward_sync,
            student_id,
            reward_type,
            amount_xp,
            badge_id,
            badge_name,
            badge_icon,
            reason,
            session_id,
        )

    async def award_xp(
        self,
        student_id: str,
        xp: int,
        reason: str = "",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.award_reward(
            student_id=student_id,
            reward_type="xp",
            amount_xp=xp,
            reason=reason,
            session_id=session_id,
        )

    def _get_rewards_sync(
        self,
        student_id: str,
        reward_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conditions = ["student_id = ?"]
        params: list[Any] = [student_id]
        if reward_type:
            conditions.append("reward_type = ?")
            params.append(reward_type)
        where = " WHERE " + " AND ".join(conditions)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM rewards{where} ORDER BY unlocked_at DESC LIMIT ? OFFSET ?",
                tuple(params) + (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    async def get_rewards(
        self,
        student_id: str,
        reward_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self._run(self._get_rewards_sync, student_id, reward_type, limit, offset)

    # ── Study Goals ───────────────────────────────────────────────────

    def _create_study_goal_sync(
        self,
        student_id: str,
        title: str,
        goal_type: str,
        target_value: float,
        start_date: float,
        end_date: float,
        reward_xp: int = 50,
        goal_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        gid = goal_id or f"goal_{int(now * 1000)}_{uuid.uuid4().hex[:8]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO study_goals (
                    id, student_id, title, goal_type, target_value, current_value,
                    start_date, end_date, is_completed, reward_xp, created_at
                ) VALUES (?, ?, ?, ?, ?, 0.0, ?, ?, 0, ?, ?)
                """,
                (
                    gid,
                    student_id,
                    title,
                    goal_type,
                    float(target_value),
                    float(start_date),
                    float(end_date),
                    int(reward_xp),
                    now,
                ),
            )
            conn.commit()
        return {
            "id": gid,
            "student_id": student_id,
            "title": title,
            "goal_type": goal_type,
            "target_value": float(target_value),
            "current_value": 0.0,
            "start_date": float(start_date),
            "end_date": float(end_date),
            "is_completed": False,
            "reward_xp": int(reward_xp),
            "created_at": now,
        }

    async def create_study_goal(
        self,
        student_id: str,
        title: str,
        goal_type: str,
        target_value: float,
        start_date: float,
        end_date: float,
        reward_xp: int = 50,
        goal_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._run(
            self._create_study_goal_sync,
            student_id,
            title,
            goal_type,
            target_value,
            start_date,
            end_date,
            reward_xp,
            goal_id,
        )

    def _get_study_goals_sync(
        self, student_id: str, active_only: bool = False
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if active_only:
                rows = conn.execute(
                    "SELECT * FROM study_goals WHERE student_id = ? AND is_completed = 0 ORDER BY created_at DESC",
                    (student_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM study_goals WHERE student_id = ? ORDER BY created_at DESC",
                    (student_id,),
                ).fetchall()
        results = []
        for r in rows:
            item = dict(r)
            item["is_completed"] = bool(item["is_completed"])
            results.append(item)
        return results

    async def get_study_goals(
        self, student_id: str, active_only: bool = False
    ) -> list[dict[str, Any]]:
        return await self._run(self._get_study_goals_sync, student_id, active_only)

    def _update_study_goal_sync(
        self,
        goal_id: str,
        current_value: float | None = None,
        is_completed: bool | None = None,
    ) -> bool:
        updates = {}
        if current_value is not None:
            updates["current_value"] = float(current_value)
        if is_completed is not None:
            updates["is_completed"] = 1 if is_completed else 0
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [goal_id]
        with self._connect() as conn:
            cur = conn.execute(f"UPDATE study_goals SET {set_clause} WHERE id = ?", tuple(values))
            conn.commit()
        return cur.rowcount > 0

    async def update_study_goal(
        self,
        goal_id: str,
        current_value: float | None = None,
        is_completed: bool | None = None,
    ) -> bool:
        return await self._run(self._update_study_goal_sync, goal_id, current_value, is_completed)

    # ── Settings ──────────────────────────────────────────────────────

    def _get_db_setting_sync(self, key: str, default: Any = None) -> Any:
        with self._connect() as conn:
            row = conn.execute("SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return _json_loads(row["value_json"], default)

    async def get_db_setting(self, key: str, default: Any = None) -> Any:
        return await self._run(self._get_db_setting_sync, key, default)

    def _set_db_setting_sync(self, key: str, value: Any, category: str = "general") -> bool:
        now = time.time()
        val_json = _json_dumps(value)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value_json, category, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    category = excluded.category,
                    updated_at = excluded.updated_at
                """,
                (key, val_json, category, now),
            )
            conn.commit()
        return True

    async def set_db_setting(self, key: str, value: Any, category: str = "general") -> bool:
        return await self._run(self._set_db_setting_sync, key, value, category)

    # ── Audit Logs ────────────────────────────────────────────────────

    def _record_audit_log_sync(
        self,
        action: str,
        actor_id: str = "",
        actor_role: str = "system",
        ip_address: str = "",
        resource_type: str = "",
        resource_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> int:
        now = time.time()
        details_json = _json_dumps(details or {})
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO audit_logs (
                    timestamp, actor_id, actor_role, ip_address, action,
                    resource_type, resource_id, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    actor_id,
                    actor_role,
                    ip_address,
                    action,
                    resource_type,
                    resource_id,
                    details_json,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    async def record_audit_log(
        self,
        action: str,
        actor_id: str = "",
        actor_role: str = "system",
        ip_address: str = "",
        resource_type: str = "",
        resource_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> int:
        return await self._run(
            self._record_audit_log_sync,
            action,
            actor_id,
            actor_role,
            ip_address,
            resource_type,
            resource_id,
            details,
        )

    def _list_audit_logs_sync(
        self,
        actor_id: str | None = None,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conditions = []
        params: list[Any] = []
        if actor_id:
            conditions.append("actor_id = ?")
            params.append(actor_id)
        if action:
            conditions.append("action = ?")
            params.append(action)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM audit_logs{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                tuple(params) + (limit, offset),
            ).fetchall()
        results = []
        for r in rows:
            item = dict(r)
            item["details"] = _json_loads(item.pop("details_json", ""), {})
            results.append(item)
        return results

    async def list_audit_logs(
        self,
        actor_id: str | None = None,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self._run(self._list_audit_logs_sync, actor_id, action, limit, offset)


_instances: dict[str, SQLiteSessionStore] = {}


def get_sqlite_session_store() -> SQLiteSessionStore:
    db_path = get_path_service().get_chat_history_db().resolve()
    key = str(db_path)
    if key not in _instances:
        _instances[key] = SQLiteSessionStore(db_path=db_path)
    return _instances[key]


__all__ = ["SQLiteSessionStore", "get_sqlite_session_store", "make_imported_session_id"]
