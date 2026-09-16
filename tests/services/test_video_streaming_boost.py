"""Unit tests for Video Streaming & VideoGen Boost improvements."""

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from deeptutor.services.monitoring.session_registry import (
    get_live_frame,
    register_session,
    store_live_frame,
    unregister_session,
    wait_for_frame,
)
from deeptutor.services.monitoring.system_camera import SystemCameraManager
from deeptutor.services.videogen.adapters.async_task import AsyncTaskVideogenAdapter
from deeptutor.services.videogen.config import VideogenConfig


@pytest.mark.asyncio
async def test_session_registry_event_notification():
    session_id = "test-sess-boost-1"
    register_session(session_id, MagicMock())

    # Test wait_for_frame receives notification when store_live_frame is called
    async def _producer():
        await asyncio.sleep(0.05)
        store_live_frame(session_id, "dGVzdC1mcmFtZQ==", time.time())

    prod_task = asyncio.create_task(_producer())
    notified = await wait_for_frame(session_id, timeout=1.0)
    await prod_task

    assert notified is True
    frame = get_live_frame(session_id)
    assert frame is not None
    assert frame[0] == "dGVzdC1mcmFtZQ=="

    unregister_session(session_id)


@pytest.mark.asyncio
async def test_session_registry_wait_for_frame_timeout():
    session_id = "test-sess-boost-2"
    register_session(session_id, MagicMock())

    # Wait for frame with short timeout without any notification
    t0 = time.perf_counter()
    notified = await wait_for_frame(session_id, timeout=0.08)
    elapsed = time.perf_counter() - t0

    assert notified is False
    assert elapsed >= 0.07

    unregister_session(session_id)


def test_system_camera_preencoded_caching():
    cam = SystemCameraManager(camera_index=99)
    assert cam.raw_quality == 80

    # Inject pre-encoded annotated frame
    fake_jpeg = b"\xff\xd8\xff\xe0FAKE_ANNOTATED"
    now = time.time()
    cam.update_annotated_jpeg(fake_jpeg, now)

    # Frame cache should return pre-encoded bytes directly
    assert cam.get_annotated_jpeg() == fake_jpeg


def test_videogen_payload_and_extraction():
    config = VideogenConfig(
        model="seedance-v1",
        aspect_ratio="16:9",
        duration="5",
        resolution="720p",
        fps="30",
        seed=42,
    )
    payload = AsyncTaskVideogenAdapter._build_submit_payload("A running cheetah", config)
    assert payload["model"] == "seedance-v1"
    assert "--ratio 16:9" in payload["content"][0]["text"]
    assert "--fps 30" in payload["content"][0]["text"]
    assert "--seed 42" in payload["content"][0]["text"]
    assert payload["aspect_ratio"] == "16:9"
    assert payload["fps"] == "30"
    assert payload["seed"] == 42


def test_videogen_extract_status_multi_formats():
    # Format 1: Volcengine content video_url
    resp1 = MagicMock()
    resp1.json.return_value = {
        "status": "succeeded",
        "content": {"video_url": "https://cdn.example.com/video1.mp4"},
    }
    st1, url1, err1 = AsyncTaskVideogenAdapter._extract_status(resp1)
    assert st1 == "succeeded"
    assert url1 == "https://cdn.example.com/video1.mp4"
    assert err1 == ""

    # Format 2: Output array (Replicate / standard task format)
    resp2 = MagicMock()
    resp2.json.return_value = {
        "status": "completed",
        "output": ["https://cdn.example.com/output_clip.mp4"],
    }
    st2, url2, err2 = AsyncTaskVideogenAdapter._extract_status(resp2)
    assert st2 == "completed"
    assert url2 == "https://cdn.example.com/output_clip.mp4"

    # Format 3: Nested data videos list
    resp3 = MagicMock()
    resp3.json.return_value = {
        "status": "done",
        "data": {"videos": [{"url": "https://cdn.example.com/nested.mp4"}]},
    }
    st3, url3, err3 = AsyncTaskVideogenAdapter._extract_status(resp3)
    assert st3 == "done"
    assert url3 == "https://cdn.example.com/nested.mp4"
