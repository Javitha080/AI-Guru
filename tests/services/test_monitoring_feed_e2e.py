"""End-to-end router tests for the system-camera monitoring mode.

Mocks the hardware layer (synthetic frame source + stub processor) and drives
the REAL FastAPI routes: WS handshake in system mode, telemetry broadcasts,
pause control, snapshot endpoint, and the MJPEG feed generator.

NOTE: the MJPEG body is consumed directly from the StreamingResponse's
body_iterator — this starlette/httpx TestClient generation buffers streaming
bodies until completion, which never happens for an infinite MJPEG stream
(real uvicorn flushes each frame immediately).
"""

import asyncio
import json
from unittest.mock import patch

from fastapi.testclient import TestClient
import numpy as np
import pytest

from deeptutor.api.main import app
from deeptutor.services.monitoring import system_monitor as sm_module
from deeptutor.services.monitoring.pose_gaze import (
    GazeResult,
    HeadPoseResult,
    PostureCategory,
)
from deeptutor.services.monitoring.python_face_processor import (
    FaceFrameResult,
    PythonFaceProcessor,
)
from deeptutor.services.monitoring.system_camera import SystemCameraManager


def _fake_frame() -> np.ndarray:
    return np.full((480, 640, 3), 135, dtype=np.uint8)


class _StubProcessor(PythonFaceProcessor):
    """Behaves like a loaded processor without touching MediaPipe."""

    def __init__(self):  # noqa: D107 - skip heavy init entirely
        self._tick = 0

    @property
    def available(self) -> bool:
        return True

    def reset_session(self):
        pass

    def process_frame(self, frame):
        self._tick += 1
        pose = HeadPoseResult(
            yaw=2.0,
            pitch=3.0,
            roll=0.0,
            posture=PostureCategory.HEAD_CENTER,
            is_facing_screen=True,
            is_reading_writing_pose=False,
        )
        gaze = GazeResult(gaze_x=0.05, gaze_y=0.02, is_focused=True, confidence=0.9)
        return FaceFrameResult(
            detected=True,
            confidence=0.95,
            brightness=0.53,
            landmarks=None,
            raw_landmarks=[(0.5, 0.5, 0.0)] * 478,
            pose=pose,
            gaze=gaze,
            ear=0.30,
            phone_detected=False,
        )

    def draw_overlay(self, frame, result, focus_state="focused", focus_score=None):
        return (frame.astype(np.int16) + 1).clip(0, 255).astype(np.uint8)

    def close(self):
        pass


@pytest.fixture()
def system_env():
    # These E2E feeds serve JPEG bytes, which OpenCV encodes; without it the
    # camera manager can still grab frames but the feed/snapshot cannot.
    pytest.importorskip("cv2")
    processor = _StubProcessor()
    camera = SystemCameraManager(camera_index=0, frame_source=_fake_frame)

    with (
        patch.object(sm_module, "get_python_face_processor", lambda: processor),
        patch.object(sm_module, "get_system_camera", lambda index=0, **kw: camera),
    ):
        yield camera

    # Force-clean any monitors the test created (sync registry).
    for sid in list(sm_module._monitors.keys()):
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(sm_module.stop_system_monitor(sid))
            loop.close()
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture()
def client(system_env):
    with TestClient(app) as c:
        yield c


class TestSystemModeRoutes:
    def test_camera_status_reports_system(self, client):
        res = client.get("/api/v1/monitoring/camera/status")
        assert res.status_code == 200
        data = res.json()
        assert data["mode"] == "system"
        assert data["available"] is True

    def test_ws_handshake_telemetry_and_pause(self, client):
        with client.websocket_connect("/api/v1/monitoring/session/s-feed-e2e") as ws:
            init = json.loads(ws.receive_text())
            assert init["type"] == "session_init"
            assert init["mode"] == "system"

            monitor = sm_module.get_system_monitor("s-feed-e2e")
            assert monitor is not None
            assert monitor.camera.is_running is True

            # Engine telemetry arrives over the socket (type-filtered: pong may
            # interleave with telemetry_update depending on tick timing).
            deadline = 100
            got_update = None
            ws.send_text(json.dumps({"type": "ping"}))
            while deadline > 0 and got_update is None:
                msg = json.loads(ws.receive_text())
                if msg.get("type") == "telemetry_update":
                    got_update = msg
                elif msg.get("type") == "pong":
                    deadline -= 1
            assert got_update is not None
            assert got_update["session_id"] == "s-feed-e2e"
            assert isinstance(got_update["focus_score"], (int, float))
            assert "engagement_trend" in got_update

            # Pause control stops the engine ticks and releases the device.
            ws.send_text(json.dumps({"type": "pause"}))
            for _ in range(60):
                if monitor.paused:
                    break
                import time

                time.sleep(0.05)
            assert monitor.paused is True
            assert monitor.camera.is_running is False

    def test_feed_and_snapshot_without_monitor_404(self, client):
        assert client.get("/api/v1/monitoring/feed/no-such").status_code == 404
        assert client.get("/api/v1/monitoring/snapshot/no-such").status_code == 404

    def test_mjpeg_generator_frames(self, system_env):
        """Consume the feed generator directly and validate MJPEG framing."""
        from deeptutor.api.routers.monitoring import monitoring_feed

        async def run():
            mon = await sm_module.start_system_monitor("s-gen-e2e")
            assert mon is not None
            response = await monitoring_feed("s-gen-e2e", _user=None)
            assert response.media_type.startswith("multipart/x-mixed-replace")

            iterator = response.body_iterator.__aiter__()
            chunk = await asyncio.wait_for(iterator.__anext__(), timeout=10.0)
            assert chunk.startswith(
                b"--aiguruframe\r\nContent-Type: image/jpeg\r\nContent-Length: "
            )
            header_end = chunk.index(b"\r\n\r\n")
            jpeg_start = header_end + 4
            assert chunk[jpeg_start : jpeg_start + 2] == b"\xff\xd8"

            await response.body_iterator.aclose()
            await sm_module.stop_system_monitor("s-gen-e2e")

        asyncio.run(run())

    def test_snapshot_serves_jpeg(self, system_env):
        async def run():
            mon = await sm_module.start_system_monitor("s-snap-e2e")
            assert mon is not None

        asyncio.run(run())

        from deeptutor.api.routers.monitoring import get_camera_snapshot

        response = asyncio.run(get_camera_snapshot("s-snap-e2e", _user=None))
        assert response.status_code == 200
        assert response.media_type == "image/jpeg"
        assert response.body[:2] == b"\xff\xd8"

        asyncio.run(sm_module.stop_system_monitor("s-snap-e2e"))
