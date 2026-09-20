# AI GURU — Run & Deploy Guide

## Fresh clone notes

- `ictfromabc/` is large on disk (~330 MB: source PDFs + OCR artifacts). The app only
  needs `Sri_Lanka_ICT_Complete_AL_OL_Lessons_and_Quizzes_Master_Archive` (~9 MB),
  which seeds the paper bank automatically on first boot — no manual import.
  Impatient cloners: `git clone --depth 1 <url>`.
- `data/` (SQLite DB, paper-bank assets) is gitignored and rebuilt locally:
  first visit to `/papers` shows "Preparing paper bank…" for ~1 min while 123 papers
  import in the background, then the catalog appears with zero commands.

## Exam integrity note (by design)

- `/papers` Study mode fetches marking schemes via `?include_answers=true`, and the
  paper-bank API (catalog, sittings, re-import) shares the app's global auth
  (`require_auth`, a no-op when `AUTH_ENABLED=false`). On a single-user device this
  is the accepted local-first tradeoff — but anyone with HTTP access can pull keys
  mid-sitting. For supervised exams: set `AUTH_ENABLED=true` and keep LAN access
  (`lan_access_enabled`) off.

## Quick start (Windows, this repo)

```powershell
cd D:\DeepTutor-1.5.11\DeepTutor-1.5.11

# One command — backend(8001) + frontend(3782) + health checks + opens UI
.venv\Scripts\python.exe -m deeptutor_cli.main start
```

Manual alternative (two terminals):

```powershell
# Terminal 1 — backend
.venv\Scripts\python.exe -m uvicorn deeptutor.api.main:app --host 127.0.0.1 --port 8001

# Terminal 2 — frontend (first compile 30-60s)
cd web ; npm run dev
```

Production frontend (faster pages): `cd web ; npm run build ; npm run start`

Docker: `docker compose up` (rootless-hardened variant in compose.yaml).

## URLs

| What | URL |
|---|---|
| Student app | http://localhost:3782 |
| Study Room | http://localhost:3782/study-room |
| Exam Room | http://localhost:3782/exam |
| Parent Portal | http://localhost:3782/parent |
| Achievements | http://localhost:3782/achievements |
| API docs | http://127.0.0.1:8001/docs |
| Health | http://127.0.0.1:8001/api/v1/health |

## First-run walkthrough

1. **Onboarding wizard** auto-appears until an LLM is configured:
   Cloud API (paste key) · Ollama · Offline rule engine. Dismissal persists (`aiguru.onboarded`).
2. **Study Room**: allow camera → real liveness check → Vision Guard goes `LIVE · ON-DEVICE`.
   Optional "Parent Live View" toggle per session.
3. **Exam Room**: drop a past-paper PDF → questions extracted verbatim → timed exam
   (MCQ first, essays after) → submit → AI grading + reference answers unlocked.
4. **Parent Portal wizard**: PIN (4–8) → Telegram bot (@BotFather token + @userinfobot chat id, test send)
   → tunnel choice (cloudflared recommended / ngrok + authtoken) → supervision rules.
   Afterwards the portal is PIN-locked; unlock also seals pending vault captures.

## Networking

- Default binds loopback only. LAN/Wi-Fi access: **Settings → Network →
  Allow devices on my network** (`lan_access_enabled`) → restart.
- Remote (any network): install [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
  or [ngrok](https://ngrok.com/download), then Parent Portal → Start Tunnel.
  Outbound-only; no router changes. Honest status incl. `local_only` when no binary on PATH.

## Data & logs

| Path | Contents |
|---|---|
| `data/user/settings/*.json` | runtime settings (ports/CORS/LAN/parsing…) |
| `data/user/chat_history.db` | SQLite: sessions, events, reports, rewards, exams, settings(kv), audit_logs |
| `data/user/video_vault/` | pending/ staging + sealed `.vault` incident captures (AES-256-GCM) |
| `data/user/workspace/exams/` | uploaded papers + extraction artifacts |

## Troubleshooting

| Symptom | Fix |
|---|---|
| Port busy (8001/3782) | kill listener or edit system.json ports |
| Frontend slow first load | dev cold compile — wait or use production build |
| Camera checks fail | browser permission + adequate lighting; face centered; model loads from /mediapipe (CDN fallback online) |
| Tunnel shows local_only | cloudflared/ngrok not on PATH — install & retry |
| Telegram silent | wrong token/chat-id, or offline (queue retries with backoff) |
| Locked out of portal | wait 5 minutes (PIN lockout) |

## Stopping

Launcher: Ctrl+C. Manual: close the two terminals, or
`Get-NetTCPConnection -LocalPort 8001,3782 | … Stop-Process -Force`.
