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
import math
import time
from typing import Any, Dict, List, Optional, Tuple

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
from deeptutor.services.monitoring.neutral_calibrator import NeutralCalibrator
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
    parse_pose_gaze,
)
from deeptutor.services.monitoring.warning_manager import (
    WarningEvent,
    WarningManager,
)

logger = logging.getLogger(__name__)

# SFace identity cadence (seconds) and frontal gate (degrees) — embedding a
# face is expensive, and non-frontal crops wreck neural FR accuracy.
SFACE_INTERVAL_S = 2.0
SFACE_FRONTAL_GATE_DEG = 25.0
SFACE_ENROLL_SAMPLES = 10
SFACE_ENROLL_WINDOW_S = 3.0
# Liveness confidence at/above which a not-live verdict is treated as an
# active spoof attempt (rides the IDENTITY_MISMATCH alert path).
SPOOF_CONFIDENCE_GATE = 0.90
# The static verdict must hold this long before it forces the identity
# mismatch path: the variance window dilutes for a handful of frames whenever
# the observed face changes, and those transient readings must not flag a
# genuine returning student.
STATIC_SPOOF_SUSTAIN_S = 3.0


def _load_sface_identity():
    """Best-effort SFace identity engine; None when unavailable (no model)."""
    try:
        from deeptutor.services.monitoring.face_identity import SFaceIdentity

        engine = SFaceIdentity.create_default()
        if engine is not None and engine.available:
            return engine
    except Exception as exc:  # noqa: BLE001 - identity is optional hardening
        logger.debug("SFace identity unavailable: %s", exc)
    return None


def _build_head_pose(yaw: float, pitch: float, roll: float):
    """Classified HeadPoseResult from calibrated angles (shared thresholds)."""
    from deeptutor.services.monitoring.face_solvers import build_head_pose as _build

    return _build(yaw, pitch, roll)


def _optional_float(value: Any) -> Optional[float]:
    """Parse a finite float from a telemetry payload value, else None."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


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
    # "sface" (neural embedding), "geometric" (landmark-ratio fallback) or
    # "unenrolled" (no baseline — verification auto-passes).
    identity_mode: str = "unenrolled"
    # Liveness rejected the frames (static photo / replay) with high
    # confidence; rides the IDENTITY_MISMATCH alert path.
    spoof_suspected: bool = False


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
        self._enrolled_identity_mode: str = "unenrolled"
        # Per-session neutral head-pose calibration (moved OFF the shared
        # processor singleton so concurrent sessions/probes never reset each
        # other's zero-point).
        self.neutral_calibrator = NeutralCalibrator()
        # SFace neural identity (Patch F) — None when the model is absent.
        self._sface = _load_sface_identity()
        self._sface_last_run = 0.0
        # Sustained static-spoof tracking + last frame's identity verdict
        # (transition detection: a face that flips mismatch→match is a NEW
        # subject and must prove liveness from scratch).
        self._static_since: Optional[float] = None
        self._prev_identity_match: Optional[bool] = None

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
        self.neutral_calibrator.reset()
        self._sface_last_run = 0.0
        self._static_since = None
        self._prev_identity_match = None

    def enroll_student_baseline(
        self, embedding: List[float], identity_mode: str = "geometric"
    ) -> None:
        """Enroll the student baseline facial feature vector."""
        self._enrolled_face_vector = embedding
        self._enrolled_identity_mode = identity_mode
        self.face_engine.enroll_face(embedding)

    def get_current_target_fps(self) -> int:
        """Calculate dynamic target FPS governed by system load."""
        return self.governor.get_recommended_cv_fps(self.base_fps)

    # ------------------------------------------------------------- identity

    @property
    def enrolled_identity_mode(self) -> str:
        return self._enrolled_identity_mode

    def sface_due(self, now: float, frame_is_frontal: bool = True) -> bool:
        """Whether the SFace neural-identity cadence window is open."""
        return (
            self._sface is not None
            and self._enrolled_face_vector is not None
            and frame_is_frontal
            and (now - self._sface_last_run) >= SFACE_INTERVAL_S
        )

    def embed_sface_sync(
        self, frame_bgr: Any, normalized_landmarks: List[Tuple[float, float, float]]
    ) -> Optional[List[float]]:
        """Embed a raw BGR frame (normalized MediaPipe landmarks) with SFace.

        Runs in the executor thread (system path); opens the cadence window.
        """
        if self._sface is None:
            return None
        self._sface_last_run = time.time()
        try:
            emb = self._sface.embed_normalized(frame_bgr, normalized_landmarks)
        except Exception as exc:  # noqa: BLE001 - identity must not break the frame
            logger.debug("SFace embed failed: %s", exc)
            return None
        return [float(v) for v in emb] if emb is not None else None

    def sface_enroll_vector(
        self, frame_bgr: Any, normalized_landmarks: List[Tuple[float, float, float]]
    ) -> Optional[List[float]]:
        """One-shot SFace embedding for enrollment (no cadence gate)."""
        if self._sface is None:
            return None
        try:
            emb = self._sface.embed_normalized(frame_bgr, normalized_landmarks)
        except Exception as exc:  # noqa: BLE001
            logger.debug("SFace enroll embed failed: %s", exc)
            return None
        return [float(v) for v in emb] if emb is not None else None

    @property
    def sface_available(self) -> bool:
        return self._sface is not None and self._sface.available

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
        identity_mode = "unenrolled"
        if face_res.detected:
            embedding: Optional[List[float]] = None
            injected = payload.get("sface_embedding")
            if isinstance(injected, (list, tuple)) and len(injected) >= 16:
                # System engine computed the neural embedding off-loop.
                try:
                    embedding = [float(v) for v in injected]
                    identity_mode = "sface"
                except (TypeError, ValueError):
                    embedding = None
            if embedding is None:
                embedding = self._maybe_sface_embedding(payload, face_res, now)
                if embedding is not None:
                    identity_mode = "sface"
            if embedding is None and face_res.embedding:
                embedding = face_res.embedding
                identity_mode = "geometric"
            if embedding is not None and self._enrolled_face_vector is not None:
                if identity_mode == self._enrolled_identity_mode:
                    is_identity_match, identity_sim = self.face_engine.verify_identity(
                        embedding,
                        self._enrolled_face_vector,
                    )
                else:
                    # SFace and geometric vectors live in DIFFERENT spaces —
                    # cross-mode cosine (both happen to be 128-d!) is garbage.
                    # Fall back to geometric-vs-geometric for legacy baselines.
                    geo_now = face_res.embedding
                    if geo_now is None and face_res.landmarks is not None:
                        try:
                            geo_now = self.face_engine.generate_geometric_embedding(
                                face_res.landmarks
                            )
                        except Exception:  # noqa: BLE001
                            geo_now = None
                    if geo_now is not None:
                        is_identity_match, identity_sim = self.face_engine.verify_identity(
                            geo_now,
                            self._enrolled_face_vector,
                        )
                    else:
                        is_identity_match, identity_sim = False, 0.0
            elif self._enrolled_face_vector is not None:
                # No embedding and no landmarks-derived vector: cannot verify
                # an enrolled baseline — that is a mismatch (fail-closed).
                is_identity_match = False
                identity_sim = 0.0
            # Un-enrolled mode (no baseline) keeps the legacy pass so
            # pre-enrollment sessions are not flagged.

        # 3. Liveness Analysis
        laplacian_val = payload.get("texture_laplacian_var")
        ear_override = payload.get("ear_override")
        liveness_res = self.liveness_detector.evaluate_frame(
            landmarks=face_res.landmarks,
            timestamp=now,
            texture_laplacian_var=laplacian_val,
            ear_override=ear_override,
        )
        # Consume the liveness verdict: a sustained static image / replay with
        # high confidence rides the existing IDENTITY_MISMATCH alert path so a
        # photo swap actually alerts the parent (proper SPOOF_SUSPECTED enum
        # later). The verdict must be SUSTAINED — the variance window dilutes
        # for a few frames whenever the observed face changes, and a transient
        # "static" reading during that handover must never flag identity.
        static_condition = (
            face_res.detected
            and not liveness_res.is_live
            and liveness_res.confidence >= SPOOF_CONFIDENCE_GATE
        )
        if static_condition:
            if self._static_since is None:
                self._static_since = now
            sustained_static = (now - self._static_since) >= STATIC_SPOOF_SUSTAIN_S
        else:
            self._static_since = None
            sustained_static = False

        # A face whose verdict flips mismatch→match is someone NEW sitting
        # down (the genuine student returning). Their liveness proof must
        # start fresh — re-evaluate this frame on a clean window.
        if is_identity_match and self._prev_identity_match is False and face_res.detected:
            self.liveness_detector.reset()
            liveness_res = self.liveness_detector.evaluate_frame(
                landmarks=face_res.landmarks,
                timestamp=now,
                texture_laplacian_var=laplacian_val,
                ear_override=ear_override,
            )
            static_condition = (
                not liveness_res.is_live and liveness_res.confidence >= SPOOF_CONFIDENCE_GATE
            )
            if not static_condition:
                self._static_since = None
                sustained_static = False
        if face_res.detected:
            self._prev_identity_match = is_identity_match

        spoof_suspect = sustained_static
        if spoof_suspect and self._enrolled_face_vector is not None:
            # Consume the liveness verdict: the photo/replay rides the
            # IDENTITY_MISMATCH alert path. Un-enrolled sessions have no
            # identity to mismatch (the spoof is still recorded on the result).
            is_identity_match = False

        # 4. Head Pose and Gaze — one model-fitted pose for BOTH engine paths.
        # Preference: MediaPipe facial-transformation matrix (browser path via
        # head_matrix, system path via head_angles_raw) → payload pose →
        # geometric fallback estimator. All paths pass through the per-session
        # NeutralCalibrator.
        raw_p, raw_g = parse_pose_gaze(payload)
        raw_angles: Optional[Tuple[float, float, float]] = None
        head_matrix = payload.get("head_matrix")
        if isinstance(head_matrix, (list, tuple)) and len(head_matrix) == 16:
            try:
                from deeptutor.services.monitoring.face_solvers import euler_from_face_matrix

                raw_angles = euler_from_face_matrix([float(v) for v in head_matrix])
            except (TypeError, ValueError):
                raw_angles = None
        if raw_angles is None and isinstance(payload.get("head_angles_raw"), (list, tuple)):
            try:
                vals = [float(v) for v in payload["head_angles_raw"]]
                if len(vals) == 3 and all(math.isfinite(v) for v in vals):
                    raw_angles = (vals[0], vals[1], vals[2])
            except (TypeError, ValueError):
                raw_angles = None
        if raw_angles is not None:
            yaw, pitch, roll = self.neutral_calibrator.apply(*raw_angles)
            pose_res = _build_head_pose(yaw, pitch, roll)
        elif raw_p is not None:
            # Legacy payload with a pre-computed pose dict (synthetic tests,
            # older clients): calibrate + re-classify through the shared path.
            try:
                calibrated = self.neutral_calibrator.apply(
                    float(raw_p.get("yaw", 0.0)),
                    float(raw_p.get("pitch", 0.0)),
                    float(raw_p.get("roll", 0.0)),
                )
            except (TypeError, ValueError):
                calibrated = (0.0, 0.0, 0.0)
            pose_res = _build_head_pose(*calibrated)
        else:
            pose_gaze = self.pose_estimator.process(face_res.landmarks)
            calibrated = self.neutral_calibrator.apply(
                pose_gaze.pose.yaw, pose_gaze.pose.pitch, pose_gaze.pose.roll
            )
            pose_res = _build_head_pose(*calibrated)

        # Gaze: true iris-driven gaze from landmarks when we have them (both
        # paths ship 478 all_points now); else the payload gaze dict; else the
        # head-pose proxy.
        gaze_res: Optional[GazeResult] = None
        if face_res.landmarks is not None and face_res.landmarks.all_points:
            try:
                from deeptutor.services.monitoring.face_solvers import build_gaze as _build_gaze

                raw_list = [(p.x, p.y, p.z) for p in face_res.landmarks.all_points if p is not None]
                if len(raw_list) > 473:
                    gaze_res = _build_gaze(raw_list, pose_res)
            except Exception:  # noqa: BLE001 - gaze is a soft signal
                gaze_res = None
        if gaze_res is None and raw_g is not None:
            gaze_res = build_gaze_result(raw_g)
        if gaze_res is None:
            gaze_res = self.pose_estimator.estimate_gaze(face_res.landmarks, pose_res)

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
            eye_closure=_optional_float(payload.get("eye_closure")),
            jaw_open=_optional_float(payload.get("jaw_open")),
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
            identity_mode=identity_mode,
            spoof_suspected=spoof_suspect,
        )

    # ------------------------------------------------------------ identity

    def _maybe_sface_embedding(
        self, payload: Dict[str, Any], face_res: Any, now: float
    ) -> Optional[List[float]]:
        """Time-gated SFace neural embedding from the payload's JPEG frame.

        Returns the embedding or None when SFace is unavailable /
        cadence-gated / non-frontal / no frame. Falls back to the geometric
        embedding path at the caller.
        """
        if self._sface is None or self._enrolled_face_vector is None:
            return None
        if face_res.landmarks is None:
            return None
        # Frontal gate on the raw pose (matrix, raw angles, or pose dict).
        raw_angles: Optional[Tuple[float, float, float]] = None
        hm = payload.get("head_matrix")
        if isinstance(hm, (list, tuple)) and len(hm) == 16:
            try:
                from deeptutor.services.monitoring.face_solvers import euler_from_face_matrix

                raw_angles = euler_from_face_matrix([float(v) for v in hm])
            except (TypeError, ValueError):
                raw_angles = None
        if raw_angles is None:
            har = payload.get("head_angles_raw")
            if isinstance(har, (list, tuple)) and len(har) == 3:
                try:
                    raw_angles = (float(har[0]), float(har[1]), float(har[2]))
                except (TypeError, ValueError):
                    raw_angles = None
        if raw_angles is None:
            p = payload.get("pose")
            if isinstance(p, dict):
                try:
                    raw_angles = (
                        float(p.get("yaw", 0.0)),
                        float(p.get("pitch", 0.0)),
                        float(p.get("roll", 0.0)),
                    )
                except (TypeError, ValueError):
                    raw_angles = None
        if raw_angles is None:
            return None
        if (
            abs(raw_angles[0]) > SFACE_FRONTAL_GATE_DEG
            or abs(raw_angles[1]) > SFACE_FRONTAL_GATE_DEG
        ):
            return None
        if now - self._sface_last_run < SFACE_INTERVAL_S:
            return None

        jpeg_b64 = payload.get("jpeg_b64")
        if not isinstance(jpeg_b64, str) or len(jpeg_b64) < 32:
            return None
        bgr = self._sface.decode_bgr(jpeg_b64)
        if bgr is None:
            return None
        self._sface_last_run = now
        try:
            raw_pts = [(p.x, p.y, p.z) for p in face_res.landmarks.all_points]
            emb = self._sface.embed_normalized(bgr, raw_pts)
        except Exception as exc:  # noqa: BLE001 - identity must not break the frame
            logger.debug("SFace embed failed: %s", exc)
            return None
        return [float(v) for v in emb] if emb is not None else None

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


async def hydrate_identity_baseline(pipeline: LocalCVPipeline) -> None:
    """Load the enrolled identity baseline into a (per-session) pipeline.

    Order: inherit from the process-global singleton (in-memory enrollments),
    else load the ENCRYPTED persisted baseline from the kv settings table —
    a backend restart must never silently drop sessions into un-enrolled
    mode while the client still believes it is enrolled.
    """
    try:
        from deeptutor.services.monitoring.cv_pipeline import get_cv_pipeline

        baseline = get_cv_pipeline().face_engine.get_enrolled_face()
        if baseline is not None:
            pipeline.enroll_student_baseline(
                list(baseline),
                identity_mode=getattr(get_cv_pipeline(), "enrolled_identity_mode", "geometric"),
            )
            return
    except Exception:  # noqa: BLE001 - inheritance best-effort
        pass
    try:
        from deeptutor.services.monitoring.identity_store import load_baseline
        from deeptutor.services.path_service import get_path_service

        db_path = str(get_path_service().user_dir / "chat_history.db")
        stored = await load_baseline(db_path)
        if stored is not None:
            embedding, mode = stored
            pipeline.enroll_student_baseline(embedding, identity_mode=mode)
            logger.info("Identity baseline restored from encrypted store (mode=%s)", mode)
    except Exception as exc:  # noqa: BLE001 - persistence best-effort
        logger.debug("Identity baseline hydration skipped: %s", exc)
