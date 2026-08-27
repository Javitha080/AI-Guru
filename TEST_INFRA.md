# E2E Test Infra: AI Guru

## Test Philosophy
- Multi-tier requirement-driven and adversarial testing.
- Hermetic test execution with deterministic database fixtures (`AIGuruTestDB`) and mock hardware pipelines (`MockCVPipeline`, `MockParentRemoteGateway`).
- Methodology: Category-Partition + Boundary Value Analysis + Pairwise Combinations + Real-World Workloads + Adversarial Integrity Stress.

## Feature Inventory & Test Mapping
| # | Feature | Requirement | Tier 1 (Feature) | Tier 2 (Boundary) | Tier 3 (Cross-Feature) | Tier 4 (Workload) | Tier 5 (Adversarial) |
|---|---------|-------------|:----------------:|:-----------------:|:----------------------:|:-----------------:|:--------------------:|
| 1 | Study Room CV Telemetry | R1 | 5 tests | 5 tests | ✓ | ✓ | ✓ (tests/test_cv_adversarial.py) |
| 2 | Presence & Distraction FSM | R1 | 5 tests | 5 tests (hysteresis) | ✓ | ✓ | ✓ (temporal stress) |
| 3 | Telegram & Notification Outbox | R1 | 5 tests | 5 tests (retry backoff) | ✓ | ✓ | ✓ (outbox atomic claim) |
| 4 | Parent Portal Security & PIN JWT | R1, R2 | 5 tests | 5 tests (lockout) | ✓ | ✓ | ✓ (PBKDF2 brute-force defense) |
| 5 | GURUVAULT02 Encrypted Vault | R1, R2 | 5 tests | 5 tests (wrong PIN HMAC) | ✓ | ✓ | ✓ (XOR removal / tampering) |
| 6 | Exam Room Verbatim Parser & Grading | R1, R2 | 5 tests | 5 tests | ✓ | ✓ | ✓ (Docling/MarkItDown fallback) |
| 7 | Gamification & XP Distribution | R1, R2 | 5 tests | 5 tests | ✓ | ✓ | ✓ (streak calculation) |
| 8 | Cloudflare / Ngrok Tunnel Watchdog | R1, R4 | 5 tests | 5 tests | ✓ | ✓ | ✓ (tamper simulation) |

## Test Architecture
- Backend Runner: `.venv\Scripts\python.exe -m pytest tests/e2e tests/test_study_monitoring.py tests/test_study_monitoring_stress.py tests/test_cv_adversarial.py tests/services/test_remote_security.py tests/test_fresh_install_smoke.py -q`
- Frontend Runner: `cd web ; npm.cmd run test:node`
- Type Safety: `cd web ; npx.cmd tsc --noEmit`

## Coverage Summary
- Backend Test Battery: 100 passing pytest tests across 6 dedicated test modules.
- Frontend Test Battery: 413 passing unit/integration tests across 63 test files.
- TypeScript Compile Diagnostics: 0 errors.
