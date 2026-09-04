"""Security suite for the AI Guru parent portal (vault crypto, JWT gate,
PIN lifecycle, pairing links).

Isolation strategy: every DB-backed service resolves its database through a
``_get_db_path`` classmethod — we point all of them at one temp SQLite file,
so no fixture from conftest is required and real user data can never be hit.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import time
import uuid

import pytest

pytest.importorskip("cryptography")

from deeptutor.services.remote import video_vault as vv_mod
from deeptutor.services.remote.audit_logger import AuditLogger
from deeptutor.services.remote.auth_jwt import JWTAuthService
from deeptutor.services.remote.pairing import PairingService
from deeptutor.services.remote.telegram_config import TelegramConfigStore
from deeptutor.services.remote.video_vault import VideoVaultManager


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch):
    """Point every remote-service DB + vault dir at a temp location."""
    db_path = tmp_path / "chat_history.db"
    vault_dir = tmp_path / "video_vault"

    monkeypatch.setattr(JWTAuthService, "_get_db_path", staticmethod(lambda: db_path))
    monkeypatch.setattr(PairingService, "_get_db_path", staticmethod(lambda: db_path))
    monkeypatch.setattr(AuditLogger, "_get_db_path", staticmethod(lambda: db_path))
    monkeypatch.setattr(VideoVaultManager, "get_vault_dir", classmethod(lambda cls: _ensure(vault_dir)))
    monkeypatch.setattr(
        VideoVaultManager,
        "get_pending_dir",
        classmethod(lambda cls: _ensure(vault_dir / "pending")),
    )
    # Fresh brute-force tracker per test
    from deeptutor.services.remote import auth_jwt as aj

    monkeypatch.setattr(aj, "_PIN_ATTEMPT_TRACKER", {})
    return db_path


def _ensure(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


# ------------------------------------------------------------- vault crypto


@pytest.mark.asyncio
async def test_vault_snapshot_roundtrip_and_wrong_pin(isolated_env):
    pin = "4321"
    jpeg = b"\xff\xd8FAKEJPEG" + os.urandom(64)

    clip_id = await VideoVaultManager.save_encrypted_snapshot(
        session_id="sess_x", student_id="s1", parent_pin=pin,
        image_bytes=jpeg, event_type="PHONE_DETECTED", metadata={"confidence": 0.9},
    )
    assert clip_id.endswith(".vault")

    ok = await VideoVaultManager.decrypt_snapshot(clip_id, pin)
    assert ok and ok["kind"] == "snapshot"
    import base64

    assert base64.b64decode(ok["image_base64"]) == jpeg

    with pytest.raises(PermissionError):
        await VideoVaultManager.decrypt_snapshot(clip_id, "0000")


@pytest.mark.asyncio
async def test_vault_pending_clip_seal_flow(isolated_env):
    pin = "998877"
    frames = [os.urandom(32) for _ in range(4)]

    await VideoVaultManager.save_pending_clip("sess_y", "LOOKING_AWAY", frames, fps=5.0,
                                              metadata={"confidence": 0.85})
    assert VideoVaultManager.count_pending() == 1

    sealed = await VideoVaultManager.seal_pending(pin)
    assert sealed == 1
    assert VideoVaultManager.count_pending() == 0

    items = await VideoVaultManager.list_encrypted_snapshots(session_id="sess_y")
    assert items and items[0]["event_type"] == "LOOKING_AWAY"

    out = await VideoVaultManager.decrypt_snapshot(items[0]["clip_id"], pin)
    assert out and out["kind"] == "clip" and len(out["frames_base64"]) == 4


@pytest.mark.asyncio
async def test_vault_refuses_without_cryptography(isolated_env, monkeypatch):
    monkeypatch.setattr(vv_mod, "HAS_CRYPTOGRAPHY", False)
    with pytest.raises(RuntimeError):
        await VideoVaultManager.save_encrypted_snapshot(
            session_id="s", student_id="st", parent_pin="1111",
            image_bytes=b"x", event_type="E",
        )


# --------------------------------------------------------------- PIN + JWT


@pytest.mark.asyncio
async def test_pin_lifecycle_and_lockout(isolated_env):
    assert await JWTAuthService.has_parent_pin("default") is False
    await JWTAuthService.set_parent_pin("1357", "default")
    assert await JWTAuthService.has_parent_pin("default") is True

    # Wrong PIN increments attempts; message shows remaining tries.
    with pytest.raises(ValueError, match="attempts remaining"):
        await JWTAuthService.verify_parent_pin("9999", "default")
    # Correct PIN issues a token pair.
    result = await JWTAuthService.verify_parent_pin("1357", "default")
    assert result["access_token"] and result["refresh_token"]

    # Lockout after MAX_FAILED_ATTEMPTS consecutive failures.
    for _ in range(JWTAuthService.MAX_FAILED_ATTEMPTS):
        with pytest.raises(ValueError):
            await JWTAuthService.verify_parent_pin("0000", "default")
    with pytest.raises(ValueError, match="Too many failed attempts"):
        await JWTAuthService.verify_parent_pin("1357", "default")


@pytest.mark.asyncio
async def test_pin_format_and_weak_code_rejection(isolated_env):
    # Non-digit / wrong-length codes are rejected before anything is stored.
    for bad in ("abcd", "12 4", "12", "123456789", ""):
        with pytest.raises(ValueError, match="digits"):
            await JWTAuthService.set_parent_pin(bad, "fmt")

    # Trivially guessable codes are rejected.
    for weak in ("1234", "4321", "1111", "0000", "2580", "123456"):
        with pytest.raises(ValueError, match="predictable|common"):
            await JWTAuthService.set_parent_pin(weak, "weak")

    assert await JWTAuthService.has_parent_pin("fmt") is False
    assert await JWTAuthService.has_parent_pin("weak") is False


@pytest.mark.asyncio
async def test_refresh_rotation_invalidates_old_token(isolated_env):
    await JWTAuthService.set_parent_pin("2468", "rot")
    auth = await JWTAuthService.verify_parent_pin("2468", "rot")
    old_refresh = auth["refresh_token"]

    rotated = await JWTAuthService.rotate_refresh_token(old_refresh)
    assert rotated["access_token"] and rotated["refresh_token"]
    assert await JWTAuthService.verify_token(rotated["access_token"])

    # Replay of the rotated-away refresh token must fail (revoked).
    with pytest.raises(ValueError):
        await JWTAuthService.rotate_refresh_token(old_refresh)

    # Access tokens are NOT valid refresh tokens.
    with pytest.raises(ValueError, match="Not a refresh token"):
        await JWTAuthService.rotate_refresh_token(auth["access_token"])


@pytest.mark.asyncio
async def test_revoke_refresh_token_for_logout(isolated_env):
    refresh = await JWTAuthService.create_refresh_token("default")
    assert await JWTAuthService.revoke_refresh_token(refresh) is True
    with pytest.raises(ValueError, match="[Rr]evoked"):
        await JWTAuthService.refresh_access_token(refresh)
    # Idempotent / garbage input is safe.
    assert await JWTAuthService.revoke_refresh_token(refresh) is False
    assert await JWTAuthService.revoke_refresh_token("not-a-token") is False


@pytest.mark.asyncio
async def test_change_pin_requires_current(isolated_env):
    await JWTAuthService.set_parent_pin("1717", "p1")
    with pytest.raises(ValueError, match="Current PIN is incorrect"):
        await JWTAuthService.change_parent_pin("2468", "wrong", "p1")
    assert await JWTAuthService.change_parent_pin("2468", "1717", "p1") is True
    res = await JWTAuthService.verify_parent_pin("2468", "p1")
    assert res["success"] is True


@pytest.mark.asyncio
async def test_jwt_verify_refresh_revoke(isolated_env):
    access = await JWTAuthService.create_access_token("default", device_info="unit-test")
    payload = await JWTAuthService.verify_token(access)
    assert payload["role"] == "parent" and payload["type"] == "access"

    refresh = await JWTAuthService.create_refresh_token("default")
    new_access = await JWTAuthService.refresh_access_token(refresh)
    assert await JWTAuthService.verify_token(new_access)

    refreshed = await JWTAuthService.verify_token(new_access)
    await JWTAuthService.revoke_token(refreshed["jti"])
    with pytest.raises(ValueError, match="[Rr]evoked"):
        await JWTAuthService.verify_token(new_access)


@pytest.mark.asyncio
async def test_pairing_generate_verify_revoke(isolated_env):
    gen = await PairingService.generate_pairing_code("student-primary", "default")
    code = gen["code"]
    assert code.startswith("GURU-")

    link = await PairingService.verify_pairing_code("default", code)
    assert link and link["status"] == "active"

    students = await PairingService.get_linked_students("default")
    assert any(s["student_id"] == "student-primary" for s in students)
    perms = students[0].get("permissions", {})
    assert perms.get("can_view_live") is True

    link_id = students[0]["link_id"]
    assert await PairingService.revoke_link(link_id) is True
    assert await PairingService.get_linked_students("default") == []


@pytest.mark.asyncio
async def test_pin_change_invalidates_outstanding_tokens(isolated_env):
    """PIN set/change bumps the epoch: every earlier JWT dies immediately."""
    await JWTAuthService.set_parent_pin("3141", "ep")
    auth = await JWTAuthService.verify_parent_pin("3141", "ep")
    old_access, old_refresh = auth["access_token"], auth["refresh_token"]
    assert await JWTAuthService.verify_token(old_access)

    await JWTAuthService.change_parent_pin("5926", "3141", "ep")

    for stale in (old_access, old_refresh):
        with pytest.raises(ValueError, match="superseded"):
            await JWTAuthService.verify_token(stale)

    # Fresh login under the new PIN works.
    fresh = await JWTAuthService.verify_parent_pin("5926", "ep")
    assert await JWTAuthService.verify_token(fresh["access_token"])


@pytest.mark.asyncio
async def test_revoked_rows_are_purged(isolated_env):
    import aiosqlite

    token = await JWTAuthService.create_access_token("default")
    payload = await JWTAuthService.verify_token(token)
    await JWTAuthService.revoke_token(payload["jti"])

    # Backdate the row beyond any possible refresh-token lifetime.
    db_path = isolated_env
    async with aiosqlite.connect(db_path) as db:
        await ensure_kv(db)
        await db.execute(
            "UPDATE settings SET value = ? WHERE key = ?",
            (str(int(time.time()) - 30 * 86400), f"revoked_{payload['jti']}"),
        )
        await db.commit()

    # A new revocation triggers the lazy purge of expired rows.
    other = await JWTAuthService.create_refresh_token("default")
    other_payload = await JWTAuthService.verify_token(other)
    await JWTAuthService.revoke_token(other_payload["jti"])

    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM settings WHERE key = ?", (f"revoked_{payload['jti']}",)
        )
        assert (await cur.fetchone())[0] == 0
        # The fresh revocation is still present.
        cur = await db.execute(
            "SELECT COUNT(*) FROM settings WHERE key = ?", (f"revoked_{other_payload['jti']}",)
        )
        assert (await cur.fetchone())[0] == 1


def test_legacy_pin_hash_still_verifies():
    salt = bytes.fromhex("ab" * 16)
    h = hashlib.pbkdf2_hmac("sha256", b"1357", salt, 100_000, 32)
    legacy_hash = f"{salt.hex()}${h.hex()}"
    assert JWTAuthService._verify_pin_hash("1357", legacy_hash) is True
    assert JWTAuthService._verify_pin_hash("0000", legacy_hash) is False


def test_v2_pin_hash_embeds_iterations():
    stored = JWTAuthService._hash_pin("2468", b"\xcd" * 16)
    assert stored.startswith("v2$600000$")
    assert JWTAuthService._verify_pin_hash("2468", stored) is True
    assert JWTAuthService._verify_pin_hash("1357", stored) is False


async def ensure_kv(db):
    from deeptutor.services.remote.kv_settings import ensure_kv_settings

    await ensure_kv_settings(db)


# --------------------------------------------------- router-level HTTP gate


def test_require_parent_http_gate(isolated_env, monkeypatch):
    import asyncio

    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from deeptutor.api.routers.parent import require_parent

    app = FastAPI()

    @app.get("/guarded")
    async def guarded(payload: dict = Depends(require_parent)):
        return {"ok": True, "sub": payload.get("sub")}

    client = TestClient(app)

    # No token -> 401 parent_auth_required
    res = client.get("/guarded")
    assert res.status_code == 401 and res.json()["detail"] == "parent_auth_required"

    # Garbage token -> 401
    res = client.get("/guarded", headers={"Authorization": "Bearer not-a-jwt"})
    assert res.status_code == 401

    # Valid parent token -> 200
    access = asyncio.run(JWTAuthService.create_access_token("default"))
    res = client.get("/guarded", headers={"Authorization": f"Bearer {access}"})
    assert res.status_code == 200 and res.json()["ok"] is True

    # A *student*-role token must be rejected even if cryptographically valid.
    from deeptutor.services.remote import auth_jwt as aj

    pyjwt = aj.jwt
    secret = asyncio.run(JWTAuthService.get_secret_key())
    now = int(time.time())
    forged_student = pyjwt.encode(
        {"sub": "student-primary", "role": "user", "type": "access",
         "iat": now, "exp": now + 300, "jti": uuid.uuid4().hex},
        secret, algorithm="HS256",
    )
    # A *student*-role token must be rejected even if cryptographically valid.
    from deeptutor.services.remote import auth_jwt as aj

    pyjwt = aj.jwt
    secret = asyncio.run(JWTAuthService.get_secret_key())
    now = int(time.time())
    forged_student = pyjwt.encode(
        {"sub": "student-primary", "role": "user", "type": "access",
         "iat": now, "exp": now + 300, "jti": uuid.uuid4().hex},
        secret, algorithm="HS256",
    )
    res = client.get("/guarded", headers={"Authorization": f"Bearer {forged_student}"})
    assert res.status_code == 401


# ------------------------------------------------- refactor regression suite


@pytest.fixture()
def alert_env(isolated_env, monkeypatch):
    """Extend isolation to the alert pipeline's DB handles (outbox + store)."""
    from deeptutor.services.monitoring import notification_queue as nq
    from deeptutor.services.monitoring import outbox_repo as obr
    from deeptutor.services.remote import telegram_config as tc

    db_path = isolated_env
    monkeypatch.setattr(tc, "_db_path", lambda: db_path)
    monkeypatch.setattr(obr, "db_path", lambda: db_path)
    monkeypatch.setattr(nq, "_db_path", lambda: db_path)
    return db_path


@pytest.mark.asyncio
async def test_verify_parent_access_token_rejects_refresh(isolated_env):
    await JWTAuthService.set_parent_pin("3579", "p2")
    auth = await JWTAuthService.verify_parent_pin("3579", "p2")

    payload = await JWTAuthService.verify_parent_access_token(auth["access_token"])
    assert payload["type"] == "access"

    with pytest.raises(ValueError, match="Not a parent access token"):
        await JWTAuthService.verify_parent_access_token(auth["refresh_token"])
    with pytest.raises(ValueError):
        await JWTAuthService.verify_parent_access_token("")
    with pytest.raises(ValueError):
        await JWTAuthService.verify_parent_access_token("garbage-token")


@pytest.mark.asyncio
async def test_change_pin_wrong_current_locks_out(isolated_env):
    await JWTAuthService.set_parent_pin("1717", "p3")
    for _ in range(JWTAuthService.MAX_FAILED_ATTEMPTS):
        with pytest.raises(ValueError):
            await JWTAuthService.change_parent_pin("2468", "0000", "p3")
    # Budget exhausted: even the CORRECT current PIN is now locked out.
    with pytest.raises(ValueError, match="Too many failed attempts"):
        await JWTAuthService.change_parent_pin("2468", "1717", "p3")


@pytest.mark.asyncio
async def test_vault_same_second_staging_never_collides(isolated_env):
    jpeg = b"\xff\xd8fake" + os.urandom(16)
    s1 = await VideoVaultManager.save_pending_snapshot("sess_c", "PHONE_DETECTED", jpeg)
    s2 = await VideoVaultManager.save_pending_snapshot("sess_c", "PHONE_DETECTED", jpeg)
    assert s1 != s2
    assert VideoVaultManager.count_pending() == 2

    assert await VideoVaultManager.seal_pending("7531") == 2
    items = await VideoVaultManager.list_encrypted_snapshots(session_id="sess_c")
    assert len(items) == 2


@pytest.mark.asyncio
async def test_vault_session_filter_is_exact(isolated_env):
    pin = "7531"
    await VideoVaultManager.save_encrypted_snapshot(
        session_id="abc", student_id="s", parent_pin=pin,
        image_bytes=b"\xff\xd8a", event_type="E",
    )
    await VideoVaultManager.save_encrypted_snapshot(
        session_id="abc123", student_id="s", parent_pin=pin,
        image_bytes=b"\xff\xd8b", event_type="E",
    )
    items = await VideoVaultManager.list_encrypted_snapshots(session_id="abc")
    assert {i["session_id"] for i in items} == {"abc"}


@pytest.mark.asyncio
async def test_telegram_config_store_crud(alert_env):
    assert await TelegramConfigStore.get("default") is None

    await TelegramConfigStore.save("default", bot_token="tok123", chat_id="42", enabled=True)
    assert await TelegramConfigStore.get("default") == {"bot_token": "tok123", "chat_id": "42"}

    masked = await TelegramConfigStore.get_masked("default")
    assert masked["configured"] is True and masked["chat_id"] == "42"
    assert "tok123" not in masked["bot_token_masked"]

    # Blank token keeps the saved credential (Chat-ID-only edit).
    await TelegramConfigStore.save("default", bot_token="  ", chat_id="43", enabled=True)
    kept = await TelegramConfigStore.get("default")
    assert kept and kept["bot_token"] == "tok123" and kept["chat_id"] == "43"

    # Disabled rows read as unconfigured but keep their secret for re-enable.
    await TelegramConfigStore.save("default", bot_token="", chat_id="43", enabled=False)
    assert await TelegramConfigStore.get("default") is None

    with pytest.raises(ValueError, match="first-time"):
        await TelegramConfigStore.save("other", bot_token="  ", chat_id="1")

    await TelegramConfigStore.save("p2", bot_token="t2", chat_id="7", enabled=True)
    assert {p for p, _ in await TelegramConfigStore.list_enabled()} == {"p2"}


@pytest.mark.asyncio
async def test_outbox_enqueue_flush_per_parent(alert_env, monkeypatch):
    from deeptutor.services.monitoring import notification_queue as nq
    from deeptutor.services.remote import telegram_notifier as tn

    sent = []

    async def fake_send(*args, **kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setattr(tn.TelegramNotifier, "send_message", fake_send)

    await TelegramConfigStore.save("default", bot_token="t", chat_id="1", enabled=True)
    payload = {"category": "NOTICE", "message": "m", "severity": "warning",
               "confidence": 0.9, "duration_seconds": 5}
    assert await nq.enqueue("warning", payload) > 0
    assert await nq.flush_once(limit=5) == 1
    assert len(sent) == 1 and sent[0]["chat_id"] == "1"
    # Already sent: second flush is a no-op.
    assert await nq.flush_once(limit=5) == 0
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_outbox_concurrent_flush_delivers_once(alert_env, monkeypatch):
    from deeptutor.services.monitoring import notification_queue as nq
    from deeptutor.services.remote import telegram_notifier as tn

    delivered = []

    async def slow_send(*args, **kwargs):
        await asyncio.sleep(0.2)
        delivered.append(1)
        return True

    monkeypatch.setattr(tn.TelegramNotifier, "send_message", slow_send)

    await TelegramConfigStore.save("default", bot_token="t", chat_id="1", enabled=True)
    await nq.enqueue("warning", {"category": "NOTICE", "message": "m",
                                 "severity": "warning", "confidence": 0.9,
                                 "duration_seconds": 5})
    results = await asyncio.gather(nq.flush_once(limit=5), nq.flush_once(limit=5))
    assert sum(results) == 1
    assert len(delivered) == 1


@pytest.mark.asyncio
async def test_outbox_fans_out_to_linked_parents(alert_env, monkeypatch):
    from deeptutor.services.monitoring import notification_queue as nq
    from deeptutor.services.remote import telegram_notifier as tn

    chats = []

    async def fake_send(*args, **kwargs):
        chats.append(kwargs.get("chat_id"))
        return True

    monkeypatch.setattr(tn.TelegramNotifier, "send_message", fake_send)

    await TelegramConfigStore.save("mom", bot_token="t", chat_id="100", enabled=True)
    await TelegramConfigStore.save("dad", bot_token="t", chat_id="200", enabled=True)
    gen = await PairingService.generate_pairing_code("kid1", "mom")
    await PairingService.verify_pairing_code("mom", gen["code"])
    gen2 = await PairingService.generate_pairing_code("kid1", "dad")
    await PairingService.verify_pairing_code("dad", gen2["code"])

    rows = await nq.enqueue_for_student("warning", {"category": "NOTICE", "message": "m",
                                                    "severity": "warning", "confidence": 0.9,
                                                    "duration_seconds": 5}, "kid1")
    assert len(rows) == 2
    assert await nq.flush_once(limit=10) == 2
    assert sorted(chats) == ["100", "200"]


@pytest.mark.asyncio
async def test_listener_reads_all_enabled_parents(alert_env):
    from deeptutor.services.remote import telegram_command_listener as tcl

    await TelegramConfigStore.save("default", bot_token="t", chat_id="1", enabled=True)
    await TelegramConfigStore.save("p2", bot_token="t", chat_id="2", enabled=True)
    await TelegramConfigStore.save("off", bot_token="t", chat_id="3", enabled=False)
    configs = await tcl._read_configs()
    assert {p for p, _ in configs} == {"default", "p2"}
    assert tcl.TelegramCommandListener()._offsets == {}


@pytest.mark.asyncio
async def test_pairing_regenerate_keeps_active(isolated_env):
    gen = await PairingService.generate_pairing_code("student-primary", "default")
    await PairingService.verify_pairing_code("default", gen["code"])
    await PairingService.generate_pairing_code("student-primary", "default")
    students = await PairingService.get_linked_students("default")
    assert any(s["student_id"] == "student-primary" for s in students)


@pytest.mark.asyncio
async def test_pairing_verify_merges_without_unique_violation(isolated_env):
    gen_a = await PairingService.generate_pairing_code("studentX", "parentA")
    gen_b = await PairingService.generate_pairing_code("studentX", "parentB")
    await PairingService.verify_pairing_code("parentB", gen_b["code"])
    link = await PairingService.verify_pairing_code("parentB", gen_a["code"])
    assert link and link["status"] == "active" and link["parent_id"] == "parentB"
    rows = await PairingService.get_linked_students("parentB")
    assert sum(1 for r in rows if r["student_id"] == "studentX") == 1


@pytest.mark.asyncio
async def test_live_permission_no_links_passes(isolated_env):
    from deeptutor.api.routers.parent import _require_live_permission

    assert await _require_live_permission("default", "sess-1") is None


@pytest.mark.asyncio
async def test_live_permission_denied_without_can_view_live(isolated_env, monkeypatch):
    from fastapi import HTTPException

    from deeptutor.api.routers import parent as parent_router

    async def fake_links(cls, parent_id):
        return [{"student_id": "s1", "permissions": {"can_view_live": False}}]

    async def fake_get_session(self, session_id):
        return {"student_id": "s1"}

    monkeypatch.setattr(
        PairingService, "get_linked_students", classmethod(fake_links)
    )
    from deeptutor.services.study import session_manager as sm

    monkeypatch.setattr(sm.StudySessionManager, "get_session", fake_get_session)
    with pytest.raises(HTTPException) as exc_info:
        await parent_router._require_live_permission("default", "sess-9")
    assert exc_info.value.status_code == 403
