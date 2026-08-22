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
2. **No git repo here.** Never run git commands. A pre-change backup pattern is:
   robocopy to `%TEMP%\opencode\` excluding `.venv node_modules .next __pycache__`.
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
.venv\Scripts\python.exe -m pytest tests/e2e tests/test_study_monitoring.py tests/test_study_monitoring_stress.py tests/test_cv_adversarial.py tests/services/test_remote_security.py tests/test_fresh_install_smoke.py -q   # 93 tests
cd web ; npx tsc --noEmit ; npm.cmd run test:node        # tsc clean + 396 node tests
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); import deeptutor.api.main; print('OK')"

# Lint/security (scoped only):
.venv\Scripts\python.exe -m ruff check <changed .py files>
```

Health: `GET http://127.0.0.1:8001/api/v1/health` · API docs `/docs` · UI `http://localhost:3782`

## Database — chat_history.db (SQLite, per-user)

Created ONLY by `services/database/migrations.py` (applied at app startup).
**Migration 001**: 11 core tables · **002**: exams/exam_answers · registry in
`MIGRATIONS` list — add new tables there, never ad-hoc CREATE in routers.

Hard-won schema facts (violating these caused every P0 we fixed):

| Table | Contract |
|---|---|
| `study_sessions` | `status CHECK IN ('in_progress','completed','paused','abandoned')` — NO 'created'. `start_time REAL NOT NULL` → create rows as `'in_progress'` + start_time=now |
| `monitoring_events` | `id INTEGER AUTOINCREMENT` (never insert TEXT ids), column is `metadata_json` (NOT metadata), event_type/severity CHECK-constrained |
| `session_reports` | Real columns: focus_score/engagement_score/total_study_seconds/productive_seconds/distracted_seconds NOT NULL + ai_tutor_feedback… NO `report_data` col |
| `rewards` | `amount_xp`, reward_type CHECK ('xp','badge','streak_bonus','milestone'); FK students(id) |
| `settings` ⚠️ | **DUAL SHAPE** — migrations make `(key,value_json NOT NULL,…)`; the security stack needs `(key,value TEXT,…)`. NEVER hand-roll CREATE/SELECT here: always call `ensure_kv_settings(db)` first (services/remote/kv_settings.py — rebuilds to a dual-column layout once, keeps both writers working) |

FK enforcement is ON (PRAGMA) — seed `users`+`students` (helper patterns exist in
`gamification_service._ensure_student`, `pairing._ensure_identity_rows`,
`exams._award_exam_xp`) before referencing `student_id`.

## Backend map (deeptutor/)

37 routers under `api/routers/` mounted in `api/main.py` (prefix `/api/v1/*`,
most gated by `Depends(require_auth)` from `routers/auth.py`). Highlights:

| Area | Files |
|---|---|
| Parent portal 🔒 | `routers/parent.py` — EVERY route requires `require_parent` JWT except bootstrap trio (has-pin/set-pin/verify-pin) + refresh. PIN=PBKDF2+lockout; tokens 15min/7d via `services/remote/auth_jwt.py` |
| Monitoring | `routers/monitoring.py` (WS `/monitoring/session/{id}` behind `ws_require_auth`; live-consent/frame endpoints; strictness hook) ← `services/monitoring/` (cv_pipeline 8-stage, presence FSM 5s/20s, distraction whitelist, warning gates conf≥0.8/cooldown60s/max5-per-10min, `dispatch.py` = glue to telemetry+telegram+vault) |
| Telegram outbox | `services/monitoring/notification_queue.py` — atomic claim (pending→sending→sent/dead), retry backoff 30·2ⁿ cap600s max8, loop-pinned worker started at lifespan + lazily |
| Tunnel | `services/remote/tunnel_gateway.py` cloudflared/ngrok watchdog; HONEST statuses (`local_only` never fakes active); `url_is_public` flag |
| Vault | `services/remote/video_vault.py` GURUVAULT02 envelope (random content-key wrapped by PBKDF2-600k KEK, HMAC wrong-PIN check, v1 read-only legacy, XOR fallback REMOVED). Flow: pending/ staging → seal_pending(pin). Filename regex `_VAULT_NAME_RE` anchors on epoch |
| Exams | `routers/exams.py` + `services/exams/{engine,store}.py` — VERBATIM paper extraction (reuse agents/question mimic_source parse; options split regex; MCQ grading mirrors QuizViewer semantics server-side; essays via factory.complete JSON judge; reference answers hidden until status='graded'; XP via rewards INSERT + check_and_award) |
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
- Any user-visible metric must come from a real query — hardcoded demo numbers are banned (this repo's audit explicitly hunted them).
- Frontend numeric fallbacks render `—`/null-state honestly; never fabricate scores.
- Windows console: prefer writing temp .py/.ps1 scripts over clever one-liners.
- Tests to extend when adding features: mirror placement (tests/services/<area>.py, tests/e2e tiers use MockCVPipeline/MockParentRemoteGateway fixtures + FK auto-provisioning wrapper in e2e/conftest).

## Companion docs

- `docs/AI-GURU-CODEBASE-MAP.md` — full router/service/page inventory + data flows
- `docs/AI-GURU-PARENT-ACCESS.md` — parent setup guide (non-technical)
- `docs/AI-GURU-RUN-GUIDE.md` — run/deploy/docker + troubleshooting
