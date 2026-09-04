"""Synthetic landmark + telemetry factories (headless simulation).

Extracted from ``FaceEngine.create_synthetic_landmarks`` and
``LocalCVPipeline.generate_mock_telemetry`` so production geometry stays
lean. Original methods remain as thin shims for backward-compat.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional

from deeptutor.services.monitoring.face_engine import FaceLandmarks, Point3D
from deeptutor.services.monitoring.landmarks_codec import landmarks_to_payload


def create_synthetic_landmarks(
    yaw: float = 0.0,
    pitch: float = 0.0,
    roll: float = 0.0,
    eye_open_ratio: float = 0.3,
) -> FaceLandmarks:
    """Generate realistic synthetic 3D landmarks. Angles in degrees."""
    rad_yaw = math.radians(yaw)
    rad_pitch = math.radians(pitch)

    cx, cy = 0.5 + 0.1 * math.sin(rad_yaw), 0.5 + 0.1 * math.sin(rad_pitch)

    ear_h = 0.02 * (eye_open_ratio / 0.3)
    lx, ly = cx - 0.1, cy - 0.08
    rx, ry = cx + 0.1, cy - 0.08

    left_eye = [
        Point3D(lx - 0.03, ly, 0.0),
        Point3D(lx - 0.015, ly - ear_h, 0.0),
        Point3D(lx + 0.015, ly - ear_h, 0.0),
        Point3D(lx + 0.03, ly, 0.0),
        Point3D(lx + 0.015, ly + ear_h, 0.0),
        Point3D(lx - 0.015, ly + ear_h, 0.0),
    ]
    right_eye = [
        Point3D(rx - 0.03, ry, 0.0),
        Point3D(rx - 0.015, ry - ear_h, 0.0),
        Point3D(rx + 0.015, ry - ear_h, 0.0),
        Point3D(rx + 0.03, ry, 0.0),
        Point3D(rx + 0.015, ry + ear_h, 0.0),
        Point3D(rx - 0.015, ry + ear_h, 0.0),
    ]
    mouth = [
        Point3D(cx - 0.04, cy + 0.15, 0.0),
        Point3D(cx, cy + 0.13, 0.0),
        Point3D(cx + 0.04, cy + 0.15, 0.0),
        Point3D(cx, cy + 0.17, 0.0),
    ]
    return FaceLandmarks(
        left_eye=left_eye,
        right_eye=right_eye,
        nose_tip=Point3D(cx, cy, -0.05 * math.cos(rad_yaw)),
        mouth=mouth,
        chin=Point3D(cx, cy + 0.25, 0.0),
        forehead=Point3D(cx, cy - 0.25, 0.0),
        left_cheek=Point3D(cx - 0.2, cy, 0.05 * math.sin(rad_yaw)),
        right_cheek=Point3D(cx + 0.2, cy, -0.05 * math.sin(rad_yaw)),
    )


def generate_mock_telemetry(
    face_engine: Any,
    scenario: str = "normal_study",
    timestamp: Optional[float] = None,
) -> Dict[str, Any]:
    """Generate synthetic telemetry payloads for headless simulation."""
    ts = timestamp if timestamp is not None else time.time()

    def _pack(landmarks: FaceLandmarks, **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "detected": True,
            "confidence": 0.95,
            "brightness": 120.0,
            "landmarks": landmarks_to_payload(landmarks),
            "embedding": face_engine.generate_geometric_embedding(landmarks),
        }
        payload.update(extra)
        return payload

    if scenario == "absent":
        return {"detected": False, "confidence": 0.0, "brightness": 120.0}
    if scenario == "writing_reading":
        lm = create_synthetic_landmarks(yaw=5.0, pitch=35.0)
        return _pack(lm, confidence=0.96, brightness=130.0, writing_gesture=True)
    if scenario == "drinking_water":
        lm = create_synthetic_landmarks(yaw=0.0, pitch=5.0)
        return _pack(lm, confidence=0.95, brightness=125.0, hand_to_mouth_gesture=True)
    if scenario == "looking_away":
        lm = create_synthetic_landmarks(yaw=45.0, pitch=0.0)
        return _pack(lm, confidence=0.92, brightness=120.0)
    if scenario == "phone_usage":
        lm = create_synthetic_landmarks(yaw=0.0, pitch=15.0)
        return _pack(lm, confidence=0.95, brightness=120.0, phone_detected=True)
    if scenario == "static_photo":
        lm = create_synthetic_landmarks(yaw=0.0, pitch=0.0, eye_open_ratio=0.30)
        return _pack(lm, confidence=0.99, brightness=120.0, texture_laplacian_var=25.0)
    if scenario == "identity_mismatch":
        lm = create_synthetic_landmarks(yaw=-10.0, pitch=5.0, roll=15.0)
        alt_emb: List[float] = [-(i % 7 - 3) * 0.1 for i in range(128)]
        return _pack(lm, confidence=0.95, brightness=120.0, embedding=alt_emb)
    # normal_study
    sin_var = 0.05 * math.sin(ts * 3.0)
    lm = create_synthetic_landmarks(
        yaw=sin_var * 5.0,
        pitch=5.0 + sin_var * 2.0,
        eye_open_ratio=0.30 + 0.05 * math.sin(ts * 5.0),
    )
    return _pack(lm, confidence=0.97, brightness=135.0, texture_laplacian_var=180.0)


__all__ = ["create_synthetic_landmarks", "generate_mock_telemetry"]
