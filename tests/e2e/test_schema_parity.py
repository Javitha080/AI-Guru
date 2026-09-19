"""E2E mock-schema parity guard.

``tests/e2e/conftest.py::SCHEMA_SQL`` is a hand-rolled stand-in for the real
``deeptutor.services.database.migrations`` schema. When production migrations
gain tables/columns, this mock silently drifts and tier tests keep passing
against the wrong contract. This module fails loudly on that drift.
"""

from __future__ import annotations

import re
import sqlite3

from deeptutor.services.database.migrations import CORE_TABLE_NAMES
from tests.e2e.conftest import SCHEMA_SQL


def _mock_tables() -> set[str]:
    return set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SCHEMA_SQL))


def test_mock_schema_covers_all_core_tables():
    mock = _mock_tables()
    # schema_migrations is production bookkeeping; the mock intentionally omits it.
    expected = set(CORE_TABLE_NAMES) - {"schema_migrations"}
    missing = expected - mock
    assert not missing, f"E2E mock schema missing tables: {sorted(missing)}"


def test_mock_schema_enforces_hard_won_contracts():
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(SCHEMA_SQL)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

        # study_sessions: no 'created' status, start_time NOT NULL
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='study_sessions'"
        ).fetchone()[0]
        assert "'in_progress','completed','paused','abandoned'" in ddl.replace('"', "'").replace(" ", "")
        assert "start_time REAL NOT NULL" in ddl

        # monitoring_events: AUTOINCREMENT id, metadata_json column
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='monitoring_events'"
        ).fetchone()[0]
        assert "AUTOINCREMENT" in ddl
        assert "metadata_json" in ddl

        # session_reports: real metric columns, no report_data blob
        cols = [r[1] for r in conn.execute("PRAGMA table_info(session_reports)")]
        for col in (
            "focus_score",
            "engagement_score",
            "total_study_seconds",
            "productive_seconds",
            "distracted_seconds",
        ):
            assert col in cols, f"session_reports missing {col}"
        assert "report_data" not in cols

        # rewards: amount_xp column
        cols = [r[1] for r in conn.execute("PRAGMA table_info(rewards)")]
        assert "amount_xp" in cols
        assert tables >= {"users", "students", "settings", "audit_logs"}
    finally:
        conn.close()
