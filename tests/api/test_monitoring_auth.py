"""Auth-gate regression tests for the monitoring REST surface.

The router is mounted WITHOUT a router-level auth dependency, so every REST
endpoint must carry ``Depends(require_auth)`` itself. These tests prove the
four engine endpoints (enroll-face / verify-liveness / analyze-frame / status)
reject anonymous callers when AUTH_ENABLED=true — previously they were wide
open even in hardened deployments.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import auth as auth_router_module
from deeptutor.api.routers import monitoring


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setattr(auth_router_module, "AUTH_ENABLED", True)
    application = FastAPI()
    application.include_router(monitoring.router, prefix="/api/v1/monitoring")
    return application


def test_engine_endpoints_reject_anonymous_callers(app):
    client = TestClient(app)

    assert client.post("/api/v1/monitoring/enroll-face", json={}).status_code == 401
    assert (
        client.post(
            "/api/v1/monitoring/verify-liveness", json={"frames_landmarks": []}
        ).status_code
        == 401
    )
    assert client.post("/api/v1/monitoring/analyze-frame", json={}).status_code == 401
    assert client.get("/api/v1/monitoring/status").status_code == 401


def test_live_endpoints_still_gate_too(app):
    client = TestClient(app)
    assert (
        client.post(
            "/api/v1/monitoring/live/consent?session_id=x", json={"enabled": True}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/monitoring/live/frame?session_id=x", json={"jpeg_b64": "x" * 64}
        ).status_code
        == 401
    )


def test_gates_lift_when_auth_disabled(monkeypatch):
    """Default local mode (auth off): engine endpoints must stay reachable."""
    monkeypatch.setattr(auth_router_module, "AUTH_ENABLED", False)
    application = FastAPI()
    application.include_router(monitoring.router, prefix="/api/v1/monitoring")
    client = TestClient(application)

    res = client.get("/api/v1/monitoring/status")
    assert res.status_code == 200
