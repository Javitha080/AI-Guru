"""
AI Guru Local Study Monitoring Package.
=======================================

Provides local computer vision processing, face verification, anti-spoof liveness,
pose and gaze estimation, presence state machines, engagement scores, distraction
filtering, and alert warning cooldowns.

Guarantees 100% on-device execution with ZERO cloud biometric egress.
"""

from deeptutor.services.monitoring.cv_pipeline import (
    FrameAnalysisResult,
    LocalCVPipeline,
    get_cv_pipeline,
)
from deeptutor.services.monitoring.distraction_analyzer import (
    DistractionAnalysisResult,
    DistractionAnalyzer,
    DistractionType,
    WhitelistedAction,
)
from deeptutor.services.monitoring.engagement_estimator import (
    EngagementEstimator,
    EngagementSnapshot,
)
from deeptutor.services.monitoring.face_engine import (
    FaceDetectionResult,
    FaceEngine,
    FaceLandmarks,
    Point3D,
)
from deeptutor.services.monitoring.liveness_detector import (
    LivenessDetector,
    LivenessResult,
)
from deeptutor.services.monitoring.pose_gaze import (
    GazeResult,
    HeadPoseResult,
    PoseAndGazeEstimation,
    PoseGazeEstimator,
    PostureCategory,
)
from deeptutor.services.monitoring.presence_state_machine import (
    PresenceState,
    PresenceStateMachine,
    PresenceStateResult,
    PresenceTransitionEvent,
)
from deeptutor.services.monitoring.warning_manager import (
    WarningEvent,
    WarningManager,
)

__all__ = [
    "Point3D",
    "FaceLandmarks",
    "FaceDetectionResult",
    "FaceEngine",
    "LivenessResult",
    "LivenessDetector",
    "PostureCategory",
    "HeadPoseResult",
    "GazeResult",
    "PoseAndGazeEstimation",
    "PoseGazeEstimator",
    "PresenceState",
    "PresenceTransitionEvent",
    "PresenceStateResult",
    "PresenceStateMachine",
    "EngagementSnapshot",
    "EngagementEstimator",
    "DistractionType",
    "WhitelistedAction",
    "DistractionAnalysisResult",
    "DistractionAnalyzer",
    "WarningEvent",
    "WarningManager",
    "FrameAnalysisResult",
    "LocalCVPipeline",
    "get_cv_pipeline",
]
