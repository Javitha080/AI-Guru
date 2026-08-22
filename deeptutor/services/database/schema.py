"""
AI Guru Core Database Schema DDL Definitions and Pragmas.

Defines the 11 core relational tables, indices, and schema_migrations table
for the local-first AI Guru architecture.
"""

from __future__ import annotations

# Recommended SQLite PRAGMAs for concurrency, integrity, and performance
PRAGMAS = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;
"""

# Version 1 Migration DDL: 11 Core Relational Tables + Migrations Table
V1_SCHEMA_DDL = """
-- Schema Migrations Tracker
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at REAL NOT NULL
);

-- 1. Local User Accounts
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
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- 2. Student Profiles
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
CREATE INDEX IF NOT EXISTS idx_students_user ON students(user_id);

-- 3. Parent Profiles
CREATE TABLE IF NOT EXISTS parents (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email TEXT DEFAULT '',
    phone_number TEXT DEFAULT '',
    notification_preferences_json TEXT DEFAULT '{"email": false, "warnings": true, "daily_summary": true}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_parents_user ON parents(user_id);

-- 4. Parent-Student Pairing Links
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
CREATE INDEX IF NOT EXISTS idx_ps_links_parent ON parent_student_links(parent_id);
CREATE INDEX IF NOT EXISTS idx_ps_links_student ON parent_student_links(student_id);
CREATE INDEX IF NOT EXISTS idx_ps_links_code ON parent_student_links(pairing_code);

-- 5. Study Sessions
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
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_study_sessions_student ON study_sessions(student_id, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_study_sessions_status ON study_sessions(status);

-- 6. Monitoring Computer Vision Events
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
CREATE INDEX IF NOT EXISTS idx_monitoring_events_type ON monitoring_events(event_type, timestamp ASC);

-- 7. Session Evaluation Reports
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
CREATE INDEX IF NOT EXISTS idx_session_reports_student ON session_reports(student_id, generated_at DESC);

-- 8. Rewards & Gamification
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
CREATE INDEX IF NOT EXISTS idx_rewards_type ON rewards(reward_type);

-- 9. Study Goals
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
CREATE INDEX IF NOT EXISTS idx_study_goals_student ON study_goals(student_id, created_at DESC);

-- 10. System & Application Settings
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_settings_category ON settings(category);

-- 11. Security & Audit Logs
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
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON audit_logs(actor_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action, timestamp DESC);
"""

CORE_TABLE_NAMES = (
    "schema_migrations",
    "users",
    "students",
    "parents",
    "parent_student_links",
    "study_sessions",
    "monitoring_events",
    "session_reports",
    "rewards",
    "study_goals",
    "settings",
    "audit_logs",
)

# Version 2 Migration DDL: Past-paper exam engine (additive, no existing
# table is altered). Exams store their full paper as JSON so the schema can
# evolve without further migrations; answers are one row per question.
V2_EXAM_SCHEMA_DDL = """
-- 12. Exam Papers (verbatim past-paper exams)
CREATE TABLE IF NOT EXISTS exams (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_filename TEXT DEFAULT '',
    paper_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('created', 'active', 'submitted', 'graded')) DEFAULT 'created',
    mcq_duration_seconds INTEGER NOT NULL DEFAULT 7200,
    essay_duration_seconds INTEGER,
    total_marks INTEGER NOT NULL DEFAULT 0,
    student_id TEXT DEFAULT 'student-primary',
    created_at REAL NOT NULL,
    started_at REAL,
    ends_at REAL,
    submitted_at REAL
);
CREATE INDEX IF NOT EXISTS idx_exams_student ON exams(student_id, created_at DESC);

-- 13. Per-question answers + grades for an exam attempt
CREATE TABLE IF NOT EXISTS exam_answers (
    exam_id TEXT NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL,
    answer_text TEXT DEFAULT '',
    option_key TEXT DEFAULT '',
    awarded REAL DEFAULT 0,
    max_marks REAL NOT NULL DEFAULT 1,
    feedback TEXT DEFAULT '',
    verdict TEXT DEFAULT '',
    graded INTEGER NOT NULL DEFAULT 0,
    answered_at REAL,
    PRIMARY KEY (exam_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_exam_answers_exam ON exam_answers(exam_id);
"""
