"""
AI Guru Local Face Engine.
==========================

Provides local face detection, landmark extraction, and identity verification
against enrolled baseline feature vectors.

Guarantees 100% on-device execution with zero cloud egress.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import math
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _coerce_float(value: Any, default: float) -> float:
    """Finite-float coercion shared by the telemetry fast path."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


@dataclass
class Point3D:
    x: float
    y: float
    z: float = 0.0


@dataclass
class FaceLandmarks:
    """Standardized facial landmarks structure."""

    left_eye: List[Point3D] = field(default_factory=list)
    right_eye: List[Point3D] = field(default_factory=list)
    nose_tip: Point3D = field(default_factory=lambda: Point3D(0.5, 0.5, 0.0))
    mouth: List[Point3D] = field(default_factory=list)
    chin: Point3D = field(default_factory=lambda: Point3D(0.5, 0.8, 0.0))
    forehead: Point3D = field(default_factory=lambda: Point3D(0.5, 0.2, 0.0))
    left_cheek: Point3D = field(default_factory=lambda: Point3D(0.3, 0.5, 0.0))
    right_cheek: Point3D = field(default_factory=lambda: Point3D(0.7, 0.5, 0.0))
    all_points: List[Point3D] = field(default_factory=list)


@dataclass
class FaceDetectionResult:
    """Result of local face detection and landmark extraction."""

    detected: bool
    confidence: float = 0.0
    bounding_box: Tuple[float, float, float, float] = (
        0.0,
        0.0,
        0.0,
        0.0,
    )  # x, y, width, height (normalized 0-1)
    landmarks: Optional[FaceLandmarks] = None
    embedding: Optional[List[float]] = None  # 128D or normalized feature vector
    brightness: float = 0.5  # Mean image luminance (0-255 or 0-1 normalized)


class FaceEngine:
    """
    Local face detection and identity verification engine.
    Computes genuine geometric embeddings and cosine similarity matching.
    """

    MATCH_THRESHOLD: float = 0.65  # Cosine similarity threshold for match

    def __init__(self, match_threshold: float = 0.65) -> None:
        self.match_threshold = match_threshold
        self._enrolled_embedding: Optional[List[float]] = None

    def enroll_face(self, embedding: List[float]) -> None:
        """Enroll the baseline student identity embedding."""
        if not embedding or len(embedding) == 0:
            raise ValueError("Face embedding must not be empty.")
        self._enrolled_embedding = self._normalize_vector(embedding)
        logger.info(
            "Enrolled baseline face embedding (dimension=%d)", len(self._enrolled_embedding)
        )

    def get_enrolled_face(self) -> Optional[List[float]]:
        """Return the enrolled baseline feature vector."""
        return self._enrolled_embedding

    @staticmethod
    def _normalize_vector(vec: List[float]) -> List[float]:
        """L2-normalize a feature vector."""
        norm = math.sqrt(sum(v * v for v in vec))
        if norm < 1e-12:
            return [0.0] * len(vec)
        return [v / norm for v in vec]

    @staticmethod
    def compute_cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """
        Compute genuine cosine similarity between two feature vectors:
        Cosine Sim = (A . B) / (||A|| * ||B||)
        """
        if not vec_a or not vec_b:
            return 0.0
        if len(vec_a) != len(vec_b):
            # Never silently truncate: comparing vectors from DIFFERENT
            # embedding spaces by their overlapping prefix produced confident
            # garbage. A dimension mismatch is a mismatch.
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))

        if norm_a < 1e-12 or norm_b < 1e-12:
            return 0.0

        similarity = dot_product / (norm_a * norm_b)
        return max(-1.0, min(1.0, similarity))

    def verify_identity(
        self,
        current_embedding: List[float],
        baseline_embedding: Optional[List[float]] = None,
    ) -> Tuple[bool, float]:
        """
        Verify if current face matches enrolled student baseline.
        Returns (is_match, similarity_score).
        """
        target_baseline = baseline_embedding or self._enrolled_embedding
        if target_baseline is None:
            # If no baseline is enrolled, identity check passes in un-enrolled mode
            return True, 1.0

        sim = self.compute_cosine_similarity(current_embedding, target_baseline)
        is_match = sim >= self.match_threshold
        return is_match, round(sim, 4)

    def extract_landmarks_from_telemetry(self, raw_data: dict[str, Any]) -> FaceDetectionResult:
        """
        Construct FaceDetectionResult from client-side WebWorker / MediaPipe telemetry.

        Fail-closed: malformed payloads never raise and never look focused.
        Missing/invalid numbers fall back to safe defaults; invalid landmarks
        yield detected=True with landmarks=None (downstream estimators then
        report UNKNOWN / not-focused rather than crashing).
        """
        # Fast path: the system engine passes its ALREADY-CONSTRUCTED
        # FaceLandmarks object inline (no dict round-trip — serializing 478
        # points to dicts and re-parsing them every tick cost ~10k dict
        # allocations/s on the event loop).
        if isinstance(raw_data, dict) and isinstance(raw_data.get("_landmarks_obj"), FaceLandmarks):
            obj: FaceLandmarks = raw_data["_landmarks_obj"]
            embedding = raw_data.get("embedding")
            if not isinstance(embedding, list) or not embedding:
                try:
                    embedding = self.generate_geometric_embedding(obj)
                except Exception:  # noqa: BLE001
                    embedding = None
            return FaceDetectionResult(
                detected=True,
                confidence=max(
                    0.0, min(1.0, _coerce_float(raw_data.get("confidence", 0.95), 0.95))
                ),
                bounding_box=(0.2, 0.2, 0.6, 0.6),
                landmarks=obj,
                embedding=embedding,
                brightness=_coerce_float(raw_data.get("brightness", 0.5), 0.5),
            )

        if not isinstance(raw_data, dict) or not raw_data.get("detected", False):
            brightness = 0.5
            try:
                if isinstance(raw_data, dict):
                    brightness = float(raw_data.get("brightness", 0.5))
                    if not math.isfinite(brightness):
                        brightness = 0.5
            except (TypeError, ValueError):
                brightness = 0.5
            return FaceDetectionResult(
                detected=False,
                confidence=0.0,
                brightness=brightness,
            )

        def _safe_float(value: Any, default: float) -> float:
            try:
                v = float(value)
            except (TypeError, ValueError):
                return default
            if not math.isfinite(v):
                return default
            return v

        def _safe_point(value: Any, default: Point3D) -> Point3D:
            if not isinstance(value, dict):
                return default
            return Point3D(
                x=_safe_float(value.get("x", default.x), default.x),
                y=_safe_float(value.get("y", default.y), default.y),
                z=_safe_float(value.get("z", default.z), default.z),
            )

        raw_bbox = raw_data.get("bbox", [0.2, 0.2, 0.6, 0.6])
        try:
            bbox_list = (
                list(raw_bbox) if isinstance(raw_bbox, (list, tuple)) else [0.2, 0.2, 0.6, 0.6]
            )
            if len(bbox_list) != 4:
                raise ValueError("bbox must have 4 elements")
            bbox_vals = tuple(max(0.0, min(1.0, _safe_float(v, 0.0))) for v in bbox_list)
            bbox: Tuple[float, float, float, float] = (
                bbox_vals[0],
                bbox_vals[1],
                bbox_vals[2],
                bbox_vals[3],
            )
        except (TypeError, ValueError):
            bbox = (0.2, 0.2, 0.6, 0.6)
        confidence = max(0.0, min(1.0, _safe_float(raw_data.get("confidence", 0.95), 0.0)))
        brightness = _safe_float(raw_data.get("brightness", 0.5), 0.5)

        # Extract landmarks if provided
        raw_landmarks = raw_data.get("landmarks", {})
        if not isinstance(raw_landmarks, dict):
            raw_landmarks = {}
        landmarks = None
        if raw_landmarks:

            def _parse_pts(pts_list: Any) -> list[Point3D]:
                if not isinstance(pts_list, list):
                    return []
                out: list[Point3D] = []
                for p in pts_list:
                    if not isinstance(p, dict):
                        continue
                    out.append(
                        Point3D(
                            x=_safe_float(p.get("x", 0.0), 0.0),
                            y=_safe_float(p.get("y", 0.0), 0.0),
                            z=_safe_float(p.get("z", 0.0), 0.0),
                        )
                    )
                return out

            left_eye = _parse_pts(raw_landmarks.get("left_eye", []))
            right_eye = _parse_pts(raw_landmarks.get("right_eye", []))
            mouth = _parse_pts(raw_landmarks.get("mouth", []))
            all_pts = _parse_pts(raw_landmarks.get("all_points", []))

            nose = _safe_point(raw_landmarks.get("nose_tip"), Point3D(0.5, 0.5, 0.0))
            chin = _safe_point(raw_landmarks.get("chin"), Point3D(0.5, 0.8, 0.0))
            forehead = _safe_point(raw_landmarks.get("forehead"), Point3D(0.5, 0.2, 0.0))
            left_cheek = _safe_point(raw_landmarks.get("left_cheek"), Point3D(0.3, 0.5, 0.0))
            right_cheek = _safe_point(raw_landmarks.get("right_cheek"), Point3D(0.7, 0.5, 0.0))

            landmarks = FaceLandmarks(
                left_eye=left_eye,
                right_eye=right_eye,
                nose_tip=nose,
                mouth=mouth,
                chin=chin,
                forehead=forehead,
                left_cheek=left_cheek,
                right_cheek=right_cheek,
                all_points=all_pts,
            )

        embedding = raw_data.get("embedding")
        if not isinstance(embedding, list) or len(embedding) == 0:
            embedding = None
        else:
            # Keep only finite numbers; drop garbage vectors entirely.
            clean: List[float] = []
            for v in embedding:
                try:
                    f = float(v)
                except (TypeError, ValueError):
                    clean = []
                    break
                if not math.isfinite(f):
                    clean = []
                    break
                clean.append(f)
            embedding = clean if len(clean) >= 2 else None
        if embedding is None and landmarks:
            try:
                embedding = self.generate_geometric_embedding(landmarks)
            except Exception:  # noqa: BLE001 - geometric fallback must not crash
                embedding = None

        return FaceDetectionResult(
            detected=True,
            confidence=confidence,
            bounding_box=bbox,  # type: ignore
            landmarks=landmarks,
            embedding=embedding,
            brightness=brightness,
        )

    def generate_geometric_embedding(self, landmarks: FaceLandmarks) -> List[float]:
        """
        Generate a genuine 128D geometric face feature vector from key facial landmarks.
        Uses normalized pairwise euclidean distances and ratio angles between facial anchors.
        """
        anchors = [
            landmarks.nose_tip,
            landmarks.chin,
            landmarks.forehead,
            landmarks.left_cheek,
            landmarks.right_cheek,
        ]
        if landmarks.left_eye:
            anchors.append(landmarks.left_eye[0])
            if len(landmarks.left_eye) > 1:
                anchors.append(landmarks.left_eye[len(landmarks.left_eye) // 2])
        if landmarks.right_eye:
            anchors.append(landmarks.right_eye[0])
            if len(landmarks.right_eye) > 1:
                anchors.append(landmarks.right_eye[len(landmarks.right_eye) // 2])
        if landmarks.mouth:
            anchors.append(landmarks.mouth[0])
            if len(landmarks.mouth) > 1:
                anchors.append(landmarks.mouth[len(landmarks.mouth) // 2])

        # Compute inter-landmark distance matrix
        features: List[float] = []
        # Normalization scale (inter-ocular or nose-to-chin distance)
        dx = landmarks.right_cheek.x - landmarks.left_cheek.x
        dy = landmarks.right_cheek.y - landmarks.left_cheek.y
        scale = math.sqrt(dx * dx + dy * dy)
        if scale < 1e-6:
            scale = 1.0

        for i in range(len(anchors)):
            for j in range(i + 1, len(anchors)):
                p1, p2 = anchors[i], anchors[j]
                dist = (
                    math.sqrt((p1.x - p2.x) ** 2 + (p1.y - p2.y) ** 2 + (p1.z - p2.z) ** 2) / scale
                )
                features.append(dist)
                angle = math.atan2(p2.y - p1.y, p2.x - p1.x)
                features.append(angle / math.pi)

        # Pad or interpolate to exactly 128 dimensions
        target_dim = 128
        if len(features) < target_dim:
            # Repeat and modulate features deterministically
            reps = (target_dim // len(features)) + 1
            extended = (features * reps)[:target_dim]
            features = [v * (1.0 + 0.05 * math.sin(idx)) for idx, v in enumerate(extended)]
        elif len(features) > target_dim:
            features = features[:target_dim]

        return self._normalize_vector(features)

    def create_synthetic_landmarks(
        self,
        yaw: float = 0.0,
        pitch: float = 0.0,
        roll: float = 0.0,
        eye_open_ratio: float = 0.3,
    ) -> FaceLandmarks:
        """
        Generate realistic synthetic 3D landmarks for headless/test simulation.
        Angles are in degrees. (Delegates to monitoring.synthetic.)
        """
        from deeptutor.services.monitoring.synthetic import create_synthetic_landmarks as _make

        return _make(yaw=yaw, pitch=pitch, roll=roll, eye_open_ratio=eye_open_ratio)
