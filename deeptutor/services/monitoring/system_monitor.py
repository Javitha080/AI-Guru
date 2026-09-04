"""Per-session orchestrator for the system-level monitoring engine.

Binds together SystemCameraManager (webcam), PythonFaceProcessor (MediaPipe +
solvePnP) and the existing LocalCVPipeline scoring stack into one asyncio tick
loop that:

- grabs frames, runs inference off-loop (executor), analyzes via
  ``process_telemetry_payload`` using the EXACT payload shape the browser used,
- broadcasts ``telemetry_update`` messages to every registered WebSocket,
- feeds the rolling evidence ring and dispatches warnings (with real photo
  bytes) through ``dispatch.handle_warning``,
- paints the annotated MJPEG overlay via a camera annotator callback.

The router decides between this engine and the legacy browser-driven path by
checking :func:`camera_config` + availability.
"""

from __future__ import annotations

import asyncio
import base64
import collections
import json
import logging
import time
from typing import Any, Deque, Dict, Optional

import aiosqlite

from deeptutor.services.monitoring.camera_settings import (
    CAMERA_SETTINGS_KEY,
    load_camera_config,
    save_camera_config,
)
from deeptutor.services.monitoring.cv_pipeline import LocalCVPipeline
from deeptutor.services.monitoring.dispatch import handle_warning
from deeptutor.services.monitoring.landmarks_codec import landmarks_to_payload
from deeptutor.services.monitoring.monitoring_config import (
    DEFAULT_THRESHOLDS,
    strictness_for,
)
from deeptutor.services.monitoring.python_face_processor import (
    PythonFaceProcessor,
    get_python_face_processor,
)
from deeptutor.services.monitoring.schemas import TelemetryUpdate
from deeptutor.services.monitoring.session_scores import EpisodeTracker, ScoreAccumulator
from deeptutor.services.monitoring.system_camera import (
    SystemCameraManager,
    get_system_camera,
    release_system_camera,
)

logger = logging.getLogger(__name__)

_RING_SIZE = DEFAULT_THRESHOLDS.ring_size
_RING_MIN_INTERVAL = (
    DEFAULT_THRESHOLDS.ring_min_interval
)  # seconds between evidence-ring frame updates
_SNAPSHOT_JPEG_QUALITY = 70

# Re-exported for backward-compat (routers import these from system_monitor).
__all__ = [
    "CAMERA_SETTINGS_KEY",
    "load_camera_config",
    "save_camera_config",
    "apply_supervision_strictness",
    "SystemMonitorSession",
    "get_system_monitor",
    "active_system_monitors",
    "start_system_monitor",
    "stop_system_monitor",
]


async def apply_supervision_strictness(
    pipeline: LocalCVPipeline, parent_id: str = "default"
) -> None:
    """Map a parent's strictness profile onto warning gates.

    Shared by the system-monitor path and the legacy browser-driven WS path so
    both engines enforce identical cooldown/confidence gates. ``parent_id``
    selects ``supervision_rules_{parent_id}`` (multi-parent); callers that
    cannot attribute a session yet pass the default.
    """
    try:
        from deeptutor.services.path_service import get_path_service
        from deeptutor.services.remote.kv_settings import ensure_kv_settings

        db = get_path_service().user_dir / "chat_history.db"
        async with aiosqlite.connect(db) as conn:
            await ensure_kv_settings(conn)
            cur = await conn.execute(
                "SELECT value FROM settings WHERE key = ?", (f"supervision_rules_{parent_id}",)
            )
            row = await cur.fetchone()
        if not row or not row[0]:
            return
        rules = json.loads(row[0])
        cooldown, conf = strictness_for(str(rules.get("alert_strictness", "balanced")))
        wm = getattr(pipeline, "warning_manager", None)
        if wm is not None:
            wm.cooldown_seconds = float(cooldown)
            wm.min_confidence = float(conf)
            logger.info("Supervision strictness applied: %s", rules.get("alert_strictness"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Strictness application skipped: %s", exc)


class _Listener:
    __slots__ = ("ws", "lock")

    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.lock = asyncio.Lock()


class SystemMonitorSession:
    """One active study session's system-level monitoring engine."""

    def __init__(
        self,
        session_id: str,
        camera: SystemCameraManager,
        processor: PythonFaceProcessor,
        pipeline: Optional[LocalCVPipeline] = None,
        target_fps: int = 10,
    ) -> None:
        self.session_id = session_id
        self.camera = camera
        self.processor = processor
        self.pipeline = pipeline or LocalCVPipeline()
        self.target_fps = target_fps

        self._listeners: set[_Listener] = set()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._paused = False

        self._ring: Deque[str] = collections.deque(maxlen=_RING_SIZE)
        self._last_ring_ts = 0.0
        self.last_telemetry: Dict[str, Any] = {}
        self.last_result: Any = None
        self.last_focus_score: Optional[float] = None

        # --- Score persistence (shared kernel with browser-driven loop) ---
        self._scores = ScoreAccumulator()
        self._episodes = EpisodeTracker()
        self._warning_count = 0
        self._last_persist_ts: float = 0.0
        self._persist_interval: float = 10.0  # seconds

    # Backward-compat shims for pre-refactor attribute access.
    @property
    def _focus_sum(self) -> float:
        return self._scores.focus_sum

    @property
    def _engagement_sum(self) -> float:
        return self._scores.engagement_sum

    @property
    def _score_ticks(self) -> int:
        return self._scores.ticks

    @property
    def _distraction_count(self) -> int:
        return self._episodes.distraction_count

    @property
    def _active_distractions(self) -> set[str]:
        return self._episodes.active

    # ------------------------------------------------------------- listeners

    def register(self, ws: Any) -> _Listener:
        listener = _Listener(ws)
        self._listeners.add(listener)
        return listener

    def unregister(self, listener: _Listener) -> None:
        self._listeners.discard(listener)

    @property
    def listener_count(self) -> int:
        return len(self._listeners)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        listeners = list(self._listeners)
        if not listeners:
            return

        async def _send(listener: _Listener) -> None:
            try:
                async with listener.lock:
                    # Per-consumer timeout: one wedged tab must not stall
                    # telemetry to every other listener.
                    await asyncio.wait_for(listener.ws.send_json(message), timeout=1.0)
            except Exception:  # noqa: BLE001 - dead/slow sockets drop silently
                self._listeners.discard(listener)

        await asyncio.gather(*(_send(li) for li in listeners), return_exceptions=True)

    # -------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._paused = False
        self.pipeline.reset_session()
        self.processor.reset_session()
        self.camera.set_annotator(self._paint_overlay)
        if not self.camera.start():
            logger.warning(
                "Monitor %s: camera start failed (%s)", self.session_id, self.camera.last_error
            )
        loop = asyncio.get_running_loop()
        loop.create_task(apply_supervision_strictness(self.pipeline))
        self._task = loop.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        task = self._task
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        # Flush final scores to DB before releasing the camera.
        try:
            await self._persist_scores()
        except Exception:  # noqa: BLE001
            pass
        # camera.stop() joins the grab thread (up to 3s) — never block the
        # event loop on it; offload to a worker thread.
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.camera.stop)
        except RuntimeError:
            # No running loop (sync test teardown): fall back to direct stop.
            try:
                self.camera.stop()
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass

    async def _persist_scores(self) -> None:
        """Flush running-mean focus/engagement to study_sessions (shared kernel)."""
        try:
            from deeptutor.services.study.session_manager import StudySessionManager

            focus = self._scores.mean_focus(float(self.last_focus_score or 0))
            engagement = self._scores.mean_engagement(
                float((self.last_telemetry or {}).get("engagement_score", 0))
            )
            await StudySessionManager().update_scores(
                self.session_id,
                focus,
                engagement,
                self._distraction_count,
                self._warning_count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Score persistence skipped for %s: %s", self.session_id, exc)

    async def _log_episode(
        self,
        event_type: str,
        severity: str,
        confidence: float,
        duration_seconds: float,
        message: str,
    ) -> None:
        """Persist a distraction/presence episode to monitoring_events."""
        try:
            from deeptutor.services.study.telemetry_logger import TelemetryLogger

            await TelemetryLogger().log_event(
                session_id=self.session_id,
                event_type=event_type,
                severity=severity,
                confidence=confidence,
                duration_seconds=duration_seconds,
                metadata={"message": message},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Episode logging skipped for %s/%s: %s", self.session_id, event_type, exc)

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool) -> None:
        if self._paused == value:
            return
        self._paused = value
        if value:
            # Graceful release on pause: free the device (light off), keep state.
            self.camera.stop()
            logger.info("Monitor %s paused — camera released", self.session_id)
        else:
            if not self.camera.start() and self.camera.last_error:
                logger.warning(
                    "Monitor %s resume failed: %s", self.session_id, self.camera.last_error
                )
            logger.info("Monitor %s resumed", self.session_id)

    # ------------------------------------------------------------------- loop

    async def _run_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while self._running:
            if self._paused:
                await asyncio.sleep(0.1)
                continue
            interval = 1.0 / float(
                max(1, min(self.target_fps, self.pipeline.get_current_target_fps()))
            )
            started = time.perf_counter()
            try:
                await self._tick(loop)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - one bad frame never kills monitoring
                logger.debug("Monitor tick failed for %s: %s", self.session_id, exc)
            elapsed = time.perf_counter() - started
            await asyncio.sleep(max(0.005, interval - elapsed))

    async def _tick(self, loop: asyncio.AbstractEventLoop) -> None:
        frame = self.camera.get_latest_frame()
        if frame is None:
            return

        result = await loop.run_in_executor(None, self.processor.process_frame, frame)
        self.last_result = result

        now = time.time()
        snapshot_b64 = self._maybe_ring_snapshot(frame, now)
        payload = self._build_payload(result, now)
        analysis = self.pipeline.process_telemetry_payload(payload, current_time=now)
        telemetry = self._handle_analysis(analysis, result, snapshot_b64, now)
        await self.broadcast(telemetry)

    def _build_payload(self, result: Any, now: float) -> Dict[str, Any]:
        """Build the canonical telemetry payload from a FaceFrameResult."""
        embedding = None
        if result.detected and result.landmarks is not None:
            embedding = self.pipeline.face_engine.generate_geometric_embedding(result.landmarks)

        pose_dict = gaze_dict = None
        if result.pose is not None:
            pose_dict = {
                "yaw": result.pose.yaw,
                "pitch": result.pose.pitch,
                "roll": result.pose.roll,
                "posture": result.pose.posture.value,
                "is_facing_screen": result.pose.is_facing_screen,
                "is_reading_writing_pose": result.pose.is_reading_writing_pose,
            }
        if result.gaze is not None:
            gaze_dict = {
                "gaze_x": result.gaze.gaze_x,
                "gaze_y": result.gaze.gaze_y,
                "is_focused": result.gaze.is_focused,
                "confidence": result.gaze.confidence,
            }

        return {
            "detected": result.detected,
            "confidence": result.confidence,
            "brightness": result.brightness,
            "texture_laplacian_var": result.texture_laplacian_var,
            "landmarks": landmarks_to_payload(result.landmarks),
            "embedding": embedding,
            "pose": pose_dict,
            "gaze": gaze_dict,
            "phone_detected": result.phone_detected,
            "timestamp": now,
            # Inject the processor's EAR so the liveness detector uses the
            # higher-quality value from the full 478-point mesh rather than
            # re-deriving from the 6-point landmark subset.
            "ear_override": round(result.ear, 4) if result.ear > 0 else None,
        }

    def _handle_analysis(
        self, analysis: Any, result: Any, snapshot_b64: Optional[str], now: float
    ) -> Dict[str, Any]:
        """Accumulate scores, log episodes, dispatch warnings, build telemetry."""
        focus_score = float(analysis.distraction.focus_score or 0)
        self.last_focus_score = focus_score

        # --- Score accumulation for periodic DB persistence (shared kernel) ---
        self._scores.add_frame(focus_score, float(analysis.engagement.score or 0))

        # --- Edge-triggered distraction episode logging ---
        dtype = (
            analysis.distraction.distraction_type.value
            if analysis.distraction.is_distracted
            else None
        )
        if self._episodes.on_frame(analysis.distraction.is_distracted, dtype):
            assert dtype is not None
            event_type = "PHONE_DETECTED" if "PHONE" in dtype.upper() else "LOOKING_AWAY"
            from deeptutor.services.background import spawn_bg as _spawn_log

            _spawn_log(
                self._log_episode(
                    event_type,
                    "warning",
                    float(analysis.distraction.confidence or 0),
                    float(analysis.distraction.duration_seconds or 0),
                    str(analysis.distraction.reason or dtype),
                ),
                name=f"sys-episode-{self.session_id}",
            )

        telemetry_msg = TelemetryUpdate(
            session_id=self.session_id,
            timestamp=analysis.timestamp,
            presence=analysis.presence.state.value,
            focus_score=focus_score,
            engagement_score=analysis.engagement.score,
            engagement_trend=analysis.engagement.trend,
            posture=analysis.pose.posture.value,
            is_distracted=analysis.distraction.is_distracted,
            whitelisted_action=(
                analysis.distraction.whitelisted_action.value
                if analysis.distraction.whitelisted_action
                else None
            ),
            fps=analysis.fps,
            ear=round(result.ear, 3),
        )
        telemetry = telemetry_msg.to_dict()
        self.last_telemetry = telemetry

        warning_event = analysis.dispatched_warning
        if warning_event is not None:
            self._handle_warning_event(analysis, warning_event, telemetry, snapshot_b64)

        # --- Periodic score persistence (every 10s) ---
        if now - self._last_persist_ts >= self._persist_interval:
            self._last_persist_ts = now
            from deeptutor.services.background import spawn_bg as _spawn_persist

            _spawn_persist(
                self._persist_scores(),
                name=f"sys-persist-{self.session_id}",
            )

        return telemetry

    def _handle_warning_event(
        self,
        analysis: Any,
        warning_event: Any,
        telemetry: Dict[str, Any],
        snapshot_b64: Optional[str],
    ) -> None:
        severity = str(warning_event.severity)
        telemetry["warning"] = {
            "warning_id": warning_event.warning_id,
            "category": warning_event.category,
            "message": warning_event.message,
            "severity": severity,
            "confidence": float(analysis.distraction.confidence),
            "duration_seconds": float(analysis.distraction.duration_seconds),
        }
        # Track actionable warnings (not nudges / info pings)
        if severity not in ("info", "nudge"):
            self._warning_count += 1
        # Nudges flow through handle_warning too — its tiering policy keeps
        # them local (telemetry-only) while warnings/alerts reach parents.
        ring = list(self._ring)
        current = ring[-1] if ring else snapshot_b64
        from deeptutor.services.background import spawn_bg

        spawn_bg(
            handle_warning(
                session_id=self.session_id,
                warning=telemetry["warning"],
                current_frame_b64=current,
                ring_frames_b64=ring,
                photo_jpeg_b64=current,
            ),
            name=f"system-warning-{self.session_id}",
        )

    def _maybe_ring_snapshot(self, frame: Any, now: float) -> Optional[str]:
        """Append a throttled JPEG snapshot to the evidence ring; returns it."""
        if now - self._last_ring_ts < _RING_MIN_INTERVAL:
            return None
        encoded = _encode_jpeg_b64(frame, quality=_SNAPSHOT_JPEG_QUALITY)
        if encoded is None:
            return None
        self._last_ring_ts = now
        self._ring.append(encoded)
        return encoded

    def _paint_overlay(self, frame: Any) -> Any:
        result = self.last_result
        score = self.last_focus_score
        if result is None:
            return frame
        if getattr(result, "detected", False):
            distracted = bool(
                self.last_telemetry.get("is_distracted")
                or (self.last_telemetry.get("warning") or {}).get("severity")
                in ("alert", "warning")
            )
            state = (
                "distracted"
                if distracted
                else ("drifting" if (score is not None and score < 70) else "focused")
            )
        else:
            state = "distracted" if self.last_telemetry.get("presence") == "away" else "drifting"
        return self.processor.draw_overlay(frame, result, focus_state=state, focus_score=score)

    # ----------------------------------------------------------- feed helpers

    def get_annotated_jpeg(self) -> Optional[bytes]:
        return self.camera.get_annotated_jpeg()

    def get_snapshot_jpeg(self) -> Optional[bytes]:
        return self.camera.get_raw_jpeg()


_monitors: Dict[str, SystemMonitorSession] = {}


def get_system_monitor(session_id: str) -> Optional[SystemMonitorSession]:
    return _monitors.get(session_id)


def active_system_monitors() -> Dict[str, SystemMonitorSession]:
    return dict(_monitors)


async def start_system_monitor(
    session_id: str,
    camera_config: Optional[Dict[str, Any]] = None,
    pipeline: Optional[LocalCVPipeline] = None,
) -> Optional[SystemMonitorSession]:
    """Start (or reuse) the system monitor for a session.

    Each session owns a FRESH LocalCVPipeline (never the process-global
    singleton) so presence timers, liveness history, and warning cooldowns
    cannot leak across concurrent sessions. The identity baseline enrolled
    via /enroll-face is inherited once at creation.

    Returns None when the CV stack or hardware is unavailable — callers then
    fall back to the browser-driven pipeline.
    """
    existing = _monitors.get(session_id)
    if existing is not None:
        return existing

    processor = get_python_face_processor()
    if not processor.available:
        logger.info("System monitoring unavailable: face processor cannot load")
        return None

    cfg = camera_config or await load_camera_config()
    camera = get_system_camera(int(cfg.get("camera_index", 0)))
    if not camera.available:
        logger.info("System monitoring unavailable: no camera device")
        release_system_camera(int(cfg.get("camera_index", 0)))
        return None

    if pipeline is None:
        pipe = LocalCVPipeline()
        # Inherit the enrolled identity baseline (if any) so /enroll-face
        # and /enroll-from-camera keep working with per-session pipelines.
        try:
            from deeptutor.services.monitoring.cv_pipeline import get_cv_pipeline

            baseline = get_cv_pipeline().face_engine.get_enrolled_face()
            if baseline is not None:
                pipe.enroll_student_baseline(list(baseline))
        except Exception:  # noqa: BLE001 - enrollment inheritance is best-effort
            pass
    else:
        pipe = pipeline
    monitor = SystemMonitorSession(
        session_id=session_id,
        camera=camera,
        processor=processor,
        pipeline=pipe,
        target_fps=int(cfg.get("target_fps", 10)),
    )
    try:
        monitor.start()
    except RuntimeError as exc:
        logger.warning("System monitor start failed for %s: %s", session_id, exc)
        return None
    _monitors[session_id] = monitor
    logger.info("System monitor started for session %s", session_id)
    return monitor


async def stop_system_monitor(session_id: str) -> None:
    monitor = _monitors.pop(session_id, None)
    if monitor is None:
        return
    await monitor.stop()
    cfg = await load_camera_config()
    # Release the physical device when this was its last consumer.
    if not _monitors:
        release_system_camera(int(cfg.get("camera_index", 0)))
    logger.info("System monitor stopped for session %s", session_id)


# --------------------------------------------------------------- utilities


def _encode_jpeg_b64(frame: Any, quality: int = 70) -> Optional[str]:
    try:
        import cv2

        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        if not ok:
            return None
        return base64.b64encode(buf.tobytes()).decode("ascii")
    except Exception:  # noqa: BLE001
        return None


def _landmarks_to_payload(landmarks: Any) -> Optional[Dict[str, Any]]:
    """Serialize FaceLandmarks (deprecated shim → landmarks_codec)."""
    return landmarks_to_payload(landmarks)
