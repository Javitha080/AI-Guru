"""Debug-session suite for the P0 live-supervision batch (Phase 1 refactor).

Exercises the REAL parent router + REAL parent JWT service on an isolated
DB, with only the camera/network edges faked:

- WS handshake: subprotocol token, ``?token=`` fallback, refresh rejection,
  garbage rejection (4001s), live frame delivery as binary
- Pairing gate on WS + snapshot: allowed / denied / not-linked, enforced
  BEFORE any frame bytes are touched
- ``student_id`` targeting on snapshot / start / WS
- ``_resolve_live_session`` / ``_require_live_permission`` edge matrix

Monitoring-socket state is driven through the canonical
``monitoring_session`` module globals (the same objects the router reads);
a fixture restores them after every test so nothing leaks between suites.
"""

from __future__ import annotations

import base64
from pathlib import Path
import time
from typing import Any, Dict, List

import pytest

pytest.importorskip("cryptography")

from deeptutor.services.remote.audit_logger import AuditLogger
from deeptutor.services.remote.auth_jwt import JWTAuthService
from deeptutor.services.remote.pairing import PairingService

JPEG = b"\xff\xd8\xff\xe0FAKEJPEG" + bytes(range(64))


@pytest.fixture()
def live_env(tmp_path: Path, monkeypatch):
    """Isolated DB for every remote service + fresh brute-force tracker."""
    db_path = tmp_path / "chat_history.db"
    monkeypatch.setattr(JWTAuthService, "_get_db_path", staticmethod(lambda: db_path))
    monkeypatch.setattr(PairingService, "_get_db_path", staticmethod(lambda: db_path))
    monkeypatch.setattr(AuditLogger, "_get_db_path", staticmethod(lambda: db_path))
    from deeptutor.services.remote import auth_jwt as aj

    monkeypatch.setattr(aj, "_PIN_ATTEMPT_TRACKER", {})
    return db_path


@pytest.fixture()
def registry_state():
    """Snapshot + restore the canonical monitoring-session globals."""
    from deeptutor.api.routers import monitoring_session as ms

    saved = (
        dict(ms._active_monitoring_sessions),
        set(ms._live_consent),
        dict(ms._live_frames),
    )
    ms._active_monitoring_sessions.clear()
    ms._live_consent.clear()
    ms._live_frames.clear()
    try:
        yield ms
    finally:
        ms._active_monitoring_sessions.clear()
        ms._active_monitoring_sessions.update(saved[0])
        ms._live_consent.clear()
        ms._live_consent.update(saved[1])
        ms._live_frames.clear()
        ms._live_frames.update(saved[2])


@pytest.fixture()
def audit_tape(monkeypatch):
    """Replace the fire-and-forget audit with a synchronous recorder."""
    from deeptutor.api.routers import parent as parent_router

    calls: List[tuple] = []

    def record(action: str, actor: str = "local",
               details: Dict[str, Any] | None = None, **kwargs: Any) -> None:
        calls.append((action, actor, details or {}))

    monkeypatch.setattr(parent_router, "_audit", record)
    return calls


def _make_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from deeptutor.api.routers import parent as parent_router

    app = FastAPI()
    app.include_router(parent_router.router, prefix="/api/v1/parent")
    return TestClient(app), parent_router


async def _parent_tokens(parent_id: str = "default"):
    await JWTAuthService.set_parent_pin("3579", parent_id)
    auth = await JWTAuthService.verify_parent_pin("3579", parent_id)
    return auth["access_token"], auth["refresh_token"]


def _register_live(ms, session_id: str, with_frame: bool = True) -> None:
    ms._active_monitoring_sessions[session_id] = object()
    ms._live_consent.add(session_id)
    if with_frame:
        ms._live_frames[session_id] = (
            base64.b64encode(JPEG).decode("ascii"),
            time.time(),
        )


def _mock_study_session(monkeypatch, session: Dict[str, Any] | None,
                        listing: Dict[str, List[Dict[str, Any]]] | None = None):
    from deeptutor.services.study import session_manager as sm

    async def fake_get_session(self, session_id: str):
        if session is None:
            raise KeyError(session_id)
        return dict(session)

    async def fake_list_sessions(self, student_id: str, limit: int = 20, offset: int = 0):
        return {"items": list((listing or {}).get(student_id, [])), "total": 0}

    monkeypatch.setattr(sm.StudySessionManager, "get_session", fake_get_session)
    monkeypatch.setattr(sm.StudySessionManager, "list_sessions", fake_list_sessions)


def _mock_links(monkeypatch, links: List[Dict[str, Any]]):
    async def fake_links(cls, parent_id: str):
        return [dict(link) for link in links]

    monkeypatch.setattr(PairingService, "get_linked_students", classmethod(fake_links))


def _mock_tunnel(monkeypatch, public: bool = True):
    from deeptutor.services.remote.tunnel_gateway import TunnelGateway

    async def fake_start(cls, local_port=None, provider="cloudflare", ngrok_token=None):
        return {"status": "active" if public else "starting",
                "url": "https://demo.trycloudflare.com" if public else None,
                "provider": "cloudflare", "url_is_public": public}

    monkeypatch.setattr(TunnelGateway, "start_tunnel", classmethod(fake_start))
    monkeypatch.setattr(TunnelGateway, "is_url_public", classmethod(lambda cls: public))
    monkeypatch.setattr(
        TunnelGateway, "get_tunnel_url",
        classmethod(lambda cls: "https://demo.trycloudflare.com" if public else None),
    )


# ------------------------------------------------------------------ resolver


@pytest.mark.asyncio
async def test_resolve_explicit_session_passthrough(live_env, registry_state):
    from deeptutor.api.routers.parent import _resolve_live_session

    assert await _resolve_live_session("sess-x") == "sess-x"


@pytest.mark.asyncio
async def test_resolve_current_picks_consented_active(live_env, registry_state):
    from deeptutor.api.routers.parent import _resolve_live_session

    assert await _resolve_live_session("current") is None
    assert await _resolve_live_session(None) is None
    _register_live(registry_state, "sess-a", with_frame=False)
    assert await _resolve_live_session("current") == "sess-a"


@pytest.mark.asyncio
async def test_resolve_student_prefers_in_progress(live_env, registry_state, monkeypatch):
    from deeptutor.api.routers.parent import _resolve_live_session

    _mock_study_session(monkeypatch, {"student_id": "kid1"}, {
        "kid1": [
            {"id": "old-done", "status": "completed"},
            {"id": "live-now", "status": "in_progress"},
        ],
        "kid2": [{"id": "done", "status": "completed"}],
    })
    assert await _resolve_live_session("current", "kid1") == "live-now"
    assert await _resolve_live_session("sess-ignored", "kid2") is None
    assert await _resolve_live_session("current", "ghost") is None


# ---------------------------------------------------------------- permission


@pytest.mark.asyncio
async def test_permission_allows_linked_student(live_env, registry_state, monkeypatch, audit_tape):
    from deeptutor.api.routers.parent import _require_live_permission

    _mock_links(monkeypatch, [{"student_id": "s1", "permissions": {"can_view_live": True}}])
    _mock_study_session(monkeypatch, {"student_id": "s1"})
    assert await _require_live_permission("default", "sess-1") is None
    assert audit_tape == []


@pytest.mark.asyncio
async def test_permission_denies_unlinked_student(live_env, registry_state, monkeypatch, audit_tape):
    from fastapi import HTTPException

    from deeptutor.api.routers.parent import _require_live_permission

    _mock_links(monkeypatch, [{"student_id": "s1", "permissions": {"can_view_live": True}}])
    _mock_study_session(monkeypatch, {"student_id": "s-other"})
    with pytest.raises(HTTPException) as exc_info:
        await _require_live_permission("default", "sess-1")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "student_not_linked_to_parent"
    assert audit_tape and audit_tape[0][0] == "live.denied_not_linked"


@pytest.mark.asyncio
async def test_permission_fail_open_when_unattributed(
    live_env, registry_state, monkeypatch, audit_tape
):
    from deeptutor.api.routers.parent import _require_live_permission

    _mock_links(monkeypatch, [{"student_id": "s1", "permissions": {}}])
    _mock_study_session(monkeypatch, None)  # study manager hiccup
    assert await _require_live_permission("default", "sess-1") is None
    assert audit_tape and audit_tape[0][0] == "live.unattributed_session"


# ------------------------------------------------------------------ snapshot


@pytest.mark.asyncio
async def test_snapshot_serves_frame(live_env, registry_state, audit_tape):
    client, _ = _make_client()
    access, _ = await _parent_tokens()
    _register_live(registry_state, "sess-1")

    res = client.get(
        "/api/v1/parent/live/snapshot?session_id=sess-1",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    assert res.content == JPEG


@pytest.mark.asyncio
async def test_snapshot_denied_before_frames(
    live_env, registry_state, monkeypatch, audit_tape
):
    """A frame IS staged, yet a can_view_live=False link yields 403, not JPEG."""
    client, _ = _make_client()
    access, _ = await _parent_tokens()
    _register_live(registry_state, "sess-1")  # frame present + consented + active
    _mock_links(monkeypatch, [{"student_id": "s1", "permissions": {"can_view_live": False}}])
    _mock_study_session(monkeypatch, {"student_id": "s1"})

    res = client.get(
        "/api/v1/parent/live/snapshot?session_id=sess-1",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert res.status_code == 403
    assert res.json()["detail"] == "can_view_live not granted"


@pytest.mark.asyncio
async def test_snapshot_student_targeting(live_env, registry_state, monkeypatch, audit_tape):
    client, _ = _make_client()
    access, _ = await _parent_tokens()
    _register_live(registry_state, "sess-live")
    _mock_study_session(monkeypatch, {"student_id": "kid1"}, {
        "kid1": [{"id": "sess-live", "status": "in_progress"}],
    })

    res = client.get(
        "/api/v1/parent/live/snapshot?student_id=kid1",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert res.status_code == 200 and res.content == JPEG

    res = client.get(
        "/api/v1/parent/live/snapshot?student_id=nobody",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert res.status_code == 404


# --------------------------------------------------------------------- start


@pytest.mark.asyncio
async def test_live_start_grants_consent_and_reports_urls(
    live_env, registry_state, monkeypatch, audit_tape
):
    client, _ = _make_client()
    access, _ = await _parent_tokens()
    _mock_tunnel(monkeypatch, public=True)
    registry_state._active_monitoring_sessions["sess-9"] = object()
    _mock_study_session(monkeypatch, {"student_id": "kid1"}, {
        "kid1": [{"id": "sess-9", "status": "in_progress"}],
    })

    res = client.post(
        "/api/v1/parent/live/start?student_id=kid1",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["session_id"] == "sess-9" and body["enabled"] is True
    assert body["tunnel_url"] == "https://demo.trycloudflare.com/parent"
    assert body["lan_url"].endswith("/parent")

    from deeptutor.services.monitoring.session_registry import has_consent

    assert has_consent("sess-9") is True


@pytest.mark.asyncio
async def test_live_start_denied_for_unlinked_student(
    live_env, registry_state, monkeypatch, audit_tape
):
    client, _ = _make_client()
    access, _ = await _parent_tokens()
    _mock_tunnel(monkeypatch, public=True)
    registry_state._active_monitoring_sessions["sess-9"] = object()
    _mock_links(monkeypatch, [{"student_id": "s1", "permissions": {"can_view_live": True}}])
    _mock_study_session(monkeypatch, {"student_id": "kidX"}, {
        "kidX": [{"id": "sess-9", "status": "in_progress"}],
    })

    res = client.post(
        "/api/v1/parent/live/start?student_id=kidX",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert res.status_code == 403

    from deeptutor.services.monitoring.session_registry import has_consent

    assert has_consent("sess-9") is False


# ------------------------------------------------------------------------ WS


@pytest.mark.asyncio
async def test_ws_subprotocol_auth_streams_frames(live_env, registry_state, audit_tape):
    client, _ = _make_client()
    access, _ = await _parent_tokens()
    _register_live(registry_state, "sess-ws")

    with client.websocket_connect(
        "/api/v1/parent/live/stream?session_id=sess-ws",
        subprotocols=[f"parent.{access}"],
    ) as ws:
        assert ws.receive_bytes() == JPEG


@pytest.mark.asyncio
async def test_ws_query_token_fallback_streams(live_env, registry_state, audit_tape):
    client, _ = _make_client()
    access, _ = await _parent_tokens()
    _register_live(registry_state, "sess-ws")

    with client.websocket_connect(
        f"/api/v1/parent/live/stream?session_id=sess-ws&token={access}",
    ) as ws:
        assert ws.receive_bytes() == JPEG


@pytest.mark.asyncio
async def test_ws_rejects_refresh_and_garbage(live_env, registry_state, audit_tape):
    from starlette.websockets import WebSocketDisconnect

    client, _ = _make_client()
    access, refresh = await _parent_tokens()
    assert access != refresh
    _register_live(registry_state, "sess-ws")

    for bad in (f"parent.{refresh}", "parent.garbage-token", "parent."):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                "/api/v1/parent/live/stream?session_id=sess-ws",
                subprotocols=[bad],
            ):
                pass
        assert exc_info.value.code == 4001

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/api/v1/parent/live/stream?session_id=sess-ws"):
            pass
    assert exc_info.value.code == 4001


@pytest.mark.asyncio
async def test_ws_waiting_state_without_frames(live_env, registry_state, audit_tape):
    client, _ = _make_client()
    access, _ = await _parent_tokens()
    _register_live(registry_state, "sess-ws", with_frame=False)

    with client.websocket_connect(
        "/api/v1/parent/live/stream?session_id=sess-ws",
        subprotocols=[f"parent.{access}"],
    ) as ws:
        msg = ws.receive_json()
        assert msg["type"] == "waiting"


@pytest.mark.asyncio
async def test_ws_permission_denied_closes_4003(
    live_env, registry_state, monkeypatch, audit_tape
):
    from starlette.websockets import WebSocketDisconnect

    client, _ = _make_client()
    access, _ = await _parent_tokens()
    _register_live(registry_state, "sess-ws")
    _mock_links(monkeypatch, [{"student_id": "s1", "permissions": {"can_view_live": False}}])
    _mock_study_session(monkeypatch, {"student_id": "s1"})

    with client.websocket_connect(
        "/api/v1/parent/live/stream?session_id=sess-ws",
        subprotocols=[f"parent.{access}"],
    ) as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_text()
        assert exc_info.value.code == 4003


@pytest.mark.asyncio
async def test_ws_student_targeting(live_env, registry_state, monkeypatch, audit_tape):
    client, _ = _make_client()
    access, _ = await _parent_tokens()
    _register_live(registry_state, "sess-live")
    _mock_study_session(monkeypatch, {"student_id": "kid1"}, {
        "kid1": [{"id": "sess-live", "status": "in_progress"}],
    })

    with client.websocket_connect(
        "/api/v1/parent/live/stream?session_id=current&student_id=kid1",
        subprotocols=[f"parent.{access}"],
    ) as ws:
        assert ws.receive_bytes() == JPEG
