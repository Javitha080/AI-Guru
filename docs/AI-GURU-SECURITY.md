# AI GURU — Security Model

Audience: developers + reviewers. Non-technical parent setup lives in
`AI-GURU-PARENT-ACCESS.md`.

## Threat model & guarantees

| Asset | Where it lives | Protection |
|---|---|---|
| Study sessions / events / reports / rewards / exams | `data/user/chat_history.db` (SQLite) | Local-only; FK constraints ON; never exposed over network — only via API routes |
| Camera frames | RAM only (vision pipeline → WS → in-memory ring) | **Zero cloud egress**: frames are processed on-device; raw frames are never written to disk or uploaded |
| Incident evidence | `video_vault/pending/` → sealed `.vault` blobs | Staging dir is private to the OS user; sealed files use AES-256-GCM envelope: random 32-byte content key wrapped by PBKDF2-HMAC-SHA256(parent PIN, salt, 600k) KEK; HMAC verifier detects wrong PIN pre-decrypt; legacy v1 read-only |
| Parent passcode | settings table (`parent_pin_*`) | PBKDF2-HMAC-SHA256 100k + per-id lockout (5 fails → 5 min), constant-time compare |
| Parent sessions | JWT HS256 (secret in settings) | access 15 min / refresh 7 days, jti revocation list, device field; refresh rotation endpoint |
| Telegram credentials | settings table | masked on read; test-send before save recommended |
| Tunnel | cloudflared/ngrok outbound | No inbound ports opened; honest statuses (`local_only` never pretends active); watchdog restarts ×3 with backoff |

## Access-control layers

1. **App auth** (optional): JWT cookie/bearer via `require_auth`; roles admin/user;
   bootstrap-only registration. WS endpoints use `ws_require_auth(ws)` **before accept**.
2. **Parent gate** (separate from app auth): every `/api/v1/parent/*` route requires
   `require_parent` (role=parent, type=access JWT issued by verify-pin). Exemptions:
   bootstrap trio (`has-pin`, `set-pin`, `verify-pin`) + `/auth/refresh`.
   A logged-in *student* cannot touch parent routes.
3. **Pairing permissions** (`parent_student_links.permissions_json`):
   `can_view_live` gates live snapshots; `can_view_reports` reserved for report scope.
4. **Exam integrity**: reference answers/explanations hidden until exam status = graded.

## Monitoring safety rails
Warning spam control: confidence ≥0.80 · 60 s cooldown per category · max 5 per 10 min
(strictness presets map to 30/60/90 s and .75/.80/.85).
Presence FSM hysteresis (5 s/20 s) prevents single-frame absence claims.

## Notification outbox
SQLite-backed queue with atomic claim (pending→sending→sent/dead), stale-claim recovery,
exponential backoff 30·2ⁿ capped at 600 s, drop after 8 retries. Offline-safe.

## Audit trail
`AuditLogger.log_event` records: PIN set/change/verify(+lockout), telegram config changes,
tunnel start/stop/restart, vault seal/list/decrypt(+denials), pairing generate/verify/revoke,
live snapshot access, logout. Surfaced via `/parent/audit-log`.

## Secrets hygiene
- Never commit keys/tokens (`.env.example` documents shape only).
- Provider API keys stored locally via key vault (`services/config/key_vault.py`); UI shows masks.
- Tunnel authtokens accepted per-request; persisted values stay in local settings only.

## Known limitations (honest)
- Vault strength = PIN entropy; a weak PIN is brute-forceable offline by anyone with
  filesystem access. Use ≥6 digits.
- `pending/` holds unsealed JPEGs until a parent unlocks once (seal-on-unlock mitigates).
- LAN mode binds 0.0.0.0 — enable only on trusted home networks (passcode still guards parent pages).
- Live view is consent-gated but transport security depends on tunnel TLS (cloudflared/ngrok provide HTTPS).
