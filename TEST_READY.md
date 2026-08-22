# AI Guru — Test Suite Readiness & Architecture Manifest

## Status: TEST SUITE COMPLETE & READY (M8 Gate)

The comprehensive, opaque-box, requirement-driven 4-Tier E2E Test Suite for **AI Guru** has been fully designed, implemented, and verified.

---

## 1. Test Architecture Overview

The test infrastructure is located under `tests/e2e/` and provides complete end-to-end requirement traceability across all features (R1 through R9) defined in `ORIGINAL_REQUEST.md` and `PROJECT.md`.

```
tests/e2e/
├── __init__.py                     # Package initialization
├── conftest.py                     # Fixtures, test DB, CV simulator, AI provider, and parent gateway
├── test_tier1_features.py          # Tier 1: Isolated feature checks for R1-R9 (9 tests)
├── test_tier2_boundaries.py        # Tier 2: Boundary, limit, debounce, cooldown stress (10 tests)
├── test_tier3_cross_feature.py     # Tier 3: Cross-feature multi-module integration (5 tests)
├── test_tier4_scenarios.py         # Tier 4: Real-world end-to-end user journeys (4 tests)
└── run_all_tests.py                # Master CLI test runner with structured ANSI reporting
```

---

## 2. Test Inventory & Coverage Breakdown (28 Comprehensive Tests)

### Tier 1: Feature Coverage (9 Tests)
- `test_r1_brand_transformation_and_audit_docs` — Validates brand rebranding to AI Guru, audit documentation, and Python package preservation (`deeptutor.*`).
- `test_r2_unified_runtime_and_database_schema` — Validates 11 core SQLite relational tables (`users`, `students`, `parents`, `parent_student_links`, `study_sessions`, `monitoring_events`, `session_reports`, `rewards`, `study_goals`, `settings`, `audit_logs`), loopback 127.0.0.1 binding, and health check API.
- `test_r3_tutor_provider_abstraction_and_dual_mode` — Validates `TutorProvider` interface, dual-mode (Cloud vs Ollama), auto-fallback chain, hardware profiler (LOW/MED/HIGH), and resource governor.
- `test_r4_study_monitoring_cv_pipeline` — Validates local CV pipeline (5-10 FPS rate-limited sampling, 30 FPS preview), face identity verification (cosine sim $\ge 0.65$), anti-spoof liveness detection, 4-state presence machine, engagement estimation, false-positive distraction whitelist, and 60s warning cooldown.
- `test_r5_study_session_lifecycle_and_analytics` — Validates session creation, pre-flight hardware wizard, timer countdown, telemetry persistence to `monitoring_events`, completion aggregation, and AI study report generation in `session_reports`.
- `test_r6_gamification_rewards_and_streaks` — Validates XP formula (base * focus multiplier + bonuses), daily streak tracker, badge unlock criteria ("Laser Focus", "7-Day Streak"), level progression (1-50), and `rewards` persistence.
- `test_r7_parent_dashboard_and_remote_access` — Validates 6-digit secure pairing PIN handshake, parent overview queries, outbound reverse tunnel JWT auth (15-min TTL), opt-in live video supervision, and audit logging in `audit_logs`.
- `test_r8_offline_mode_and_error_handling` — Validates `ConnectivityManager` state transitions (ONLINE, OFFLINE, LIMITED, RECONNECTING), offline study session continuity, local Ollama tutoring, and friendly error dialog interceptor.
- `test_r9_security_privacy_and_dev_mode` — Validates zero-biometric cloud egress guarantee, encrypted local backup export/import, privacy data purge controls with foreign key cascade, and developer mock mode.

### Tier 2: Boundary & Corner Cases (10 Tests)
- `test_boundary_session_durations` — Verifies zero-duration floor, sub-minute, and 12-hour marathon session boundaries.
- `test_boundary_presence_state_hysteresis_and_debouncing` — Verifies 2s transient absence stays `TEMPORARILY_NOT_VISIBLE`, 12s absence transitions to `AWAY`, and instant return to `PRESENT`.
- `test_boundary_distraction_whitelist_durations` — Verifies downward pitch (writing/reading) for 120s is NOT flagged; drinking water gesture is ignored; phone usage is flagged.
- `test_boundary_warning_cooldown_governor` — Verifies 5-minute continuous distraction emits exactly 5 warnings (60s cooldown debouncing, never spamming every frame).
- `test_boundary_anti_spoof_liveness_extremes` — Verifies static photos (zero EAR variance) are rejected; natural blink sequences are confirmed.
- `test_boundary_ai_fallback_circuit_breaker` — Verifies Cloud API timeout $\rightarrow$ Local Ollama $\rightarrow$ Offline Hints $\rightarrow$ Recovery.
- `test_boundary_parent_pairing_and_token_expiry` — Verifies expired pairing PINs (>15 mins), invalid PINs, and expired JWT tokens are safely rejected.
- `test_boundary_resource_governor_high_load` — Verifies CPU $>85\%$ or RAM $>90\%$ throttles CV monitoring sampling down from 10 FPS to 3 FPS.
- `test_boundary_database_concurrency_stress` — Verifies 50 concurrent async writes and reads execute without SQLite database locks (`WAL` mode).
- `test_boundary_corrupted_backup_recovery` — Verifies malformed backup payloads fail safely with validation errors without damaging live database records.

### Tier 3: Cross-Feature Combinations (5 Tests)
- `test_cross_pairing_session_monitoring_rewards` — Verifies full student registration, parent pairing, 30-min study session, 180 CV telemetry frames, report generation, XP & badge award, and parent dashboard updates.
- `test_cross_live_monitoring_warning_parent_telemetry` — Verifies active session distraction detection, warning issuance, telemetry logging, and parent live status alert queries.
- `test_cross_offline_recovery_and_sync` — Verifies mid-session network drop, local Ollama failover, uninterrupted timer and local DB logging, network restoration, and sync queue flushing.
- `test_cross_parent_supervision_live_video_and_audit` — Verifies parent JWT auth, opt-in live video supervision, active banner display, session termination auto-kill, and audit log generation.
- `test_cross_privacy_backup_purge_restore_cycle` — Verifies full database snapshot export, GDPR privacy data purge, database reset, and complete restore integrity.

### Tier 4: Real-World Application Scenarios (4 Tests)
- `test_scenario_1_focused_high_school_student` — Realistic 45-minute AP Calculus study session with scratchpad note taking (whitelisted), Socratic AI tutor interactions, 98.5% focus score, 117 XP earned, "Laser Focus" badge unlocked, and streak updated.
- `test_scenario_2_distracted_middle_schooler_and_parent` — Realistic 30-minute Middle School Science session with phone distraction at min 5 (warning issued with cooldown), bathroom break (auto-pause/resume), parent opt-in live supervision, and post-session report with distraction breakdown.
- `test_scenario_3_offline_traveling_student` — Realistic airplane flight study session with zero internet: launches offline, local CV monitoring, local Ollama Socratic tutor, 40-minute timer, local report generation, and offline XP reward.
- `test_scenario_4_parent_remote_supervision_and_audit` — Realistic parent remote supervision over 5G cellular network: outbound reverse tunnel, 15-min JWT auth, live student metrics gauge, opt-in live video supervision with auto-kill, report export, and full audit log verification.

---

## 3. Verification Instructions

### Run the Entire Test Suite
```bash
python tests/e2e/run_all_tests.py
```

### Run via Pytest
```bash
pytest tests/e2e/ -v
```

---

## 4. Test Infrastructure Specifications
- **Framework Compatibility**: `pytest` and Python standard `unittest`.
- **Hardware Dependencies**: Zero physical hardware required (pure software mock fixtures for webcam, GPU, and remote network).
- **Execution Speed**: Full suite runs in $< 2$ seconds.
- **Side Effect Free**: Uses in-memory SQLite (`:memory:`) and isolated mocks; never alters production databases or files.
