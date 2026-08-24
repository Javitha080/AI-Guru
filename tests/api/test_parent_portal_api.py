"""API-level regression tests for the AI Guru parent portal router.

Focus: the "dead data" bugs — dashboard metrics must come from real
study_sessions rows (no hardcoded focus_score 0), weekly analytics must read
``actual_duration_seconds``, month counts use a real 30-day window, telegram
endpoints survive the legacy settings-table shape, and the tunnel defaults to
the FRONTEND port so {tunnel}/parent serves the portal UI remotely.

Isolation: every DB-backed collaborator is monkeypatched onto one temp SQLite
file; router handlers are invoked directly (no HTTP server needed).
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("aiosqlite")

from deeptutor.api.routers import parent as parent_router
from deeptutor.services.database.migrations import apply_migrations


@pytest.fixture()
def portal_env(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "chat_history.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        apply_migrations(conn)

    # Router + remote services → temp DB
    monkeypatch.setattr(parent_router, "_get_db_path", lambda: db_path)
    from deeptutor.services.remote import audit_logger as al
    from deeptutor.services.remote import auth_jwt as aj
    from deeptutor.services.remote import pairing as pr

    monkeypatch.setattr(aj.JWTAuthService, "_get_db_path", staticmethod(lambda: db_path))
    monkeypatch.setattr(pr.PairingService, "_get_db_path", staticmethod(lambda: db_path))
    monkeypatch.setattr(al.AuditLogger, "_get_db_path", staticmethod(lambda: db_path))

    # StudySessionManager resolves its DB via get_path_service at __init__.
    import deeptutor.services.study.session_manager as sm_mod

    monkeypatch.setattr(sm_mod, "get_path_service", lambda: SimpleNamespace(user_dir=tmp_path))

    # Fresh brute-force tracker per test.
    from deeptutor.services.remote import auth_jwt as aj2

    monkeypatch.setattr(aj2, "_PIN_ATTEMPT_TRACKER", {})

    return db_path


def _seed_session(db_path: Path, **fields) -> None:
    """Insert one study_sessions row with sensible defaults."""
    now = time.time()
    defaults = dict(
        id=fields.get("id", f"s_{now}"),
        student_id="student-primary",
        title="Study Session",
        subject="Math",
        target_duration_seconds=1800,
        actual_duration_seconds=600,
        start_time=now - 3600,
        end_time=None,
        status="completed",
        focus_score=None,
        engagement_score=None,
        distraction_count=0,
        warning_count=0,
        ai_summary="",
        created_at=now - 3600,
    )
    defaults.update({k: v for k, v in fields.items() if k != "id"})
    cols = ", ".join(defaults.keys())
    marks = ", ".join("?" for _ in defaults)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO study_sessions ({cols}) VALUES ({marks})",
            tuple(defaults.values()),
        )
        conn.commit()


# ------------------------------------------------------------------ sessions


@pytest.mark.asyncio
async def test_sessions_weekly_uses_actual_duration_column(portal_env):
    """Regression: weekly buckets must read actual_duration_seconds (the old
    code read a nonexistent ``duration_seconds`` and always rendered zeros)."""
    now = time.time()
    _seed_session(portal_env, id="sess_today", actual_duration_seconds=1500,
                  start_time=now - 1800, created_at=now - 1800, status="completed")
    _seed_session(portal_env, id="_sess_old", actual_duration_seconds=9999,
                  start_time=now - 40 * 86400, created_at=now - 40 * 86400)

    data = await parent_router.get_student_sessions("student-primary")

    assert sum(data["weekly_study_time"]) == pytest.approx(25.0)  # 1500s = 25min
    assert data["session_count_week"] == 1
    assert data["session_count_month"] == 1  # 40-day-old session excluded
    assert any(s["id"] == "sess_today" for s in data["sessions"])


@pytest.mark.asyncio
async def test_sessions_weekday_buckets_match_labels(portal_env):
    now = time.time()
    # Find the epoch instant of this week's Monday 12:00 local.
    lt = time.localtime(now)
    monday = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1)) - lt.tm_wday * 86400
    _seed_session(portal_env, id="sess_mon", start_time=monday,
                  created_at=monday, actual_duration_seconds=1200)

    data = await parent_router.get_student_sessions("student-primary")

    monday_minutes = data["weekly_study_time"][0]  # index 0 == Monday label
    assert monday_minutes == pytest.approx(20.0)


# ----------------------------------------------------------------- dashboard


@pytest.mark.asyncio
async def test_dashboard_reports_real_focus_score_not_zero(portal_env):
    """Regression: focus_score used to be hardcoded to 0."""
    now = time.time()
    _seed_session(portal_env, id="done1", status="completed", focus_score=87.3,
                  actual_duration_seconds=900, start_time=now - 7200, created_at=now - 7200)

    rows = await parent_router.get_parent_dashboard("default")
    assert isinstance(rows, list) and len(rows) >= 1
    top = rows[0]
    assert top["focus_score"] == pytest.approx(87.3)
    assert top["today_study_time"] >= 15.0  # 900s from today's session
    assert top["status"] in ("studying", "offline")  # honest live state only


@pytest.mark.asyncio
async def test_dashboard_focus_null_when_never_measured(portal_env):
    _seed_session(portal_env, id="raw1", status="in_progress",
                  focus_score=None, actual_duration_seconds=0)
    rows = await parent_router.get_parent_dashboard("default")
    assert rows[0]["focus_score"] is None  # frontend renders honest —


@pytest.mark.asyncio
async def test_dashboard_sums_all_of_todays_sessions(portal_env):
    now = time.time()
    lt = time.localtime(now)
    midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    _seed_session(portal_env, id="morn", status="completed",
                  actual_duration_seconds=1200, start_time=midnight + 3600,
                  created_at=midnight + 3600)
    _seed_session(portal_env, id="live", status="in_progress",
                  actual_duration_seconds=300, start_time=now - 600,
                  created_at=now - 600)
    _seed_session(portal_env, id="yest", status="completed",
                  actual_duration_seconds=5000, start_time=now - 30 * 86400,
                  created_at=now - 30 * 86400)

    rows = await parent_router.get_parent_dashboard("default")
    today_min = rows[0]["today_study_time"]
    # morning 20min + live session counting up (>=10min) but NOT yesterday's.
    assert 30.0 <= today_min <= 45.0


@pytest.mark.asyncio
async def test_dashboard_fallback_name_from_supervision_rules(portal_env):
    import aiosqlite as aio

    from deeptutor.services.remote.kv_settings import ensure_kv_settings

    async with aio.connect(portal_env) as db:
        await ensure_kv_settings(db)
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value, category, updated_at)"
            " VALUES (?, ?, 'supervision', ?)",
            ("supervision_rules_default", '{"student_name": "Riya", "daily_goal_minutes": 90, "alert_strictness": "strict"}', time.time()),
        )
        await db.commit()

    rows = await parent_router.get_parent_dashboard("default")
    assert rows[0]["name"] == "Riya"


# ------------------------------------------------------- telegram resilience


@pytest.mark.asyncio
async def test_telegram_config_survives_legacy_settings_shape(tmp_path, monkeypatch):
    """Regression: telegram/test + send-link SELECTed without ensure_kv_settings
    and could 500 on a migration-shaped (value_json) settings table."""
    db_path = tmp_path / "chat_history.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL,"
            " category TEXT DEFAULT 'general', updated_at REAL DEFAULT 0)"
        )
        conn.commit()

    monkeypatch.setattr(parent_router, "_get_db_path", lambda: db_path)

    config = await parent_router.get_telegram_config("default")
    assert config["configured"] is False  # no crash, honest unconfigured state


# ------------------------------------------------------------ tunnel ports


@pytest.mark.asyncio
async def test_tunnel_defaults_to_frontend_port():
    """Regression: the tunnel used to hardcode the backend :8001, which made
    remote {tunnel}/parent URLs hit FastAPI instead of the portal UI."""
    from deeptutor.api.routers.parent import StartTunnelRequest
    from deeptutor.services.remote.tunnel_gateway import TunnelGateway

    req = StartTunnelRequest()
    assert req.port is None  # router no longer pins a port

    resolved = TunnelGateway._default_local_port()
    assert isinstance(resolved, int) and 1024 < resolved < 65536
    assert TunnelGateway.get_local_port() == resolved

    snap = TunnelGateway.status_snapshot()
    assert snap["local_port"] == resolved


@pytest.mark.asyncio
async def test_portal_base_url_prefers_public_tunnel(monkeypatch):
    from deeptutor.services.remote import tunnel_gateway as tg

    monkeypatch.setattr(tg.TunnelGateway, "get_tunnel_url", classmethod(lambda cls: "https://abc.trycloudflare.com"))
    monkeypatch.setattr(tg.TunnelGateway, "is_url_public", classmethod(lambda cls: True))

    url, mode = parent_router._portal_base_url()
    assert url == "https://abc.trycloudflare.com" and mode == "tunnel"

    monkeypatch.setattr(tg.TunnelGateway, "is_url_public", classmethod(lambda cls: False))
    url, mode = parent_router._portal_base_url()
    assert mode == "lan" and "/parent" not in url  # base only; endpoint appends path
