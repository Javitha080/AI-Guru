"""Regression: /verify-liveness must accept the bare LandmarkGroups shape.

The browser pre-flight (visionPipeline.takeRecentLandmarkFrames) POSTs bare
landmark groups with no ``detected`` wrapper. The endpoint previously dropped
every such frame ("Insufficient frame sequence"), so production could never
verify green while tests (which use wrapped generate_mock_telemetry) passed.
"""

from __future__ import annotations

import math

from fastapi.testclient import TestClient

from deeptutor.api.main import app
from deeptutor.services.monitoring.cv_pipeline import get_cv_pipeline
from deeptutor.services.monitoring.landmarks_codec import landmarks_to_payload


def _bare_groups_sequence(live: bool):
    pipe = get_cv_pipeline()
    if live:
        lms = []
        for i in range(8):
            eye_r = 0.08 if i in (4, 5) else (0.30 + 0.01 * math.sin(i))
            lms.append(
                pipe.face_engine.create_synthetic_landmarks(
                    yaw=0.2 * math.sin(i), pitch=0.0, eye_open_ratio=eye_r
                )
            )
        return [landmarks_to_payload(lm) for lm in lms]
    lm = pipe.face_engine.create_synthetic_landmarks(
        yaw=0.0, pitch=0.0, eye_open_ratio=0.30
    )
    return [landmarks_to_payload(lm) for _ in range(8)]


def test_verify_liveness_accepts_bare_frontend_groups():
    client = TestClient(app)
    live_bare = _bare_groups_sequence(live=True)
    # Sanity: this is really the bare shape (no wrapper keys).
    assert "detected" not in live_bare[0]
    assert "landmarks" not in live_bare[0]

    resp_live = client.post(
        "/api/v1/monitoring/verify-liveness",
        json={"frames_landmarks": live_bare},
    )
    assert resp_live.status_code == 200
    assert resp_live.json()["is_live"] is True

    resp_static = client.post(
        "/api/v1/monitoring/verify-liveness",
        json={"frames_landmarks": _bare_groups_sequence(live=False)},
    )
    assert resp_static.status_code == 200
    assert resp_static.json()["is_live"] is False


def test_extract_parses_bare_groups_directly():
    pipe = get_cv_pipeline()
    lm = pipe.face_engine.create_synthetic_landmarks()
    bare = landmarks_to_payload(lm)
    parsed = pipe.face_engine.extract_landmarks_from_telemetry(bare)
    assert parsed.landmarks is not None
