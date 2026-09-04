"""Pure vision solvers extracted from PythonFaceProcessor.

EAR, SolvePnP head-pose, and iris-gaze live here as stateless functions so
the processor class stays a thin lifecycle + orchestration facade.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np

from deeptutor.services.monitoring.pose_gaze import (
    GazeResult,
    HeadPoseResult,
    PoseGazeEstimator,
)

LEFT_IRIS_IDX = 468
RIGHT_IRIS_IDX = 473


def compute_ear(raw: List[Tuple[float, float, float]]) -> float:
    def eye_ratio(ca: int, cb: int, ta: int, ba: int, tb: int, bb: int) -> float:
        pa, pb = raw[ca], raw[cb]
        width = math.dist(pa[:2], pb[:2])
        if width < 1e-9:
            return 0.0
        v1 = math.dist(raw[ta][:2], raw[ba][:2])
        v2 = math.dist(raw[tb][:2], raw[bb][:2])
        return (v1 + v2) / (2.0 * width)

    try:
        left = eye_ratio(33, 133, 159, 145, 158, 153)
        right = eye_ratio(263, 362, 386, 374, 385, 380)
        return round((left + right) / 2.0, 4)
    except IndexError:
        return 0.0


def solve_pnp_angles(
    raw: List[Tuple[float, float, float]],
    w: int,
    h: int,
    model_points: np.ndarray,
    image_idx: List[int],
    flip_x: np.ndarray,
    pitch_sign: float,
) -> Tuple[float, float, float]:
    """Solve head-pose angles via cv2.solvePnP (no neutral calibration)."""
    import cv2  # lazy: processor guards availability

    image_pts = np.array(
        [(raw[i][0] * w, raw[i][1] * h) for i in image_idx],
        dtype=np.float64,
    )
    focal = float(w)
    cam_matrix = np.array(
        [[focal, 0.0, w / 2.0], [0.0, focal, h / 2.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    dist_coeffs = np.zeros((4, 1), dtype=np.float64)
    ok, rvec, _ = cv2.solvePnP(
        model_points, image_pts, cam_matrix, dist_coeffs, flags=cv2.SOLVEPNP_ITERATIVE
    )
    if not ok:
        return 0.0, 0.0, 0.0
    rmat, _ = cv2.Rodrigues(rvec)
    m = flip_x @ rmat
    yaw = -math.degrees(math.atan2(-m[2][0], m[2][2]))
    pitch = pitch_sign * math.degrees(math.asin(max(-1.0, min(1.0, float(m[2][1])))))
    roll = math.degrees(math.atan2(-m[0][1], m[1][1]))
    return yaw, pitch, roll


def build_head_pose(yaw: float, pitch: float, roll: float) -> HeadPoseResult:
    posture, is_facing, is_rw = PoseGazeEstimator.classify(yaw, pitch, roll)
    return HeadPoseResult(
        yaw=round(yaw, 1),
        pitch=round(pitch, 1),
        roll=round(roll, 1),
        posture=posture,
        is_facing_screen=is_facing,
        is_reading_writing_pose=is_rw,
    )


def build_gaze(raw: List[Tuple[float, float, float]], pose: HeadPoseResult) -> GazeResult:
    iris_dx = iris_dy = 0.0
    try:
        l_mid = ((raw[33][0] + raw[133][0]) / 2.0, (raw[33][1] + raw[133][1]) / 2.0)
        r_mid = ((raw[263][0] + raw[362][0]) / 2.0, (raw[263][1] + raw[362][1]) / 2.0)
        l_w = max(1e-6, abs(raw[133][0] - raw[33][0]))
        r_w = max(1e-6, abs(raw[362][0] - raw[263][0]))
        iris_dx = (
            (raw[LEFT_IRIS_IDX][0] - l_mid[0]) / l_w
            + (raw[RIGHT_IRIS_IDX][0] - r_mid[0]) / r_w
        ) / 2.0
        l_h = max(1e-6, abs(raw[159][1] - raw[145][1]) + abs(raw[158][1] - raw[153][1]))
        iris_dy = (raw[LEFT_IRIS_IDX][1] - l_mid[1]) / l_h
    except IndexError:
        iris_dx = iris_dy = 0.0
    gaze_x = max(-1.0, min(1.0, (pose.yaw / 45.0) * 0.75 + iris_dx * 1.5))
    gaze_y = max(-1.0, min(1.0, (pose.pitch / 40.0) * 0.75 + iris_dy * 1.5))
    is_focused = abs(gaze_x) <= 0.55 and gaze_y <= 0.62
    return GazeResult(
        gaze_x=round(gaze_x, 3),
        gaze_y=round(gaze_y, 3),
        is_focused=is_focused,
        confidence=0.90 if is_focused else 0.85,
    )


__all__ = ["compute_ear", "solve_pnp_angles", "build_head_pose", "build_gaze"]
