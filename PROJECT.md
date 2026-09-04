# Project: AI Guru — System-Wide Audit, Debugging, and Polish

## Architecture

AI Guru is a local-first AI tutoring platform built on the DeepTutor 1.5.11 architecture with advanced student study-monitoring (on-device CV), past-paper Exam Room, passcode-gated Parent Portal (with Telegram alerts and outbound Cloudflare/ngrok tunnels), encrypted incident video vault (GURUVAULT02 PBKDF2/AES-GCM), and a floating PiP assistant.

### Architecture Map & Data Flow
1. **Frontend Presentation & State Layer (`web/`)**:
   - Next.js 16 App Router, React 19, Tailwind CSS, TypeScript.
   - Ember Glass theme tokens, GSAP motion utilities (`useGsapReveal.ts`), motion tokens in `globals.css`.
   - Unified WebSocket transport (`lib/unified-ws.ts`), single-flight Parent Portal API client (`lib/parent/parent-api.ts`), MediaPipe WebAssembly FaceLandmarker pipeline (`lib/monitoring/visionPipeline.ts`).
   - Workspace Views: Study Room (`/study-room`), Exam Room (`/exam`, `/papers`), Parent Portal (`/parent`), Unified Chat (`/home`), Floating PiP Guru, Achievements (`/achievements`), Book Creator (`/book`), Co-Writer (`/co-writer`), Settings (`/settings/*`).
2. **Backend API & Service Layer (`deeptutor/`)**:
   - FastAPI application (`deeptutor/api/main.py`) mounting 40 router modules (`deeptutor/api/routers/` + `multi_user/router.py`).
   - Services:
     - `services/monitoring/`: 8-stage CV pipeline, presence FSM (5s/20s thresholds), distraction whitelist, telemetry dispatcher.
     - `services/exams/`: Verbatim paper extraction (MinerU/Docling/MarkItDown), MCQ deterministic grader, LLM essay judge, paper bank sitting runner.
     - `services/remote/`: Video vault (`video_vault.py` GURUVAULT02 PBKDF2/AES-GCM), tunnel watchdog (`tunnel_gateway.py`), parent JWT auth (`auth_jwt.py`).
     - `services/gamification/`: SQLite rewards, XP calculations, streak bonuses, milestone badges.
     - `services/study/`: Session manager, telemetry logger, session report generator.
3. **Storage & Persistence Layer (`chat_history.db`)**:
   - SQLite with WAL mode, foreign key constraints enabled.
   - Versioned migrations (001–007) managed strictly via `services/database/migrations.py`.
   - Dual-shape key-value settings (`value TEXT` and `value_json TEXT NOT NULL`) initialized via `ensure_kv_settings(db)`.

---

## Feature Inventory

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F01 | Backend Router Mounting & Wiring | 40 router modules in `deeptutor/api/routers/` fully wired with live endpoints | M1 (Backend Hardening) | Survey Backend |
| F02 | Payload Validation & Path Traversal Guards | Typed Pydantic models, strict path traversal checks, raster magic-byte validation | M1 (Backend Hardening) | Survey Backend |
| F03 | Database Schema & Migration Integrity | Strict adherence to migrations 001–007, `metadata_json`, `study_sessions` CHECK, `ensure_kv_settings` | M1 (Backend Hardening) | Survey Backend |
| F04 | Mock Elimination in Backend Services | Real CV pipeline, PBKDF2/AES-GCM vault, verbatim exam engine, real gamification | M1 (Backend Hardening) | Survey Backend |
| F05 | Frontend Workspace Live Data Binding | All workspace pages wired to live backend API/WS without fake stats | M2 (Frontend UI Wiring) | Survey Frontend |
| F06 | Honest Fallbacks & Error States | Render honest `—`/null-states, offline banners, and skeleton loaders on network disconnect | M2 (Frontend UI Wiring) | Survey Frontend |
| F07 | TypeScript Safety | Clean compilation with zero TypeScript errors (`npx.cmd tsc --noEmit`) | M2 (Frontend UI Wiring) | Survey Frontend |
| F08 | UI Motion & Transition Token Polish | Smooth modals, dropdowns, sliding tabs, toast pop-ins, and AI thinking states | M3 (Motion Polish) | Survey Polish |
| F09 | Motion Token Alignment | Standardized `--duration-*`, `--ease-*`, and `prefers-reduced-motion` compliance | M3 (Motion Polish) | Survey Polish |
| F10 | 5-Tier E2E & Adversarial Test Battery | Comprehensive test suite covering Tiers 1–5, stress tests, and fresh install smoke | M4 (E2E Test Suite) | Survey Testing |
| F11 | Final System Diagnostic & Debug Report | Exhaustive diagnostic report categorizing all audited subsystems, bugs resolved, and logs | M5 (Final Report) | Request R5 |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Backend Routers & API Wiring Audit | Audit all 38 backend routers, eliminate mock stubs, verify DB schema adherence, harden error handling | None | DONE |
| M2 | Frontend Workspace Real-Data Wiring & Fallbacks | Audit workspace routes, eliminate fake metrics, verify honest fallback/loading states, ensure TS 0 errors | M1 | DONE |
| M3 | UI/UX Motion Tokens & Transitions Polish | Apply transitions-dev and transitions-polish tokens across modals, tabs, dropdowns, thinking states | M2 | DONE |
| M4 | E2E Multi-Tier Test Suite Verification | Run & verify full test suite (Tiers 1–5, 100 milestone pytest tests + 420 frontend tests) | M1, M2, M3 | IN_PROGRESS |
| M5 | Comprehensive Diagnostic & Polish Report | Compile system-wide diagnostic, bug resolution, wiring inventory, and verification logs | M4 | PLANNED |

---

## Interface Contracts

### Backend ↔ Frontend API Contract
- Base URL: `http://127.0.0.1:8001/api/v1/` proxied via Next.js `web/proxy.ts`.
- WebSocket Transport: `/ws/study/{session_id}`, `/ws/monitoring/session/{session_id}`, `/ws/chat/stream`.
- Authentication:
  - Student / General: Cookie-based / Bearer JWT validated via `require_auth` / `ws_require_auth`.
  - Parent Portal: PIN-derived Bearer JWT validated via `require_parent` (15m access / 7d refresh in sessionStorage).
- Error Response Format: `{"detail": string | list[dict]}` with standard HTTP status codes (400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found, 422 Unprocessable Entity, 500 Internal Server Error).

### Storage ↔ Service Contract
- SQLite Database: `chat_history.db`.
- Migrations: Applied in order 001 -> 007 at lifespan startup in `deeptutor/services/database/migrations.py`.
- Settings Table: Dual-shape `(key TEXT PRIMARY KEY, value TEXT, value_json TEXT NOT NULL, updated_at REAL)`. Always call `ensure_kv_settings(db)`.
- Study Sessions Table: Status column must strictly be one of `'in_progress'`, `'completed'`, `'paused'`, `'abandoned'`.
- Monitoring Events Table: Columns `(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, event_type TEXT, timestamp REAL, severity TEXT, metadata_json TEXT)`.

---

## Code Layout

- `deeptutor/api/routers/`: 40 REST & WebSocket routers (incl. `multi_user/router.py`).
- `deeptutor/services/`: Core business logic (monitoring, exams, remote/security, gamification, study, config).
- `deeptutor/agents/`: LLM tutoring pipelines (chat, question, research, visualize, math_animator).
- `web/app/(workspace)/`: User workspace routes (study-room, exam, papers, achievements, book, co-writer).
- `web/app/(portal)/`: Passcode-gated Parent Portal routes.
- `web/components/`: Reusable React components (floating assistant, chat, exam, monitoring, modals, common).
- `web/lib/`: Frontend state stores, API clients, motion utilities, WebAssembly vision pipelines.
- `tests/`: Multi-tier pytest test suites (e2e, CV monitoring, security, adversarial, fresh install).
- `web/tests/`: Node-based frontend unit test suites.
