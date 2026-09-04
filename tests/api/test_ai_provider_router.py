"""
Tests for AI Guru AI Provider & Tutoring Mode API Router.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from deeptutor.api.main import app

client = TestClient(app)


def test_get_ai_provider_status() -> None:
    resp = client.get("/api/v1/ai-provider/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "mode" in data
    assert "active_provider" in data
    assert "hardware_profile" in data
    assert "cloud" in data
    assert "ollama" in data
    assert "offline" in data


def test_set_ai_tutoring_mode() -> None:
    # Set to offline
    resp = client.post("/api/v1/ai-provider/mode", json={"mode": "offline"})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "offline"

    # Set back to auto
    resp2 = client.post("/api/v1/ai-provider/mode", json={"mode": "auto"})
    assert resp2.status_code == 200
    assert resp2.json()["mode"] == "auto"


def test_get_hardware_profile_endpoint() -> None:
    resp = client.get("/api/v1/ai-provider/hardware-profile")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tier"] in {"LOW", "MEDIUM", "HIGH"}
    assert "recommended_models" in data
    assert "vram_gb" in data
    assert "cpu_cores_physical" in data


def test_get_governor_status_endpoint() -> None:
    resp = client.get("/api/v1/ai-provider/governor")
    assert resp.status_code == 200
    data = resp.json()
    assert "cpu_percent" in data
    assert "ram_percent" in data
    assert "is_overloaded" in data
    assert "recommended_cv_fps" in data
    assert data["recommended_cv_fps"] >= 1


def test_key_vault_endpoints() -> None:
    # 1. List keys
    list_resp = client.get("/api/v1/ai-provider/keys")
    assert list_resp.status_code == 200
    assert "keys" in list_resp.json()

    # 2. Save a test key
    save_resp = client.post(
        "/api/v1/ai-provider/keys",
        json={"provider": "test_provider", "api_key": "sk-proj-testkey1234567890"},
    )
    assert save_resp.status_code == 200
    save_data = save_resp.json()
    assert save_data["status"] == "success"
    assert save_data["provider"] == "test_provider"
    assert "masked_key" in save_data
    assert "testkey" not in save_data["masked_key"]

    # 3. Verify key is in list (masked)
    list_resp2 = client.get("/api/v1/ai-provider/keys")
    assert list_resp2.status_code == 200
    keys = list_resp2.json()["keys"]
    assert "test_provider" in keys
    assert "..." in keys["test_provider"]

    # 4. Delete key
    del_resp = client.delete("/api/v1/ai-provider/keys/test_provider")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "success"

    # 5. Delete non-existent key returns 404
    del_resp404 = client.delete("/api/v1/ai-provider/keys/non_existent_key_xyz")
    assert del_resp404.status_code == 404
