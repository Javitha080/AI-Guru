"""HTTP + pipeline regression tests for photo-upload identity enrollment.

Covers the class of bugs where a face baseline could be silently replaced,
unreadable uploads raised 500s instead of honest 422s, SFace neural vectors
were judged against the geometric cosine cut, and cadence-gated ticks with no
neural embedding scored cross-space mismatches that flagged genuine students.
"""

from __future__ import annotations

import io

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import monitoring_core
from deeptutor.services.monitoring.cv_pipeline import get_cv_pipeline
from deeptutor.services.monitoring.face_engine import FaceEngine
from deeptutor.services.monitoring.face_identity import SFACE_COSINE_THRESHOLD


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Monitoring router over an isolated temp dir (no real DB writes)."""
    from deeptutor.services.monitoring.cv_pipeline import LocalCVPipeline

    class _FakePaths:
        user_dir = tmp_path

    monkeypatch.setattr(
        "deeptutor.services.path_service.get_path_service", lambda: _FakePaths()
    )

    async def _fake_persist(pipeline, embedding, mode):
        return True

    monkeypatch.setattr(monitoring_core, "_persist_baseline", _fake_persist)

    async def _no_baseline(db_path):
        return None

    monkeypatch.setattr(
        "deeptutor.services.monitoring.identity_store.load_baseline", _no_baseline
    )
    # Deterministic geometric path (CI has no SFace model; local runs may).
    monkeypatch.setattr(LocalCVPipeline, "sface_available", False)

    pipe = get_cv_pipeline()
    pipe.clear_identity_baseline()

    app = FastAPI()
    app.include_router(monitoring_core.router, prefix="/api/v1/monitoring")
    with TestClient(app) as http:
        yield http
    pipe.clear_identity_baseline()


def _jpeg_bytes(size: int = 200, seed: int = 7) -> bytes:
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    rng = np.random.default_rng(seed)
    img = (rng.random((size, size, 3)) * 255).astype("uint8")
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return bytes(buf.tobytes())


def _groups_dict():
    pipe = get_cv_pipeline()
    lm = pipe.face_engine.create_synthetic_landmarks()
    pt = lambda p: {"x": p.x, "y": p.y, "z": p.z}  # noqa: E731
    return {
        "left_eye": [pt(p) for p in lm.left_eye],
        "right_eye": [pt(p) for p in lm.right_eye],
        "mouth": [pt(p) for p in lm.mouth],
        "all_points": [pt(p) for p in lm.all_points],
        "nose_tip": pt(lm.nose_tip),
        "chin": pt(lm.chin),
        "forehead": pt(lm.forehead),
        "left_cheek": pt(lm.left_cheek),
        "right_cheek": pt(lm.right_cheek),
    }


def _mock_processor(monkeypatch, brightness: float = 0.5):
    from deeptutor.services.monitoring.python_face_processor import FaceFrameResult

    pipe = get_cv_pipeline()
    lm = pipe.face_engine.create_synthetic_landmarks()
    raw = [(p.x, p.y, p.z) for p in lm.all_points]
    while len(raw) < 478:
        raw.append((0.5, 0.5, 0.0))

    class _FakeProcessor:
        available = True

        def process_frame(self, frame):
            return FaceFrameResult(
                detected=True,
                confidence=0.95,
                brightness=brightness,
                landmarks=lm,
                raw_landmarks=list(raw),
                head_angles_raw=(0.0, 0.0, 0.0),
            )

    monkeypatch.setattr(
        "deeptutor.services.monitoring.python_face_processor.get_python_face_processor",
        lambda: _FakeProcessor(),
    )


def test_identity_status_unenrolled(client):
    res = client.get("/api/v1/monitoring/identity-status")
    assert res.status_code == 200
    body = res.json()
    assert body["enrolled"] is False
    assert body["identity_mode"] == "unenrolled"


def test_enroll_photo_rejects_garbage(client):
    res = client.post(
        "/api/v1/monitoring/enroll-from-photo",
        files={"photo": ("tiny.jpg", b"not-a-photo", "image/jpeg")},
    )
    assert res.status_code == 422


def test_enroll_photo_rejects_non_image_bytes(client):
    res = client.post(
        "/api/v1/monitoring/enroll-from-photo",
        files={"photo": ("blob.bin", b"\x00" * 6000, "application/octet-stream")},
    )
    assert res.status_code in (422, 413)


def test_verify_identity_without_baseline(client):
    res = client.post("/api/v1/monitoring/verify-identity", json={"landmarks": _groups_dict()})
    assert res.status_code == 200
    body = res.json()
    assert body["enrolled"] is False
    assert body["match"] is None


def test_verify_identity_rejects_empty_payload(client):
    groups = _groups_dict()
    assert client.post("/api/v1/monitoring/enroll-face", json={"landmarks": groups}).status_code == 200
    res = client.post("/api/v1/monitoring/verify-identity", json={})
    assert res.status_code == 422


def test_enroll_photo_success_and_gate(client, monkeypatch):
    _mock_processor(monkeypatch)
    first = client.post(
        "/api/v1/monitoring/enroll-from-photo",
        files={"photo": ("face.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["enrolled"] is True
    assert body["dimension"] > 0

    st = client.get("/api/v1/monitoring/identity-status").json()
    assert st["enrolled"] is True

    # Second upload without force must NOT replace the baseline.
    second = client.post(
        "/api/v1/monitoring/enroll-from-photo",
        files={"photo": ("other.jpg", _jpeg_bytes(seed=9), "image/jpeg")},
    )
    assert second.status_code == 200
    assert second.json()["already_enrolled"] is True
    assert second.json()["enrolled"] is False

    # Force replaces.
    third = client.post(
        "/api/v1/monitoring/enroll-from-photo?force=true",
        files={"photo": ("other.jpg", _jpeg_bytes(seed=9), "image/jpeg")},
    )
    assert third.json()["enrolled"] is True


def test_verify_identity_match_after_enroll(client):
    groups = _groups_dict()
    res = client.post(
        "/api/v1/monitoring/enroll-face",
        json={"landmarks": groups, "student_id": "student-primary"},
    )
    assert res.status_code == 200, res.text

    check = client.post("/api/v1/monitoring/verify-identity", json={"landmarks": groups})
    assert check.status_code == 200
    body = check.json()
    assert body["enrolled"] is True
    assert body["match"] is True
    assert body["similarity"] >= 0.99


def test_delete_clears_baseline(client):
    groups = _groups_dict()
    assert client.post("/api/v1/monitoring/enroll-face", json={"landmarks": groups}).status_code == 200
    assert client.get("/api/v1/monitoring/identity-status").json()["enrolled"] is True
    assert client.delete("/api/v1/monitoring/identity-baseline").status_code == 200
    assert client.get("/api/v1/monitoring/identity-status").json()["enrolled"] is False


def test_sface_threshold_differs_from_geometric():
    engine = FaceEngine()
    # Cosine 0.5: genuine on the SFace scale, mismatch on the geometric cut.
    cur = [1.0, 0.0] + [0.0] * 14
    base = [0.5, 0.8660254] + [0.0] * 14
    match_sface, sim = engine.verify_identity(cur, base, threshold=SFACE_COSINE_THRESHOLD)
    assert match_sface is True
    assert sim == pytest.approx(0.5, abs=0.01)
    match_geo, _ = engine.verify_identity(cur, base)
    assert match_geo is False


def test_cross_mode_frame_holds_verdict():
    pipe = get_cv_pipeline()
    pipe.clear_identity_baseline()
    try:
        # Neural baseline, then a tick with only a geometric vector
        # (cadence-gated / turned head): must hold, never false-mismatch.
        pipe.enroll_student_baseline([1.0] * 128, identity_mode="sface")
        payload = {
            "detected": True,
            "confidence": 0.95,
            "brightness": 0.5,
            "landmarks": _groups_dict(),
        }
        out = pipe.process_telemetry_payload(payload, current_time=1000.0)
        assert out.identity_matched is True
    finally:
        pipe.clear_identity_baseline()
        pipe.reset_session()
