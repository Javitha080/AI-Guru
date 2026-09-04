"""AI Guru system-level camera driver.

Owns the physical webcam through OpenCV (DirectShow on Windows, MSMF/any
fallback) on a dedicated background thread so the study-monitoring engine can
run without ANY browser involvement — the study room simply renders the
backend's MJPEG feed and no ``getUserMedia`` permission prompt ever appears.

The manager keeps a lock-protected latest-frame buffer plus lazily-encoded
JPEG caches:
- ``get_latest_frame()``   — raw BGR frame for inference
- ``get_raw_jpeg()``       — clean JPEG for evidence / Telegram photos
- ``get_annotated_jpeg()`` — JPEG painted by the injected annotator callback
                             (face mesh + gaze ray overlay)

An optional ``frame_source`` callable replaces the hardware capture entirely;
tests inject synthetic numpy frames without a physical camera.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:  # Guarded so the rest of the app boots even without OpenCV.
    import cv2
except Exception:  # noqa: BLE001
    cv2 = None  # type: ignore[assignment]


_RAW_JPEG_QUALITY = 80


class SystemCameraManager:
    """Background webcam grabber with thread-safe frame buffers."""

    GRAB_TARGET_FPS: int = 15
    _MAX_CONSECUTIVE_FAILURES: int = 30
    # Some webcams take several seconds before the first read succeeds; only
    # apply the fast-fail rule once a first frame has actually arrived.
    _FIRST_FRAME_GRACE_S: float = 10.0

    def __init__(
        self,
        camera_index: int = 0,
        width: int = 640,
        height: int = 480,
        frame_source: Optional[Callable[[], Optional["np.ndarray"]]] = None,
    ) -> None:
        self.camera_index = int(camera_index)
        self.width = int(width)
        self.height = int(height)
        self._frame_source = frame_source

        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._capture = None

        self._latest_frame: Optional["np.ndarray"] = None
        self._frame_ts: float = 0.0
        self._raw_jpeg: Optional[bytes] = None
        self._raw_jpeg_ts: float = 0.0
        self._annotated_jpeg: Optional[bytes] = None
        self._annotated_jpeg_ts: float = 0.0
        self._annotator: Optional[Callable[["np.ndarray"], "np.ndarray"]] = None

        self.last_error: str = ""

    # ------------------------------------------------------------ lifecycle

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    @property
    def available(self) -> bool:
        if self._frame_source is not None:
            return True
        return cv2 is not None

    def start(self) -> bool:
        """Start the grabbing thread. Returns False (with last_error) on failure."""
        if self._running.is_set():
            return True
        if not self.available:
            self.last_error = "OpenCV is not installed"
            return False

        if self._frame_source is None:
            cap = self._open_capture()
            if cap is None:
                self.last_error = f"No camera device available at index {self.camera_index}"
                logger.warning("System camera unavailable: %s", self.last_error)
                return False
            self._capture = cap

        self.last_error = ""
        self._running.set()
        self._thread = threading.Thread(
            target=self._grab_loop,
            name=f"system-camera-{self.camera_index}",
            daemon=True,
        )
        self._thread.start()
        logger.info("System camera #%d started (%dx%d)", self.camera_index, self.width, self.height)
        return True

    def _open_capture(self):
        if cv2 is None:
            return None
        backends = []
        # MSMF first: DSHOW can raise "can't be used to capture by index" or
        # half-open devices that never deliver a frame (observed on Win11).
        if hasattr(cv2, "CAP_MSMF"):
            backends.append(cv2.CAP_MSMF)
        if hasattr(cv2, "CAP_DSHOW"):
            backends.append(cv2.CAP_DSHOW)
        backends.append(cv2.CAP_ANY)
        tried = []
        for backend in backends:
            try:
                cap = cv2.VideoCapture(self.camera_index, backend)
            except Exception as exc:  # noqa: BLE001
                tried.append(f"backend={backend}: {exc}")
                continue
            if cap is not None and cap.isOpened():
                try:
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    cap.set(cv2.CAP_PROP_FPS, self.GRAB_TARGET_FPS)
                except Exception:  # noqa: BLE001 - property hints are best-effort
                    pass
                logger.info("Camera opened via backend=%s", backend)
                return cap
            tried.append(f"backend={backend}: not opened")
            try:
                cap.release()
            except Exception:  # noqa: BLE001
                pass
        self.last_error = "; ".join(tried)
        return None

    def stop(self) -> None:
        """Stop grabbing and release the device. Idempotent."""
        self._running.clear()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        self._thread = None
        cap = self._capture
        self._capture = None
        if cap is not None:
            try:
                cap.release()
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            self._latest_frame = None
            self._raw_jpeg = None
            self._annotated_jpeg = None
        logger.info("System camera #%d stopped", self.camera_index)

    def set_annotator(self, annotator: Optional[Callable[["np.ndarray"], "np.ndarray"]]) -> None:
        """Inject the overlay painter used for the MJPEG feed."""
        self._annotator = annotator
        with self._lock:
            self._annotated_jpeg = None

    # -------------------------------------------------------------- buffers

    def get_latest_frame(self) -> Optional["np.ndarray"]:
        with self._lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def get_frame_age_seconds(self) -> float:
        with self._lock:
            if self._frame_ts <= 0.0:
                return float("inf")
            return max(0.0, time.time() - self._frame_ts)

    def get_raw_jpeg(self) -> Optional[bytes]:
        with self._lock:
            frame = self._latest_frame
            cached = self._raw_jpeg
            cached_ts = self._raw_jpeg_ts
        # Re-encode only when the cache lags the newest frame (JPEG encode of a
        # 640x480 frame costs a few ms; MJPEG consumers poll faster than grabs).
        if frame is not None and (cached is None or cached_ts < self._frame_ts_unlocked()):
            encoded = _encode_jpeg(frame, quality=_RAW_JPEG_QUALITY)
            if encoded is not None:
                with self._lock:
                    self._raw_jpeg = encoded
                    self._raw_jpeg_ts = time.time()
                return encoded
        return cached

    def get_annotated_jpeg(self) -> Optional[bytes]:
        with self._lock:
            frame = self._latest_frame
            cached = self._annotated_jpeg
            cached_ts = self._annotated_jpeg_ts
        if frame is not None and (cached is None or cached_ts < self._frame_ts_unlocked()):
            painter = self._annotator
            annotated = frame
            if painter is not None:
                try:
                    annotated = painter(frame)
                except Exception as exc:  # noqa: BLE001 - feed must survive paint bugs
                    logger.debug("Overlay painting failed: %s", exc)
                    annotated = frame
            encoded = _encode_jpeg(annotated, quality=_RAW_JPEG_QUALITY)
            if encoded is not None:
                with self._lock:
                    self._annotated_jpeg = encoded
                    self._annotated_jpeg_ts = time.time()
                return encoded
        return cached

    def _frame_ts_unlocked(self) -> float:
        with self._lock:
            return self._frame_ts

    # ------------------------------------------------------------ grab loop

    def _grab_loop(self) -> None:
        min_interval = 1.0 / float(max(1, self.GRAB_TARGET_FPS))
        failures = 0
        first_frame_deadline = time.perf_counter() + self._FIRST_FRAME_GRACE_S
        next_tick = time.perf_counter()
        while self._running.is_set():
            next_tick += min_interval
            frame = self._read_one_frame()
            if frame is None:
                failures += 1
                warmed_up = self._frame_ts > 0.0
                gave_up = (
                    failures >= self._MAX_CONSECUTIVE_FAILURES
                    if warmed_up
                    else time.perf_counter() >= first_frame_deadline
                )
                if gave_up:
                    self.last_error = (
                        "Camera stopped delivering frames"
                        if warmed_up
                        else f"Camera delivered no frames within {self._FIRST_FRAME_GRACE_S:.0f}s of start"
                    )
                    logger.warning("System camera #%d: %s", self.camera_index, self.last_error)
                    self._running.clear()
                    break
            else:
                failures = 0
                with self._lock:
                    self._latest_frame = frame
                    self._frame_ts = time.time()

            delay = next_tick - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                next_tick = time.perf_counter()

    def _read_one_frame(self) -> Optional["np.ndarray"]:
        if self._frame_source is not None:
            try:
                frame = self._frame_source()
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"frame source failed: {exc}"
                return None
            return frame if frame is not None else None

        if self._capture is None:
            return None
        ok, frame = self._capture.read()
        if not ok or frame is None:
            return None
        return frame


def _encode_jpeg(frame: "np.ndarray", quality: int = 80) -> Optional[bytes]:
    if cv2 is None or frame is None:
        return None
    try:
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        return bytes(buf.tobytes()) if ok else None
    except Exception:  # noqa: BLE001
        return None


_managers: Dict[int, SystemCameraManager] = {}
_registry_lock = threading.Lock()


def get_system_camera(camera_index: int = 0, **kwargs) -> SystemCameraManager:
    """Process-wide manager per camera index (the physical device is exclusive)."""
    key = int(camera_index)
    with _registry_lock:
        mgr = _managers.get(key)
        if mgr is None:
            mgr = SystemCameraManager(camera_index=key, **kwargs)
            _managers[key] = mgr
        return mgr


def release_system_camera(camera_index: int = 0) -> None:
    """Stop and forget the manager for an index (called when monitoring ends)."""
    key = int(camera_index)
    with _registry_lock:
        mgr = _managers.pop(key, None)
    if mgr is not None:
        mgr.stop()
