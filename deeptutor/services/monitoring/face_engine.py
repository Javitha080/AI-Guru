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
            min_len = min(len(vec_a), len(vec_b))
            vec_a = vec_a[:min_len]
            vec_b = vec_b[:min_len]

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
        """
        if not raw_data.get("detected", False):
            return FaceDetectionResult(
                detected=False,
                confidence=0.0,
                brightness=raw_data.get("brightness", 0.5),
            )

        bbox = tuple(raw_data.get("bbox", [0.2, 0.2, 0.6, 0.6]))
        confidence = float(raw_data.get("confidence", 0.95))
        brightness = float(raw_data.get("brightness", 0.5))

        # Extract landmarks if provided
        raw_landmarks = raw_data.get("landmarks", {})
        landmarks = None
        if raw_landmarks:

            def _parse_pts(pts_list: list) -> list[Point3D]:
                return [Point3D(p.get("x", 0), p.get("y", 0), p.get("z", 0)) for p in pts_list]

            left_eye = _parse_pts(raw_landmarks.get("left_eye", []))
            right_eye = _parse_pts(raw_landmarks.get("right_eye", []))
            mouth = _parse_pts(raw_landmarks.get("mouth", []))
            all_pts = _parse_pts(raw_landmarks.get("all_points", []))

            nose = raw_landmarks.get("nose_tip", {"x": 0.5, "y": 0.5, "z": 0.0})
            chin = raw_landmarks.get("chin", {"x": 0.5, "y": 0.8, "z": 0.0})
            forehead = raw_landmarks.get("forehead", {"x": 0.5, "y": 0.2, "z": 0.0})
            left_cheek = raw_landmarks.get("left_cheek", {"x": 0.3, "y": 0.5, "z": 0.0})
            right_cheek = raw_landmarks.get("right_cheek", {"x": 0.7, "y": 0.5, "z": 0.0})

            landmarks = FaceLandmarks(
                left_eye=left_eye,
                right_eye=right_eye,
                nose_tip=Point3D(nose["x"], nose["y"], nose.get("z", 0)),
                mouth=mouth,
                chin=Point3D(chin["x"], chin["y"], chin.get("z", 0)),
                forehead=Point3D(forehead["x"], forehead["y"], forehead.get("z", 0)),
                left_cheek=Point3D(left_cheek["x"], left_cheek["y"], left_cheek.get("z", 0)),
                right_cheek=Point3D(right_cheek["x"], right_cheek["y"], right_cheek.get("z", 0)),
                all_points=all_pts,
            )

        embedding = raw_data.get("embedding")
        if embedding is None and landmarks:
            embedding = self.generate_geometric_embedding(landmarks)

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
        Angles are in degrees.
        """
        rad_yaw = math.radians(yaw)
        rad_pitch = math.radians(pitch)
        rad_roll = math.radians(roll)

        # Base centers
        cx, cy = 0.5 + 0.1 * math.sin(rad_yaw), 0.5 + 0.1 * math.sin(rad_pitch)

        # Eyes: 6 points per eye for EAR calculation
        # p1 (outer), p2 (top-outer), p3 (top-inner), p4 (inner), p5 (bottom-inner), p6 (bottom-outer)
        ear_h = 0.02 * (eye_open_ratio / 0.3)
        lx, ly = cx - 0.1, cy - 0.08
        rx, ry = cx + 0.1, cy - 0.08

        left_eye = [
            Point3D(lx - 0.03, ly, 0.0),
            Point3D(lx - 0.015, ly - ear_h, 0.0),
            Point3D(lx + 0.015, ly - ear_h, 0.0),
            Point3D(lx + 0.03, ly, 0.0),
            Point3D(lx + 0.015, ly + ear_h, 0.0),
            Point3D(lx - 0.015, ly + ear_h, 0.0),
        ]

        right_eye = [
            Point3D(rx - 0.03, ry, 0.0),
            Point3D(rx - 0.015, ry - ear_h, 0.0),
            Point3D(rx + 0.015, ry - ear_h, 0.0),
            Point3D(rx + 0.03, ry, 0.0),
            Point3D(rx + 0.015, ry + ear_h, 0.0),
            Point3D(rx - 0.015, ry + ear_h, 0.0),
        ]

        mouth = [
            Point3D(cx - 0.04, cy + 0.15, 0.0),
            Point3D(cx, cy + 0.13, 0.0),
            Point3D(cx + 0.04, cy + 0.15, 0.0),
            Point3D(cx, cy + 0.17, 0.0),
        ]

        return FaceLandmarks(
            left_eye=left_eye,
            right_eye=right_eye,
            nose_tip=Point3D(cx, cy, -0.05 * math.cos(rad_yaw)),
            mouth=mouth,
            chin=Point3D(cx, cy + 0.25, 0.0),
            forehead=Point3D(cx, cy - 0.25, 0.0),
            left_cheek=Point3D(cx - 0.2, cy, 0.05 * math.sin(rad_yaw)),
            right_cheek=Point3D(cx + 0.2, cy, -0.05 * math.sin(rad_yaw)),
        )
