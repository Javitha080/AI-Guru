"""Tests for the system-level camera driver (SystemCameraManager).

Uses injected synthetic frame sources so no physical webcam is required.
"""

import time

import numpy as np

from deeptutor.services.monitoring.system_camera import (
    SystemCameraManager,
    get_system_camera,
    release_system_camera,
)


def _make_frame(value: int = 100) -> np.ndarray:
    return np.full((480, 640, 3), value, dtype=np.uint8)


class TestSystemCameraLifecycle:
    def test_start_grabs_frames_from_source(self):
        counter = {"n": 0}

        def source():
            counter["n"] += 1
            return _make_frame(counter["n"] % 255)

        cam = SystemCameraManager(frame_source=source)
        assert cam.available is True
        assert cam.start() is True
        try:
            deadline = time.time() + 2.0
            while time.time() < deadline and cam.get_latest_frame() is None:
                time.sleep(0.02)
            frame = cam.get_latest_frame()
            assert frame is not None
            assert frame.shape == (480, 640, 3)
            assert counter["n"] > 0
        finally:
            cam.stop()

    def test_stop_is_idempotent_and_clears_buffers(self):
        cam = SystemCameraManager(frame_source=lambda: _make_frame())
        assert cam.start() is True
        time.sleep(0.15)
        assert cam.is_running is True
        cam.stop()
        cam.stop()  # second call must not raise
        assert cam.is_running is False
        assert cam.get_latest_frame() is None
        assert cam.get_raw_jpeg() is None

    def test_raw_and_annotated_jpeg_encoding(self):
        cam = SystemCameraManager(frame_source=lambda: _make_frame(90))
        cam.start()
        try:
            deadline = time.time() + 2.0
            while time.time() < deadline and cam.get_latest_frame() is None:
                time.sleep(0.02)
            raw = cam.get_raw_jpeg()
            assert raw is not None and len(raw) > 100
            assert raw[:2] == b"\xff\xd8"  # JPEG SOI marker

            # No annotator yet → annotated equals raw encoding of same frame.
            annotated = cam.get_annotated_jpeg()
            assert annotated is not None and len(annotated) > 100

            cam.set_annotator(lambda f: f.copy())
            time.sleep(0.1)
            assert cam.get_annotated_jpeg() is not None
        finally:
            cam.stop()

    def test_failing_source_reports_error_and_stops(self):
        def bad_source():
            return None

        cam = SystemCameraManager(frame_source=bad_source)
        cam._MAX_CONSECUTIVE_FAILURES = 5  # shrink for a fast test
        assert cam.start() is True
        deadline = time.time() + 3.0
        while time.time() < deadline and cam.is_running:
            time.sleep(0.05)
        assert cam.is_running is False
        assert "frames" in cam.last_error.lower()

    def test_registry_singleton_per_index(self):
        a = get_system_camera(3, frame_source=lambda: _make_frame())
        b = get_system_camera(3, frame_source=lambda: _make_frame())
        assert a is b
        release_system_camera(3)
        c = get_system_camera(3, frame_source=lambda: _make_frame())
        assert c is not a
        release_system_camera(3)

    def test_get_latest_frame_returns_copy(self):
        cam = SystemCameraManager(frame_source=lambda: _make_frame(7))
        cam.start()
        try:
            deadline = time.time() + 2.0
            while time.time() < deadline and cam.get_latest_frame() is None:
                time.sleep(0.02)
            f1 = cam.get_latest_frame()
            assert f1 is not None
            f1[:] = 0
            f2 = cam.get_latest_frame()
            assert f2 is not None and f2.mean() > 0
        finally:
            cam.stop()
