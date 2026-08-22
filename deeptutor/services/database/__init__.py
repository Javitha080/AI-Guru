"""
AI Guru Local Relational Database Module.

Provides schema definitions, versioned migrations, and connection helpers
for the local-first SQLite architecture.
"""

from __future__ import annotations

from deeptutor.services.database.migrations import (
    apply_migrations,
    enable_pragmas,
    get_applied_migrations,
    get_db_version,
    verify_tables_exist,
)
from deeptutor.services.database.schema import CORE_TABLE_NAMES, PRAGMAS, V1_SCHEMA_DDL

__all__ = [
    "CORE_TABLE_NAMES",
    "PRAGMAS",
    "V1_SCHEMA_DDL",
    "apply_migrations",
    "enable_pragmas",
    "get_applied_migrations",
    "get_db_version",
    "verify_tables_exist",
]
