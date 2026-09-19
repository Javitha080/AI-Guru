"""Fresh-install end-to-end smoke for the AI Guru supervision stack.

Proves the complete persistence chain on a brand-new database (migrations
applied exactly like production startup):

    session create/start -> monitoring events persist -> warning dispatch ->
    encrypted vault staging -> report generation -> gamification XP/badges ->
    settings dual-shape bridge -> parent PIN/JWT.

Runs against an isolated workspace; never touches real user data.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytestmark = [pytest.mark.asyncio]


async def _run(tmp: Path) -> dict:
    from deeptutor.services import path_service as ps

    previous = ps.PathService._instance
    svc = ps.PathService(workspace_root=tmp)
    ps.PathService._instance = svc
    try:
        return await _run_isolated(tmp, svc)
    finally:
        ps.PathService._instance = previous


async def _run_isolated(tmp: Path, svc) -> dict:

    db = svc.user_dir / "chat_history.db"
    db.parent.mkdir(parents=True, exist_ok=True)

    from deeptutor.services.database.migrations import apply_migrations, enable_pragmas

    conn = sqlite3_connect(db)
    enable_pragmas(conn)
    applied = apply_migrations(conn)
    conn.commit()
    conn.close()
    assert {1, 2} <= set(applied), f"expected migrations [1,2] applied, got {applied}"

    results: dict = {}

    # ---- Study sessions -----------------------------------------------------
    from deeptutor.services.study.session_manager import StudySessionManager

    mgr = StudySessionManager()
    session = await mgr.create_session("student-primary", "Smoke", "Physics", 900)
    await mgr.start_session(session["id"])
    await mgr.stop_session(session["id"])
    row = await mgr.get_session(session["id"])
    assert row["status"] == "completed"
    results["session_id"] = session["id"]

    # ---- Telemetry events ---------------------------------------------------
    from deeptutor.services.study.telemetry_logger import TelemetryLogger

    tel = TelemetryLogger()
    await tel.log_event(
        session_id=session["id"],
        event_type="WARNING_ISSUED",
        severity="warning",
        confidence=0.9,
        duration_seconds=8.0,
        metadata={"category": "PHONE_DETECTED", "message": "Phone detected"},
    )
    summary = await tel.get_session_summary(session["id"])
    assert summary["by_type"].get("WARNING_ISSUED", 0) >= 1
    results["events"] = summary["total_events"]

    # ---- Encrypted vault staging -> seal ------------------------------------
    from deeptutor.services.remote.video_vault import VideoVaultManager

    await VideoVaultManager.save_pending_snapshot(
        session["id"], "PHONE_DETECTED", b"\xff\xd8smoke" + b"\x00" * 16
    )
    assert VideoVaultManager.count_pending() == 1
    sealed = await VideoVaultManager.seal_pending("5926")
    assert sealed == 1
    assert VideoVaultManager.count_pending() == 0
    results["vault_sealed"] = sealed

    # ---- Report generation --------------------------------------------------
    from deeptutor.services.study.report_generator import ReportGenerator

    stored = await ReportGenerator().generate_report(session["id"], "student-primary")
    assert stored.get("ai_tutor_feedback")
    results["report_focus"] = stored["focus_score"]

    # ---- Gamification -------------------------------------------------------
    from deeptutor.services.gamification.gamification_service import GamificationService

    await GamificationService.award_xp(
        "student-primary", 60, f"session_completed:{session['id']}", session_id=session["id"]
    )
    await GamificationService.check_and_award("student-primary")
    prof = await GamificationService.get_profile("student-primary")
    assert prof["xp"] >= 60 and prof["total_sessions"] == 1
    badges = [
        b["id"] for b in await GamificationService.get_badges("student-primary") if b["earned"]
    ]
    assert "first_session" in badges
    results["xp"] = prof["xp"]
    results["badges"] = badges

    # ---- Parent PIN + JWT on the same DB (settings dual-shape) --------------
    from deeptutor.services.remote.auth_jwt import JWTAuthService

    await JWTAuthService.set_parent_pin("2468", "default")
    auth = await JWTAuthService.verify_parent_pin("2468", "default")
    payload = await JWTAuthService.verify_token(auth["access_token"])
    assert payload["role"] == "parent"
    results["parent_jwt"] = True

    return results


def sqlite3_connect(db: Path):
    import sqlite3

    return sqlite3.connect(db)


def test_fresh_install_full_chain(tmp_path: Path):
    results = asyncio.run(_run(tmp_path / "smoke_ws"))
    assert results["parent_jwt"] is True
    assert results["events"] >= 1
    assert results["vault_sealed"] == 1
    assert "first_session" in results["badges"]
