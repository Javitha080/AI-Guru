# Project: AI Guru

## Architecture

AI Guru is an intelligent, local-first, privacy-focused AI tutoring and study-monitoring platform built on an agent-native architecture.

```
                                    ┌───────────────────────────────────┐
                                    │      Next.js 16 (React 19) UI     │
                                    │     (Student & Parent Portals)    │
                                    └─────────────────┬─────────────────┘
                                                      │ HTTP / WebSocket
                                                      ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       AI GURU LOCAL RUNTIME (FastAPI)                                  │
│                                                                                                        │
│  ┌─────────────────────────┐  ┌────────────────────────┐  ┌─────────────────────────────────────────┐  │
│  │   ChatOrchestrator      │  │  StudyMonitoringEngine │  │         TutorProvider Manager           │  │
│  │  - 7 Capabilities       │  │  - 5-10 FPS Analysis   │  │  - Mode A: External Cloud APIs          │  │
│  │  - 43 Built-in Tools    │  │  - Face & Liveness     │  │  - Mode B: Local Ollama LLMs            │  │
│  │  - StreamBus Fan-Out    │  │  - Presence & Posture  │  │  - Mode C: Offline Rule Engine          │  │
│  │                         │  │  - Distraction Filter  │  │  - Hardware Profiler & Governor         │  │
│  └────────────┬────────────┘  └───────────┬────────────┘  └────────────────────┬────────────────────┘  │
│               │                           │                                    │                       │
│               └───────────────────────────┼────────────────────────────────────┘                       │
│                                           ▼                                                            │
│                         ┌───────────────────────────────────┐                                          │
│                         │   Session & Gamification Engine   │                                          │
│                         │   - Study Session Lifecycle       │                                          │
│                         │   - Real-Time Telemetry Logging   │                                          │
│                         │   - XP, Streaks & Badges          │                                          │
│                         └─────────────────┬─────────────────┘                                          │
│                                           ▼                                                            │
│                         ┌───────────────────────────────────┐                                          │
│                         │  Local Relational Database Store  │                                          │
│                         │   (SQLite / aiosqlite in WAL)     │                                          │
│                         │   - 11 Core Relational Tables     │                                          │
│                         │   - Versioned Migrations          │                                          │
│                         └─────────────────┬─────────────────┘                                          │
│                                           │                                                            │
│  ┌────────────────────────────────────────┴─────────────────────────────────────────────────────────┐  │
│  │  Parent Remote Access Gateway (Outbound Encrypted Tunnel + JWT Auth + Opt-In Live Supervision)     │  │
│  └────────────────────────────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Feature Inventory

Every feature from R1 through R9 is assigned to a milestone:

| # | Feature ID | Feature Name | Description | Milestone | Source |
|---|------------|--------------|-------------|-----------|--------|
| 1 | `REQ-R1-01` | Architecture Audit Document | Create `docs/AI-GURU-ARCHITECTURE-AUDIT.md` documenting full system | M1 | R1, AC Line 102 |
| 2 | `REQ-R1-02` | Implementation Phasing Plan | Create `docs/AI-GURU-IMPLEMENTATION-PLAN.md` with phased approach | M1 | R1, AC Line 103 |
| 3 | `REQ-R1-03` | Web UI Rebranding | Rebrand user-visible strings to "AI Guru" across web UI, headers, layout | M1 | R1, AC Line 58 |
| 4 | `REQ-R1-04` | PWA & Metadata Rebranding | Update manifest.json, OpenGraph metadata, page titles to "AI Guru" | M1 | R1, AC Line 58 |
| 5 | `REQ-R1-05` | CLI & Banner Rebranding | Rebrand CLI help, welcome banners, and outputs to "AI Guru" | M1 | R1, AC Line 58 |
| 6 | `REQ-R1-06` | Internal Code Preservation | Preserve internal Python package `deeptutor.*` imports and logic | M1 | R1, AC Line 57 |
| 7 | `REQ-R2-01` | Unified Service Launcher | Single command `deeptutor start` / `aiguru start` launching backend+frontend | M2 | R2, AC Line 61 |
| 8 | `REQ-R2-02` | Comprehensive Health Check | `/api/v1/health` status for DB, backend, camera, mic, AI, Ollama, CV, CPU, RAM | M2 | R2, AC Line 62 |
| 9 | `REQ-R2-03` | Localhost Binding & Port Security | Bind backend and DB strictly to 127.0.0.1; zero external port exposure | M2 | R2, AC Line 63 |
| 10 | `REQ-R2-04` | 11-Table SQLite Schema | Create all 11 core tables (users, students, parents, sessions, events, etc.) | M2 | R2, AC Line 79 |
| 11 | `REQ-R2-05` | Non-Destructive Migrations | Schema migration manager preserving all existing chat & session history | M2 | R2, AC Line 79 |
| 12 | `REQ-R2-06` | Windows Auto-Startup Support | Settings toggle for Windows startup entry | M2 | R2 Line 23 |
| 13 | `REQ-R2-07` | Subsystem Recovery | Automatic supervisor recovery for internal workers | M2 | R2 Line 23 |
| 14 | `REQ-R3-01` | `TutorProvider` Interface | Base abstract interface unifying cloud and local LLMs | M3 | R3, AC Line 66 |
| 15 | `REQ-R3-02` | Cloud Provider Adapter | Adapter wrapping external API providers with streaming & thinking tags | M3 | R3, AC Line 66 |
| 16 | `REQ-R3-03` | Ollama Local Provider Adapter | Adapter connecting to local Ollama (`http://127.0.0.1:11434`) | M3 | R3, AC Line 66 |
| 17 | `REQ-R3-04` | AI Mode Settings UI | UI for switching between External API, Ollama, and Auto-Mode | M3 | R3, AC Line 66 |
| 18 | `REQ-R3-05` | Auto-Fallback Chain | Seamless fallback: Cloud API -> Local Ollama -> Offline Mode on network cut | M3 | R3, AC Line 68 |
| 19 | `REQ-R3-06` | Secure Local API Key Vault | Store API keys in local config with masked frontend delivery | M3 | R3, AC Line 67 |
| 20 | `REQ-R3-07` | Hardware Profiler | Detect GPU (NVIDIA/AMD/Intel/Apple) & CPU, categorize into LOW/MED/HIGH | M3 | R3 Line 27 |
| 21 | `REQ-R3-08` | Resource Governor | Dynamically throttle background tasks & CV rate if CPU > 85% or RAM > 90% | M3 | R3 Line 27 |
| 22 | `REQ-R3-09` | AI Onboarding Setup Wizard | First-run setup modal for AI provider selection & Ollama model download | M3 | R3 Line 27 |
| 23 | `REQ-R4-01` | Local-Only CV Pipeline | 100% local video processing pipeline; zero biometric frames sent to cloud | M4 | R4, AC Line 72 |
| 24 | `REQ-R4-02` | Decoupled Sampling (5-10 FPS) | Full 30 FPS preview with 5-10 FPS rate-limited inference | M4 | R4, AC Line 71 |
| 25 | `REQ-R4-03` | Face Detection & Landmarks | Local face bounding box and 3D facial landmark mesh | M4 | R4, AC Line 72 |
| 26 | `REQ-R4-04` | Face Identity Verification | Verify student identity against enrolled baseline (cosine sim >= 0.65) | M4 | R4, AC Line 78 |
| 27 | `REQ-R4-05` | Anti-Spoof Liveness Detector | Reject printed photos and screen replays via texture & blink analysis | M4 | R4, AC Line 78 |
| 28 | `REQ-R4-06` | Head Pose & Gaze Estimation | Compute Yaw, Pitch, Roll angles to track visual attention | M4 | R4 Line 31 |
| 29 | `REQ-R4-07` | Presence State Machine | 4-state machine (PRESENT, TEMPORARILY_NOT_VISIBLE, AWAY, UNKNOWN) with hysteresis | M4 | R4, AC Line 73 |
| 30 | `REQ-R4-08` | Real-Time Engagement Estimator | Continuous 0-100 engagement score from gaze, posture, and stability | M4 | R4 Line 31 |
| 31 | `REQ-R4-09` | Distraction False-Positive Filter | Whitelist reading, writing, turning pages, drinking water; flag phones & absence | M4 | R4, AC Line 74 |
| 32 | `REQ-R4-10` | Warning System & Cooldown | Distraction alerts with confidence threshold and 60s cooldown | M4 | R4, AC Line 75 |
| 33 | `REQ-R5-01` | Study Session Creation | UI to select subject, topic, duration, and AI capability | M5 | R5, AC Line 78 |
| 34 | `REQ-R5-02` | Pre-flight Hardware Check | Step-by-step wizard validating camera, lighting, and framing | M5 | R5, AC Line 78 |
| 35 | `REQ-R5-03` | Pre-flight Identity & Liveness | Face match and blink verification before timer starts | M5 | R5, AC Line 78 |
| 36 | `REQ-R5-04` | Interactive Study Room View | Split-screen workspace: timer, focus gauge, camera preview, AI tutor | M5 | R5, AC Line 78 |
| 37 | `REQ-R5-05` | Real-Time Telemetry Logging | Persist focus, presence, and distraction events to `monitoring_events` table | M5 | R5, AC Line 79 |
| 38 | `REQ-R5-06` | Session Completion & Aggregation | End session, compute focus %, study time, and distraction summary | M5 | R5, AC Line 78 |
| 39 | `REQ-R5-07` | AI Study Summary Report | LLM-generated study recap, strengths, improvement areas, and metrics | M5 | R5, AC Line 78 |
| 40 | `REQ-R5-08` | Session Report UI & Export | Visual report view with graphs and export capability | M5 | R5, AC Line 78 |
| 41 | `REQ-R6-01` | XP Points Calculation Engine | Compute earned XP based on duration and focus multiplier | M5 | R6, AC Line 78 |
| 42 | `REQ-R6-02` | Daily Streak Tracker | Track consecutive study days, handle streaks and freezes | M5 | R6 Line 39 |
| 43 | `REQ-R6-03` | Badges & Achievement System | Unlock badges ("Laser Focus", "7-Day Streak") and record in `rewards` | M5 | R6 Line 39 |
| 44 | `REQ-R6-04` | Level Progression System | Level progression (1-50) based on cumulative XP | M5 | R6 Line 39 |
| 45 | `REQ-R6-05` | Gamification Dashboard Widgets | UI widgets displaying level, XP bar, streak flame, and badge collection | M5 | R6 Line 39 |
| 46 | `REQ-R7-01` | Parent-Student Pairing | 6-digit secure pairing code handshake linking student and parent | M6 | R7, AC Line 82 |
| 47 | `REQ-R7-02` | Parent Overview Dashboard | Portal showing live status, study time, focus score, streak, reports | M6 | R7, AC Line 83 |
| 48 | `REQ-R7-03` | Parent Analytics Views | Trend charts for daily/weekly/monthly focus and subjects | M6 | R7, AC Line 83 |
| 49 | `REQ-R7-04` | Zero-Config Outbound Tunnel | Encrypted reverse tunnel for remote access without port forwarding | M6 | R7, AC Line 87 |
| 50 | `REQ-R7-05` | Short-Lived Tokens & Revocation | JWT auth with 15-min expiry, refresh rotation, device tracking | M6 | R7, AC Line 88 |
| 51 | `REQ-R7-06` | Opt-in Live Video Supervision | Encrypted point-to-point live camera stream with banner and auto-kill | M6 | R7, AC Line 84 |
| 52 | `REQ-R7-07` | Remote Data Privacy Isolation | Relay stores zero study data; all queries proxy to local SQLite DB | M6 | R7 Line 43 |
| 53 | `REQ-R7-08` | Parent Access Audit Logging | Record all parent logins, live video views, and report downloads in `audit_logs` | M6 | R7, AC Line 89 |
| 54 | `REQ-R8-01` | `ConnectivityManager` Service | Monitor states: ONLINE, OFFLINE, LIMITED, RECONNECTING | M6 | R8, AC Line 92 |
| 55 | `REQ-R8-02` | Navbar Connectivity Indicator | UI badge showing online/offline & AI provider status | M6 | R8, AC Line 93 |
| 56 | `REQ-R8-03` | Offline Study Session Continuity | Uninterrupted offline timer, CV monitoring, local reports, and rewards | M6 | R8, AC Line 92 |
| 57 | `REQ-R8-04` | Local Ollama Offline Tutoring | AI tutoring chats execute through local Ollama when offline | M6 | R8 Line 47 |
| 58 | `REQ-R8-05` | User-Friendly Error Interceptor | Intercept low-level exceptions and display friendly actionable dialogs | M6 | R8, AC Line 94 |
| 59 | `REQ-R9-01` | Zero-Cloud Biometric Privacy | Strict local-only guarantee for camera frames, embeddings, and audio | M7 | R9, AC Line 97 |
| 60 | `REQ-R9-02` | Encrypted Local Backup & Restore | Export/import encrypted SQLite database backup archive (`.aiguru-backup`) | M7 | R9, AC Line 98 |
| 61 | `REQ-R9-03` | Privacy Data Deletion Controls | Granular deletion of monitoring history, sessions, or account with confirmation | M7 | R9, AC Line 99 |
| 62 | `REQ-R9-04` | Developer Simulation Test Mode | Headless simulation mode (`--mock-camera`, `--dev`) for testing without webcam | M7 | R9 Line 51 |
| 63 | `REQ-R9-05` | Complete Documentation Suite | 8 comprehensive docs in `docs/` and root README.md | M7 | R9, AC Lines 102-105 |
| 64 | `REQ-E2E-01` | Comprehensive E2E Test Suite | 4-Tier Opaque-Box E2E Test Suite + Tier 5 Adversarial Coverage Hardening | M8 | Acceptance Criteria |

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Architecture Audit & Brand Transformation | R1: `docs/AI-GURU-ARCHITECTURE-AUDIT.md`, `docs/AI-GURU-IMPLEMENTATION-PLAN.md`, complete user-facing rebranding across Web UI, PWA, CLI, locales, preserving internal `deeptutor` package namespace | none | DONE |
| M2 | Local-First Unified Runtime & Database | R2: 11-table SQLite schema, migrations in `sqlite_store.py`, `/api/v1/health` endpoint, localhost 127.0.0.1 binding, launcher supervisor, Windows auto-start | M1 | DONE |
| M3 | AI Provider Abstraction (`TutorProvider`) & Dual-Mode | R3: `TutorProvider` interface, Cloud API + Local Ollama adapters, settings UI, hardware profiler (LOW/MED/HIGH), resource governor, auto-fallback | M2 | DONE |
| M4 | Study Monitoring Engine (Local CV) | R4: Local CV pipeline (5-10 FPS analysis, 30 FPS preview), face detection, identity verification, anti-spoof liveness, presence state machine, false-positive distraction filter, warning cooldown | M2 | IN_PROGRESS |
| M5 | Study Session Lifecycle & Gamification | R5 & R6: Session creation, pre-flight wizard, study room UI, telemetry logging, AI report summaries, XP calculation, streak tracking, badge system | M3, M4 | PLANNED |
| M6 | Parent Dashboard, Remote Access & Offline Resilience | R7 & R8: Parent pairing code, parent dashboard, encrypted outbound tunnel gateway, short-lived JWTs, opt-in live video, audit logs, ConnectivityManager, friendly error interceptor | M5 | PLANNED |
| M7 | Security, Backup, Dev Mode & Documentation | R9: Zero-biometric egress verification, encrypted backup/restore UI, privacy data purge, developer mock mode, all 8 documentation files (`docs/*`, `README.md`) | M6 | PLANNED |
| M8 | Final Verification & Adversarial Hardening | Phase 1: 100% E2E test suite pass (Tiers 1-4); Phase 2: Adversarial Coverage Hardening (Tier 5) | M1-M7 | PLANNED |

## Interface Contracts

### 1. Database Store (`deeptutor.services.session.sqlite_store`) ↔ All Subsystems
- **Tables**: `users`, `students`, `parents`, `parent_student_links`, `study_sessions`, `monitoring_events`, `session_reports`, `rewards`, `study_goals`, `settings`, `audit_logs`.
- **Methods**:
  - `create_study_session(...) -> StudySession`
  - `record_monitoring_event(session_id, event_type, confidence, duration, metadata) -> int`
  - `finish_study_session(session_id, stats) -> SessionReport`
  - `award_xp(student_id, xp, reason) -> Reward`
  - `create_pairing_code(student_id) -> str`
  - `verify_pairing_code(parent_id, code) -> bool`

### 2. AI Tutor Provider (`deeptutor.services.llm.tutor_provider`) ↔ ChatOrchestrator
- **Class**: `TutorProvider(ABC)`
- **Methods**:
  - `async stream(messages: list[dict], params: dict) -> AsyncIterator[StreamChunk]`
  - `async complete(messages: list[dict], params: dict) -> CompletionResponse`
  - `async check_health() -> ProviderHealth`
  - `get_hardware_profile() -> HardwareTier (LOW | MEDIUM | HIGH)`

### 3. Study Monitoring Engine ↔ Frontend / WebSocket
- **Endpoints**:
  - `WS /api/v1/monitoring/session/{session_id}` (Telemetry streaming)
  - `POST /api/v1/monitoring/enroll-face` (Local feature vector baseline)
  - `POST /api/v1/monitoring/verify-liveness` (Anti-spoof check)
- **Events**: `PRESENCE_CHANGE`, `LOOKING_AWAY`, `PHONE_DETECTED`, `IDENTITY_VERIFIED`, `WARNING_ISSUED`.

### 4. Parent Remote Access ↔ Parent Dashboard
- **Endpoints**:
  - `POST /api/v1/parent/auth/pair` (Code handshake)
  - `GET /api/v1/parent/student/{student_id}/live-status`
  - `GET /api/v1/parent/student/{student_id}/reports`
  - `WS /api/v1/parent/live-stream/{session_id}` (Opt-in WebRTC video feed)

## Code Layout

- Backend Root: `deeptutor/`
  - API Routers: `deeptutor/api/routers/` (`health.py`, `study_session.py`, `monitoring.py`, `parent.py`, `gamification.py`, `backup.py`)
  - Runtime & Supervisor: `deeptutor/runtime/` (`launcher.py`, `orchestrator.py`, `banner.py`, `governor.py`)
  - Services: `deeptutor/services/` (`database/`, `llm/tutor_provider.py`, `monitoring/`, `gamification/`, `remote/`, `backup/`)
- CLI Root: `deeptutor_cli/main.py`
- Frontend Root: `web/`
  - App Router: `web/app/` (`(workspace)/home`, `(workspace)/study-room`, `(workspace)/parent`, `(workspace)/reports`, `(workspace)/rewards`)
  - Components: `web/components/` (`monitoring/`, `session/`, `parent/`, `gamification/`, `settings/`, `layout/`)
  - Locales: `web/locales/{en,zh}/app.json`
- Documentation: `docs/` (`AI-GURU-ARCHITECTURE-AUDIT.md`, `AI-GURU-IMPLEMENTATION-PLAN.md`, `AI-GURU-LOCAL-SETUP.md`, `AI-GURU-SECURITY.md`, `AI-GURU-PARENT-ACCESS.md`, `AI-GURU-AI-MODELS.md`, `AI-GURU-TROUBLESHOOTING.md`) and `README.md`
- E2E Tests: `tests/e2e/` (Tiers 1-4 requirement-driven test runners)
