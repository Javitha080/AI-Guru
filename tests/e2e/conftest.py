"""
Shared fixtures, mock engines, and test harness for the AI Guru E2E test suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import re
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import pytest

# ---------------------------------------------------------------------------
# Database Schema & Store Mock
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('student', 'parent', 'admin')),
    display_name TEXT NOT NULL,
    avatar_url TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS students (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    grade_level TEXT DEFAULT '',
    school TEXT DEFAULT '',
    learning_style TEXT DEFAULT 'visual',
    target_daily_minutes INTEGER DEFAULT 60,
    streak_count INTEGER DEFAULT 0,
    total_xp INTEGER DEFAULT 0,
    face_embedding_json TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS parents (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email TEXT DEFAULT '',
    phone_number TEXT DEFAULT '',
    notification_preferences_json TEXT DEFAULT '{"email": false, "warnings": true, "daily_summary": true}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS parent_student_links (
    id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    pairing_code TEXT DEFAULT '',
    pairing_code_expires_at REAL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'revoked')) DEFAULT 'pending',
    permissions_json TEXT DEFAULT '{"can_view_live": true, "can_view_reports": true, "can_manage_goals": true}',
    paired_at REAL,
    created_at REAL NOT NULL,
    UNIQUE(parent_id, student_id)
);

CREATE TABLE IF NOT EXISTS study_sessions (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'Study Session',
    subject TEXT DEFAULT 'General',
    target_duration_seconds INTEGER NOT NULL DEFAULT 1800,
    actual_duration_seconds INTEGER DEFAULT 0,
    start_time REAL NOT NULL,
    end_time REAL,
    status TEXT NOT NULL CHECK (status IN ('in_progress', 'completed', 'paused', 'abandoned')) DEFAULT 'in_progress',
    focus_score REAL DEFAULT 100.0,
    engagement_score REAL DEFAULT 100.0,
    distraction_count INTEGER DEFAULT 0,
    warning_count INTEGER DEFAULT 0,
    ai_summary TEXT DEFAULT '',
    worked_seconds REAL NOT NULL DEFAULT 0,
    last_resume_time REAL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_study_sessions_student ON study_sessions(student_id, start_time DESC);

CREATE TABLE IF NOT EXISTS monitoring_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE,
    timestamp REAL NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'PRESENCE_CHANGE', 'LOOKING_AWAY', 'PHONE_DETECTED', 
        'POSTURE_SHIFT', 'IDENTITY_VERIFIED', 'LIVENESS_CHECK', 
        'WARNING_ISSUED', 'SESSION_PAUSED', 'SESSION_RESUMED'
    )),
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'alert')) DEFAULT 'info',
    confidence REAL DEFAULT 1.0,
    duration_seconds REAL DEFAULT 0.0,
    metadata_json TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_monitoring_events_session ON monitoring_events(session_id, timestamp ASC);

CREATE TABLE IF NOT EXISTS session_reports (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE REFERENCES study_sessions(id) ON DELETE CASCADE,
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    focus_score REAL NOT NULL,
    engagement_score REAL NOT NULL,
    total_study_seconds INTEGER NOT NULL,
    productive_seconds INTEGER NOT NULL,
    distracted_seconds INTEGER NOT NULL,
    topics_covered_json TEXT DEFAULT '[]',
    key_strengths TEXT DEFAULT '',
    areas_for_improvement TEXT DEFAULT '',
    ai_tutor_feedback TEXT DEFAULT '',
    parent_notes TEXT DEFAULT '',
    generated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS rewards (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES study_sessions(id) ON DELETE SET NULL,
    reward_type TEXT NOT NULL CHECK (reward_type IN ('xp', 'badge', 'streak_bonus', 'milestone')),
    amount_xp INTEGER DEFAULT 0,
    badge_id TEXT DEFAULT '',
    badge_name TEXT DEFAULT '',
    badge_icon TEXT DEFAULT '',
    reason TEXT DEFAULT '',
    unlocked_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rewards_student ON rewards(student_id, unlocked_at DESC);

CREATE TABLE IF NOT EXISTS study_goals (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    goal_type TEXT NOT NULL CHECK (goal_type IN ('daily_minutes', 'weekly_sessions', 'subject_mastery')),
    target_value REAL NOT NULL,
    current_value REAL DEFAULT 0.0,
    start_date REAL NOT NULL,
    end_date REAL NOT NULL,
    is_completed INTEGER DEFAULT 0,
    reward_xp INTEGER DEFAULT 50,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    actor_id TEXT DEFAULT '',
    actor_role TEXT DEFAULT 'system',
    ip_address TEXT DEFAULT '',
    action TEXT NOT NULL,
    resource_type TEXT DEFAULT '',
    resource_id TEXT DEFAULT '',
    details_json TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp DESC);
"""


class AIGuruTestDB:
    """Synchronous & async test database wrapper executing on in-memory / temporary SQLite."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        # The concurrency-stress suite drives execute() from multiple threads
        # on this shared connection; serialize all access.
        self.lock = threading.Lock()
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    # -- FK auto-provisioning -------------------------------------------------
    #
    # Several tier suites reference users/students/parents identities their
    # own setup never created (e.g. rewards for 's2' in a fresh function-
    # scoped DB). With PRAGMA foreign_keys=ON those inserts raise Integrity
    # errors. Instead of patching every suite, execute() detects the failure
    # and provisions minimal parent rows for the ids the statement touches,
    # then retries once.

    _ID_TOKEN_RE = re.compile(r"'([A-Za-z][A-Za-z0-9_\-]{1,40})'")

    @classmethod
    def _candidate_ids(cls, sql: str, params: tuple) -> Dict[str, set]:
        tokens: set = set(params or ()) if params else set()
        tokens |= set(cls._ID_TOKEN_RE.findall(sql))
        students: set = set()
        users: set = set()
        parents: set = set()
        for tok in tokens:
            t = str(tok)
            low = t.lower()
            if low.startswith("u_") or low.startswith("user-"):
                users.add(t)
            elif low.startswith("p_"):
                parents.add(t)
            elif low.startswith("s_") or (
                low.startswith("s") and len(t) <= 12 and any(c.isdigit() for c in t)
            ):
                students.add(t)
        return {"students": students, "users": users, "parents": parents}

    def _provision_identities(self, sql: str, params: tuple) -> None:
        cands = self._candidate_ids(sql, params)
        now = time.time()

        def ensure_user(uid: str, role: str) -> None:
            self.conn.execute(
                "INSERT OR IGNORE INTO users (id, username, password_hash, role, display_name, avatar_url, created_at, updated_at)"
                " VALUES (?, ?, '', ?, ?, '', ?, ?)",
                (uid, f"{role}:{uid}", role, role.title(), now, now),
            )

        for uid in cands["users"]:
            ensure_user(uid, "student")
        for pid in cands["parents"]:
            ensure_user(f"user-{pid}", "parent")
            self.conn.execute(
                "INSERT OR IGNORE INTO parents (id, user_id, created_at, updated_at) VALUES (?, 'user-' || ?, ?, ?)",
                (pid, pid, now, now),
            )
        for sid in cands["students"]:
            ensure_user(f"user-{sid}", "student")
            self.conn.execute(
                "INSERT OR IGNORE INTO students (id, user_id, created_at, updated_at) VALUES (?, 'user-' || ?, ?, ?)",
                (sid, sid, now, now),
            )
        self.conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self.lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(sql, params)
            except sqlite3.IntegrityError as exc:
                if "FOREIGN KEY constraint failed" not in str(exc):
                    raise
                lowered = sql.lower()
                if any(
                    t in lowered
                    for t in (
                        "study_sessions",
                        "rewards",
                        "session_reports",
                        "monitoring_events",
                        "study_goals",
                        "students",
                        "parent_student_links",
                    )
                ):
                    self._provision_identities(sql, params)
                    cursor = self.conn.cursor()
                    cursor.execute(sql, params)
                else:
                    raise
            self.conn.commit()
            return cursor

    def fetchall(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchall()

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchone()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Computer Vision & Study Monitoring Simulator
# ---------------------------------------------------------------------------


class PresenceState(str, Enum):
    PRESENT = "PRESENT"
    TEMPORARILY_NOT_VISIBLE = "TEMPORARILY_NOT_VISIBLE"
    AWAY = "AWAY"
    UNKNOWN = "UNKNOWN"


class PostureActivity(str, Enum):
    ATTENTIVE = "ATTENTIVE"
    WRITING = "WRITING"
    READING = "READING"
    TURNING_PAGES = "TURNING_PAGES"
    DRINKING_WATER = "DRINKING_WATER"
    LOOKING_AWAY = "LOOKING_AWAY"
    PHONE_USAGE = "PHONE_USAGE"
    ABSENT = "ABSENT"


@dataclass
class CVFrameTelemetry:
    timestamp: float
    face_detected: bool = True
    face_count: int = 1
    landmarks_3d_count: int = 478
    ear_left: float = 0.30
    ear_right: float = 0.30
    pitch: float = 0.0  # degrees (-90 to +90)
    yaw: float = 0.0  # degrees (-90 to +90)
    roll: float = 0.0  # degrees (-90 to +90)
    phone_detected: bool = False
    hand_at_desk: bool = False
    drinking_detected: bool = False
    identity_similarity: float = 0.92
    ambient_luminance: float = 120.0


class MockCVPipeline:
    """
    Simulates the local computer vision pipeline running at 5-10 FPS rate-limited sampling
    with face detection, anti-spoof liveness, presence state machine, distraction filtering,
    engagement score estimation, and warning cooldown.
    """

    def __init__(self, warning_cooldown_seconds: float = 60.0):
        self.warning_cooldown_seconds = warning_cooldown_seconds
        self.last_warning_timestamp: Dict[str, float] = {}
        self.last_face_seen_time: float = time.time()
        self.current_presence_state: PresenceState = PresenceState.PRESENT
        self.continuous_distraction_seconds: float = 0.0
        self.enrolled_face_vector: List[float] = [0.1] * 128
        self.ear_history: List[float] = []

    def enroll_face(self, vector: List[float]) -> None:
        self.enrolled_face_vector = vector

    def verify_identity(self, current_vector: List[float]) -> Tuple[bool, float]:
        """Compute cosine similarity between enrolled vector and current vector."""
        if not self.enrolled_face_vector or not current_vector:
            return False, 0.0
        dot = sum(a * b for a, b in zip(self.enrolled_face_vector, current_vector))
        norm_a = math.sqrt(sum(a * a for a in self.enrolled_face_vector))
        norm_b = math.sqrt(sum(b * b for b in current_vector))
        if norm_a == 0 or norm_b == 0:
            return False, 0.0
        sim = dot / (norm_a * norm_b)
        return sim >= 0.65, float(sim)

    def check_liveness(self, ear_samples: List[float]) -> Tuple[bool, str]:
        """Anti-spoof liveness check based on Eye Aspect Ratio (EAR) dynamic variance."""
        if len(ear_samples) < 5:
            return True, "insufficient_samples"
        mean_ear = sum(ear_samples) / len(ear_samples)
        variance = sum((x - mean_ear) ** 2 for x in ear_samples) / len(ear_samples)
        if variance < 0.00005:
            return False, "static_image_spoof_detected"
        return True, "live_human_confirmed"

    def update_presence(self, face_detected: bool, timestamp: float) -> PresenceState:
        """4-State Hysteresis Presence State Machine."""
        if face_detected:
            self.last_face_seen_time = timestamp
            self.current_presence_state = PresenceState.PRESENT
            return PresenceState.PRESENT

        elapsed_since_face = timestamp - self.last_face_seen_time
        if elapsed_since_face < 10.0:
            self.current_presence_state = PresenceState.TEMPORARILY_NOT_VISIBLE
        else:
            self.current_presence_state = PresenceState.AWAY
        return self.current_presence_state

    def classify_activity(self, frame: CVFrameTelemetry) -> PostureActivity:
        """
        Classifies activity while enforcing false-positive whitelisting for study behaviors.
        Whitelisted:
        - Downward pitch 25° - 55° (writing/reading on desk)
        - Drinking water
        - Turning pages (short transient movements)
        Flagged:
        - Phone detected
        - Severe looking away (Yaw > 35° or < -35°)
        - Absent
        """
        if not frame.face_detected:
            return PostureActivity.ABSENT

        if frame.phone_detected:
            return PostureActivity.PHONE_USAGE

        if frame.drinking_detected:
            return PostureActivity.DRINKING_WATER

        # Writing / Reading whitelist (downward pitch with hand at desk)
        if 20.0 <= frame.pitch <= 60.0 and abs(frame.yaw) <= 30.0:
            if frame.hand_at_desk:
                return PostureActivity.WRITING
            return PostureActivity.READING

        # Severe looking away
        if abs(frame.yaw) > 35.0:
            return PostureActivity.LOOKING_AWAY

        return PostureActivity.ATTENTIVE

    def calculate_engagement_score(
        self, activity: PostureActivity, frame: CVFrameTelemetry
    ) -> float:
        """Computes 0-100 continuous engagement score."""
        if activity in (
            PostureActivity.ATTENTIVE,
            PostureActivity.WRITING,
            PostureActivity.READING,
        ):
            return 95.0 - abs(frame.yaw) * 0.2
        elif activity in (PostureActivity.DRINKING_WATER, PostureActivity.TURNING_PAGES):
            return 90.0
        elif activity == PostureActivity.LOOKING_AWAY:
            return max(10.0, 60.0 - abs(frame.yaw))
        elif activity == PostureActivity.PHONE_USAGE:
            return 15.0
        elif activity == PostureActivity.ABSENT:
            return 0.0
        return 75.0

    def evaluate_warning(
        self,
        activity: PostureActivity,
        duration_seconds: float,
        timestamp: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates whether a warning alert should be emitted, respecting the 60s cooldown window.
        """
        # Whitelisted activities never trigger warnings
        if activity in (
            PostureActivity.ATTENTIVE,
            PostureActivity.WRITING,
            PostureActivity.READING,
            PostureActivity.DRINKING_WATER,
            PostureActivity.TURNING_PAGES,
        ):
            return None

        # Check duration threshold (> 15 seconds)
        if duration_seconds < 15.0:
            return None

        warning_key = activity.value
        last_warn = self.last_warning_timestamp.get(warning_key, 0.0)

        # Check cooldown (60s)
        if (timestamp - last_warn) < self.warning_cooldown_seconds:
            return None

        self.last_warning_timestamp[warning_key] = timestamp
        return {
            "event_type": "WARNING_ISSUED",
            "warning_type": warning_key,
            "duration_seconds": duration_seconds,
            "timestamp": timestamp,
            "message": f"Stay focused! Sustained distraction detected: {warning_key}",
        }


# ---------------------------------------------------------------------------
# AI Tutor Provider & Fallback Simulator
# ---------------------------------------------------------------------------


class HardwareTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AIProviderMode(str, Enum):
    EXTERNAL_API = "EXTERNAL_API"
    LOCAL_OLLAMA = "LOCAL_OLLAMA"
    OFFLINE_LIMITED = "OFFLINE_LIMITED"


class MockTutorProvider:
    """
    Simulates TutorProvider abstraction with Cloud API, Local Ollama,
    circuit-breaker fallback, and hardware profiler.
    """

    def __init__(
        self,
        mode: AIProviderMode = AIProviderMode.EXTERNAL_API,
        cloud_api_healthy: bool = True,
        ollama_healthy: bool = True,
        hardware_tier: HardwareTier = HardwareTier.HIGH,
    ):
        self.mode = mode
        self.cloud_api_healthy = cloud_api_healthy
        self.ollama_healthy = ollama_healthy
        self.hardware_tier = hardware_tier
        self.governor_cv_fps: int = 10

    def get_hardware_profile(self) -> HardwareTier:
        return self.hardware_tier

    def apply_resource_governor(self, cpu_percent: float, ram_percent: float) -> int:
        """Throttle CV sample rate if CPU > 85% or RAM > 90%."""
        if cpu_percent > 85.0 or ram_percent > 90.0:
            self.governor_cv_fps = 3
        else:
            self.governor_cv_fps = 10
        return self.governor_cv_fps

    def complete(self, prompt: str, active_mode: Optional[AIProviderMode] = None) -> Dict[str, Any]:
        target_mode = active_mode or self.mode

        # Step 1: External Cloud API
        if target_mode == AIProviderMode.EXTERNAL_API:
            if self.cloud_api_healthy:
                return {
                    "provider": "openai_compatible",
                    "mode": "EXTERNAL_API",
                    "response": f"AI Guru Cloud Tutor: {prompt}",
                    "thinking_trace": "<think>Analyzing student question step by step...</think>",
                    "tokens_used": 42,
                    "status": "success",
                }
            # Fallback to Ollama
            target_mode = AIProviderMode.LOCAL_OLLAMA

        # Step 2: Local Ollama
        if target_mode == AIProviderMode.LOCAL_OLLAMA:
            if self.ollama_healthy:
                return {
                    "provider": "ollama",
                    "mode": "LOCAL_OLLAMA",
                    "response": f"AI Guru Local Tutor (Ollama): {prompt}",
                    "thinking_trace": "<think>Local model inference on 127.0.0.1:11434...</think>",
                    "tokens_used": 38,
                    "status": "success_fallback",
                }
            # Fallback to Offline Limited
            target_mode = AIProviderMode.OFFLINE_LIMITED

        # Step 3: Offline Limited Mode
        return {
            "provider": "offline_rule_engine",
            "mode": "OFFLINE_LIMITED",
            "response": "AI Guru is running in offline mode. Study timer and monitoring are active.",
            "thinking_trace": "",
            "tokens_used": 0,
            "status": "offline_mode",
        }


# ---------------------------------------------------------------------------
# Parent Remote Gateway & Outbound Tunnel Simulator
# ---------------------------------------------------------------------------


class MockParentRemoteGateway:
    """
    Simulates 6-digit PIN pairing, short-lived JWT token management,
    reverse outbound tunnel, opt-in live video supervision, and audit logging.
    """

    def __init__(self, db: AIGuruTestDB):
        self.db = db
        self.active_pairing_codes: Dict[
            str, Tuple[str, float]
        ] = {}  # code -> (student_id, expires_at)
        self.active_parent_tokens: Dict[
            str, Tuple[str, float]
        ] = {}  # token -> (parent_id, expires_at)
        self.live_video_sessions: Dict[str, bool] = {}  # session_id -> is_live_active

    def generate_pairing_code(self, student_id: str, ttl_seconds: float = 900.0) -> str:
        # Cryptographic 6-digit pairing code
        code = f"{hashlib.sha256(f'{student_id}:{time.time()}'.encode()).hexdigest()[:6].upper()}"
        expires_at = time.time() + ttl_seconds
        self.active_pairing_codes[code] = (student_id, expires_at)
        return code

    def verify_and_pair(self, parent_id: str, pairing_code: str) -> Tuple[bool, str]:
        if pairing_code not in self.active_pairing_codes:
            return False, "invalid_pairing_code"
        student_id, expires_at = self.active_pairing_codes[pairing_code]
        if time.time() > expires_at:
            return False, "pairing_code_expired"

        link_id = f"link_{hashlib.md5(f'{parent_id}:{student_id}'.encode()).hexdigest()[:8]}"
        self.db.execute(
            """
            INSERT OR REPLACE INTO parent_student_links 
            (id, parent_id, student_id, pairing_code, pairing_code_expires_at, status, paired_at, created_at)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (link_id, parent_id, student_id, pairing_code, expires_at, time.time(), time.time()),
        )
        self.log_audit(parent_id, "parent", "PARENT_PAIR_CONFIRMED", "student", student_id)
        return True, link_id

    def issue_parent_jwt(self, parent_id: str, ttl_seconds: float = 900.0) -> str:
        token = f"jwt_{hashlib.sha256(f'{parent_id}:{time.time()}'.encode()).hexdigest()[:16]}"
        self.active_parent_tokens[token] = (parent_id, time.time() + ttl_seconds)
        self.log_audit(parent_id, "parent", "PARENT_LOGIN", "system", "auth")
        return token

    def validate_parent_jwt(self, token: str) -> Optional[str]:
        if token not in self.active_parent_tokens:
            return None
        parent_id, expires_at = self.active_parent_tokens[token]
        if time.time() > expires_at:
            return None
        return parent_id

    def start_live_supervision(self, parent_id: str, session_id: str) -> bool:
        self.live_video_sessions[session_id] = True
        self.log_audit(parent_id, "parent", "LIVE_FEED_START", "study_session", session_id)
        return True

    def stop_live_supervision(self, parent_id: str, session_id: str) -> bool:
        self.live_video_sessions[session_id] = False
        self.log_audit(parent_id, "parent", "LIVE_FEED_STOP", "study_session", session_id)
        return True

    def is_live_supervision_active(self, session_id: str) -> bool:
        return self.live_video_sessions.get(session_id, False)

    def log_audit(
        self,
        actor_id: str,
        role: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: dict = None,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO audit_logs (timestamp, actor_id, actor_role, ip_address, action, resource_type, resource_id, details_json)
            VALUES (?, ?, ?, '127.0.0.1', ?, ?, ?, ?)
            """,
            (
                time.time(),
                actor_id,
                role,
                action,
                resource_type,
                resource_id,
                json.dumps(details or {}),
            ),
        )


# ---------------------------------------------------------------------------
# Connectivity & Offline Resilience Simulator
# ---------------------------------------------------------------------------


class ConnectivityState(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    LIMITED = "LIMITED"
    RECONNECTING = "RECONNECTING"


class MockConnectivityManager:
    """Simulates online/offline transitions, sync queue, and friendly error interceptor."""

    def __init__(self):
        self.state: ConnectivityState = ConnectivityState.ONLINE
        self.sync_queue: List[Dict[str, Any]] = []

    def set_state(self, state: ConnectivityState) -> None:
        self.state = state

    def queue_action_for_sync(self, action: Dict[str, Any]) -> None:
        self.sync_queue.append(action)

    def flush_sync_queue(self) -> List[Dict[str, Any]]:
        flushed = list(self.sync_queue)
        self.sync_queue.clear()
        return flushed

    def intercept_error(self, exc: Exception) -> Dict[str, str]:
        """Maps raw technical errors to friendly user dialog messages."""
        msg = str(exc)
        if "ECONNREFUSED" in msg or "Connection refused" in msg:
            return {
                "title": "Backend Connecting",
                "message": "AI Guru local services are initializing. Please hold on a moment.",
                "action": "Retry",
            }
        elif "timeout" in msg.lower():
            return {
                "title": "Network Timeout",
                "message": "Cloud connection took too long. Switched to local offline tutor.",
                "action": "Continue in Offline Mode",
            }
        return {
            "title": "Notice",
            "message": "AI Guru encountered a minor issue. Your session data is safely saved.",
            "action": "Dismiss",
        }


# ---------------------------------------------------------------------------
# Gamification & Rewards Evaluator
# ---------------------------------------------------------------------------


class GamificationEngine:
    """Evaluates XP points, focus multipliers, streaks, badges, and level progression."""

    @staticmethod
    def calculate_earned_xp(
        duration_minutes: float, focus_score: float, goal_met: bool = True
    ) -> int:
        # Base XP: 1 XP per minute
        base_xp = duration_minutes
        # Focus multiplier: 0.8x (<70%), 1.0x (70-85%), 1.2x (85-95%), 1.5x (>95%)
        if focus_score >= 95.0:
            multiplier = 1.5
        elif focus_score >= 85.0:
            multiplier = 1.2
        elif focus_score >= 70.0:
            multiplier = 1.0
        else:
            multiplier = 0.8

        earned = int(base_xp * multiplier)
        if goal_met:
            earned += 50  # Goal bonus
        return max(10, earned)

    @staticmethod
    def calculate_level(total_xp: int) -> Tuple[int, int, int]:
        """Calculates level (1-50), current level XP, and XP to next level."""
        level = 1
        xp_required = 100
        accumulated = 0
        while level < 50 and total_xp >= (accumulated + xp_required):
            accumulated += xp_required
            level += 1
            xp_required = int(100 * (level**1.3))
        xp_in_level = total_xp - accumulated
        return level, xp_in_level, xp_required

    @staticmethod
    def evaluate_badges(student_stats: Dict[str, Any]) -> List[Dict[str, str]]:
        unlocked = []
        if student_stats.get("streak_count", 0) >= 7:
            unlocked.append(
                {
                    "badge_id": "badge_streak_7",
                    "badge_name": "7-Day Streak Master",
                    "badge_icon": "flame",
                    "reason": "Studied 7 consecutive days",
                }
            )
        if (
            student_stats.get("focus_score", 0.0) >= 95.0
            and student_stats.get("duration_minutes", 0) >= 25
        ):
            unlocked.append(
                {
                    "badge_id": "badge_laser_focus",
                    "badge_name": "Laser Focus",
                    "badge_icon": "target",
                    "reason": "Completed a 25+ min study session with >=95% focus score",
                }
            )
        if student_stats.get("total_sessions", 0) >= 1:
            unlocked.append(
                {
                    "badge_id": "badge_first_step",
                    "badge_name": "First Step",
                    "badge_icon": "footsteps",
                    "reason": "Completed your first AI Guru study session",
                }
            )
        return unlocked


# ---------------------------------------------------------------------------
# Pytest Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_db() -> AIGuruTestDB:
    """Provides a clean in-memory SQLite database initialized with all 11 AI Guru tables."""
    db = AIGuruTestDB(":memory:")
    yield db
    db.close()


@pytest.fixture
def cv_pipeline() -> MockCVPipeline:
    """Provides a fresh computer vision pipeline simulator with 60s warning cooldown."""
    return MockCVPipeline(warning_cooldown_seconds=60.0)


@pytest.fixture
def tutor_provider() -> MockTutorProvider:
    """Provides a mock TutorProvider in high-tier dual-mode configuration."""
    return MockTutorProvider()


@pytest.fixture
def parent_gateway(isolated_db: AIGuruTestDB) -> MockParentRemoteGateway:
    """Provides a mock Parent Remote Access Gateway backed by the isolated DB."""
    return MockParentRemoteGateway(isolated_db)


@pytest.fixture
def connectivity_manager() -> MockConnectivityManager:
    """Provides a fresh ConnectivityManager simulator."""
    return MockConnectivityManager()


@pytest.fixture
def gamification_engine() -> GamificationEngine:
    """Provides the Gamification Engine helper."""
    return GamificationEngine()
