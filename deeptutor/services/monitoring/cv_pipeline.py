"""
AI Guru Local Computer Vision Processing Pipeline.
==================================================

Orchestrates local-first video frame processing and telemetry analysis:
- Rate-limited inference (5-10 FPS, dynamically scaled by ResourceGovernor)
- 100% On-device execution with ZERO cloud egress invariant
- Headless mock simulation generator for automated testing without physical camera
- Modular integration of FaceEngine, LivenessDetector, PoseGazeEstimator,
  PresenceStateMachine, EngagementEstimator, DistractionAnalyzer, and WarningManager.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any, Dict, List, Optional

from deeptutor.services.governor import ResourceGovernor, get_resource_governor
from deeptutor.services.monitoring.distraction_analyzer import (
    DistractionAnalysisResult,
    DistractionAnalyzer,
)
from deeptutor.services.monitoring.engagement_estimator import (
    EngagementEstimator,
    EngagementSnapshot,
)
from deeptutor.services.monitoring.face_engine import (
    FaceEngine,
    FaceLandmarks,
)
from deeptutor.services.monitoring.liveness_detector import (
    LivenessDetector,
    LivenessResult,
)
from deeptutor.services.monitoring.pose_gaze import (
    GazeResult,
    HeadPoseResult,
    PoseGazeEstimator,
)
from deeptutor.services.monitoring.presence_state_machine import (
    PresenceStateMachine,
    PresenceStateResult,
)
from deeptutor.services.monitoring.schemas import (
    build_gaze_result,
    build_pose_result,
    parse_pose_gaze,
)
from deeptutor.services.monitoring.warning_manager import (
    WarningEvent,
    WarningManager,
)

logger = logging.getLogger(__name__)


@dataclass
class FrameAnalysisResult:
    """Consolidated telemetry and monitoring inference output."""

    timestamp: float
    fps: float
    face_detected: bool
    presence: PresenceStateResult
    pose: HeadPoseResult
    gaze: GazeResult
    liveness: LivenessResult
    engagement: EngagementSnapshot
    distraction: DistractionAnalysisResult
    identity_matched: bool
    identity_similarity: float
    dispatched_warning: Optional[WarningEvent] = None
    cloud_egress_bytes: int = 0  # Invariant: Must always remain 0


class LocalCVPipeline:
    """
    Unified local Computer Vision study monitoring pipeline.
    """

    DEFAULT_BASE_FPS: int = 10

    def __init__(
        self,
        base_fps: int = DEFAULT_BASE_FPS,
        governor: Optional[ResourceGovernor] = None,
        face_engine: Optional[FaceEngine] = None,
        liveness_detector: Optional[LivenessDetector] = None,
        pose_estimator: Optional[PoseGazeEstimator] = None,
        state_machine: Optional[PresenceStateMachine] = None,
        engagement_estimator: Optional[EngagementEstimator] = None,
        distraction_analyzer: Optional[DistractionAnalyzer] = None,
        warning_manager: Optional[WarningManager] = None,
    ) -> None:
        self.base_fps = base_fps
        self.governor = governor or get_resource_governor()

        # Component instances
        self.face_engine = face_engine or FaceEngine()
        self.liveness_detector = liveness_detector or LivenessDetector()
        self.pose_estimator = pose_estimator or PoseGazeEstimator()
        self.state_machine = state_machine or PresenceStateMachine()
        self.engagement_estimator = engagement_estimator or EngagementEstimator()
        self.distraction_analyzer = distraction_analyzer or DistractionAnalyzer()
        self.warning_manager = warning_manager or WarningManager()

        # Runtime metrics
        self._frame_count: int = 0
        self._last_process_time: float = 0.0
        self._actual_fps: float = float(base_fps)
        self._session_start_time: float = time.time()
        self._enrolled_face_vector: Optional[List[float]] = None

    def reset_session(self) -> None:
        """Reset all stateful detectors for a fresh study session."""
        self._frame_count = 0
        self._last_process_time = 0.0
        self._session_start_time = time.time()
        self.liveness_detector.reset()
        self.state_machine.reset(self._session_start_time)
        self.engagement_estimator.reset()
        self.distraction_analyzer.reset()
        self.warning_manager.reset()

    def enroll_student_baseline(self, embedding: List[float]) -> None:
        """Enroll the student baseline facial feature vector."""
        self._enrolled_face_vector = embedding
        self.face_engine.enroll_face(embedding)

    def get_current_target_fps(self) -> int:
        """Calculate dynamic target FPS governed by system load."""
        return self.governor.get_recommended_cv_fps(self.base_fps)

    def process_telemetry_payload(
        self,
        payload: Dict[str, Any],
        current_time: Optional[float] = None,
    ) -> FrameAnalysisResult:
        """
        Process structured frame telemetry received from client-side WebWorker / MediaPipe.
        """
        if not isinstance(payload, dict):
            payload = {"detected": False, "confidence": 0.0, "brightness": 0.5}
        now = current_time if current_time is not None else time.time()
        try:
            now_f = float(now)
            if not (now_f == now_f and abs(now_f) != float("inf")):
                now = time.time()
            else:
                now = now_f
        except (TypeError, ValueError):
            now = time.time()
        self._frame_count += 1

        # Calculate FPS
        if self._last_process_time > 0.0:
            dt = max(0.001, now - self._last_process_time)
            instant_fps = 1.0 / dt
            self._actual_fps = 0.9 * self._actual_fps + 0.1 * instant_fps
        self._last_process_time = now

        # 1. Extract Face Detection and Landmarks
        face_res = self.face_engine.extract_landmarks_from_telemetry(payload)

        # 2. Identity Verification (fail-closed: face claimed but no usable
        # embedding must NOT verify as the enrolled student).
        is_identity_match = True
        identity_sim = 1.0
        if face_res.detected and face_res.embedding:
            is_identity_match, identity_sim = self.face_engine.verify_identity(
                face_res.embedding,
                self._enrolled_face_vector,
            )
        elif face_res.detected:
            # No embedding and no landmarks-derived vector: cannot verify.
            # When a baseline is enrolled this is a mismatch; in un-enrolled
            # mode (no baseline) keep the legacy pass so pre-enrollment
            # sessions are not flagged.
            if self._enrolled_face_vector is not None:
                is_identity_match = False
                identity_sim = 0.0

        # 3. Liveness Analysis
        laplacian_val = payload.get("texture_laplacian_var")
        ear_override = payload.get("ear_override")
        liveness_res = self.liveness_detector.evaluate_frame(
            landmarks=face_res.landmarks,
            timestamp=now,
            texture_laplacian_var=laplacian_val,
            ear_override=ear_override,
        )

        # 4. Head Pose and Gaze Estimation (shared schema helpers)
        raw_p, raw_g = parse_pose_gaze(payload)
        if raw_p is not None and raw_g is not None:
            pose_res = build_pose_result(raw_p)
            gaze_res = build_gaze_result(raw_g)
        else:
            pose_gaze = self.pose_estimator.process(face_res.landmarks)
            pose_res = pose_gaze.pose
            gaze_res = pose_gaze.gaze

        # 5. Presence State Machine
        presence_res = self.state_machine.update(
            face_detected=face_res.detected,
            confidence=face_res.confidence,
            timestamp=now,
            brightness=face_res.brightness,
        )

        # 6. Distraction Analysis with False-Positive Whitelist
        phone_detected = bool(payload.get("phone_detected", False))
        hand_to_mouth = bool(payload.get("hand_to_mouth_gesture", False))
        page_turn = bool(payload.get("page_turn_gesture", False))
        writing_gesture = (
            bool(payload.get("writing_gesture", False)) or pose_res.is_reading_writing_pose
        )

        distraction_res = self.distraction_analyzer.analyze(
            timestamp=now,
            presence_state=presence_res.state,
            pose=pose_res,
            liveness=liveness_res,
            identity_match=is_identity_match,
            phone_object_detected=phone_detected,
            hand_to_mouth_gesture=hand_to_mouth,
            page_turn_gesture=page_turn,
            writing_gesture=writing_gesture,
            gaze=gaze_res,
        )

        # 7. Engagement Estimation
        engagement_res = self.engagement_estimator.update(
            presence_state=presence_res.state,
            pose=pose_res,
            gaze_focused=gaze_res.is_focused,
            is_distracted=distraction_res.is_distracted,
        )

        # 8. Warning Dispatcher & Cooldown (episode-aware: observe first so a
        # state that stays true frame-after-frame notifies once, not per cooldown).
        # Tiered: a gentle nudge may fire early in the episode ([3s,6s) window);
        # the real warning/alert tier keeps its classic gates untouched.
        # evaluate() does observe+dispatch atomically (no ordering bugs).
        warning_event = self.warning_manager.evaluate(
            timestamp=now,
            distraction=distraction_res,
        )

        return FrameAnalysisResult(
            timestamp=now,
            fps=round(self._actual_fps, 1),
            face_detected=face_res.detected,
            presence=presence_res,
            pose=pose_res,
            gaze=gaze_res,
            liveness=liveness_res,
            engagement=engagement_res,
            distraction=distraction_res,
            identity_matched=is_identity_match,
            identity_similarity=identity_sim,
            dispatched_warning=warning_event,
            cloud_egress_bytes=0,  # Strict zero cloud egress guarantee
        )

    def generate_mock_telemetry(
        self,
        scenario: str = "normal_study",
        timestamp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Generate synthetic telemetry payloads for headless CI/CD and unit testing.
        Delegates to monitoring.synthetic (kept as shim for backward-compat).
        """
        from deeptutor.services.monitoring.synthetic import generate_mock_telemetry as _gen

        return _gen(self.face_engine, scenario=scenario, timestamp=timestamp)

    @staticmethod
    def _landmarks_to_dict(landmarks: FaceLandmarks) -> Dict[str, Any]:
        """Convert FaceLandmarks dataclass to serialized telemetry dict."""
        from deeptutor.services.monitoring.landmarks_codec import landmarks_to_payload

        return landmarks_to_payload(landmarks) or {}


_global_pipeline_instance: Optional[LocalCVPipeline] = None


def get_cv_pipeline() -> LocalCVPipeline:
    """Return singleton instance of LocalCVPipeline."""
    global _global_pipeline_instance
    if _global_pipeline_instance is None:
        _global_pipeline_instance = LocalCVPipeline()
    return _global_pipeline_instance
