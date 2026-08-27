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

from dataclasses import dataclass, field
import logging
import math
import os
from pathlib import Path
import time
from typing import List, Optional, Tuple

import numpy as np

from deeptutor.services.monitoring.face_engine import FaceLandmarks, Point3D
from deeptutor.services.monitoring.pose_gaze import (
    GazeResult,
    HeadPoseResult,
    PoseGazeEstimator,
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
        (0.0, 0.0, 0.0),          # nose tip            ↔ idx 1
        (0.0, -330.0, -65.0),     # chin                ↔ idx 152
        (-225.0, 170.0, -135.0),  # eye outer corner A  ↔ idx 33
        (225.0, 170.0, -135.0),   # eye outer corner B  ↔ idx 263
        (-150.0, -150.0, -125.0),  # mouth corner A     ↔ idx 61
        (150.0, -150.0, -125.0),   # mouth corner B     ↔ idx 291
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
        self._last_phone_detected = False
        self._last_phone_ts = 0.0

        # Neutral head-pose baseline captured from the first stable detections
        # of a session so absolute camera placement cancels out.
        self._neutral: Optional[Tuple[float, float, float]] = None
        self._neutral_samples: List[Tuple[float, float, float]] = []

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
            )
            self._landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)

            if self._enable_object_detection:
                obj_model = resolve_model_path(
                    "DEEPTUTOR_OBJECT_MODEL_PATH",
                    Path(self._object_model_path) if self._object_model_path else _DEFAULT_OBJECT_MODEL,
                )
                if obj_model is not None:
                    det_options = mp.tasks.vision.ObjectDetectorOptions(
                        base_options=mp.tasks.BaseOptions(model_asset_path=str(obj_model)),
                        running_mode=mp.tasks.vision.RunningMode.IMAGE,
                        max_results=5,
                        score_threshold=_PHONE_SCORE_THRESHOLD,
                    )
                    self._object_detector = mp.tasks.vision.ObjectDetector.create_from_options(det_options)
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
        """Clear neutral-pose calibration for a fresh study session."""
        self._neutral = None
        self._neutral_samples.clear()

    # ------------------------------------------------------------ inference

    def process_frame(self, frame: "np.ndarray") -> FaceFrameResult:
        result = FaceFrameResult()
        if frame is None or cv2 is None or not self._ensure_loaded():
            return result

        h, w = frame.shape[:2]
        result.frame_width = w
        result.frame_height = h
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        result.brightness = float(np.mean(gray)) / 255.0

        self._tick += 1
        if self._tick % self._texture_every_n == 1:
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
            self._neutral_samples.clear()
            return result

        face = faces[0]
        raw = [(float(p.x), float(p.y), float(float(p.z))) for p in face]
        result.raw_landmarks = raw
        result.detected = True
        result.confidence = 0.95

        result.landmarks = self._build_landmark_groups(raw)
        result.ear = self._compute_ear(raw)

        yaw, pitch, roll = self._head_pose_from_pnp(raw, w, h)
        result.pose = self._build_head_pose(yaw, pitch, roll)
        result.gaze = self._build_gaze(raw, result.pose)

        now = time.time()
        if self._object_detector is not None and self._tick % self._phone_detect_every_n == 1:
            self._last_phone_detected = self._detect_phone(mp_image)
            self._last_phone_ts = now
        elif now - self._last_phone_ts <= 1.5:
            # Between detector runs keep the last verdict sticky (with TTL) so
            # a held phone still accumulates distraction duration across frames.
            pass
        else:
            self._last_phone_detected = False
        result.phone_detected = self._last_phone_detected

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
        """Eye aspect ratio from eyelid geometry (mean of both eyes)."""
        def eye_ratio(corner_a: int, corner_b: int, lid_top_a: int, lid_bot_a: int, lid_top_b: int, lid_bot_b: int) -> float:
            pa, pb = raw[corner_a], raw[corner_b]
            width = math.dist(pa[:2], pb[:2])
            if width < 1e-9:
                return 0.0
            v1 = math.dist(raw[lid_top_a][:2], raw[lid_bot_a][:2])
            v2 = math.dist(raw[lid_top_b][:2], raw[lid_bot_b][:2])
            return (v1 + v2) / (2.0 * width)

        try:
            left = eye_ratio(33, 133, 159, 145, 158, 153)
            right = eye_ratio(263, 362, 386, 374, 385, 380)
            return round((left + right) / 2.0, 4)
        except IndexError:
            return 0.0

    # ------------------------------------------------------------- head pose

    def _head_pose_from_pnp(self, raw: List[Tuple[float, float, float]], w: int, h: int) -> Tuple[float, float, float]:
        image_pts = np.array(
            [(raw[i][0] * w, raw[i][1] * h) for i in _PNP_IMAGE_IDX],
            dtype=np.float64,
        )
        focal = float(w)
        cam_matrix = np.array(
            [[focal, 0.0, w / 2.0], [0.0, focal, h / 2.0], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )
        dist_coeffs = np.zeros((4, 1), dtype=np.float64)

        ok, rvec, _ = cv2.solvePnP(
            _PNP_MODEL_POINTS, image_pts, cam_matrix, dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not ok:
            return 0.0, 0.0, 0.0

        # Camera-frame rotation → model-frame pose rotation → Euler extraction
        # matching the canonical model's Z·X·Y composition (verified exactly by
        # tests/services/test_python_face_processor.py).
        rmat, _ = cv2.Rodrigues(rvec)
        m = _FLIP_X @ rmat
        yaw = -math.degrees(math.atan2(-m[2][0], m[2][2]))
        pitch = _PITCH_SIGN * math.degrees(math.asin(max(-1.0, min(1.0, float(m[2][1])))))
        roll = math.degrees(math.atan2(-m[0][1], m[1][1]))
        return self._apply_neutral(yaw, pitch, roll)

    def _apply_neutral(self, yaw: float, pitch: float, roll: float) -> Tuple[float, float, float]:
        if self._neutral is None:
            # Only accumulate neutral baseline samples when the raw detection
            # is roughly frontal — prevents desk-looking or turned-around
            # startup from poisoning the zero-point.
            if abs(yaw) < 20.0 and abs(pitch) < 25.0 and abs(roll) < 15.0:
                self._neutral_samples.append((yaw, pitch, roll))
            # First stable frontal detections define the student's natural seat pose.
            if len(self._neutral_samples) >= 12:
                arr = np.array(self._neutral_samples)
                med = np.median(arr, axis=0)
                self._neutral = (float(med[0]), float(med[1]), float(med[2]))
                logger.info("Head-pose neutral calibrated: %s", self._neutral)
            return yaw, pitch, roll
        ny, np_, nr = self._neutral
        return yaw - ny, pitch - np_, roll - nr

    def _build_head_pose(self, yaw: float, pitch: float, roll: float) -> HeadPoseResult:
        posture, is_facing_screen, is_reading_writing = PoseGazeEstimator.classify(yaw, pitch, roll)
        return HeadPoseResult(
            yaw=round(yaw, 1),
            pitch=round(pitch, 1),
            roll=round(roll, 1),
            posture=posture,
            is_facing_screen=is_facing_screen,
            is_reading_writing_pose=is_reading_writing,
        )

    # ----------------------------------------------------------------- gaze

    def _build_gaze(self, raw: List[Tuple[float, float, float]], pose: HeadPoseResult) -> GazeResult:
        iris_dx = iris_dy = 0.0
        try:
            # Iris center offset between the eye-corner midpoint, normalized by
            # eye width (x) — a true eye-only deviation signal.
            l_mid = ((raw[33][0] + raw[133][0]) / 2.0, (raw[33][1] + raw[133][1]) / 2.0)
            r_mid = ((raw[263][0] + raw[362][0]) / 2.0, (raw[263][1] + raw[362][1]) / 2.0)
            l_w = max(1e-6, abs(raw[133][0] - raw[33][0]))
            r_w = max(1e-6, abs(raw[362][0] - raw[263][0]))
            iris_dx = (
                (raw[LEFT_IRIS_IDX][0] - l_mid[0]) / l_w
                + (raw[RIGHT_IRIS_IDX][0] - r_mid[0]) / r_w
            ) / 2.0
            l_h = max(1e-6, abs(raw[159][1] - raw[145][1]) + abs(raw[158][1] - raw[153][1]))
            iris_dy = ((raw[LEFT_IRIS_IDX][1] - l_mid[1]) / l_h)
        except IndexError:
            iris_dx = iris_dy = 0.0

        gaze_x = max(-1.0, min(1.0, (pose.yaw / 45.0) * 0.75 + iris_dx * 1.5))
        gaze_y = max(-1.0, min(1.0, (pose.pitch / 40.0) * 0.75 + iris_dy * 1.5))
        is_focused = abs(gaze_x) <= 0.55 and gaze_y <= 0.62
        confidence = 0.90 if is_focused else 0.85

        return GazeResult(
            gaze_x=round(gaze_x, 3),
            gaze_y=round(gaze_y, 3),
            is_focused=is_focused,
            confidence=confidence,
        )

    # ------------------------------------------------------- phone detector

    def _detect_phone(self, mp_image) -> bool:
        try:
            det = self._object_detector.detect(mp_image)
            for detection in getattr(det, "detections", []) or []:
                for category in detection.categories:
                    if category.category_name.lower() in _PHONE_LABELS and category.score >= _PHONE_SCORE_THRESHOLD:
                        return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("Object detector tick failed: %s", exc)
        return False

    # -------------------------------------------------------------- overlay

    _STATE_COLORS = {
        "focused": (90, 200, 90),      # BGR green
        "drifting": (60, 165, 255),    # BGR amber
        "distracted": (60, 60, 230),   # BGR red
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
            for (x, y, _z) in result.raw_landmarks:
                cv2.circle(overlay, (int(x * w), int(y * h)), 1, (255, 235, 160), -1)
            annotated = cv2.addWeighted(overlay, 0.35, annotated, 0.65, 0)

            nx, ny = int(result.raw_landmarks[NOSE_TIP_IDX][0] * w), int(result.raw_landmarks[NOSE_TIP_IDX][1] * h)
            if result.gaze is not None:
                dx = int(result.gaze.gaze_x * 110)
                dy = int(result.gaze.gaze_y * 110)
                cv2.arrowedLine(annotated, (nx, ny), (nx + dx, ny + dy), (255, 255, 120), 2, tipLength=0.28)
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
        cv2.putText(annotated, hud_bits[0], (18, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2)
        if len(hud_bits) > 1:
            cv2.putText(annotated, hud_bits[1][:34], (18, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1)
        return annotated


_singleton: Optional[PythonFaceProcessor] = None


def get_python_face_processor() -> PythonFaceProcessor:
    """Process-wide processor singleton (models are heavy; one instance serves all sessions)."""
    global _singleton
    if _singleton is None:
        _singleton = PythonFaceProcessor()
    return _singleton
