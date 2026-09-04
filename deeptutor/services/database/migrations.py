"""
Schema migration manager for AI Guru local SQLite database.

Enforces versioned, non-destructive schema migrations, preserving 100%
of existing chat history and table structures.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Callable

from deeptutor.services.database.schema import (
    CORE_TABLE_NAMES,
    V1_SCHEMA_DDL,
    V2_EXAM_SCHEMA_DDL,
    V4_PAPER_BANK_SCHEMA_DDL,
    v3_pause_aware_durations,
    v5_exam_sitting_columns,
    v6_paper_bank_grade11,
    v7_exams_review_status,
)

logger = logging.getLogger(__name__)


# List of migration definitions: (version, name, migration_func_or_sql)
MIGRATIONS: list[tuple[int, str, str | Callable[[sqlite3.Connection], None]]] = [
    (1, "001_core_relational_tables", V1_SCHEMA_DDL),
    (2, "002_exam_engine_tables", V2_EXAM_SCHEMA_DDL),
    # Callable: column-by-column idempotency — a DB that already carries
    # worked_seconds must not crash startup with "duplicate column name".
    (3, "003_pause_aware_durations", v3_pause_aware_durations),
    (4, "004_paper_bank_tables", V4_PAPER_BANK_SCHEMA_DDL),
    (5, "005_exam_sitting_columns", v5_exam_sitting_columns),
    (6, "006_paper_bank_grade11", v6_paper_bank_grade11),
    (7, "007_exams_review_status", v7_exams_review_status),
]


def enable_pragmas(conn: sqlite3.Connection) -> None:
    """Enable SQLite WAL mode, foreign keys, and busy timeout."""
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
    except sqlite3.OperationalError as e:
        logger.debug("Failed to set WAL mode (may be in-memory or read-only): %s", e)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA synchronous = NORMAL;")


def ensure_migrations_table(conn: sqlite3.Connection) -> None:
    """Ensure the schema_migrations table exists before running migrations."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at REAL NOT NULL
        );
        """
    )


def get_applied_migrations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return all applied migrations sorted by version."""
    ensure_migrations_table(conn)
    rows = conn.execute(
        "SELECT version, name, applied_at FROM schema_migrations ORDER BY version ASC"
    ).fetchall()
    return [
        {
            "version": int(row[0] if isinstance(row, (tuple, list)) else row["version"]),
            "name": str(row[1] if isinstance(row, (tuple, list)) else row["name"]),
            "applied_at": float(row[2] if isinstance(row, (tuple, list)) else row["applied_at"]),
        }
        for row in rows
    ]


def get_db_version(conn: sqlite3.Connection) -> int:
    """Return current highest migration version applied, or 0 if none."""
    ensure_migrations_table(conn)
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    if row and row[0] is not None:
        return int(row[0])
    return 0


def apply_migrations(conn: sqlite3.Connection) -> list[int]:
    """
    Run all pending migrations in order.
    Returns list of newly applied migration versions.
    """
    enable_pragmas(conn)
    ensure_migrations_table(conn)

    applied = {m["version"] for m in get_applied_migrations(conn)}
    newly_applied: list[int] = []

    for version, name, handler in MIGRATIONS:
        if version in applied:
            continue

        logger.info("Applying database migration %d (%s)...", version, name)
        now = time.time()
        try:
            if callable(handler):
                handler(conn)
            elif isinstance(handler, str):
                conn.executescript(handler)
            else:
                raise TypeError(f"Unknown migration handler type: {type(handler)}")

            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, now),
            )
            conn.commit()
            newly_applied.append(version)
            logger.info("Successfully applied migration %d (%s)", version, name)
        except Exception:
            logger.exception("Failed to apply migration %d (%s)", version, name)
            conn.rollback()
            raise

    return newly_applied


def verify_tables_exist(conn: sqlite3.Connection) -> dict[str, bool]:
    """Verify presence of all 11 core tables."""
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    existing_tables = {row[0] if isinstance(row, (tuple, list)) else row["name"] for row in rows}
    return {table: (table in existing_tables) for table in CORE_TABLE_NAMES}


__all__ = [
    "enable_pragmas",
    "ensure_migrations_table",
    "get_applied_migrations",
    "get_db_version",
    "apply_migrations",
    "verify_tables_exist",
]
