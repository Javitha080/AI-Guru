"""SFace neural face identity (real face recognition, replaces inert ratios).

The geometric "embedding" (face-proportion ratios + angles) is nearly
identical across all human faces — two different frontal people score cosine
≈0.99 against a 0.65 threshold, so ``IDENTITY_MISMATCH`` could never fire for
a real impostor (empirically verified: 0.9979 for two structurally different
synthetic faces). SFace is a trained face-recognition network shipping inside
opencv-contrib (already a monitoring dependency); its OpenCV-zoo cosine
threshold is 0.363.

Model: ``face_recognition_sface_2021dec.onnx`` (OpenCV Zoo, Apache-2.0).
Fetch with ``python scripts/fetch_sface_model.py`` — until the model is
present this module reports ``available=False`` and the engine transparently
falls back to the (clearly-labelled) geometric mode.

Everything runs locally: zero cloud egress.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_SFACE_MODEL = _REPO_ROOT / "deeptutor" / "models" / "face_recognition_sface_2021dec.onnx"

# OpenCV Zoo SFace cosine similarity decision threshold.
SFACE_COSINE_THRESHOLD = 0.363

# MediaPipe landmark indices for the YuNet-style 15-float alignment row:
# subject-right eye (image-left), subject-left eye (image-right), nose tip,
# mouth corners.
_RE_YE = (33, 133)  # right eye outer/inner (image-left side)
_LE_YE = (263, 362)  # left eye outer/inner (image-right side)
_NOSE_TIP = 1
_MOUTH_R = 61
_MOUTH_L = 291


def _load_cv2():
    try:
        import cv2

        return cv2
    except Exception:  # noqa: BLE001
        return None


class SFaceIdentity:
    """Thin wrapper over ``cv2.FaceRecognizerSF`` with MediaPipe-landmark alignment."""

    def __init__(self, model_path: str, threshold: float = SFACE_COSINE_THRESHOLD) -> None:
        self.model_path = model_path
        self.threshold = threshold
        self._rec = None
        self._cv2 = _load_cv2()
        if self._cv2 is not None:
            try:
                self._rec = self._cv2.FaceRecognizerSF.create(model_path, "")
            except Exception as exc:  # noqa: BLE001
                logger.warning("SFace model failed to load (%s): %s", model_path, exc)
                self._rec = None

    @property
    def available(self) -> bool:
        return self._rec is not None and self._cv2 is not None

    @classmethod
    def create_default(cls) -> Optional["SFaceIdentity"]:
        path = os.environ.get("DEEPTUTOR_SFACE_MODEL_PATH") or str(_DEFAULT_SFACE_MODEL)
        cv2 = _load_cv2()
        if cv2 is None or not Path(path).is_file():
            return None
        return cls(path)

    # ------------------------------------------------------------- helpers

    @staticmethod
    def decode_bgr(jpeg_b64: str) -> Optional[np.ndarray]:
        """Decode a base64 JPEG to a BGR array; None on garbage."""
        cv2 = _load_cv2()
        if cv2 is None:
            return None
        try:
            buf = np.frombuffer(base64.b64decode(jpeg_b64), dtype=np.uint8)
            return cv2.imdecode(buf, cv2.IMREAD_COLOR)
        except Exception:  # noqa: BLE001
            return None

    def embed_normalized(
        self, bgr: np.ndarray, normalized_landmarks: Sequence[Tuple[float, float, float]]
    ) -> Optional[np.ndarray]:
        """Embed a face from a BGR frame + NORMALIZED MediaPipe landmarks.

        Both engine paths deliver normalized coordinates, so pixel mapping
        uses the frame's own dimensions (snapshots may be downscaled — same
        aspect ratio, alignment is scale-invariant after ``alignCrop``).
        """
        if self._rec is None or self._cv2 is None or bgr is None:
            return None
        if not normalized_landmarks or len(normalized_landmarks) <= max(
            *_LE_YE, *_RE_YE, _NOSE_TIP, _MOUTH_R, _MOUTH_L
        ):
            return None
        h, w = bgr.shape[:2]

        def px(i: int) -> Tuple[float, float]:
            return float(normalized_landmarks[i][0]) * w, float(normalized_landmarks[i][1]) * h

        try:
            xs = [float(p[0]) * w for p in normalized_landmarks]
            ys = [float(p[1]) * h for p in normalized_landmarks]
            box = [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
            re = np.mean([px(33), px(133)], axis=0)
            le = np.mean([px(263), px(362)], axis=0)
            row = np.array(
                [*box, *re, *le, *px(_NOSE_TIP), *px(_MOUTH_R), *px(_MOUTH_L), 1.0],
                dtype=np.float32,
            ).reshape(1, 15)
            aligned = self._rec.alignCrop(bgr, row)
            if aligned is None or aligned.size == 0:
                return None
            return self._rec.feature(aligned).flatten()
        except Exception as exc:  # noqa: BLE001
            logger.debug("SFace embed failed: %s", exc)
            return None

    def similarity(self, emb_a: np.ndarray, emb_b: np.ndarray) -> float:
        """Cosine similarity via the recognizer's own matcher."""
        if self._rec is None or self._cv2 is None:
            return 0.0
        try:
            return float(self._rec.match(emb_a, emb_b, self._cv2.FaceRecognizerSF_FR_COSINE))
        except Exception:  # noqa: BLE001
            return 0.0

    def verify(self, current: np.ndarray, baseline: np.ndarray) -> Tuple[bool, float]:
        sim = self.similarity(current, baseline)
        return sim >= self.threshold, sim

    def enroll_median(self, embeddings: Sequence[np.ndarray]) -> Optional[np.ndarray]:
        """Robust enrollment template: per-dimension median of ≥N samples.

        One frame is a pose/expression snapshot; the median over a short
        frontal burst is far more stable.
        """
        if not embeddings:
            return None
        stack = np.stack([np.asarray(e, dtype=np.float64).flatten() for e in embeddings])
        return np.median(stack, axis=0)


def enroll_sface_from_engine(
    sface: SFaceIdentity, samples: List[np.ndarray]
) -> Optional[List[float]]:
    """Build the persisted enrollment vector from SFace samples."""
    template = sface.enroll_median(samples)
    if template is None:
        return None
    return [float(v) for v in template]


__all__ = [
    "SFaceIdentity",
    "SFACE_COSINE_THRESHOLD",
    "enroll_sface_from_engine",
]
