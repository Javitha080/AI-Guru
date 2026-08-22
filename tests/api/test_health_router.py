"""
Tests for AI Guru Health API Router.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from deeptutor.api.main import app

client = TestClient(app)


def test_root_welcome_message() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"message": "Welcome to AI Guru API"}


def test_health_endpoint() -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "timestamp" in data
    assert "subsystems" in data
    assert "database" in data["subsystems"]
    assert "backend" in data["subsystems"]
    assert "gpu" in data["subsystems"]


def test_health_ping_endpoint() -> None:
    resp = client.get("/api/v1/health/ping")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_subroutes() -> None:
    db_resp = client.get("/api/v1/health/database")
    assert db_resp.status_code == 200
    assert "status" in db_resp.json()

    ai_resp = client.get("/api/v1/health/ai")
    assert ai_resp.status_code == 200
    assert "ai_provider" in ai_resp.json()
    assert "ollama" in ai_resp.json()

    gpu_resp = client.get("/api/v1/health/gpu")
    assert gpu_resp.status_code == 200
    assert "hardware_tier" in gpu_resp.json()
