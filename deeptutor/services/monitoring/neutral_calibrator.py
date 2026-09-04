"""Per-session neutral head-pose calibration.

Owns the "where does this student naturally sit" zero-point that absolute
camera placement would otherwise inject into every yaw/pitch/roll reading.

Lives on the per-session ``LocalCVPipeline`` (NOT on the process-wide
``PythonFaceProcessor`` singleton): two sessions — or a session plus a
pre-flight probe — sharing one processor used to reset each other's
calibration mid-stream.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class NeutralCalibrator:
    """Collects roughly-frontal samples, then re-centers head pose on their median.

    ``apply`` is called for every frame with RAW (uncalibrated) angles:

    - While collecting (no zero-point yet): samples within the frontal gate
      accumulate; the pose passes through untouched. Prevents desk-looking or
      turned-around startup from poisoning the baseline.
    - Once locked: returns (yaw, pitch, roll) minus the locked zero-point.
    """

    FRONTAL_GATE = (20.0, 25.0, 15.0)  # max |yaw|, |pitch|, |roll| to count as neutral

    def __init__(self, samples: int = 12) -> None:
        self._n = max(1, int(samples))
        self._buf: List[Tuple[float, float, float]] = []
        self._zero: Optional[Tuple[float, float, float]] = None

    @property
    def calibrated(self) -> bool:
        return self._zero is not None

    def reset(self) -> None:
        """Clear calibration for a fresh study session."""
        self._buf.clear()
        self._zero = None

    def apply(self, yaw: float, pitch: float, roll: float) -> Tuple[float, float, float]:
        if self._zero is None:
            max_yaw, max_pitch, max_roll = self.FRONTAL_GATE
            if abs(yaw) < max_yaw and abs(pitch) < max_pitch and abs(roll) < max_roll:
                self._buf.append((yaw, pitch, roll))
                if len(self._buf) >= self._n:
                    med = np.median(np.array(self._buf), axis=0)
                    self._zero = (float(med[0]), float(med[1]), float(med[2]))
                    logger.info("Head-pose neutral calibrated: %s", self._zero)
            return yaw, pitch, roll
        zy, zp, zr = self._zero
        return yaw - zy, pitch - zp, roll - zr
