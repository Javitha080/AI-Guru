"""
AI Guru Head Pose and Gaze Estimator.
=====================================

Calculates 3D Head Pose (Yaw, Pitch, Roll) and 2D Gaze Vectors from facial landmarks
to determine student visual focus and ergonomic posture.

Guarantees 100% local calculation.
"""

from __future__ import annotations

from dataclasses import dataclass
import enum
import logging
import math
from typing import Optional, Tuple

from deeptutor.services.monitoring.face_engine import FaceLandmarks
from deeptutor.services.monitoring.monitoring_config import DEFAULT_THRESHOLDS

logger = logging.getLogger(__name__)


class PostureCategory(str, enum.Enum):
    HEAD_CENTER = "HEAD_CENTER"
    LOOKING_DOWN = "LOOKING_DOWN"  # Reading/writing desk posture (Whitelisted)
    LOOKING_LEFT = "LOOKING_LEFT"
    LOOKING_RIGHT = "LOOKING_RIGHT"
    LOOKING_UP = "LOOKING_UP"
    SLOUCHING = "SLOUCHING"
    HEAD_TILT = "HEAD_TILT"
    UNKNOWN = "UNKNOWN"


@dataclass
class HeadPoseResult:
    """Calculated 3D head pose angles in degrees."""

    yaw: float  # Negative = turning left, Positive = turning right
    pitch: float  # Positive = looking down (desk), Negative = looking up
    roll: float  # Negative = tilting left, Positive = tilting right
    posture: PostureCategory
    is_facing_screen: bool
    is_reading_writing_pose: bool


@dataclass
class GazeResult:
    """Estimated visual gaze direction vector and screen focus status."""

    gaze_x: float  # -1.0 (far left) to 1.0 (far right), 0 = center
    gaze_y: float  # -1.0 (far up) to 1.0 (far down / desk), 0 = center
    is_focused: bool
    confidence: float


@dataclass
class PoseAndGazeEstimation:
    """Combined posture, head pose, and visual attention output."""

    pose: HeadPoseResult
    gaze: GazeResult


class PoseGazeEstimator:
    """
    Local Head Pose and Visual Gaze Estimator.
    """

    # Shared classification thresholds — defaults come from
    # monitoring_config.DEFAULT_THRESHOLDS (single source of truth).
    # Pitch angles for reading/writing on desk: 18 to 55 degrees downward
    PITCH_READING_MIN: float = DEFAULT_THRESHOLDS.pitch_reading_min
    PITCH_READING_MAX: float = DEFAULT_THRESHOLDS.pitch_reading_max

    # Yaw thresholds for looking away
    YAW_SCREEN_THRESHOLD: float = DEFAULT_THRESHOLDS.yaw_screen_deg
    YAW_AWAY_THRESHOLD: float = DEFAULT_THRESHOLDS.yaw_away_deg

    @classmethod
    def classify(
        cls,
        yaw_deg: float,
        pitch_deg: float,
        roll_deg: float,
    ) -> Tuple[PostureCategory, bool, bool]:
        """Shared threshold classification from (yaw, pitch, roll) degrees.

        Returns (posture, is_facing_screen, is_reading_writing_pose). Used both
        by the landmark path below and by the solvePnP head-pose path in
        python_face_processor so the two engines can never drift apart.
        """
        is_reading_writing = (
            cls.PITCH_READING_MIN <= pitch_deg <= cls.PITCH_READING_MAX
            and abs(yaw_deg) <= cls.YAW_SCREEN_THRESHOLD
        )

        is_facing_screen = (
            abs(yaw_deg) <= cls.YAW_SCREEN_THRESHOLD and -15.0 <= pitch_deg < cls.PITCH_READING_MIN
        )

        if is_reading_writing:
            posture = PostureCategory.LOOKING_DOWN
        elif is_facing_screen:
            posture = PostureCategory.HEAD_CENTER
        elif pitch_deg > cls.PITCH_READING_MAX:
            posture = PostureCategory.SLOUCHING
        elif pitch_deg < -20.0:
            posture = PostureCategory.LOOKING_UP
        elif yaw_deg < -cls.YAW_SCREEN_THRESHOLD:
            posture = PostureCategory.LOOKING_LEFT
        elif yaw_deg > cls.YAW_SCREEN_THRESHOLD:
            posture = PostureCategory.LOOKING_RIGHT
        elif abs(roll_deg) > 25.0:
            posture = PostureCategory.HEAD_TILT
        else:
            posture = PostureCategory.HEAD_CENTER

        return posture, is_facing_screen, is_reading_writing

    def estimate_pose(self, landmarks: Optional[FaceLandmarks]) -> HeadPoseResult:
        """
        Estimate 3D head pose (Yaw, Pitch, Roll) from facial landmarks.
        """
        if landmarks is None:
            return HeadPoseResult(
                yaw=0.0,
                pitch=0.0,
                roll=0.0,
                posture=PostureCategory.UNKNOWN,
                is_facing_screen=False,
                is_reading_writing_pose=False,
            )

        # Extract anchor points
        nose = landmarks.nose_tip
        forehead = landmarks.forehead
        chin = landmarks.chin
        l_cheek = landmarks.left_cheek
        r_cheek = landmarks.right_cheek

        # Compute eye centers
        if landmarks.left_eye:
            lx = sum(p.x for p in landmarks.left_eye) / len(landmarks.left_eye)
            ly = sum(p.y for p in landmarks.left_eye) / len(landmarks.left_eye)
        else:
            lx, ly = l_cheek.x + 0.1, forehead.y + 0.1

        if landmarks.right_eye:
            rx = sum(p.x for p in landmarks.right_eye) / len(landmarks.right_eye)
            ry = sum(p.y for p in landmarks.right_eye) / len(landmarks.right_eye)
        else:
            rx, ry = r_cheek.x - 0.1, forehead.y + 0.1

        mid_eye_x = (lx + rx) / 2.0
        mid_eye_y = (ly + ry) / 2.0

        # 1. Roll: slope between eyes
        dx_eyes = rx - lx
        dy_eyes = ry - ly
        roll_deg = math.degrees(math.atan2(dy_eyes, dx_eyes))

        # 2. Face dimensions for normalization
        face_width = max(
            0.01, math.sqrt((r_cheek.x - l_cheek.x) ** 2 + (r_cheek.y - l_cheek.y) ** 2)
        )
        face_height = max(0.01, math.sqrt((chin.x - forehead.x) ** 2 + (chin.y - forehead.y) ** 2))

        # 3. Yaw: asymmetry of nose relative to eye center
        # Rotate coordinates relative to roll first
        rad_roll = -math.radians(roll_deg)
        rot_nose_x = (nose.x - mid_eye_x) * math.cos(rad_roll) - (nose.y - mid_eye_y) * math.sin(
            rad_roll
        )
        rot_cheek_width = face_width

        yaw_ratio = rot_nose_x / (rot_cheek_width * 0.5)
        yaw_ratio = max(-1.0, min(1.0, yaw_ratio))
        yaw_deg = math.degrees(math.asin(yaw_ratio)) * 1.3  # Calibration factor

        # 4. Pitch: vertical position of nose between eyes and chin
        rot_nose_y = (nose.x - mid_eye_x) * math.sin(rad_roll) + (nose.y - mid_eye_y) * math.cos(
            rad_roll
        )
        # In a neutral frontal pose, eye-to-nose vertical distance is ~0.35 * face_height
        neutral_offset = 0.30 * face_height
        pitch_delta = (rot_nose_y - neutral_offset) / (face_height * 0.4)
        pitch_delta = max(-1.0, min(1.0, pitch_delta))
        pitch_deg = math.degrees(math.asin(pitch_delta)) * 1.5

        yaw_deg = round(yaw_deg, 1)
        pitch_deg = round(pitch_deg, 1)
        roll_deg = round(roll_deg, 1)

        # 5. Classify posture (shared thresholds with the solvePnP path)
        posture, is_facing_screen, is_reading_writing = self.classify(yaw_deg, pitch_deg, roll_deg)

        return HeadPoseResult(
            yaw=yaw_deg,
            pitch=pitch_deg,
            roll=roll_deg,
            posture=posture,
            is_facing_screen=is_facing_screen,
            is_reading_writing_pose=is_reading_writing,
        )

    def estimate_gaze(
        self,
        landmarks: Optional[FaceLandmarks],
        pose: HeadPoseResult,
    ) -> GazeResult:
        """
        Estimate visual gaze alignment and attention.
        Combines head pose vector with eye geometry.
        """
        if landmarks is None:
            return GazeResult(gaze_x=0.0, gaze_y=0.0, is_focused=False, confidence=0.0)

        # Gaze direction is heavily driven by head pose with eye center modulation
        gaze_x = max(-1.0, min(1.0, pose.yaw / 45.0))
        gaze_y = max(-1.0, min(1.0, pose.pitch / 45.0))

        # Focused if looking directly at screen or looking down at desk material
        is_focused = pose.is_facing_screen or pose.is_reading_writing_pose
        confidence = 0.90 if is_focused else 0.85

        return GazeResult(
            gaze_x=round(gaze_x, 3),
            gaze_y=round(gaze_y, 3),
            is_focused=is_focused,
            confidence=confidence,
        )

    def process(self, landmarks: Optional[FaceLandmarks]) -> PoseAndGazeEstimation:
        """Process landmarks to produce both head pose and gaze estimation."""
        pose = self.estimate_pose(landmarks)
        gaze = self.estimate_gaze(landmarks, pose)
        return PoseAndGazeEstimation(pose=pose, gaze=gaze)
