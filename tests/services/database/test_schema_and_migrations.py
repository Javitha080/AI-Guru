"""
Tests for AI Guru database schema and versioned migrations.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from deeptutor.services.database.migrations import (
    MIGRATIONS,
    apply_migrations,
    get_applied_migrations,
    get_db_version,
    verify_tables_exist,
)
from deeptutor.services.database.schema import CORE_TABLE_NAMES
from deeptutor.services.session.sqlite_store import SQLiteSessionStore

# Single source of truth: every migration registered in migrations.py must be
# applied on a fresh database (currently 001-007).
EXPECTED_VERSIONS = [version for version, _name, _migration in MIGRATIONS]


def test_migrations_create_all_core_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "test_mig.db"
    conn = sqlite3.connect(str(db_path))
    try:
        applied = apply_migrations(conn)
        assert applied == EXPECTED_VERSIONS
        assert get_db_version(conn) == EXPECTED_VERSIONS[-1]

        tables = verify_tables_exist(conn)
        for table_name in CORE_TABLE_NAMES:
            assert tables[table_name] is True, f"Table {table_name} was not created"
    finally:
        conn.close()


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test_idempotent.db"
    conn = sqlite3.connect(str(db_path))
    try:
        first_run = apply_migrations(conn)
        assert first_run == EXPECTED_VERSIONS

        # Second run should be a no-op
        second_run = apply_migrations(conn)
        assert len(second_run) == 0
        assert get_db_version(conn) == EXPECTED_VERSIONS[-1]

        applied_list = get_applied_migrations(conn)
        assert len(applied_list) == len(EXPECTED_VERSIONS)
        assert applied_list[0]["version"] == EXPECTED_VERSIONS[0]
        assert applied_list[0]["name"] == "001_core_relational_tables"
        assert applied_list[-1]["version"] == EXPECTED_VERSIONS[-1]
        assert applied_list[-1]["name"] == MIGRATIONS[-1][1]
    finally:
        conn.close()


def test_sqlite_store_initializes_all_tables_and_preserves_chat(tmp_path: Path) -> None:
    db_path = tmp_path / "test_store_init.db"
    store = SQLiteSessionStore(db_path=db_path)

    with store._connect() as conn:
        tables = verify_tables_exist(conn)
        for table_name in CORE_TABLE_NAMES:
            assert tables[table_name] is True, f"Table {table_name} missing from SQLiteSessionStore"

        # Check existing chat tables also exist
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        existing = {r["name"] for r in rows}
        assert "sessions" in existing
        assert "messages" in existing
        assert "turns" in existing
        assert "turn_events" in existing
        assert "notebook_entries" in existing
        assert "schema_migrations" in existing
