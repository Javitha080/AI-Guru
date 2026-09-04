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
        'WARNING_ISSUED', 'NUDGE_ISSUED', 'SESSION_PAUSED', 'SESSION_RESUMED'
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
    status TEXT NOT NULL CHECK (status IN ('created', 'active', 'review', 'submitted', 'graded')) DEFAULT 'created',
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

# Version 3 Migration DDL: pause-aware study durations (additive).
#
# worked_seconds    — validated study time excluding paused intervals
# last_resume_time  — when the current active stretch began (NULL until
#                     start/resume touches it); lets stop() close the final
#                     stretch instead of counting wall-clock from start_time.
#
# Applied via a callable (see migrations.V3_PAUSE_MIGRATION) so each column is
# added only when missing — a DB that already carries one column (partial
# apply, or created by code that shipped the columns early) must not wedge
# startup with "duplicate column name" on every boot.


def _add_column_if_missing(conn, table: str, column: str, ddl_type: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


def v3_pause_aware_durations(conn) -> None:
    _add_column_if_missing(conn, "study_sessions", "worked_seconds", "REAL NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "study_sessions", "last_resume_time", "REAL")


# Version 4 Migration DDL: Paper Bank — prebuilt local catalog of verbatim
# past papers (Grade 12/13 A/L first). Papers are pristine templates; starting
# one copies its JSON into an ``exams`` row so attempts never mutate the bank
# and any paper can be retaken unlimited times.
#
# group_key   — links Paper 1 + Paper 2 of one exam sitting (e.g. 'ict-2021-g12')
# paper_no    — 1 = MCQ paper, 2 = structured/essay paper
# file_hash   — import dedupe: the same PDF can never enter the bank twice
# default_duration_seconds — auto-set per paper_type (P1 MCQ=2h, P2 essay=3h);
#             users are never asked for a duration.
V4_PAPER_BANK_SCHEMA_DDL = """
-- 14. Paper Bank (pristine past-paper catalog)
CREATE TABLE IF NOT EXISTS paper_bank (
    id TEXT PRIMARY KEY,
    group_key TEXT NOT NULL,
    paper_no INTEGER NOT NULL DEFAULT 1 CHECK (paper_no IN (1, 2)),
    grade INTEGER NOT NULL CHECK (grade IN (11, 12, 13)),
    subject TEXT NOT NULL,
    year INTEGER NOT NULL,
    medium TEXT NOT NULL DEFAULT 'english'
        CHECK (medium IN ('english', 'sinhala', 'tamil')),
    paper_type TEXT NOT NULL DEFAULT 'mcq'
        CHECK (paper_type IN ('mcq', 'structured', 'essay', 'mixed')),
    title TEXT NOT NULL,
    source_filename TEXT DEFAULT '',
    file_hash TEXT UNIQUE,
    question_count INTEGER NOT NULL DEFAULT 0,
    mcq_count INTEGER NOT NULL DEFAULT 0,
    essay_count INTEGER NOT NULL DEFAULT 0,
    total_marks REAL NOT NULL DEFAULT 0,
    default_duration_seconds INTEGER NOT NULL DEFAULT 7200,
    paper_json TEXT NOT NULL,
    scheme_answers_json TEXT DEFAULT '{}',
    topic_tags_json TEXT DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL,
    UNIQUE (group_key, paper_no)
);
CREATE INDEX IF NOT EXISTS idx_paper_bank_catalog
    ON paper_bank(subject, grade, year, paper_no);
CREATE INDEX IF NOT EXISTS idx_paper_bank_group ON paper_bank(group_key);

-- 15. Per-question practice log across all attempts. Feeds topic stats,
-- weak-area detection and the recommendation engine.
CREATE TABLE IF NOT EXISTS question_practice_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    bank_paper_id TEXT REFERENCES paper_bank(id) ON DELETE CASCADE,
    exam_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    topic TEXT DEFAULT '',
    question_type TEXT DEFAULT '',
    verdict TEXT DEFAULT '',
    awarded REAL NOT NULL DEFAULT 0,
    max_marks REAL NOT NULL DEFAULT 1,
    practiced_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_qpl_student_topic
    ON question_practice_log(student_id, topic);
CREATE INDEX IF NOT EXISTS idx_qpl_exam ON question_practice_log(exam_id);
"""


# Version 5 Migration: sitting-aware exam columns (idempotent, callable —
# same rationale as v3: a DB that already carries some columns must not wedge
# startup with "duplicate column name").
#
# sitting_id          — groups the Paper 1 + Paper 2 attempts of one sitting
# paper_no            — which half of the sitting this attempt is (NULL for
#                       legacy upload-flow exams)
# bank_paper_id       — the pristine catalog paper this attempt was copied from
# addon_seconds_used  — total extra time bought through the gamified shop
# xp_multiplier       — final XP scale factor (each add-on purchase lowers it)
def v5_exam_sitting_columns(conn) -> None:
    _add_column_if_missing(conn, "exams", "sitting_id", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "exams", "paper_no", "INTEGER")
    _add_column_if_missing(
        conn,
        "exams",
        "bank_paper_id",
        "TEXT REFERENCES paper_bank(id) ON DELETE SET NULL",
    )
    _add_column_if_missing(conn, "exams", "addon_seconds_used", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "exams", "xp_multiplier", "REAL NOT NULL DEFAULT 1.0")
    # Speeds up My-Sessions listing grouped by sitting.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exams_sitting ON exams(sitting_id)")


# Version 6 Migration: widen paper_bank.grade to admit O/L papers (grade 11).
# SQLite cannot ALTER a CHECK constraint, so the table is rebuilt in place —
# all catalog rows, indexes and uniqueness carry over untouched.
def v6_paper_bank_grade11(conn) -> None:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(paper_bank)").fetchall()]
    if not cols:
        return  # v4 has not run yet; fresh installs create the wide CHECK above
    conn.execute(
        """
        CREATE TABLE paper_bank_v6 (
            id TEXT PRIMARY KEY,
            group_key TEXT NOT NULL,
            paper_no INTEGER NOT NULL DEFAULT 1 CHECK (paper_no IN (1, 2)),
            grade INTEGER NOT NULL CHECK (grade IN (11, 12, 13)),
            subject TEXT NOT NULL,
            year INTEGER NOT NULL,
            medium TEXT NOT NULL DEFAULT 'english'
                CHECK (medium IN ('english', 'sinhala', 'tamil')),
            paper_type TEXT NOT NULL DEFAULT 'mcq'
                CHECK (paper_type IN ('mcq', 'structured', 'essay', 'mixed')),
            title TEXT NOT NULL,
            source_filename TEXT DEFAULT '',
            file_hash TEXT UNIQUE,
            question_count INTEGER NOT NULL DEFAULT 0,
            mcq_count INTEGER NOT NULL DEFAULT 0,
            essay_count INTEGER NOT NULL DEFAULT 0,
            total_marks REAL NOT NULL DEFAULT 0,
            default_duration_seconds INTEGER NOT NULL DEFAULT 7200,
            paper_json TEXT NOT NULL,
            scheme_answers_json TEXT DEFAULT '{}',
            topic_tags_json TEXT DEFAULT '[]',
            created_at REAL NOT NULL,
            updated_at REAL,
            UNIQUE (group_key, paper_no)
        )
        """
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO paper_bank_v6 (
            id, group_key, paper_no, grade, subject, year, medium, paper_type,
            title, source_filename, file_hash, question_count, mcq_count,
            essay_count, total_marks, default_duration_seconds, paper_json,
            scheme_answers_json, topic_tags_json, created_at, updated_at
        )
        SELECT id, group_key, paper_no, grade, subject, year, medium, paper_type,
               title, source_filename, file_hash, question_count, mcq_count,
               essay_count, total_marks, default_duration_seconds, paper_json,
               scheme_answers_json, topic_tags_json, created_at, updated_at
        FROM paper_bank
        """
    )
    conn.execute("DROP TABLE paper_bank")
    conn.execute("ALTER TABLE paper_bank_v6 RENAME TO paper_bank")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_bank_catalog"
        " ON paper_bank(subject, grade, year, paper_no)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_bank_group ON paper_bank(group_key)")


# Version 7 Migration: admit the 'review' status on exams (double-check
# window between time-up and grading). SQLite cannot ALTER a CHECK, so the
# table is rebuilt with every column carried over verbatim.
def v7_exams_review_status(conn) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='exams'"
    ).fetchone()
    create_sql = row[0] if row else ""
    if not create_sql or "'review'" in create_sql:
        return
    conn.execute("ALTER TABLE exams RENAME TO exams_v7_old")
    new_sql = create_sql.replace("exams_v7_old", "exams")
    if "CHECK" in new_sql and "status IN (" in new_sql:
        new_sql = new_sql.replace(
            "status IN ('created', 'active', 'submitted', 'graded')",
            "status IN ('created', 'active', 'review', 'submitted', 'graded')",
        ).replace(
            "status IN ('created','active','submitted','graded')",
            "status IN ('created', 'active', 'review', 'submitted', 'graded')",
        )
    else:
        # Legacy tables without a CHECK: recreate with the full contract.
        new_sql = new_sql.replace(
            "status TEXT NOT NULL DEFAULT 'created'",
            "status TEXT NOT NULL CHECK (status IN ('created', 'active', 'review',"
            " 'submitted', 'graded')) DEFAULT 'created'",
        )
    conn.execute(new_sql)
    conn.execute(
        """
        INSERT OR REPLACE INTO exams (
            id, title, source_filename, paper_json, status,
            mcq_duration_seconds, essay_duration_seconds, total_marks,
            student_id, created_at, started_at, ends_at, submitted_at,
            sitting_id, paper_no, bank_paper_id, addon_seconds_used, xp_multiplier
        )
        SELECT id, title, source_filename, paper_json, status,
                mcq_duration_seconds, essay_duration_seconds, total_marks,
                student_id, created_at, started_at, ends_at, submitted_at,
                sitting_id, paper_no, bank_paper_id, addon_seconds_used, xp_multiplier
        FROM exams_v7_old
        """
    )
    conn.execute("DROP TABLE exams_v7_old")
    conn.execute("DROP INDEX IF EXISTS idx_exams_student")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_exams_student ON exams(student_id, created_at DESC)"
    )


# Version 8 Migration: admit 'NUDGE_ISSUED' on monitoring_events.
# SQLite cannot ALTER a CHECK constraint, so the table is rebuilt in place —
# all rows, FKs and indexes carry over untouched. Idempotent: returns early
# when the CHECK already contains NUDGE_ISSUED or the table is missing.
def v8_monitoring_nudge_event(conn) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='monitoring_events'"
    ).fetchone()
    create_sql = row[0] if row else ""
    if not create_sql:
        return
    if "NUDGE_ISSUED" in create_sql:
        return
    conn.execute("ALTER TABLE monitoring_events RENAME TO monitoring_events_v8_old")
    new_sql = create_sql.replace("monitoring_events_v8_old", "monitoring_events")
    if "'WARNING_ISSUED'" in new_sql and "NUDGE_ISSUED" not in new_sql:
        new_sql = new_sql.replace(
            "'WARNING_ISSUED'",
            "'WARNING_ISSUED', 'NUDGE_ISSUED'",
        )
    else:
        # Fallback: recreate with the full canonical contract.
        new_sql = (
            "CREATE TABLE monitoring_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id TEXT NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE, "
            "timestamp REAL NOT NULL, "
            "event_type TEXT NOT NULL CHECK (event_type IN ("
            "'PRESENCE_CHANGE', 'LOOKING_AWAY', 'PHONE_DETECTED', "
            "'POSTURE_SHIFT', 'IDENTITY_VERIFIED', 'LIVENESS_CHECK', "
            "'WARNING_ISSUED', 'NUDGE_ISSUED', 'SESSION_PAUSED', 'SESSION_RESUMED'"
            ")), "
            "severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'alert')) DEFAULT 'info', "
            "confidence REAL DEFAULT 1.0, "
            "duration_seconds REAL DEFAULT 0.0, "
            "metadata_json TEXT DEFAULT '{}'"
            ")"
        )
    conn.execute(new_sql)
    conn.execute(
        """
        INSERT OR REPLACE INTO monitoring_events (
            id, session_id, timestamp, event_type, severity,
            confidence, duration_seconds, metadata_json
        )
        SELECT id, session_id, timestamp, event_type, severity,
               confidence, duration_seconds, metadata_json
        FROM monitoring_events_v8_old
        """
    )
    conn.execute("DROP TABLE monitoring_events_v8_old")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_monitoring_events_session "
        "ON monitoring_events(session_id, timestamp ASC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_monitoring_events_type "
        "ON monitoring_events(event_type, timestamp ASC)"
    )
