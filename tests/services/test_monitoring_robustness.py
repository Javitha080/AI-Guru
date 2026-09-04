"""
Robustness regression tests for AI student monitor hardening (Phase 0/1).

Covers P0 crash/poison risks:
- per-session pipeline isolation (no global singleton share)
- transient probe must not release active camera
- fail-closed parsing (malformed telemetry never crashes, never fake-focused)
- identity fail-closed when embedding missing
- non-blocking stop + robust broadcast
"""

from __future__ import annotations

import asyncio
import time

import pytest


class TestPerSessionPipelineIsolation:
    def test_fresh_pipelines_are_independent(self):
        from deeptutor.services.monitoring.cv_pipeline import LocalCVPipeline

        a = LocalCVPipeline()
        b = LocalCVPipeline()
        assert a is not b
        assert a.state_machine is not b.state_machine
        assert a.warning_manager is not b.warning_manager
        assert a.liveness_detector is not b.liveness_detector

        # Resetting one must not touch the other.
        a.reset_session()
        a._frame_count = 99
        b.reset_session()
        assert b._frame_count == 0
        assert a._frame_count == 99

    def test_start_system_monitor_does_not_reuse_global_singleton(self):
        """start_system_monitor(pipeline=None) must create a fresh pipeline.

        Before fix it used the process-global via get_cv_pipeline() as the
        live pipeline, so two sessions corrupted each other's
        hysteresis/cooldowns. Baseline inheritance via get_enrolled_face is
        allowed; using the singleton AS the session pipeline is not.
        """
        import deeptutor.services.monitoring.system_monitor as sm

        created = []

        real_cls = sm.LocalCVPipeline

        class TrackingPipeline(real_cls):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created.append(self)

        old = sm.LocalCVPipeline
        sm.LocalCVPipeline = TrackingPipeline  # type: ignore[assignment]
        try:
            import inspect

            src = inspect.getsource(sm.start_system_monitor)
            # Desired: fresh LocalCVPipeline() when pipeline is None,
            # never get_cv_pipeline() singleton share.
            assert "LocalCVPipeline()" in src, "must construct fresh pipeline per session"
            assert "or get_cv_pipeline()" not in src, "must not use singleton as session pipeline"
            assert "pipe = pipeline or" not in src, "must not share global singleton"
        finally:
            sm.LocalCVPipeline = old


class TestTransientProbeSafety:
    def test_probe_finally_must_guard_active_monitors(self):
        import inspect

        from deeptutor.api.routers import monitoring_camera as mc

        src = inspect.getsource(mc._probe_camera_frame)
        # The transient branch must not blindly release the registry device
        # while another session is actively monitoring.
        assert "active_system_monitors" in src
        # After fix the unconditional release_system_camera in the transient
        # finally must be guarded (only when no active monitors).
        has_guard = (
            "release_system_camera" in src
            and ("if not active_system_monitors()" in src or "if len(active_system_monitors()" in src)
        )
        assert has_guard, "transient probe must guard release when monitors active"


class TestFailClosedParsing:
    def test_malformed_landmark_dicts_do_not_crash(self):
        from deeptutor.services.monitoring.face_engine import FaceEngine

        eng = FaceEngine()
        payloads = [
            {"detected": True, "confidence": 0.95, "brightness": 0.5,
             "landmarks": {"nose_tip": {}, "chin": None, "left_eye": [{}]}},
            {"detected": True, "confidence": "high", "brightness": "bright",
             "landmarks": {"nose_tip": {"x": "a"}, "left_eye": "notalist"}},
            {"detected": True, "bbox": [0.1], "landmarks": {}},
            {"detected": True, "confidence": float("inf"), "brightness": float("nan")},
        ]
        for p in payloads:
            res = None
            try:
                res = eng.extract_landmarks_from_telemetry(p)  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001
                pytest.fail(f"extract_landmarks raised on malformed payload {p!r}: {exc}")
            assert res is not None and isinstance(res.detected, bool)

    def test_schema_defaults_are_fail_closed(self):
        from deeptutor.services.monitoring.schemas import build_gaze_result, build_pose_result

        pose = build_pose_result({})
        gaze = build_gaze_result({})
        # Missing keys must NOT look focused/facing (fail-closed, not fail-open).
        assert pose.is_facing_screen is False
        assert pose.is_reading_writing_pose is False
        assert gaze.is_focused is False

    def test_identity_fail_closed_when_no_embedding(self):
        from deeptutor.services.monitoring.cv_pipeline import LocalCVPipeline

        pipe = LocalCVPipeline()
        pipe.reset_session()
        # Enroll a baseline so mismatch is meaningful.
        lm = pipe.face_engine.create_synthetic_landmarks()
        emb = pipe.face_engine.generate_geometric_embedding(lm)
        pipe.enroll_student_baseline(emb)

        # Face claimed detected but no landmarks and no embedding:
        # must NOT report matched=True sim=1.0 (spoof bypass).
        res = pipe.process_telemetry_payload(
            {"detected": True, "confidence": 0.99, "brightness": 0.5},
            current_time=1000.0,
        )
        assert res.identity_matched is False
        assert res.identity_similarity == 0.0


class TestNonBlockingStopAndBroadcast:
    @pytest.mark.asyncio
    async def test_stop_completes_fast_even_if_camera_blocks(self):
        from deeptutor.services.monitoring.system_monitor import SystemMonitorSession

        class SlowCamera:
            last_error = ""

            def set_annotator(self, fn):
                pass

            def start(self):
                return True

            def stop(self):
                time.sleep(3.0)

            def get_latest_frame(self):
                return None

        class NoopProcessor:
            def reset_session(self):
                pass

        sess = SystemMonitorSession(
            session_id="s-stop-test", camera=SlowCamera(), processor=NoopProcessor()  # type: ignore[arg-type]
        )
        sess._running = True
        # Loop must stay responsive while camera.stop() (3s join) runs:
        # a 0.05s ticker should advance ~60x during stop. A blocking
        # thread.join() would freeze the loop and the ticker would stall.
        ticks = 0

        async def _ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.05)
                ticks += 1

        ticker = asyncio.create_task(_ticker())
        try:
            await asyncio.wait_for(sess.stop(), timeout=6.0)
        finally:
            ticker.cancel()
            try:
                await ticker
            except asyncio.CancelledError:
                pass
        assert ticks >= 20, f"event loop blocked during stop() (ticks={ticks})"

    @pytest.mark.asyncio
    async def test_broadcast_isolates_slow_consumer(self):
        from deeptutor.services.monitoring.system_monitor import SystemMonitorSession

        class SlowCamera:
            def set_annotator(self, fn):
                pass

        class NoopProcessor:
            pass

        sess = SystemMonitorSession(
            session_id="s-bcast", camera=SlowCamera(), processor=NoopProcessor()  # type: ignore[arg-type]
        )

        received = []

        class FastWS:
            async def send_json(self, msg):
                received.append(("fast", msg))

        class SlowWS:
            async def send_json(self, msg):
                await asyncio.sleep(2.0)
                received.append(("slow", msg))

        class DeadWS:
            async def send_json(self, msg):
                raise RuntimeError("dead socket")

        sess.register(FastWS())
        sess.register(SlowWS())
        sess.register(DeadWS())

        start = time.perf_counter()
        await asyncio.wait_for(sess.broadcast({"type": "telemetry_update"}), timeout=5.0)
        elapsed = time.perf_counter() - start
        kinds = [k for k, _ in received]
        assert "fast" in kinds, "fast consumer must receive despite slow/dead peers"
        # Slow consumer (2s) exceeds the 1s per-consumer timeout so it is
        # evicted like the dead socket: broadcast stays fast (<1.2s) and
        # only the healthy listener remains.
        assert elapsed < 1.2, f"broadcast blocked by slow consumer ({elapsed:.2f}s)"
        assert sess.listener_count == 1
