# AI Guru — End-to-End (E2E) Test Infrastructure & Architecture Specification

## 1. Overview & Testing Philosophy

The **AI Guru E2E Test Suite** is an opaque-box, requirement-driven, deterministic test infrastructure designed to comprehensively verify all functional, security, privacy, and architectural requirements (R1 through R9) defined in `ORIGINAL_REQUEST.md` and `PROJECT.md`.

The test suite operates under a strict **4-Tier Testing Methodology**:
- **Tier 1: Feature Coverage** — Isolated, requirement-mapped verification of every feature in R1 through R9.
- **Tier 2: Boundary & Corner Cases** — Stress conditions, debouncing, limits, cooldowns, disconnects, whitelist false-positive rejection, and edge heuristics.
- **Tier 3: Cross-Feature Combinations** — Multi-module integration pipelines linking pairing, sessions, local computer vision monitoring, gamification XP, and offline recovery.
- **Tier 4: Real-World Application Scenarios** — End-to-end, lifecycle user journeys simulating realistic student study sessions, parent remote supervision, and offline travel workflows.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                   AI GURU 4-TIER E2E TEST ARCHITECTURE                  │
├──────────────────────────────────────────────────────────────────────────┤
│ Tier 1: Feature Coverage (R1 - R9 Isolated Unit & Integration Tests)     │
│ ├── R1: Brand Rebranding & Audit Docs Verification                      │
│ ├── R2: Unified Local Runtime & 11-Table SQLite Schema                   │
│ ├── R3: AI Provider Abstraction (TutorProvider) & Dual-Mode Fallback    │
│ ├── R4: Local Study Monitoring Engine (CV, Anti-Spoof, Distraction Filter)│
│ ├── R5: Study Session Lifecycle & AI Summary Reports                    │
│ ├── R6: Rewards & Gamification Engine (XP, Streaks, Badges, Levels)     │
│ ├── R7: Parent Dashboard, Outbound Tunnel & Secure Remote Access         │
│ ├── R8: Offline Mode, ConnectivityManager & Friendly Error Interceptor  │
│ └── R9: Zero-Biometric Egress, Encrypted Backups & Data Purge Controls  │
├──────────────────────────────────────────────────────────────────────────┤
│ Tier 2: Boundary & Corner Cases (Stress, Edge, Cooldowns & Whitelists)  │
│ ├── Zero / Extreme Session Durations (0s to 12h)                        │
│ ├── Presence State Debounce Hysteresis (2s transient vs 12s away)       │
│ ├── Distraction Whitelist (Writing / Reading / Water Drinking)          │
│ ├── Warning Cooldown Governor (60s suppression window)                  │
│ ├── Anti-Spoof Static Image & Screen Replay Rejection                    │
│ ├── AI Fallback Circuit Breaker (Cloud -> Ollama -> Offline Hints)      │
│ ├── Parent Pairing Expiration (15-min TTL) & Brute-Force Rate Limiting  │
│ ├── Resource Governor CPU/RAM Throttle (10 FPS -> 3 FPS)                │
│ ├── Database Concurrency & Lock-Free WAL Mode Under Load                │
│ └── Corrupted Backup Archive Error Handling & DB Protection             │
├──────────────────────────────────────────────────────────────────────────┤
│ Tier 3: Cross-Feature Combinations (Multi-Module Integration Pipelines) │
│ ├── Student Pairing + Study Session + CV Telemetry + Gamification XP    │
│ ├── Live Monitoring + Distraction Detection + Warning + Parent View     │
│ ├── Active Session + Mid-Session Internet Drop + Local AI + Resume      │
│ ├── Parent Remote Session + Opt-In Live Video + Auto-Kill + Audit Log    │
│ └── Data Privacy Purge + Backup Export + DB Reset + Backup Restore      │
├──────────────────────────────────────────────────────────────────────────┤
│ Tier 4: Real-World Application Scenarios (End-to-End User Journeys)     │
│ ├── Scenario 1: The Focused High School Student (AP Calculus + 98% XP)  │
│ ├── Scenario 2: The Distracted Middle Schooler & Attentive Parent       │
│ ├── Scenario 3: The Offline Traveling Student (Airplane Study Mode)     │
│ └── Scenario 4: Parent Remote Supervision & Privacy Audit Logging       │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Directory Layout & Module Index

```
tests/e2e/
├── __init__.py                     # Package root
├── conftest.py                     # Pytest fixtures, test models, and mock simulators
├── test_tier1_features.py          # Tier 1: Feature Coverage (R1 to R9)
├── test_tier2_boundaries.py        # Tier 2: Boundary & Corner Cases
├── test_tier3_cross_feature.py     # Tier 3: Cross-Feature Combinations
├── test_tier4_scenarios.py         # Tier 4: Real-World User Scenarios
└── run_all_tests.py                # Master CLI test runner and reporter
```

---

## 3. Test Fixtures & Emulation Architecture

The test suite is fully self-contained and does NOT require physical webcams, GPU hardware, live internet connectivity, or external cloud API credentials.

### 3.1 SQLite In-Memory / Isolated Database Fixture (`isolated_db`)
- Creates all 11 core AI Guru relational tables with WAL mode, foreign keys, and indexes:
  1. `users` — Local student, parent, admin accounts
  2. `students` — Grade level, learning style, streaks, cumulative XP
  3. `parents` — Notification preferences, linked students
  4. `parent_student_links` — Pairing PINs, link status (`active`/`pending`/`revoked`)
  5. `study_sessions` — Duration, focus score, engagement, status
  6. `monitoring_events` — Timestamped CV telemetry and warning events
  7. `session_reports` — Focus summaries, strengths, improvement areas, AI feedback
  8. `rewards` — Earned XP, badges, streak bonuses
  9. `study_goals` — Daily and weekly study targets
  10. `settings` — JSON dynamic configuration store
  11. `audit_logs` — Security and remote access audit trail

### 3.2 Mock Computer Vision & Frame Generator (`MockCVPipeline`)
- Simulates real-time 30 FPS camera preview with 5–10 FPS sampled inference.
- Emulates:
  - Face bounding boxes and 478 3D landmarks.
  - Facial identity feature vector extraction and cosine similarity matching ($\ge 0.65$).
  - Anti-spoof passive liveness via Eye Aspect Ratio ($\text{EAR}$) variance and texture harmonics.
  - Head pose angles (Pitch, Yaw, Roll).
  - Activity classification: Writing/Reading (Pitch $25^\circ - 55^\circ$ down), Water drinking, Turning pages, Phone in hand, Looking away, Absence.
  - Presence state machine with 4-state debounced hysteresis: `PRESENT`, `TEMPORARILY_NOT_VISIBLE`, `AWAY`, `UNKNOWN`.
  - Engagement estimation score ($0 - 100$).
  - Warning system with 60-second debounce cooldown.

### 3.3 Mock `TutorProvider` & Dual-Mode AI Engine (`MockTutorProvider`)
- Implements `complete()`, `stream()`, `check_health()`, and `get_hardware_profile()`.
- Emulates:
  - Mode A (External Cloud API) with streaming tokens and `<think>` reasoning tags.
  - Mode B (Local Ollama LLM) on `http://127.0.0.1:11434`.
  - Mode C (Offline Rule-Based Study Engine).
  - Circuit-breaker auto-fallback chain (Cloud API error $\rightarrow$ Local Ollama $\rightarrow$ Offline Mode).
  - Hardware profiler (`LOW`, `MEDIUM`, `HIGH`) and dynamic resource governor.

### 3.4 Mock Remote Tunnel & Parent Gateway (`MockRemoteGateway`)
- Emulates:
  - Outbound encrypted reverse WebSocket tunnel.
  - 6-digit secure pairing PIN handshake (`GURU-XXXX`).
  - Short-lived JWT access tokens (15-minute expiry) and refresh token rotation.
  - Opt-in live video supervision stream with student banner and immediate auto-kill on session end.
  - Granular parent access audit logging.

### 3.5 Mock Connectivity Manager (`MockConnectivityManager`)
- Simulates network transitions across `ONLINE`, `OFFLINE`, `LIMITED`, and `RECONNECTING`.
- Verifies zero-crash offline continuity for local timer, CV monitoring, database persistence, reports, and gamification.

---

## 4. Requirement Traceability Matrix (R1 - R9)

| Requirement ID | Feature Name | Test Module | Test Method |
|---|---|---|---|
| **REQ-R1-01..06** | Brand Transformation & Architecture Audit | `test_tier1_features.py` | `test_r1_brand_transformation_and_audit_docs` |
| **REQ-R2-01..07** | Local-First Unified Runtime & 11-Table DB | `test_tier1_features.py` | `test_r2_unified_runtime_and_database_schema` |
| **REQ-R3-01..09** | AI Provider Abstraction & Dual-Mode Fallback | `test_tier1_features.py` | `test_r3_tutor_provider_abstraction_and_dual_mode` |
| **REQ-R4-01..10** | Local Study Monitoring Engine & Distraction Filter | `test_tier1_features.py` | `test_r4_study_monitoring_cv_pipeline` |
| **REQ-R5-01..08** | Study Session Lifecycle & AI Summary Reports | `test_tier1_features.py` | `test_r5_study_session_lifecycle_and_analytics` |
| **REQ-R6-01..05** | Rewards, Streaks, Badges & Level Progression | `test_tier1_features.py` | `test_r6_gamification_rewards_and_streaks` |
| **REQ-R7-01..08** | Parent Dashboard, Outbound Tunnel & Live Video | `test_tier1_features.py` | `test_r7_parent_dashboard_and_remote_access` |
| **REQ-R8-01..05** | Offline Continuity & User-Friendly Errors | `test_tier1_features.py` | `test_r8_offline_mode_and_error_handling` |
| **REQ-R9-01..05** | Zero-Biometric Egress, Encrypted Backup & Purge | `test_tier1_features.py` | `test_r9_security_privacy_and_dev_mode` |
| **REQ-BND-01..10** | Boundary, Limits, Debounce, Cooldown & Stress | `test_tier2_boundaries.py` | `test_boundary_*` (10 test cases) |
| **REQ-CRS-01..05** | Cross-Feature Multi-Module Integration | `test_tier3_cross_feature.py` | `test_cross_*` (5 test cases) |
| **REQ-SCN-01..04** | Real-World Application User Journeys | `test_tier4_scenarios.py` | `test_scenario_*` (4 test cases) |

---

## 5. How to Run the Tests

### Method 1: Master CLI Test Runner (Recommended)
Executes all test tiers with structured ANSI progress reporting, timing benchmarks, and a summary pass/fail matrix:
```bash
python tests/e2e/run_all_tests.py
```

### Method 2: Running via Pytest
Run the entire E2E test suite:
```bash
pytest tests/e2e/ -v
```

Run specific tiers:
```bash
pytest tests/e2e/test_tier1_features.py -v
pytest tests/e2e/test_tier2_boundaries.py -v
pytest tests/e2e/test_tier3_cross_feature.py -v
pytest tests/e2e/test_tier4_scenarios.py -v
```

### Method 3: Running via Python Unittest
```bash
python -m unittest discover -s tests/e2e -p "test_*.py" -v
```

---

## 6. Exit Codes & CI/CD Integration

- **Exit Code `0`**: All tests across Tiers 1 through 4 passed successfully with 100% requirement assertion verification.
- **Exit Code `1`**: One or more tests failed or raised unexpected errors. Detailed tracebacks and failed assertions are reported to stderr/stdout.
