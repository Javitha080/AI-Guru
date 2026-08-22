<div align="center">

<p><img src="assets/figs/logo/logo.png" alt="AI Guru logo" height="56" style="vertical-align: middle;">&nbsp;<img src="assets/figs/logo/banner.png" alt="AI Guru" height="48" style="vertical-align: middle;"></p>

# AI Guru — Local-First AI Tutoring & Study Supervision

**AI Guru** is a local-first, privacy-focused tutoring and study-supervision platform
built on the [DeepTutor](https://github.com/HKUDS/DeepTutor) v1.5.11 fork.
The full agent-native tutor core (chat agent loop, RAG, capabilities) is unchanged
upstream DeepTutor — this distribution adds **on-device study monitoring**, a
**past-paper Exam Room**, and a **passcode-gated Parent Portal** with Telegram alerts,
an outbound access tunnel, and an encrypted incident vault.

<p>
  <a href="#-quick-start"><img alt="Install — from source" src="https://img.shields.io/badge/Run-deeptutor%20start-0A0A0A?style=for-the-badge&labelColor=F5F5F4" height="32"></a>
  <a href="docs/AI-GURU-RUN-GUIDE.md"><img alt="Run guide" src="https://img.shields.io/badge/Docs-Run%20Guide-2563EB?style=for-the-badge&labelColor=F5F5F4" height="32"></a>
  <a href="docs/AI-GURU-PARENT-ACCESS.md"><img alt="Parent guide" src="https://img.shields.io/badge/Docs-Parent%20Portal-059669?style=for-the-badge&labelColor=F5F5F4" height="32"></a>
</p>

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](LICENSE)

[Features](#-features) · [Architecture](#-architecture) · [Quick Start](#-quick-start) · [Project Layout](#-project-layout) · [Documentation](#-documentation) · [Testing](#-testing)

</div>

---

## What is AI Guru?

AI Guru turns a student's laptop into a self-contained tutoring and study-supervision
station. Everything sensitive stays on the machine: the camera pipeline runs entirely
in the browser via MediaPipe, all records live in a local SQLite database, and the
backend binds to `127.0.0.1` unless you explicitly opt in to LAN access.

> **Dual branding is intentional.** User-visible copy says "AI Guru"; internal
> identifiers (package name `deeptutor`, env vars `DEEPTUTOR_*`, DB names, imports)
> keep the upstream namespace so the tutor core stays drop-in compatible with
> `pip install deeptutor`.

## Features

### Inherited from DeepTutor (tutor core)

| Area | What you get |
|------|--------------|
| Chat | Single agent loop with tool calling, knowledge-base grounding, attachments, image generation, subagent consults |
| Capabilities | Quiz (with AI answer judging), Research, Visualize, Solve, Mastery Path, Math Animator |
| Knowledge | Multi-engine RAG libraries: LlamaIndex, PageIndex, GraphRAG, LightRAG, linked Obsidian vaults; versioned re-indexing |
| Book & Co-Writer | "Living book" compiler with typed interactive blocks; selection-aware Markdown drafting with accept/reject diffs |
| Memory | Three-layer inspectable memory (L1 traces / L2 facts / L3 synthesis) with a traceable Memory Graph |
| Agents & Partners | Consult local coding CLIs (Claude Code, Codex, Gemini CLI, ...) or persistent IM partners mid-turn |

### Added by AI Guru

| Feature | Description |
|---------|-------------|
| **Study Monitoring** | 100% on-device computer vision (MediaPipe FaceLandmarker in the browser): face detection, liveness verification, head pose / gaze tracking, engagement scoring, distraction analysis with a study-gesture whitelist (reading, writing, drinking water). Warning gates require confidence >= 0.8 with 60s cooldown, max 5 warnings per 10 minutes. |
| **Study Room** | Pomodoro-style sessions with pre-flight camera/lighting checks, real-time focus gauge, batched telemetry logging, and AI-generated session reports |
| **Exam Room** | Upload past papers -> verbatim question extraction -> timed exam. MCQs are graded server-side mirroring QuizViewer semantics; essays are judged by an LLM against reference answers that stay hidden until grading completes |
| **Parent Portal** | Passcode-gated dashboard (PBKDF2 PIN + lockout, 15-min JWT access tokens with 7-day refresh). Pairing via `GURU-XXXX` codes. Live status, analytics trends, incident timeline, opt-in live video supervision |
| **Telegram Alerts** | Outbound notification queue with atomic claim semantics, exponential retry backoff (30s * 2^n, cap 600s, max 8 attempts), and dead-letter handling |
| **Remote Access Tunnel** | Zero-config outbound tunnel (cloudflared / ngrok watchdog) for parent access without port forwarding — statuses are honest (`local_only` never pretends to be active), every parent route audited |
| **Encrypted Incident Vault** | Monitoring incidents are sealed into an encrypted vault (`GURUVAULT02` envelope: random per-item content key wrapped by a PBKDF2-600k key derived from the parent PIN); wrong-PIN attempts are HMAC-detected |
| **Gamification** | XP with focus multipliers, daily streaks, achievement badges, and level progression persisted in SQLite |
| **Floating Assistant** | Draggable floating tutor bubble with drag/PiP modes, text-selection chip, `Alt+Space` hotkey, and cross-window sync via BroadcastChannel |
| **Offline Resilient** | Cloud API -> local Ollama -> offline fallback chain; monitoring and timers keep running without internet |

## Architecture

```
                +-------------------------------------------+
                |        Next.js 16 (React 19) UI           |
                |   Student workspace + Parent portal       |
                +---------------------+---------------------+
                                      | HTTP / WebSocket (cookie/JWT auth)
                                      v
+--------------------------------------------------------------------------+
|                     AI GURU LOCAL RUNTIME (FastAPI :8001)                |
|                                                                          |
|  Tutor core (upstream DeepTutor):     AI Guru additions:                 |
|    agents/  - chat/question/research/   services/monitoring/  CV glue    |
|               visualize/math_animator   services/exams/       Exam Room  |
|    capabilities/ - solve/mastery/...    services/gamification/ XP/badges |
|    services/llm/factory - providers    services/remote/ tunnel+vault+JWT |
|                                                                          |
|  37 routers under /api/v1  |  WS auth before accept  |  health endpoint  |
+------------------------------------+-------------------------------------+
                                     v
                    SQLite (per-user chat_history.db, WAL)
                    versioned migrations applied at startup
                                     ^
      Browser-side CV (MediaPipe FaceLandmarker, throttled JPEG frames)
      runs fully on-device - camera frames never leave the machine
```

**Stack:** Python 3.11-3.13 · FastAPI + aiosqlite · Next.js 16 App Router · React 19 · TypeScript · Tailwind CSS · MediaPipe (vendored WASM, CDN fallback) · optional cloudflared/ngrok + Telegram Bot API.

## Quick Start

### Prerequisites

- **Python 3.11–3.13**
- **Node.js 20+** (22 LTS recommended for development)

### From source

```bash
git clone https://github.com/Javitha080/AI-Guru.git
cd AI-Guru

# Backend
python -m venv .venv
# Windows PowerShell:
#   .\.venv\Scripts\Activate.ps1
source .venv/bin/activate            # macOS / Linux
python -m pip install --upgrade pip
python -m pip install -e .

# Frontend deps
cd web && npm ci --legacy-peer-deps && cd ..

# Configure once (ports + LLM provider), then run
deeptutor init
deeptutor start
```

Open **http://localhost:3782** (frontend). The FastAPI backend listens on
**http://127.0.0.1:8001** (`/api/v1/health` for a status check, `/docs` for the API).
Stop both with `Ctrl+C`. The first-run wizard appears when no model provider is
configured yet.

Development mode with hot reload:

```bash
deeptutor start --dev                 # Next.js HMR instead of a production build
```

Windows shortcut used during development of this repo:

```powershell
.venv\Scripts\python.exe -m deeptutor_cli.main start
```

### Docker

```bash
docker run --rm --name ai-guru \
  -p 127.0.0.1:3782:3782 \
  -v aiguru-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

Only port `3782` needs publishing — the frontend proxies `/api/*` and `/ws/*`
to the backend internally. See [CONTAINERIZATION.md](CONTAINERIZATION.md) for
Compose, rootless Podman, and split deployments.

### Configuration

Runtime settings live in plain JSON under `data/user/settings/` (edit via the web
Settings page). Project-root `.env` files are intentionally ignored as app config.

| File | Purpose |
|:---|:---|
| `model_catalog.json` | LLM / embedding / search provider profiles, API keys, active models |
| `system.json` | Ports, public API base, CORS, LAN-access flag (`lan_access_enabled`) |
| `auth.json` | Optional multi-user auth toggle and credentials |
| `interface.json` | Theme, language, UI preferences |
| `main.yaml` / `agents.yaml` | Runtime behavior and capability parameters |

## Project Layout

```
deeptutor/                  Python package (internal namespace kept from upstream)
  api/routers/              37 routers mounted at /api/v1 (parent.py, monitoring.py, exams.py, ...)
  agents/                   tutor-core pipelines (chat AgentLoop, question, research, ...)
  capabilities/             LoopCapabilities (solve, mastery, obsidian, subagent, ...)
  services/
    monitoring/             CV dispatch, presence FSM, warning gates, Telegram outbox
    exams/                  paper extraction engine + exam store
    gamification/           XP, badges, streaks over rewards/study_sessions
    remote/                 JWT auth, tunnel gateway, encrypted video vault
    database/migrations.py  versioned SQLite schema migrations
deeptutor_cli/              CLI entry point (deeptutor start/init/chat/...)
web/                        Next.js 16 frontend
  app/(workspace)/          home, study-room, exam, parent, achievements, book, co-writer...
  components/monitoring/    camera preview, HUD, frame sampler, CV worker
  lib/monitoring/           visionPipeline.ts (MediaPipe FaceLandmarker, vendored WASM)
  lib/parent/               parent-api.ts (Bearer attach + auto token refresh)
tests/                      pytest suites incl. e2e tiers + adversarial CV tests
docs/                       AI Guru documentation set (see below)
```

## Documentation

| Document | Contents |
|:---|:---|
| [AI-GURU-CODEBASE-MAP.md](docs/AI-GURU-CODEBASE-MAP.md) | Full router/service/page inventory and data flows |
| [AI-GURU-RUN-GUIDE.md](docs/AI-GURU-RUN-GUIDE.md) | Run, deploy, Docker, and troubleshooting |
| [AI-GURU-PARENT-ACCESS.md](docs/AI-GURU-PARENT-ACCESS.md) | Non-technical parent portal setup guide |
| [AI-GURU-SECURITY.md](docs/AI-GURU-SECURITY.md) | Privacy architecture and threat model |
| [AI-GURU-AI-MODELS.md](docs/AI-GURU-AI-MODELS.md) | Provider configuration, Ollama setup, fallback chain |
| [AI-GURU-TROUBLESHOOTING.md](docs/AI-GURU-TROUBLESHOOTING.md) | Common issues and fixes |
| [AI-GURU-ARCHITECTURE-AUDIT.md](docs/AI-GURU-ARCHITECTURE-AUDIT.md) / [AI-GURU-IMPLEMENTATION-PLAN.md](docs/AI-GURU-IMPLEMENTATION-PLAN.md) | Design audit and phased build plan |

## Testing

```bash
# Backend battery (e2e tiers, monitoring, adversarial CV, remote security, smoke)
.venv\Scripts\python.exe -m pytest tests/e2e tests/test_study_monitoring.py \
  tests/test_study_monitoring_stress.py tests/test_cv_adversarial.py \
  tests/services/test_remote_security.py tests/test_fresh_install_smoke.py -q

# Frontend typecheck + node tests
cd web && npx tsc --noEmit && npm run test:node
```

## Privacy & Security

- Camera frames, face landmarks, and embeddings are processed **in the browser only**;
  no biometric data is ever transmitted or stored outside your machine.
- All records persist in a local SQLite file; nothing is synced to any cloud service.
- The backend binds to `127.0.0.1` by default; LAN exposure requires an explicit
  settings toggle.
- Parent Portal access is gated behind a PBKDF2-hardened passcode with lockout,
  short-lived JWTs, device revocation, and full audit logging of logins and live views.
- Incident media lives in an encrypted vault whose keys are wrapped by the parent PIN;
  legacy plaintext fallbacks have been removed.

## Credits & License

Built on [DeepTutor](https://github.com/HKUDS/DeepTutor) v1.5.11 by HKUDS
(the upstream tutor core, agents, and capabilities are used unchanged — see their
[repo](https://github.com/HKUDS/DeepTutor) and
[paper](https://arxiv.org/abs/2604.26962)). AI Guru additions (study monitoring,
Exam Room, Parent Portal, vault, tunnel, gamification wiring) are original work in
this repository.

Licensed under [Apache License 2.0](LICENSE).
