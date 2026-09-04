"""AI Guru Python-side face processing engine (system-level CV).

Runs Google MediaPipe Tasks on raw webcam frames owned by
``system_camera.SystemCameraManager``:

- FaceLandmarker: 478 3D landmarks (incl. iris) mapped into the SAME landmark
  groups the browser WASM pipeline produced, so every downstream consumer
  (FaceEngine embeddings, LivenessDetector, DistractionAnalyzer whitelists)
  keeps working unchanged.
- ``cv2.solvePnP`` head pose: fits a canonical 3D face model against six
  anchor landmarks for rock-solid yaw/pitch/roll (no false jumps), classified
  through ``PoseGazeEstimator.classify`` so thresholds stay in one place.
- Iris tracking: true gaze offset relative to eye corners, merged with head
  pose into the standard ``GazeResult``.
- EAR (eye aspect ratio) for drowsiness/blinks feeding ``LivenessDetector``.
- EfficientDet-Lite object detector: COCO "cell phone" → the existing
  ``phone_detected`` distraction flag.
- Overlay painter: cyan mesh wireframe, iris circles, attention ray and a
  focus-state border painted onto frames served on the MJPEG feed.

Heavy imports (mediapipe/cv2) are lazy and guarded: when unavailable the app
boots normally and monitoring falls back to browser-side WASM CV.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import threading
import time
from typing import Deque, List, Optional, Tuple

import numpy as np

from deeptutor.services.monitoring.face_engine import FaceLandmarks, Point3D
from deeptutor.services.monitoring.face_solvers import (
    build_gaze as _build_gaze_solver,
)
from deeptutor.services.monitoring.face_solvers import (
    build_head_pose as _build_head_pose_solver,
)
from deeptutor.services.monitoring.face_solvers import (
    compute_ear as _compute_ear_solver,
)
from deeptutor.services.monitoring.face_solvers import (
    euler_from_face_matrix as _euler_from_face_matrix,
)
from deeptutor.services.monitoring.face_solvers import (
    eye_closure_from_blendshapes as _eye_closure_from_blendshapes,
)
from deeptutor.services.monitoring.face_solvers import (
    jaw_open_from_blendshapes as _jaw_open_from_blendshapes,
)
from deeptutor.services.monitoring.face_solvers import (
    solve_pnp_angles as _solve_pnp_angles,
)
from deeptutor.services.monitoring.pose_gaze import (
    GazeResult,
    HeadPoseResult,
)

logger = logging.getLogger(__name__)

try:  # Guarded: feature-degrading dependency.
    import cv2
except Exception:  # noqa: BLE001
    cv2 = None  # type: ignore[assignment]

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_FACE_MODEL = _REPO_ROOT / "web" / "public" / "mediapipe" / "face_landmarker.task"
_DEFAULT_OBJECT_MODEL = _REPO_ROOT / "web" / "public" / "mediapipe" / "efficientdet_lite0.tflite"

# --- Landmark indices (identical to web/lib/monitoring/visionPipeline.ts) ----
LEFT_EYE_IDX = [33, 133, 159, 145, 158, 153]
RIGHT_EYE_IDX = [263, 362, 386, 374, 385, 380]
MOUTH_IDX = [61, 291, 13, 14, 82, 87]
NOSE_TIP_IDX = 1
CHIN_IDX = 152
FOREHEAD_IDX = 10
LEFT_CHEEK_IDX = 234
RIGHT_CHEEK_IDX = 454
LEFT_IRIS_IDX = 468  # center of left iris (refine-era 478-landmark model)
RIGHT_IRIS_IDX = 473

# Canonical 3D anchor model for solvePnP (classic six-point head-pose rig),
# paired with image landmarks: nose, chin, eye outer corners, mouth corners.
_PNP_MODEL_POINTS = np.array(
    [
        (0.0, 0.0, 0.0),  # nose tip            ↔ idx 1
        (0.0, -330.0, -65.0),  # chin                ↔ idx 152
        (-225.0, 170.0, -135.0),  # eye outer corner A  ↔ idx 33
        (225.0, 170.0, -135.0),  # eye outer corner B  ↔ idx 263
        (-150.0, -150.0, -125.0),  # mouth corner A     ↔ idx 61
        (150.0, -150.0, -125.0),  # mouth corner B     ↔ idx 291
    ],
    dtype=np.float64,
)
_PNP_IMAGE_IDX = [NOSE_TIP_IDX, CHIN_IDX, 33, 263, 61, 291]

# Sign calibration converting the solvePnP camera-frame rotation onto the
# backend head-pose convention (HeadPoseResult: +yaw = student turns right,
# +pitch = looking down, +roll = tilting right). Exactness is locked by the
# round-trip unit test which projects rotated canonical models through a
# synthetic pinhole rig and asserts zero recovery error.
_PITCH_SIGN = -1.0

_PHONE_LABELS = {"cell phone", "mobile phone", "phone"}
_PHONE_SCORE_THRESHOLD = 0.45
# Time-based phone-detection cadence with majority voting (Patch B). The old
# every-5th-tick + 1.5s-TTL scheme broke under governor throttling: at ≤3 fps
# the detector ran every ≥1.7s, the TTL expired in between, and the 4s
# distraction timer kept resetting — phone alerts became impossible exactly
# when the machine was under load.
PHONE_DETECT_INTERVAL_S = 0.5
PHONE_VOTE_WINDOW = 6  # ~3s of verdicts at 0.5s cadence
PHONE_VOTES_REQUIRED = 3
# Phone/hands/desk live in the lower ~65% of the frame; a tighter crop lifts
# Lite0's small-object recall and cuts detector latency.
_PHONE_CROP_TOP = 0.35

_FLIP_X = np.array(
    [[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]],
    dtype=np.float64,
)


def _load_mediapipe():
    try:
        import mediapipe as mp

        return mp
    except Exception as exc:  # noqa: BLE001
        logger.warning("MediaPipe unavailable, system CV disabled: %s", exc)
        return None


def resolve_model_path(env_key: str, default: Path) -> Optional[Path]:
    override = os.environ.get(env_key)
    candidate = Path(override) if override else default
    if candidate.is_file():
        return candidate
    return None


@dataclass
class FaceFrameResult:
    """Per-frame output of the Python face processor."""

    detected: bool = False
    confidence: float = 0.0
    brightness: float = 0.5
    texture_laplacian_var: Optional[float] = None
    landmarks: Optional[FaceLandmarks] = None
    raw_landmarks: List[Tuple[float, float, float]] = field(default_factory=list)
    pose: Optional[HeadPoseResult] = None
    gaze: Optional[GazeResult] = None
    ear: float = 0.0
    phone_detected: bool = False
    frame_width: int = 0
    frame_height: int = 0
    # RAW (uncalibrated) head angles — neutral calibration happens per-session
    # in LocalCVPipeline.NeutralCalibrator, NOT here (this object is a
    # process-wide singleton shared with pre-flight probes).
    head_angles_raw: Optional[Tuple[float, float, float]] = None
    head_matrix: Optional[List[float]] = None  # 16 floats, row-major
    # MediaPipe blendshape signals (0-1), None when blendshapes are off.
    eye_closure: Optional[float] = None
    jaw_open: Optional[float] = None


class PythonFaceProcessor:
    """MediaPipe-powered frame analyzer. Construct freely; heavy models load lazily."""

    def __init__(
        self,
        face_model_path: Optional[str] = None,
        object_model_path: Optional[str] = None,
        enable_object_detection: bool = True,
        texture_every_n: int = 3,
        phone_detect_every_n: int = 5,
    ) -> None:
        self._face_model_path = face_model_path
        self._object_model_path = object_model_path
        self._enable_object_detection = enable_object_detection
        self._texture_every_n = max(1, int(texture_every_n))
        self._phone_detect_every_n = max(1, int(phone_detect_every_n))

        self._mp = None
        self._landmarker = None
        self._object_detector = None
        self._loaded = False
        self._last_ts_ms = 0
        self._tick = 0

        # Serializes all MediaPipe inference: FaceLandmarker (VIDEO mode) is
        # NOT thread-safe, and this processor is a process-wide singleton also
        # used by pre-flight probes / enrollment while a session tick runs.
        # Without the lock, detect_for_video raises intermittently, the tick
        # swallows it as `detected=False`, and the student is marked AWAY.
        self._infer_lock = threading.Lock()

        # Time-based phone detection with majority voting (independent of the
        # governor-driven fps).
        self._phone_votes: Deque[bool] = collections.deque(maxlen=PHONE_VOTE_WINDOW)
        self._phone_last_run = 0.0
        # Deprecated n-tick cadence kept for constructor compat (unused).
        self._phone_detect_every_n = max(1, int(phone_detect_every_n))

    # -------------------------------------------------------------- lifecycle

    @property
    def available(self) -> bool:
        if cv2 is None:
            return False
        if _load_mediapipe() is None:
            return False
        return resolve_model_path("DEEPTUTOR_FACE_MODEL_PATH", _DEFAULT_FACE_MODEL) is not None

    def _ensure_loaded(self) -> bool:
        if self._loaded:
            return True
        mp = _load_mediapipe()
        if mp is None or cv2 is None:
            return False
        face_model = resolve_model_path(
            "DEEPTUTOR_FACE_MODEL_PATH",
            Path(self._face_model_path) if self._face_model_path else _DEFAULT_FACE_MODEL,
        )
        if face_model is None:
            logger.warning("Face landmarker model missing at %s", _DEFAULT_FACE_MODEL)
            return False
        try:
            options = mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(face_model)),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_faces=1,
                # Model-fitted pose + normalized eye/jaw signals for both the
                # pose path (matrix beats 2D solvePnP) and PERCLOS drowsiness.
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=True,
            )
            self._landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)

            if self._enable_object_detection:
                obj_model = resolve_model_path(
                    "DEEPTUTOR_OBJECT_MODEL_PATH",
                    Path(self._object_model_path)
                    if self._object_model_path
                    else _DEFAULT_OBJECT_MODEL,
                )
                if obj_model is not None:
                    det_options = mp.tasks.vision.ObjectDetectorOptions(
                        base_options=mp.tasks.BaseOptions(model_asset_path=str(obj_model)),
                        running_mode=mp.tasks.vision.RunningMode.IMAGE,
                        max_results=5,
                        score_threshold=_PHONE_SCORE_THRESHOLD,
                    )
                    self._object_detector = mp.tasks.vision.ObjectDetector.create_from_options(
                        det_options
                    )
                else:
                    logger.info("Phone-detection model missing; phone alerts stay inactive")
            self._mp = mp
            self._loaded = True
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Face processor init failed: %s", exc)
            self._landmarker = None
            return False

    def close(self) -> None:
        for attr in ("_landmarker", "_object_detector"):
            obj = getattr(self, attr, None)
            if obj is not None:
                try:
                    obj.close()
                except Exception:  # noqa: BLE001
                    pass
            setattr(self, attr, None)
        self._loaded = False

    def reset_session(self) -> None:
        """Reset per-frame heuristics for a fresh study session.

        Neutral head-pose calibration moved to LocalCVPipeline's
        NeutralCalibrator (per-session object); only the phone vote history
        still lives here.
        """
        self._phone_votes.clear()
        self._phone_last_run = 0.0

    # ------------------------------------------------------------ inference

    def process_frame(self, frame: "np.ndarray") -> FaceFrameResult:
        result = FaceFrameResult()
        if frame is None or cv2 is None or not self._ensure_loaded():
            return result

        # One inference at a time: pre-flight probes and enrollment share this
        # singleton with the session tick (thread-safety: H2).
        with self._infer_lock:
            return self._process_frame_locked(frame, result)

    def _process_frame_locked(
        self, frame: "np.ndarray", result: FaceFrameResult
    ) -> FaceFrameResult:
        h, w = frame.shape[:2]
        result.frame_width = w
        result.frame_height = h
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        result.brightness = float(np.mean(gray)) / 255.0

        self._tick += 1
        if self._tick % self._texture_every_n == 1:
            # KNOWN LIMIT (review M2): Laplacian variance at 64x48 separates
            # "blurry/flat" from "textured" but cannot reliably distinguish
            # screen moiré from skin — treat the texture cue as weak evidence
            # only (it modulates liveness confidence, never decides alone).
            small = cv2.resize(gray, (64, 48))
            result.texture_laplacian_var = float(cv2.Laplacian(small, cv2.CV_64F).var())

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        ts_ms = self._next_timestamp_ms()

        try:
            lm_result = self._landmarker.detect_for_video(mp_image, ts_ms)
        except Exception as exc:  # noqa: BLE001
            logger.debug("FaceLandmarker tick failed: %s", exc)
            return result

        faces = getattr(lm_result, "face_landmarks", []) or []
        if not faces:
            return result

        face = faces[0]
        raw = [(float(p.x), float(p.y), float(float(p.z))) for p in face]
        result.raw_landmarks = raw
        result.detected = True
        result.confidence = 0.95

        result.landmarks = self._build_landmark_groups(raw)
        result.ear = self._compute_ear(raw)

        # --- Head pose: MediaPipe's canonical→camera matrix first (model-
        # fitted, jitter-free), solvePnP as fallback. Angles stay RAW here —
        # the per-session pipeline applies neutral calibration.
        head_matrices = getattr(lm_result, "facial_transformation_matrixes", None) or []
        if head_matrices:
            try:
                mat = np.asarray(head_matrices[0], dtype=np.float64)
                yaw, pitch, roll = _euler_from_face_matrix(mat)
                result.head_matrix = [float(v) for v in mat.reshape(-1)]
            except Exception as exc:  # noqa: BLE001
                logger.debug("Matrix euler extraction failed: %s", exc)
                yaw, pitch, roll = self._head_pose_from_pnp(raw, w, h)
        else:
            yaw, pitch, roll = self._head_pose_from_pnp(raw, w, h)
        result.head_angles_raw = (yaw, pitch, roll)
        result.pose = self._build_head_pose(yaw, pitch, roll)
        result.gaze = self._build_gaze(raw, result.pose)

        # --- Blendshape eye/jaw signals for PERCLOS drowsiness ------------
        blendshapes = getattr(lm_result, "face_blendshapes", None) or []
        if blendshapes:
            result.eye_closure = _eye_closure_from_blendshapes(blendshapes[0])
            result.jaw_open = _jaw_open_from_blendshapes(blendshapes[0])

        # --- Time-based phone detection with majority voting --------------
        now = time.time()
        if (
            self._object_detector is not None
            and (now - self._phone_last_run) >= PHONE_DETECT_INTERVAL_S
        ):
            self._phone_last_run = now
            crop = rgb[int(h * _PHONE_CROP_TOP) :, :]
            if crop.size > 0:
                crop_img = self._mp.Image(
                    image_format=self._mp.ImageFormat.SRGB,
                    data=np.ascontiguousarray(crop),
                )
                self._phone_votes.append(self._detect_phone(crop_img))
        result.phone_detected = (
            sum(self._phone_votes) >= PHONE_VOTES_REQUIRED and len(self._phone_votes) > 0
        )

        return result

    def _next_timestamp_ms(self) -> int:
        now_ms = int(time.perf_counter() * 1000)
        self._last_ts_ms = max(now_ms, self._last_ts_ms + 1)
        return self._last_ts_ms

    # ------------------------------------------------------ landmark mapping

    def _build_landmark_groups(self, raw: List[Tuple[float, float, float]]) -> FaceLandmarks:
        def pts(idxs: List[int]) -> List[Point3D]:
            return [Point3D(x=raw[i][0], y=raw[i][1], z=raw[i][2]) for i in idxs]

        def single(idx: int) -> Point3D:
            x, y, z = raw[idx]
            return Point3D(x=x, y=y, z=z)

        return FaceLandmarks(
            left_eye=pts(LEFT_EYE_IDX),
            right_eye=pts(RIGHT_EYE_IDX),
            mouth=pts(MOUTH_IDX),
            all_points=[Point3D(x=x, y=y, z=z) for (x, y, z) in raw],
            nose_tip=single(NOSE_TIP_IDX),
            chin=single(CHIN_IDX),
            forehead=single(FOREHEAD_IDX),
            left_cheek=single(LEFT_CHEEK_IDX),
            right_cheek=single(RIGHT_CHEEK_IDX),
        )

    # ------------------------------------------------------------------ EAR

    @staticmethod
    def _compute_ear(raw: List[Tuple[float, float, float]]) -> float:
        """Eye aspect ratio from eyelid geometry (delegates to face_solvers)."""
        return _compute_ear_solver(raw)

    # ------------------------------------------------------------- head pose

    def _head_pose_from_pnp(
        self, raw: List[Tuple[float, float, float]], w: int, h: int
    ) -> Tuple[float, float, float]:
        yaw, pitch, roll = _solve_pnp_angles(
            raw, w, h, _PNP_MODEL_POINTS, _PNP_IMAGE_IDX, _FLIP_X, _PITCH_SIGN
        )
        if yaw == 0.0 and pitch == 0.0 and roll == 0.0:
            # solvePnP failure sentinel (matches legacy behavior).
            # Ambiguous with a true frontal pose, but callers treat (0,0,0)
            # as neutral either way.
            return 0.0, 0.0, 0.0
        return yaw, pitch, roll

    def _build_head_pose(self, yaw: float, pitch: float, roll: float) -> HeadPoseResult:
        return _build_head_pose_solver(yaw, pitch, roll)

    # ----------------------------------------------------------------- gaze

    def _build_gaze(
        self, raw: List[Tuple[float, float, float]], pose: HeadPoseResult
    ) -> GazeResult:
        return _build_gaze_solver(raw, pose)

    # ------------------------------------------------------- phone detector

    def _detect_phone(self, mp_image) -> bool:
        try:
            det = self._object_detector.detect(mp_image)
            for detection in getattr(det, "detections", []) or []:
                for category in detection.categories:
                    if (
                        category.category_name.lower() in _PHONE_LABELS
                        and category.score >= _PHONE_SCORE_THRESHOLD
                    ):
                        return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("Object detector tick failed: %s", exc)
        return False

    # -------------------------------------------------------------- overlay

    _STATE_COLORS = {
        "focused": (90, 200, 90),  # BGR green
        "drifting": (60, 165, 255),  # BGR amber
        "distracted": (60, 60, 230),  # BGR red
    }

    def draw_overlay(
        self,
        frame: "np.ndarray",
        result: FaceFrameResult,
        focus_state: str = "focused",
        focus_score: Optional[float] = None,
    ) -> "np.ndarray":
        """Paint mesh wireframe, iris markers, attention ray and status HUD."""
        if cv2 is None or frame is None:
            return frame
        annotated = frame.copy()
        h, w = annotated.shape[:2]

        color = self._STATE_COLORS.get(focus_state, self._STATE_COLORS["focused"])

        if result.detected and result.raw_landmarks:
            overlay = annotated.copy()
            for x, y, _z in result.raw_landmarks:
                cv2.circle(overlay, (int(x * w), int(y * h)), 1, (255, 235, 160), -1)
            annotated = cv2.addWeighted(overlay, 0.35, annotated, 0.65, 0)

            nx, ny = (
                int(result.raw_landmarks[NOSE_TIP_IDX][0] * w),
                int(result.raw_landmarks[NOSE_TIP_IDX][1] * h),
            )
            if result.gaze is not None:
                dx = int(result.gaze.gaze_x * 110)
                dy = int(result.gaze.gaze_y * 110)
                cv2.arrowedLine(
                    annotated, (nx, ny), (nx + dx, ny + dy), (255, 255, 120), 2, tipLength=0.28
                )
            for iris_idx in (LEFT_IRIS_IDX, RIGHT_IRIS_IDX):
                if len(result.raw_landmarks) > iris_idx:
                    ix, iy = result.raw_landmarks[iris_idx][:2]
                    cv2.circle(annotated, (int(ix * w), int(iy * h)), 4, (90, 220, 220), 1)
        elif result.detected is False and result.pose is None:
            pass  # no face: border alone communicates state

        cv2.rectangle(annotated, (0, 0), (w - 1, h - 1), color, 6)

        hud_bits = [f"FOCUS {focus_score:.0f}%" if focus_score is not None else "FOCUS --"]
        if result.pose is not None:
            hud_bits.append(result.pose.posture.value.replace("_", " ").title())
        cv2.rectangle(annotated, (10, 10), (250, 52), (20, 20, 20), -1)
        cv2.putText(
            annotated, hud_bits[0], (18, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2
        )
        if len(hud_bits) > 1:
            cv2.putText(
                annotated, hud_bits[1][:34], (18, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1
            )
        return annotated


_singleton: Optional[PythonFaceProcessor] = None


def get_python_face_processor() -> PythonFaceProcessor:
    """Process-wide processor singleton (models are heavy; one instance serves all sessions)."""
    global _singleton
    if _singleton is None:
        _singleton = PythonFaceProcessor()
    return _singleton
