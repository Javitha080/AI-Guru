"""Tests for the Python face processor (MediaPipe + solvePnP head pose).

The head-pose round-trip is validated WITHOUT MediaPipe inference: canonical
model points are projected through a synthetic pinhole rig at known backend-
convention angles, then recovered through the exact production code path.
"""

import math

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from deeptutor.services.monitoring.pose_gaze import PoseGazeEstimator, PostureCategory  # noqa: E402
from deeptutor.services.monitoring.python_face_processor import (  # noqa: E402
    _PNP_IMAGE_IDX,
    _PNP_MODEL_POINTS,
    FaceFrameResult,
    PythonFaceProcessor,
)


def _rot(axis: str, deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    if axis == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)
    if axis == "y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)


_FLIP_X = np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1]], dtype=np.float64)


def _project(yaw: float, pitch: float, roll: float, w: int = 640):
    """Project the canonical model rotated by backend-convention angles.

    Mirrors the ground-truth rig used to calibrate the sign conversion:
    model rotation Rz(roll)·Rx(−pitch)·Ry(−yaw), camera-frame flip Rx(π).
    """
    r_pose = _rot("z", roll) @ _rot("x", -pitch) @ _rot("y", -yaw)
    rvec, _ = cv2.Rodrigues(_FLIP_X @ r_pose)
    focal = float(w)
    cam = np.array([[focal, 0, w / 2], [0, focal, w / 2], [0, 0, 1]], dtype=np.float64)
    tvec = np.array([[0.0], [0.0], [900.0]])
    pts, _ = cv2.projectPoints(_PNP_MODEL_POINTS, rvec, tvec, cam, np.zeros((4, 1)))
    # Normalize into raw-landmark space ([0..1]) and scatter the six anchors
    # into their real positions of the 478-landmark array.
    raw = [(0.0, 0.0, 0.0)] * 478
    for idx, (x, y) in zip(_PNP_IMAGE_IDX, pts.reshape(-1, 2)):
        raw[idx] = (float(x) / w, float(y) / w, 0.0)
    return raw


def _recover(processor: PythonFaceProcessor, raw_landmarks, w=640):
    """Run the production solvePnP path with neutral calibration bypassed.

    A square frame keeps the synthetic rig's principal point identical to the
    production reconstruction (cy = h/2 must equal the projection's w/2).
    """
    processor._neutral = None
    processor._neutral_samples.clear()
    return processor._head_pose_from_pnp(raw_landmarks, w, w)


@pytest.fixture()
def processor():
    p = PythonFaceProcessor(enable_object_detection=False)
    yield p


class TestSolvePnPHeadPose:
    def test_round_trip_exact(self, processor):
        cases = [
            (0.0, 0.0, 0.0),
            (25.0, 0.0, 0.0),
            (-25.0, 0.0, 0.0),
            (0.0, 30.0, 0.0),
            (0.0, -30.0, 0.0),
            (0.0, 0.0, 15.0),
            (15.0, 10.0, -8.0),
            (-40.0, -20.0, 12.0),
        ]
        for yaw, pitch, roll in cases:
            raw = _project(yaw, pitch, roll)
            gy, gp, gr = _recover(processor, raw)
            assert abs(gy - yaw) < 1.5, f"yaw {gy} != {yaw}"
            assert abs(gp - pitch) < 1.5, f"pitch {gp} != {pitch}"
            assert abs(gr - roll) < 1.5, f"roll {gr} != {roll}"

    def test_yaw_sign_matches_backend_convention(self, processor):
        right = _recover(processor, _project(30.0, 0.0, 0.0))[0]
        left = _recover(processor, _project(-30.0, 0.0, 0.0))[0]
        assert right > 20 and left < -20

    def test_pitch_sign_look_down_positive(self, processor):
        down = _recover(processor, _project(0.0, 35.0, 0.0))[1]
        up = _recover(processor, _project(0.0, -25.0, 0.0))[1]
        assert down > 25 and up < -15


class TestClassifySharedThresholds:
    def test_classify_center(self):
        posture, facing, reading = PoseGazeEstimator.classify(0.0, 0.0, 0.0)
        assert posture == PostureCategory.HEAD_CENTER and facing and not reading

    def test_classify_reading_down(self):
        posture, _, reading = PoseGazeEstimator.classify(5.0, 35.0, 0.0)
        assert posture == PostureCategory.LOOKING_DOWN and reading

    def test_classify_looking_right(self):
        posture, facing, reading = PoseGazeEstimator.classify(40.0, 0.0, 0.0)
        assert posture == PostureCategory.LOOKING_RIGHT and not facing and not reading


class TestOverlayPainter:
    def test_draw_overlay_paints_border_and_hud(self, processor):
        frame = np.full((480, 640, 3), 120, np.uint8)
        result = FaceFrameResult()
        annotated = processor.draw_overlay(frame, result, focus_state="focused", focus_score=90.0)
        assert annotated.shape == frame.shape
        assert not np.array_equal(annotated, frame)

    def test_draw_overlay_with_mesh_points(self, processor):
        frame = np.full((480, 640, 3), 120, np.uint8)
        result = FaceFrameResult(detected=True, raw_landmarks=[(0.5, 0.5, 0.0)] * 478)
        annotated = processor.draw_overlay(frame, result, focus_state="distracted", focus_score=12.0)
        assert annotated.shape == frame.shape
        assert not np.array_equal(annotated, frame)

    def test_process_frame_handles_blank_frame(self, processor):
        if not processor.available:
            pytest.skip("MediaPipe/models unavailable in this environment")
        try:
            frame = np.full((480, 640, 3), 120, np.uint8)
            result = processor.process_frame(frame)
            assert result.detected is False
            assert 0.0 <= result.brightness <= 1.0
        finally:
            processor.close()
