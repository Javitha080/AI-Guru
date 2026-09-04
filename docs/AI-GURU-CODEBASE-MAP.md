# AI GURU — Codebase Map

> Companion to `AGENTS.md`. Everything here is verified against source
> (post-upgrade audit). Update this file when you add routers/services/pages.

---

## 1. Top-level layout

```
deeptutor/            Python backend package (FastAPI app in deeptutor/api/main.py)
  api/routers/        37 routers (~380 endpoints) under /api/v1
  agents/             Tutor pipelines: chat(AgentLoop), question, research, visualize, math_animator (+_shared)
  capabilities/       LoopCapabilities: solve, mastery, obsidian, subagent, explore_context
  services/
    monitoring/       CV pipeline + dispatch glue + telegram outbox
    remote/           Parent security stack: auth_jwt, pairing, tunnel_gateway, video_vault, telegram_notifier, kv_settings, audit_logger
    exams/            Exam engine (engine.py models/grading, store.py persistence)
    study/            session_manager, telemetry_logger, report_generator
    gamification/     gamification_service facade (+ legacy engines badge/xp/streak)
    database/         schema.py (V1 core DDL, V2 exams) + migrations.py registry
    config/           runtime_settings.py (data/user/settings/*.json), provider_runtime, key_vault
    llm/              provider_core (canonical), factory.complete/stream, tutor_provider tri-mode
    rag/ parsing/ memory/ sandbox/ partners/ mcp/ cron/ backup/ hardware(governor)/ platform(win autostart)
  multi_user/         optional JWT auth, grants, path isolation (ContextVar user)
  runtime/            launcher (spawns uvicorn+next, LAN bind switch), orchestrator, registries
  tools/ builtin/     ~30 built-in agent tools
deeptutor_cli/        `python -m deeptutor_cli.main start|serve` entrypoints
web/                  Next.js 16 App Router UI (:3782; proxy.ts → backend)
tests/                pytest suites (root tests/, tests/services/, tests/e2e tiers 1-4)
docs/                 guides incl. this file
data/user/            runtime data: settings/*.json, chat_history.db, workspace/, video_vault/
```

## 2. Router inventory (prefix → file · #endpoints)

| Prefix | File | # |
|---|---|---|
| /auth | auth.py | 15 |
| /health | health.py | 6 |
| /parent 🔒PIN-JWT | parent.py | 26 |
| /monitoring | monitoring.py | 8 (WS + live/* + events) |
| /study-session | study_session.py | 13 |
| /exams 🔒require_auth | exams.py | 7 |
| /question/judge (WS) | quiz_judge.py | 1 |
| /question-notebook | question_notebook.py | 12 |
| /knowledge | knowledge.py | 49 |
| /settings (+public ui) | settings.py | 45 |
| /memory | memory.py | 27 |
| /partners (admin) | partners.py | 32 |
| /book | book.py | 23 |
| /sessions | sessions.py | 7 |
| /mastery-path | mastery_path.py | 8 |
| /co-writer | co_writer.py | 12 |
| /skills | skills.py | 12 |
| /subagents | subagents.py | 10 |
| /system | system.py | 9 |
| /ai-provider | ai_provider.py | 10 |
| /space/mcp · /space/cli-apps | self-gated | 13 |
| others | notebook(11) mcp_settings(5) personas(5) plugins_api(4) dashboard(2) agent_config(2) imports(2) voice(2) chat(4) question(2) attachments(1) outputs(1) tools(1) unified_ws(1 WS) | |

Auth model: generic `require_auth` (JWT cookie/bearer; no-op when AUTH_ENABLED=false).
Parent portal uses a SEPARATE PIN→JWT gate (`require_parent`) — student tokens are rejected.

## 3. Monitoring data flow (student side)

```
getUserMedia ──► <video hidden> ──► web/lib/monitoring/visionPipeline.ts
   MediaPipe FaceLandmarker (WASM GPU→CPU, assets /mediapipe/*, CDN fallback)
   per tick @targetFps(default 5):
     landmarks{left_eye[6],right_eye[6],mouth[6],all_points[478],nose_tip,chin,forehead,cheeks}
     brightness(0-1) · jpeg_b64(q0.6,320px)
   └─ WS /api/v1/monitoring/session/{id}  {type:'telemetry', data:{...}}
Backend cv_pipeline.process_telemetry_payload (8 stages):
  face_engine(geometry, cosine≥0.65 identity vs enrolled baseline)
  liveness(EAR blink<0.18/>0.25, motion var, texture laplacian)
  pose_gaze(yaw/pitch/roll, posture classes) → presence FSM(PRESENT/TNV≥5s/AWAY≥20s)
  distraction whitelist(read/write/drink≤6s/page≤4s/posture≤4s) vs flags(phone≥4s,mismatch≥15s,drowsy≥4s,away)
  engagement EMA 45/35/20 weights → warning_manager(conf≥0.80·cooldown60s·5/10min)
dispatch.handle_warning ⇒ telemetry_logger(batched INSERT metadata_json)
                        ⇒ notification_queue.enqueue('warning') [atomic claim→Telegram]
                        ⇒ video_vault.save_pending_clip/snapshot (ring buffer 30f)
WS close ⇒ _purge_session_state + update_scores(session row)
```
Strictness mapping (supervision_rules_default): gentle 90s/.85 · balanced 60s/.80 · strict 30s/.75.
Shared kernel (refactor): monitoring_config (all thresholds) · schemas (TelemetryUpdate/brightness/pose-gaze)
 · session_scores (ScoreAccumulator/EpisodeTracker) · landmarks_codec · synthetic (mock telemetry)
 · camera_settings · warning_gates (EpisodeGate/RateLimiter) · warning_sinks · outbox_repo
 · face_solvers (EAR/PnP/gaze) · session_registry (preferred over direct _active_* globals).
Frontend: lib/monitoring/wsReconnect (shared backoff) + monitoringApi (central URLs)
 · hooks/useMonitorMode + useWarningFeed composed by useStudyTelemetry.
Migration 008 adds NUDGE_ISSUED to monitoring_events (was silently dropped).

## 4. Parent portal flow

```
Wizard: set-pin(PBKDF2, no current needed first time) → telegram config(test send)
        → tunnel start(cloudflared quick/ngrok; watchdog auto-restart×3; url_is_public honest)
        → supervision rules PUT /parent/supervision-rules
verify-pin ⇒ {access_token 15min, refresh_token 7d} → sessionStorage aiguru.parent.*
pFetch() attaches Bearer; on 401 parent_auth_required → POST /auth/refresh once.
On unlock: POST /vault/seal {pin} seals pending captures (AES-GCM envelope v2).
Dashboard: real status via monitoring._active_monitoring_sessions + latest in_progress session;
           streak/xp/level from GamificationService. Incidents: WARNING_ISSUED rows joined to sessions.
Live view: student toggles consent → POST /monitoring/live/frame (~1.5s throttle, RAM only,
           TTL 60s, purged on WS close) ⇄ GET /parent/live/snapshot (can_view_live enforced).
Audit: every security action → AuditLogger.log_event (audit_logs table).
```

## 5. Exam engine flow

```
POST /exams/upload (pdf) → ParseService(mineru/docling/markitdown/pymupdf4llm/text_only;
      content-addressed cache) → question_extractor verbatim *_questions.json
  → templates_to_paper(): split_options regex (A)/A./… ≥3 options & starts at 'A')
  → solve_missing_answers() ONE batch LLM call only when answer key absent (tolerated fail)
  → exams + exam_answers tables (migration 002)
start → ends_at=now+mcq_duration. submit: MCQ deterministic (mirrors QuizViewer:
      choice key/text match, concept T/F coerce, fill_in_blank ci-equal);
      essays via llm factory JSON judge {verdict,score,feedback} timeout120s.
GET /result hides reference_answer/explanation until status='graded'.
XP: rewards INSERT (FK-safe ensure_student) + check_and_award badges.
```

## 6. Frontend pages/components of note

| Path | Role |
|---|---|
| app/(workspace)/home/[[...sessionId]] | main chat (UnifiedChatContext reducer ~2000 lines) |
| app/(workspace)/study-room | monitored session UX (Vision Guard card, warnings feed, camera preview, live-view toggle) |
| app/(workspace)/exam | upload→timed runner(MCQ-first)→results; submitRef guards double-submit |
| app/(workspace)/parent/page.tsx | wizard/lock/tabs overview·analytics·vault·settings; pFetch everywhere |
| components/floating/FloatingGuru(.tsx)+Panel | bubble+panel+PiP detach(documentPictureInPicture)+BroadcastChannel mirror 'aiguru-floating' |
| lib/unified-ws.ts | typed WS client (heartbeat30s/dead45s/backoff5/resume_from) |
| context/UnifiedChatContext.tsx | session/stream state machine for chat |
| components/onboarding/{AIWizard,FirstRunGate}.tsx | first-run overlay gate (aiguru.onboarded flag + provider status) |
| app/(utility)/settings/network | ports/CORS/LAN toggle(lan_access_enabled) |

Deleted dead code (do not resurrect): services/monitoring/mock_feed.py,
web/components/monitoring/* (superseded by visionPipeline).

## 7. Config surface

- `data/user/settings/system.json`: backend_port/frontend_port, cors, next_public_api_base(_external),
  sandbox_allow_subprocess, chat_attachment budgets, **lan_access_enabled**.
- DB settings table keys (kv-text shape): jwt_secret, revoked_{jti}, parent_pin_{pid},
  telegram_{pid}, supervision_rules_{pid}, tunnel_provider.
- Env: DEEPTUTOR_API_BASE_URL (proxy target), DEEPTUTOR_HOST override, AUTH_ENABLED.
- Model catalog: services/model_catalog.json drives LLM/embedding/search presets.

## 8. Testing map

| Suite | Covers |
|---|---|
| tests/e2e (tiers1-4, conftest mocks: MockCVPipeline/MockTutorProvider/MockParentRemoteGateway/AIGuruTestDB with FK auto-provision execute()) | requirement scenarios incl. adversarial |
| tests/test_study_monitoring*.py, test_cv_adversarial.py | FSM thresholds, whitelists, spoof cases |
| tests/services/test_remote_security.py | vault v2 roundtrip/wrong-PIN, PIN lifecycle/lockout, JWT refresh/revoke, require_parent HTTP gate, pairing |
| tests/test_fresh_install_smoke.py | full chain on brand-new DB (migrations→sessions→events→report→xp/badges→PIN/JWT) |
| web: npm run test:node (396) + tsc --noEmit + eslint | frontend logic/type contracts |
