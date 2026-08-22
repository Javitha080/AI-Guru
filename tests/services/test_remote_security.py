"""Security suite for the AI Guru parent portal (vault crypto, JWT gate,
PIN lifecycle, pairing links).

Isolation strategy: every DB-backed service resolves its database through a
``_get_db_path`` classmethod — we point all of them at one temp SQLite file,
so no fixture from conftest is required and real user data can never be hit.
"""

from __future__ import annotations

import os
import uuid
import time
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from deeptutor.services.remote import video_vault as vv_mod
from deeptutor.services.remote.video_vault import VideoVaultManager
from deeptutor.services.remote.auth_jwt import JWTAuthService
from deeptutor.services.remote.pairing import PairingService
from deeptutor.services.remote.audit_logger import AuditLogger


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
    await JWTAuthService.set_parent_pin("1234", "default")
    assert await JWTAuthService.has_parent_pin("default") is True

    # Wrong PIN increments attempts; message shows remaining tries.
    with pytest.raises(ValueError, match="attempts remaining"):
        await JWTAuthService.verify_parent_pin("9999", "default")
    # Correct PIN issues a token pair.
    result = await JWTAuthService.verify_parent_pin("1234", "default")
    assert result["access_token"] and result["refresh_token"]

    # Lockout after MAX_FAILED_ATTEMPTS consecutive failures.
    for _ in range(JWTAuthService.MAX_FAILED_ATTEMPTS):
        with pytest.raises(ValueError):
            await JWTAuthService.verify_parent_pin("0000", "default")
    with pytest.raises(ValueError, match="Too many failed attempts"):
        await JWTAuthService.verify_parent_pin("1234", "default")


@pytest.mark.asyncio
async def test_change_pin_requires_current(isolated_env):
    await JWTAuthService.set_parent_pin("1111", "p1")
    with pytest.raises(ValueError, match="Current PIN is incorrect"):
        await JWTAuthService.change_parent_pin("2222", "wrong", "p1")
    assert await JWTAuthService.change_parent_pin("2222", "1111", "p1") is True
    res = await JWTAuthService.verify_parent_pin("2222", "p1")
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
    res = client.get("/guarded", headers={"Authorization": f"Bearer {forged_student}"})
    assert res.status_code == 401
