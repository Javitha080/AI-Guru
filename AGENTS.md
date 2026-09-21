# AI GURU — Agent Context (READ FIRST)

> **What this repo is:** AI Guru — a local-first AI tutoring platform built on the
> DeepTutor 1.5.11 fork. Adds: student study-monitoring (on-device CV),
> past-paper Exam Room, passcode-gated Parent Portal (Telegram alerts +
> outbound tunnel), encrypted incident vault, floating assistant.
> Upstream tutor core (agents/RAG/capabilities) is unchanged DeepTutor.

## ⚠️ Read-before-you-code rules

1. **Dual branding is intentional.** Internal identifiers stay `deeptutor`
   (package name, imports, env vars `DEEPTUTOR_*`, DB names). User-visible copy
   says "AI Guru". Do NOT rename internals.
2. **Git repository active.** Origin is `https://github.com/Javitha080/AI-Guru.git`.
   Verify tests and safety before committing or pushing changes.
3. **LSP lies about `aiosqlite`** (`Import could not be resolved`) — environmental,
   not real. Verify with: `.venv\Scripts\python.exe -c "import deeptutor.api.main"`.
4. **PowerShell 5.1 shell**: no `&&`; use `if ($?) { ... }`. Avoid inline regex with
   quotes — write temp scripts instead.
5. **Long-scoped subagents frequently return EMPTY results here.** Prefer doing work
   directly, or very short-scoped agents (<10 tool calls).
6. Python is ALWAYS `.venv\Scripts\python.exe` (3.12). Frontend commands run from
   `web\` via `npm.cmd` / `npx.cmd`.

## Run / verify

```powershell
# Full app (backend 8001 + frontend 3782, health-checked):
.venv\Scripts\python.exe -m deeptutor_cli.main start

# Manual backend / frontend:
.venv\Scripts\python.exe -m uvicorn deeptutor.api.main:app --host 127.0.0.1 --port 8001   # term 1
cd web ; npm run dev                                                                       # term 2 (first compile 30-60s)

# Verification battery (all must be green after ANY change):
.venv\Scripts\python.exe -m pytest tests/e2e tests/test_study_monitoring.py tests/test_study_monitoring_stress.py tests/test_cv_adversarial.py tests/services/test_remote_security.py tests/test_fresh_install_smoke.py -q
cd web ; npx tsc --noEmit ; npm.cmd run test:node        # tsc clean + node tests
# (CI runs the FULL suite instead: pytest tests deeptutor/learning/tests on 3.11–3.13 + web build)
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); import deeptutor.api.main; print('OK')"

# Lint/security (scoped only):
.venv\Scripts\python.exe -m ruff check <changed .py files>
```

Health: `GET http://127.0.0.1:8001/api/v1/health` · API docs `/docs` · UI `http://localhost:3782`

## Database — chat_history.db (SQLite, per-user)

Created ONLY by `services/database/migrations.py` (DDL in `services/database/schema.py`,
applied at app startup). Registry `MIGRATIONS` is at v1–v11 (001 core · 002 exams ·
003+ pause-durations/paper-bank/sitting-cols/nudge-event/outbox…) — append new
tables/migrations there, never ad-hoc CREATE in routers. Callable migrations must be
column-by-column idempotent (rerun-safe on already-migrated DBs).

Hard-won schema facts (violating these caused every P0 we fixed):

| Table | Contract |
|---|---|
| `study_sessions` | `status CHECK IN ('in_progress','completed','paused','abandoned')` — NO 'created'. `start_time REAL NOT NULL` → create rows as `'in_progress'` + start_time=now |
| `monitoring_events` | `id INTEGER AUTOINCREMENT` (never insert TEXT ids), column is `metadata_json` (NOT metadata), event_type/severity CHECK-constrained |
| `session_reports` | Real columns: focus_score/engagement_score/total_study_seconds/productive_seconds/distracted_seconds NOT NULL + ai_tutor_feedback… NO `report_data` col |
| `rewards` | `amount_xp`, reward_type CHECK ('xp','badge','streak_bonus','milestone'); FK students(id) |
| `settings` ⚠️ | **DUAL SHAPE** — migrations make `(key,value_json NOT NULL,…)`; the security stack needs `(key,value TEXT,…)`. NEVER hand-roll CREATE/SELECT here: always `await ensure_kv_settings(db)` (async, aiosqlite conn) first (services/remote/kv_settings.py — rebuilds to a dual-column layout once, keeps both writers working) |

FK enforcement is ON (PRAGMA) — seed `users`+`students` before referencing `student_id`.
`GamificationService.award_xp` does this itself (`INSERT OR IGNORE`, never raises —
returns False; idempotency is the caller's duty). Raw-SQL paths: copy the
`gamification_service._ensure_student` / `pairing._ensure_identity_rows` pattern.

## Backend map (deeptutor/)

~40 routers under `api/routers/` (+ `multi_user/router.py`) mounted in `api/main.py`
(prefix `/api/v1/*`, most gated by `Depends(require_auth)` from `routers/auth.py`).
`routers/monitoring.py` is an aggregation shim over `monitoring_core` /
`monitoring_camera` / `monitoring_session` — edit the sub-router, not the shim. Highlights:

| Area | Files |
|---|---|
| Parent portal 🔒 | `routers/parent.py` — EVERY route requires `require_parent` JWT except bootstrap trio (has-pin/set-pin/verify-pin) + refresh (rotation revokes old). PIN=PBKDF2-600k (v2$ format)+lockout (5 fails→5min); tokens 15min/7d via `services/remote/auth_jwt.py` |
| Monitoring | `routers/monitoring.py` (WS `/monitoring/session/{id}` behind `ws_require_auth`; live-consent/frame endpoints; strictness hook) ← `services/monitoring/` (cv_pipeline 8-stage, presence FSM 5s/20s, distraction whitelist, warning gates conf≥0.8/cooldown60s/max5-per-10min, `dispatch.py` = glue to telemetry+telegram+vault). ALL thresholds live in one dataclass `monitoring_config.DEFAULT_THRESHOLDS` (strictness profiles override subsets) — tune there, never scattered constants |
| Telegram outbox | `services/monitoring/notification_queue.py` — atomic claim (pending→sending→sent/dead), retry backoff 30·2ⁿ cap600s max8, loop-pinned worker started at lifespan + lazily |
| Tunnel | `services/remote/tunnel_gateway.py` cloudflared/ngrok watchdog; HONEST statuses (`local_only` never fakes active); `url_is_public` flag |
| Vault | `services/remote/video_vault.py` GURUVAULT02 envelope (random content-key wrapped by PBKDF2-600k KEK, HMAC wrong-PIN check, v1 read-only legacy, XOR fallback REMOVED). Flow: pending/ staging → seal_pending(pin). Filename regex `_VAULT_NAME_RE` anchors on epoch |
| Exams | `routers/exams.py` + `services/exams/{engine,store}.py` — VERBATIM paper extraction (reuse agents/question mimic_source parse; options split regex; MCQ grading mirrors QuizViewer semantics server-side; essays via factory.complete JSON judge; reference answers hidden until status='graded'; XP via `GamificationService.award_xp` + check_and_award). Paper bank auto-seeds in background at startup (`BankStore.ensure_seeded`); ingestion extras live alongside: bank_import/master_archive_importer/gemini_ocr |
| Gamification | `services/gamification/gamification_service.py` — REAL facade (the old phantom module is gone). profile/badges/rewards/award_xp/check_and_award over rewards+study_sessions |
| Study | `services/study/session_manager.py` (+get_session_report), telemetry_logger (batched, metadata_json), report_generator (real columns) |
| Settings | `services/config/runtime_settings.py` (JSON files in data/user/settings/) + db-side kv via kv_settings. `lan_access_enabled` system flag → launcher binds 0.0.0.0 |
| Auth/multi-user | optional JWT cookie/bearer; roles admin/user only (parent gate is separate PIN-JWT); ws auth: `ws_require_auth(ws)` BEFORE accept |

Tutor-core upstream (do not casually refactor): `agents/` pipelines
(chat AgentLoop, question, research, visualize, math_animator),
`capabilities/` LoopCapabilities (solve/mastery/obsidian/subagent/explore_context),
`core/` protocols, `runtime/orchestrator.py`, `services/llm/factory.complete/stream`.

## Frontend map (web/ — Next.js 16 App Router, React 19, TS, Tailwind)

- Transport: all `/api/*` proxied to backend by `proxy.ts` (env `DEEPTUTOR_API_BASE_URL`). WS client `lib/unified-ws.ts` (cookie-auth, resume_from).
- Pages: `(workspace)/home|study-room|exam|parent|achievements|book|co-writer…`, settings under `(utility)/settings/*`, auth `(auth)/login|register`.
- Floating chat: `components/floating/` (FloatingGuru owner: bubble/drag/PiP/selection-chip/Alt+Space; store `lib/floating/floatingChatStore.ts`; mirror sync via BroadcastChannel 'aiguru-floating'). Opens via CustomEvent `aiguru:open-floating-chat` (detail.context).
- Vision: `lib/monitoring/visionPipeline.ts` — MediaPipe FaceLandmarker (vendored assets `web/public/mediapipe/`, CDN fallback), landmark groups matching backend face_engine keys, brightness/Laplacian, throttled jpeg_b64, owns monitoring WS when sessionId given.
- Parent portal: `app/(workspace)/parent/page.tsx` + `lib/parent/parent-api.ts` (**pFetch** = Bearer attach + auto-refresh on 401 `parent_auth_required`; sessionStorage keys `aiguru.parent.access|refresh`). Vault tab expects `{items,pending_count}`; seal-on-unlock; incidents timeline from `/parent/sessions/{sid}` recent_incidents.
- Quiz: `lib/quiz-judge.ts` emits optional `onGrade({verdict,score})` frame; QuizViewer persists `[AI Score]` into notebook ai_judgment.
- First-run: `components/onboarding/FirstRunGate.tsx` mounts AIWizard when provider unconfigured && !localStorage('aiguru.onboarded').
- i18n: locales en only currently; literal English strings acceptable (eslint i18n warnings are tolerated).

## Conventions & gotchas checklist

- New DB access touching `settings`? → ensure_kv_settings first. New table? → migrations.py entry.
- New parent endpoint? → add `Depends(require_parent)`; audit via `_audit(...)` helper.
- Root `.env` is intentionally ignored as app config — settings live in `data/user/settings/*.json`.
- `redirect_slashes=False` in `api/main.py` — do NOT remove (trailing-slash 307s downgrade HTTPS behind proxies).
- CORS is two-mode (`_build_cors_settings`): permissive regex when auth is off, explicit origins when on — check before touching LAN/tunnel behavior.
- Any user-visible metric must come from a real query — hardcoded demo numbers are banned (this repo's audit explicitly hunted them).
- Frontend numeric fallbacks render `—`/null-state honestly; never fabricate scores.
- Windows console: prefer writing temp .py/.ps1 scripts over clever one-liners.
- Tests to extend when adding features: mirror placement (tests/services/<area>.py, tests/e2e tiers use MockCVPipeline/MockParentRemoteGateway fixtures + FK auto-provisioning wrapper in e2e/conftest). NOTE: e2e/conftest.py carries its own hand-maintained SCHEMA_SQL mock, not real migrations — sync it when changing schema.

## CI / toolchain (must stay in sync)

- Gates: `lint → typecheck → security → web → python-tests → docker`, aggregated in
  `CI Summary` (`.github/workflows/ci.yml`) — branch protection must require `CI Summary`
  alone, never an individual matrix entry. `push` is path-filtered; `pull_request` never is.
- Pins/profiles: ruff `0.16.0`, mypy `1.13.0` relaxed. The mypy exclusion profile
  (`tests/|scripts/|data/|agents/|services/rag/`) must stay identical in `ci.yml`,
  `.pre-commit-config.yaml`, `scripts/ci_check.py`. Bandit gate is HIGH-only (`-lll`).
- Python `>=3.11,<3.14` cap is intentional (no faiss wheels on 3.14; the 3.14 CI entry is
  experimental). Heavy extras are opt-in with fallbacks: `graphrag`, `rag-lightrag`,
  `monitoring` (opencv/mediapipe; absent → browser WASM CV).
- Frontend: `npm ci --legacy-peer-deps`; dev server via `node ./scripts/dev.mjs` (owns port
  resolution); prod build is `next build --webpack`.

## Companion docs

- `docs/AI-GURU-CODEBASE-MAP.md` — full router/service/page inventory + data flows
- `docs/AI-GURU-PARENT-ACCESS.md` — parent setup guide (non-technical)
- `docs/AI-GURU-RUN-GUIDE.md` — run/deploy/docker + troubleshooting

<!-- antislop:start -->
## antislop
For UI, copy, people, mobile layout, or code comments work, read `antislop.md` (core) and then the skill for the task:
- UI / visual: `skills/antislop-ui/SKILL.md`
- Copy & text: `skills/antislop-copywriting/SKILL.md`
- People: `skills/antislop-human/SKILL.md`
- Mobile / responsive: `skills/antislop-layoutmobile/SKILL.md`
- Code comments: `skills/antislop-code/SKILL.md`
Before starting, ask the user when antislop applies: during the work, or after it is done.
<!-- antislop:end -->
