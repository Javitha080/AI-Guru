"""Single landmark serialization for the monitoring engine.

Replaces the duplicated ``_landmarks_to_dict`` (cv_pipeline) and
``_landmarks_to_payload`` (system_monitor) helpers with one canonical
dict shape that ``FaceEngine.extract_landmarks_from_telemetry`` parses.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _pts(pts: List[Any]) -> List[Dict[str, float]]:
    return [{"x": float(p.x), "y": float(p.y), "z": float(p.z)} for p in pts]


def landmarks_to_payload(landmarks: Any) -> Optional[Dict[str, Any]]:
    """Serialize FaceLandmarks into the telemetry dict shape."""
    if landmarks is None:
        return None
    return {
        "left_eye": _pts(landmarks.left_eye),
        "right_eye": _pts(landmarks.right_eye),
        "mouth": _pts(landmarks.mouth),
        "all_points": _pts(getattr(landmarks, "all_points", [])),
        "nose_tip": {"x": landmarks.nose_tip.x, "y": landmarks.nose_tip.y, "z": landmarks.nose_tip.z},
        "chin": {"x": landmarks.chin.x, "y": landmarks.chin.y, "z": landmarks.chin.z},
        "forehead": {"x": landmarks.forehead.x, "y": landmarks.forehead.y, "z": landmarks.forehead.z},
        "left_cheek": {"x": landmarks.left_cheek.x, "y": landmarks.left_cheek.y, "z": landmarks.left_cheek.z},
        "right_cheek": {"x": landmarks.right_cheek.x, "y": landmarks.right_cheek.y, "z": landmarks.right_cheek.z},
    }


__all__ = ["landmarks_to_payload"]
