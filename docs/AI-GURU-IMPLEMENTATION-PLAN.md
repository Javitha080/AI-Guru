# AI Guru — Phased Engineering Implementation & Verification Plan

> **Document Version**: 2.0.0  
> **Status**: Approved Implementation Roadmap  
> **Authoritative Target**: DeepTutor 1.5.11 $\rightarrow$ **AI Guru** Local-First Platform  
> **Scope**: Milestones M1 through M8 with Explicit Acceptance Gates and Verification Criteria

---

## 1. Executive Overview & Strategy

The engineering rollout of **AI Guru** transforms the existing DeepTutor 1.5.11 repository into a production-grade, local-first, privacy-focused AI tutoring and study-monitoring platform. The implementation is organized into **eight discrete, sequential milestones (M1–M8)** designed with strict non-regression guarantees:

1. **Non-Destructive Evolution**: Every existing feature (all 7 multi-stage capabilities, 43 tools, and 33 REST/WebSocket endpoints) remains functional throughout all phases.
2. **Local-First & Zero-Biometric Egress**: Computer vision and biometric feature vectors execute 100% locally with zero cloud network exposure.
3. **Continuous Verification**: Each milestone includes concrete acceptance gates, unit/integration test suites, and strict regression test checklists before advancing to the next phase.

---

## 2. Master Milestone Roadmap

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                     ENGINEERING PHASING ROADMAP                                  │
├───────────────────┬──────────────────────────────────────────┬───────────────────┬───────────────┤
│ Milestone         │ Focus Area                               │ Requirements      │ Status        │
├───────────────────┼──────────────────────────────────────────┼───────────────────┼───────────────┤
│ **Milestone 1**   │ Architecture Audit & Brand Transformation│ REQ-R1-01 ~ R1-06 │ **ACTIVE**    │
│ **Milestone 2**   │ Local Runtime & 11-Table Relational DB   │ REQ-R2-01 ~ R2-07 │ Scheduled     │
│ **Milestone 3**   │ AI Provider Abstraction & Dual-Mode      │ REQ-R3-01 ~ R3-09 │ Scheduled     │
│ **Milestone 4**   │ Local CV Study Monitoring Engine         │ REQ-R4-01 ~ R4-10 │ Scheduled     │
│ **Milestone 5**   │ Study Session Lifecycle & Gamification   │ REQ-R5-01 ~ R6-05 │ Scheduled     │
│ **Milestone 6**   │ Parent Dashboard, Remote Tunnel & Offline│ REQ-R7-01 ~ R8-05 │ Scheduled     │
│ **Milestone 7**   │ Security, Backup, Dev Mode & Full Docs   │ REQ-R9-01 ~ R9-05 │ Scheduled     │
│ **Milestone 8**   │ Final Verification & Adversarial Tests   │ REQ-E2E-01        │ Scheduled     │
└───────────────────┴──────────────────────────────────────────┴───────────────────┴───────────────┘
```

---

## 3. Detailed Milestone Engineering Specifications

### 3.1 Milestone 1 (M1): Architecture Audit & Brand Transformation

#### Objectives:
- Complete exhaustive architectural audit (`docs/AI-GURU-ARCHITECTURE-AUDIT.md`) and implementation roadmap (`docs/AI-GURU-IMPLEMENTATION-PLAN.md`).
- Execute clean brand transformation across all user-facing surfaces (Web UI, PWA manifest, metadata, translation bundles, CLI banners, user documentation).
- Guarantee zero regression on internal Python package namespace (`deeptutor.*`) and imports.

#### Tasks & Work Breakdown:
1. `M1.1`: Create `docs/AI-GURU-ARCHITECTURE-AUDIT.md` covering full inventory of capabilities, tools, routers, schema, and new AI Guru subsystems.
2. `M1.2`: Create `docs/AI-GURU-IMPLEMENTATION-PLAN.md` with phased rollout, risk analysis, and acceptance criteria.
3. `M1.3`: Update Web UI titles and metadata in `web/app/layout.tsx`.
4. `M1.4`: Update Header bar, brand logo, and navigation titles in `web/components/layout/HeaderBar.tsx` and `web/components/layout/AppShell.tsx`.
5. `M1.5`: Rebrand English and Chinese localized strings in `web/locales/en/app.json` and `web/locales/zh/app.json`.
6. `M1.6`: Rebrand CLI startup ASCII banner and version labels in `deeptutor/runtime/banner.py` and help messages in `deeptutor_cli/main.py`.
7. `M1.7`: Verify Next.js build compilation (`npm run build`) and Python import integrity.

#### Acceptance Gate M1:
- [x] `docs/AI-GURU-ARCHITECTURE-AUDIT.md` and `docs/AI-GURU-IMPLEMENTATION-PLAN.md` exist and are fully populated.
- [x] Browser tab title displays "AI Guru" and HeaderBar displays AI Guru logo and title.
- [x] CLI `--help` and banner print "AI Guru" branding.
- [x] `pip install -e .` and `npm run build` execute cleanly with zero errors.
- [x] All 7 capabilities and 43 tools remain registered and functional.

---

### 3.2 Milestone 2 (M2): Local-First Unified Runtime & Database

#### Objectives:
- Implement the 11-table relational SQLite schema with version-controlled migrations in `deeptutor/services/database/`.
- Configure SQLite `WAL` mode, 5000ms busy timeout, and foreign key constraints.
- Implement comprehensive `/api/v1/health` subsystem health check endpoint.
- Enforce strict `127.0.0.1` localhost binding by default across launcher and API servers.
- Provide Windows auto-startup service hook and supervisor worker recovery.

#### Tasks & Work Breakdown:
1. `M2.1`: Implement `deeptutor/services/database/schema.py` defining DDL for 11 core tables (`users`, `students`, `parents`, `parent_student_links`, `study_sessions`, `monitoring_events`, `session_reports`, `rewards`, `study_goals`, `settings`, `audit_logs`).
2. `M2.2`: Implement migration manager in `deeptutor/services/database/migrations.py` with `schema_migrations` tracking table to ensure non-destructive upgrades of `data/user/chat_history.db`.
3. `M2.3`: Build comprehensive health aggregator `deeptutor/api/routers/health.py` probing DB, backend, camera, mic, AI provider, Ollama, CV engine, remote access, CPU, and RAM.
4. `M2.4`: Update `deeptutor/runtime/launcher.py` and `deeptutor_cli/main.py` ensuring default host is `127.0.0.1`.
5. `M2.5`: Implement Windows startup registry hook in `deeptutor/services/platform/windows_startup.py`.
6. `M2.6`: Add process supervisor recovery mechanism in `launcher.py` for worker crashes.

#### Acceptance Gate M2:
- SQLite database initializes all 11 tables with zero data loss on existing chat history.
- `GET /api/v1/health` returns HTTP 200 with structured JSON status for all subsystems.
- Port scan verifies backend and DB are bound strictly to `127.0.0.1`.
- Process supervisor successfully restarts terminated worker processes.

---

### 3.3 Milestone 3 (M3): AI Provider Abstraction (`TutorProvider`) & Dual-Mode

#### Objectives:
- Implement `TutorProvider` abstract base interface unifying Cloud APIs and Local Ollama.
- Implement Cloud Provider Adapter (OpenAI, Claude, DashScope, DeepSeek, Gemini, Perplexity) with `<think>` tag extraction.
- Implement Local Ollama Adapter querying `http://127.0.0.1:11434` for installed models.
- Implement hardware capability profiler (`LOW`, `MEDIUM`, `HIGH`) and dynamic `psutil` resource governor.
- Create AI Mode Settings UI and first-run AI Onboarding Wizard in Next.js.

#### Tasks & Work Breakdown:
1. `M3.1`: Define `TutorProvider` ABC in `deeptutor/services/llm/tutor_provider.py`.
2. `M3.2`: Implement `CloudAdapter` in `deeptutor/services/llm/cloud_adapter.py`.
3. `M3.3`: Implement `OllamaAdapter` in `deeptutor/services/llm/ollama_adapter.py`.
4. `M3.4`: Build `FallbackManager` orchestrating the circuit breaker chain: Cloud $\rightarrow$ Ollama $\rightarrow$ Offline Mode.
5. `M3.5`: Implement `HardwareProfiler` in `deeptutor/services/hardware/profiler.py` detecting GPU VRAM and CPU cores.
6. `M3.6`: Implement `ResourceGovernor` in `deeptutor/services/hardware/governor.py` throttling tasks when CPU $>85\%$ or RAM $>90\%$.
7. `M3.7`: Build AI Settings UI (`web/components/settings/AISettings.tsx`) and onboarding wizard (`web/components/onboarding/AIWizard.tsx`).
8. `M3.8`: Secure local API key storage with masked frontend delivery (`sk-...****`).

#### Acceptance Gate M3:
- User can toggle between Cloud API, Local Ollama, and Auto-Fallback in Settings UI.
- Simulated network failure during chat automatically falls back to Ollama with seamless UI toast.
- Hardware profiler correctly identifies system GPU/CPU tier and recommends model size.
- API keys are never exposed in plaintext in browser network responses or bundles.

---

### 3.4 Milestone 4 (M4): Study Monitoring Engine (Local Computer Vision)

#### Objectives:
- Build local-first computer vision pipeline running 100% on client/local backend with zero cloud egress.
- Decouple camera rendering (30 FPS local preview) from analysis inference (5–10 FPS).
- Implement facial landmark mesh, identity verification (cosine similarity $\ge 0.65$), and anti-spoof passive liveness.
- Implement 4-state presence state machine (`PRESENT`, `TEMPORARILY_NOT_VISIBLE`, `AWAY`, `UNKNOWN`).
- Implement false-positive distraction filter whitelisting reading, writing, turning pages, and drinking water.
- Implement warning system with confidence gating ($\ge 0.80$) and 60-second debounce cooldown.

#### Tasks & Work Breakdown:
1. `M4.1`: Implement client-side camera stream sampler in `web/components/monitoring/FrameSampler.ts` throttling inference to 5–10 FPS.
2. `M4.2`: Implement MediaPipe Face Mesh / Blendshape worker in `web/components/monitoring/CVWorker.ts`.
3. `M4.3`: Implement backend face verifier in `deeptutor/services/monitoring/verifier.py` comparing 128D facial feature vectors against enrolled baseline.
4. `M4.4`: Implement passive liveness detector in `deeptutor/services/monitoring/liveness.py` analyzing Laplacian variance and EAR blink micro-motion.
5. `M4.5`: Build presence hysteresis state machine in `deeptutor/services/monitoring/state_machine.py`.
6. `M4.6`: Implement posture and head pose classifier in `deeptutor/services/monitoring/pose.py` (Pitch, Yaw, Roll).
7. `M4.7`: Implement distraction analyzer in `deeptutor/services/monitoring/distraction_filter.py` with study gesture whitelist.
8. `M4.8`: Implement warning cooldown governor in `deeptutor/services/monitoring/warning_governor.py` (60s token bucket).

#### Acceptance Gate M4:
- Zero video frames or biometric vectors are transmitted over external networks.
- Writing in a notebook (head pitched down 20°–50°) is classified as studying (Focus = 100%).
- Holding a static photo to the camera fails liveness check and blocks session start.
- Looking away $>10$s triggers distraction warning; no duplicate warnings within 60s cooldown.

---

### 3.5 Milestone 5 (M5): Study Session Lifecycle & Gamification

#### Objectives:
- Implement complete study session lifecycle: creation, pre-flight hardware wizard, interactive study room, and summary report.
- Stream real-time focus, presence, and distraction telemetry to `monitoring_events` table.
- Generate LLM-powered post-session summary reports with strengths, weaknesses, and next steps.
- Implement XP calculation engine with focus multipliers, daily streak tracking with freeze, badge unlocks, and 50-level progression.

#### Tasks & Work Breakdown:
1. `M5.1`: Build session creation modal in `web/components/session/CreateSessionModal.tsx`.
2. `M5.2`: Implement pre-flight hardware and lighting check wizard in `web/components/session/PreFlightCheck.tsx`.
3. `M5.3`: Build interactive study room view in `web/app/(workspace)/study-room/page.tsx` with Pomodoro timer, focus gauge, privacy camera preview, and AI chat.
4. `M5.4`: Implement real-time telemetry persistence in `deeptutor/services/session/telemetry_logger.py`.
5. `M5.5`: Implement session completion aggregator and LLM report generator in `deeptutor/services/session/report_generator.py`.
6. `M5.6`: Implement XP engine in `deeptutor/services/gamification/xp_engine.py` applying focus multipliers.
7. `M5.7`: Implement daily streak tracker and streak freeze in `deeptutor/services/gamification/streak_tracker.py`.
8. `M5.8`: Implement achievement badge evaluator in `deeptutor/services/gamification/badge_engine.py` and level system in `level_system.py`.
9. `M5.9`: Build gamification UI widgets (XP bar, streak flame, badge trophy case) in `web/components/gamification/RewardCard.tsx`.

#### Acceptance Gate M5:
- Completing a study session generates a structured report in DB with focus graphs and AI summary.
- XP is correctly calculated using focus multipliers and saved to `rewards` table.
- Daily streaks increment accurately on consecutive study days.
- Badges unlock automatically upon meeting milestone criteria.

---

### 3.6 Milestone 6 (M6): Parent Dashboard, Remote Access & Offline Resilience

#### Objectives:
- Implement parent-student pairing handshake via 6-digit cryptographically secure pairing codes (`GURU-XXXX`).
- Build Parent Overview Dashboard with real-time status cards, historical trend charts, and report exports.
- Implement zero-config outbound encrypted tunnel gateway for remote parent access across NAT/firewalls.
- Enforce short-lived JWT access tokens (15-min expiry) with refresh rotation and device revocation.
- Implement opt-in point-to-point live video supervision with prominent student banner and auto-kill on session end.
- Implement `ConnectivityManager` (ONLINE, OFFLINE, LIMITED, RECONNECTING) and friendly non-technical error interceptors.

#### Tasks & Work Breakdown:
1. `M6.1`: Implement pairing code generator and verification in `deeptutor/services/remote/pairing.py`.
2. `M6.2`: Build Parent Dashboard in `web/app/(workspace)/parent/page.tsx` and analytics in `web/components/parent/ParentAnalytics.tsx`.
3. `M6.3`: Implement outbound reverse tunnel gateway in `deeptutor/services/remote/tunnel_gateway.py`.
4. `M6.4`: Implement JWT authentication and session revocation in `deeptutor/services/remote/auth_jwt.py`.
5. `M6.5`: Implement opt-in WebRTC live video feed in `web/components/parent/LiveVideoView.tsx` with student banner notification.
6. `M6.6`: Implement parent audit logger in `deeptutor/services/remote/audit_logger.py` logging all remote access actions.
7. `M6.7`: Build `ConnectivityManager` in `web/context/ConnectivityContext.tsx` and navbar indicator `web/components/layout/ConnectivityBadge.tsx`.
8. `M6.8`: Build friendly error interceptor in `web/components/common/FriendlyErrorModal.tsx`.

#### Acceptance Gate M6:
- Parent enters 6-digit code to pair; parent portal displays student live status and history.
- Outbound tunnel enables remote parent access across NAT without router port forwarding.
- Student UI clearly displays glowing notification when live camera supervision is active.
- Unplugging network cable allows study session, timer, CV monitoring, and local AI to continue uninterrupted.

---

### 3.7 Milestone 7 (M7): Security, Backup, Dev Mode & Full Documentation

#### Objectives:
- Conduct rigorous zero-biometric-egress network verification audit.
- Implement AES-GCM encrypted local backup and restore system (`.aiguru-backup`).
- Implement granular privacy data purge and factory reset controls.
- Implement Developer Simulation Test Mode (`--mock-camera`, `--dev`) for headless CI/CD testing.
- Produce complete 8-document suite in `docs/` and root `README.md`.

#### Tasks & Work Breakdown:
1. `M7.1`: Implement encrypted backup and restore manager in `deeptutor/services/backup/backup_manager.py`.
2. `M7.2`: Implement privacy data deletion in `deeptutor/services/database/purge_manager.py`.
3. `M7.3`: Implement mock video stream generator in `deeptutor/services/monitoring/mock_feed.py` for CLI flags `--mock-camera` and `--dev`.
4. `M7.4`: Create `README.md` with complete AI Guru overview, features, and setup commands.
5. `M7.5`: Create `docs/AI-GURU-LOCAL-SETUP.md` (installation guide for Windows/macOS/Linux, Ollama model setup).
6. `M7.6`: Create `docs/AI-GURU-SECURITY.md` (privacy architecture, zero-cloud biometrics, threat models).
7. `M7.7`: Create `docs/AI-GURU-PARENT-ACCESS.md` (remote pairing, tunnel architecture, security guarantees).
8. `M7.8`: Create `docs/AI-GURU-AI-MODELS.md` (hardware profiling, Ollama models, quantization recommendations).
9. `M7.9`: Create `docs/AI-GURU-TROUBLESHOOTING.md` (common error codes, camera fixes, performance tuning).

#### Acceptance Gate M7:
- Encrypted backup archive can be created and restored with full cryptographic verification.
- User can purge session history and biometric baseline with confirmation phrase.
- Headless test suite passes cleanly using `--mock-camera`.
- All 8 documentation files exist, are complete, and accurately describe the system.

---

### 3.8 Milestone 8 (M8): Final Verification & Adversarial Hardening

#### Objectives:
- Execute 4-Tier Opaque-Box E2E test suite covering all functional requirements.
- Execute Tier 5 Adversarial Coverage Hardening (simulated network cuts, extreme camera angles, high CPU load, corrupted data).
- Produce authoritative forensic verification report certifying platform readiness.

#### Tasks & Work Breakdown:
1. `M8.1`: Run Tier 1 Core Architecture & Preservation Tests.
2. `M8.2`: Run Tier 2 Local CV Monitoring & Distraction Tests.
3. `M8.3`: Run Tier 3 Session Lifecycle, Gamification & AI Mode Tests.
4. `M8.4`: Run Tier 4 Parent Remote Access & Tunnel Tests.
5. `M8.5`: Run Tier 5 Adversarial Hardening Tests (network drops, camera disconnections, resource spikes).
6. `M8.6`: Compile final verification audit report.

#### Acceptance Gate M8:
- 100% pass rate across all 5 test tiers.
- Zero functional regressions against baseline DeepTutor capabilities.
- Forensic audit certification approved.

---

## 4. Risk Assessment & Mitigation Strategies

| Risk Category | Potential Failure Mode | Impact | Architectural Mitigation Strategy |
|---------------|------------------------|--------|-----------------------------------|
| **CV False Positives** | Student writing or reading physical book classified as distracted | High (frustrates student) | Implement study gesture whitelist: head pitch $20^\circ-55^\circ$ downward with hand activity is classified as active studying. |
| **Alert Fatigue** | Warning chimes triggering repeatedly during minor posture shifts | Medium | 60-second debounce cooldown per category; minimum 10s continuous threshold before issuing alert. |
| **System Overload** | CV inference and local LLM overloading student CPU/GPU | High (causes lag) | Decouple monitoring inference to 5–10 FPS; `ResourceGovernor` dynamically throttles CV sample rate if CPU $>85\%$. |
| **NAT Traversal** | Parents unable to connect from external networks | High (breaks remote portal) | Outbound reverse encrypted WebSocket tunnel connects to relay gateway; zero router configuration required. |
| **Offline LLM Missing** | Ollama not installed or model missing during offline study | Medium | Fallback to Mode C (Offline Rule Engine) providing timer, flashcards, and study note recording without error crashes. |
| **Biometric Leakage** | Camera frames inadvertently sent to external APIs | Critical (violates privacy) | Architecture boundary: CV worker runs in isolated local sandbox; zero network socket accepts frame data. |

---

## 5. Verification & Rollback Procedures

### 5.1 Verification Checklist Per Phase
- **Build Verification**: `pip install -e .` and `npm run build` pass with zero exit codes.
- **Import Verification**: Python test script importing all 7 capabilities and 43 tools passes.
- **Database Verification**: SQLite migrations run idempotently on existing databases without deleting tables.
- **Health Verification**: `/api/v1/health` returns healthy status across all active subsystems.

### 5.2 Rollback Strategy
- Every database migration includes an automatic backup snapshot (`data/user/chat_history.db.bak`) prior to applying DDL changes.
- Configuration settings in `data/user/settings/*.json` maintain schema versioning with automatic default fallbacks.
