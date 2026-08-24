# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Guru — a local-first AI tutoring and study-monitoring platform built on the DeepTutor 1.5.11 fork. Adds on-device study monitoring (browser-side CV), a past-paper Exam Room, a passcode-gated Parent Portal (Telegram alerts + outbound tunnel), an encrypted incident vault, XP/streak/badge gamification, and a floating assistant. The upstream tutor core (`deeptutor/agents`, `capabilities`, RAG) is unchanged DeepTutor.

**Dual branding is intentional.** User-visible copy says "AI Guru"; internal identifiers stay `deeptutor` (package name, imports, env vars `DEEPTUTOR_*`, DB names). Never rename internals.

## Commands

Python is ALWAYS `.venv/Scripts/python.exe` (3.12). Frontend runs from `web/` via `npm.cmd`/`npx.cmd`. This is Windows; Claude Code's shell is bash (use forward slashes, no PowerShell syntax).

```bash
# Full app (backend :8001 + frontend :3782, health-checked supervisor)
.venv/Scripts/python.exe -m deeptutor_cli.main start          # add --dev for Next.js HMR

# Manual backend / frontend
.venv/Scripts/python.exe -m uvicorn deeptutor.api.main:app --host 127.0.0.1 --port 8001
cd web && npm run dev                                          # first compile 30-60s

# Verification battery — ALL must be green after ANY change:
.venv/Scripts/python.exe -m pytest tests/e2e tests/test_study_monitoring.py tests/test_study_monitoring_stress.py tests/test_cv_adversarial.py tests/services/test_remote_security.py tests/test_fresh_install_smoke.py -q
cd web && npx tsc --noEmit && npm run test:node                # tsc clean + node tests
.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'.'); import deeptutor.api.main; print('OK')"

# Lint/security (scoped to changed files only)
.venv/Scripts/python.exe -m ruff check <changed .py files>
```

Single test: `.venv/Scripts/python.exe -m pytest tests/services/test_foo.py::test_name -q`

Health: `GET http://127.0.0.1:8001/api/v1/health` · API docs `/docs` · UI `http://localhost:3782`

Note: LSP falsely reports `aiosqlite` as unresolvable ("Import could not be resolved") — environmental, not real. Verify imports with the python command above instead.

## Architecture

```
Next.js 16 App Router (web/)  ──HTTP/WS──▶  FastAPI backend (deeptutor/, :8001)
                                              │
        Browser-side CV (MediaPipe FaceLandmarker, throttled JPEG frames;
        frames NEVER leave the machine)       ▼
                                    SQLite per-user chat_history.db (WAL),
                                    versioned migrations applied at startup
```

- **Backend**: ~37 routers under `api/routers/` mounted in `api/main.py` at `/api/v1/*`; most gated by `Depends(require_auth)` (`routers/auth.py`). WS routes call `ws_require_auth(ws)` BEFORE accept.
- **Frontend**: all `/api/*` proxied to backend by `proxy.ts` (env `DEEPTUTOR_API_BASE_URL`). WS client `lib/unified-ws.ts`.
- **AI Guru additions** (services): `services/monitoring/` (CV dispatch, presence FSM, distraction whitelist, warning gates conf≥0.8/cooldown 60s/max 5 per 10min, Telegram outbox), `services/exams/` (paper extraction + store), `services/gamification/` (XP/badges/streaks), `services/remote/` (JWT auth, tunnel gateway, encrypted video vault GURUVAULT02, pairing), `services/study/` (session manager, telemetry, reports).
- **Tutor-core upstream — do not casually refactor**: `agents/` pipelines (chat AgentLoop, question, research, visualize, math_animator), `capabilities/` LoopCapabilities, `core/` protocols, `runtime/orchestrator.py`, `services/llm/factory.complete/stream`.
- **Config**: runtime settings are JSON under `data/user/settings/` (`system.json`, `model_catalog.json`, `auth.json`, ...); project-root `.env` files are intentionally ignored as app config. Backend binds `127.0.0.1` unless `lan_access_enabled` is set.
- **Floating chat**: `components/floating/FloatingGuru` opens via CustomEvent `aiguru:open-floating-chat`; cross-window sync via BroadcastChannel `aiguru-floating`.
- **Parent portal frontend**: use `pFetch` from `lib/parent/parent-api.ts` (Bearer attach + auto-refresh on 401).

Full inventories: `AGENTS.md` (agent context with schema contracts), `PROJECT.md` (requirements/milestones), `docs/AI-GURU-CODEBASE-MAP.md` (router/service/page map).

## Database — hard rules

DB is created ONLY by `services/database/migrations.py` (applied at startup). Add new tables as entries in the `MIGRATIONS` list — never ad-hoc CREATE TABLE in routers.

Schema contracts (violating these caused past P0 bugs):

| Table | Contract |
|---|---|
| `study_sessions` | `status` CHECK IN ('in_progress','completed','paused','abandoned') — NO 'created'. Create rows as `'in_progress'` with `start_time=now` |
| `monitoring_events` | INTEGER autoincrement id (never TEXT), column is `metadata_json` (NOT metadata), event_type/severity CHECK-constrained |
| `session_reports` | Real columns (focus_score, engagement_score, total_study_seconds, productive_seconds, distracted_seconds...) — NO `report_data` column |
| `rewards` | `amount_xp`, reward_type CHECK ('xp','badge','streak_bonus','milestone') |
| `settings` ⚠️ | DUAL SHAPE — always call `ensure_kv_settings(db)` (`services/remote/kv_settings.py`) before any hand-written CREATE/SELECT here |

FK enforcement is ON (PRAGMA) — seed `users`+`students` rows before referencing `student_id` (helper patterns exist in `gamification_service._ensure_student`, `pairing._ensure_identity_rows`, `exams._award_exam_xp`).

## Conventions & gotchas

- New parent endpoint? → `Depends(require_parent)` + audit via `_audit(...)` helper.
- Any user-visible metric must come from a real query — hardcoded demo numbers are banned. Frontend numeric fallbacks render `—`/null-state honestly; never fabricate scores.
- Tests: mirror placement (`tests/services/<area>.py`); e2e tiers use MockCVPipeline/MockParentRemoteGateway fixtures plus FK auto-provisioning wrapper in `tests/e2e/conftest.py`.
- i18n: English-only currently; literal English strings acceptable (eslint i18n warnings tolerated).
- Prefer writing temp `.py`/`.ps1` scripts over clever one-liners on Windows console.
- Long-scoped subagents frequently return empty results in this repo — prefer doing work directly or very short-scoped agents (<10 tool calls).
