"""User-friendly tests for the landmark serializer.

In plain language: face landmarks (eyes, mouth, nose, chin, …) must survive
a trip through `landmarks_to_payload` with every coordinate intact, because
`FaceEngine.extract_landmarks_from_telemetry` parses exactly this shape back.
A missing key here means silently lost face data downstream.
"""

from __future__ import annotations

from types import SimpleNamespace

from deeptutor.services.monitoring.landmarks_codec import landmarks_to_payload


def _pt(x: float, y: float, z: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(x=x, y=y, z=z)


def _landmarks() -> SimpleNamespace:
    return SimpleNamespace(
        left_eye=[_pt(0.1, 0.2, 0.3), _pt(0.4, 0.5, 0.6)],
        right_eye=[_pt(0.7, 0.8, 0.9)],
        mouth=[_pt(0.0, 0.1, 0.2)],
        all_points=[_pt(1.0, 2.0, 3.0)],
        nose_tip=_pt(0.5, 0.5, 0.1),
        chin=_pt(0.5, 0.9, 0.0),
        forehead=_pt(0.5, 0.1, 0.0),
        left_cheek=_pt(0.2, 0.5, 0.0),
        right_cheek=_pt(0.8, 0.5, 0.0),
    )


def test_none_landmarks_stay_none():
    assert landmarks_to_payload(None) is None


def test_payload_carries_every_landmark_group():
    payload = landmarks_to_payload(_landmarks())
    assert payload is not None
    for group in (
        "left_eye",
        "right_eye",
        "mouth",
        "all_points",
        "nose_tip",
        "chin",
        "forehead",
        "left_cheek",
        "right_cheek",
    ):
        assert group in payload, f"payload dropped landmark group '{group}'"


def test_coordinates_survive_exactly():
    payload = landmarks_to_payload(_landmarks())
    assert payload is not None
    assert payload["left_eye"] == [
        {"x": 0.1, "y": 0.2, "z": 0.3},
        {"x": 0.4, "y": 0.5, "z": 0.6},
    ]
    assert payload["nose_tip"] == {"x": 0.5, "y": 0.5, "z": 0.1}
    assert payload["all_points"] == [{"x": 1.0, "y": 2.0, "z": 3.0}]


def test_payload_values_are_plain_floats():
    """Downstream JSON encoding must never see exotic numeric types."""
    payload = landmarks_to_payload(_landmarks())
    assert payload is not None
    for pt in payload["left_eye"]:
        assert all(type(v) is float for v in pt.values())
