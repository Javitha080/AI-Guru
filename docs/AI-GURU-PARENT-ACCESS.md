# AI Guru — Parent Access & Supervision Guide

A complete, non-technical walkthrough of the AI Guru parent-supervision
system: what it is, how to set it up in under 10 minutes, and how it keeps
your child's data private.

---

## What the parent system does

| Capability | Where |
|---|---|
| **Passcode-protected portal** (`Ask Pass` gate) | `/parent` |
| **Telegram alerts** — session start, distraction warnings, end-of-session report card | Telegram bot you create once |
| **Remote access from any network** — outbound encrypted tunnel (Cloudflare or Ngrok) | `/parent` → Tunnel card |
| **Local-network access** — same-WiFi viewing without a tunnel | Advanced (LAN mode) |
| **Encrypted incident vault** — distraction snapshots/clips only a parent PIN can open | `/parent` → Vault tab |
| **Study analytics** — weekly time, focus trend, session history, reports | `/parent` → Analytics/Reports |

Privacy model: **camera frames are processed on your child's computer and
never uploaded**. Only short text alerts travel via Telegram; the tunnel
exposes the app UI — protected by your passcode — not raw video.

---

## One-time setup (~10 minutes)

Open **AI Guru → Parent Portal**. The portal is a dedicated full-screen page
(no student sidebar or assistant) with a built-in wizard that handles both
first-time setup and later changes:

1. **Create your passcode (PIN)** — 4–8 digits, numbers only. This locks the portal.
   - Trivially guessable codes are rejected (repeated digits, sequential runs
     like `1234`/`4321`, common PINs like `2580`).
   - Changing an existing PIN always requires the *current* PIN — in the wizard
     or in Settings → Change Parent Passcode.
   - 5 wrong attempts = 5-minute lockout.
2. **Connect your Telegram bot** (2 minutes, optional — skippable)
   - In Telegram, message **@BotFather** → `/newbot` → follow prompts → copy the **bot token**.
   - Message **@userinfobot** → it replies with your **chat id**.
   - Paste both into wizard step 2 → press **Save & Send Test Alert** → check Telegram.
3. **Choose remote access**
   - **Cloudflare (recommended)**: install `cloudflared`, click Start. No account needed.
   - **Ngrok**: install `ngrok`, paste your auth token, click Start.
   - The tunnel automatically targets the app's UI port, so the public link
     `https://<your-tunnel>/parent` opens the real portal (API calls ride along
     through the built-in proxy) — no port juggling.
   - Honest status: `active` (public URL), `local_only`
     (no binary installed — still works on this PC / LAN), or `reconnecting`.
4. **Supervision rules** — student name, daily target minutes, alert strictness.

Finally press **Link via Telegram** (Overview banner) or use Settings to push
the portal link to your Telegram for one-tap access. When the tunnel is not
active the message contains your honest LAN address instead
(`http://<your-pc-ip>:<frontend-port>/parent`).

> **Pairing codes** (`GURU-######`) for multi-child households live in
> **Settings → Student Pairing**: Generate, enter the code on the student
> device, then Verify/Revoke from the same card.

---

## Daily use

- **Student side**: study as usual in Study Room. A Vision Guard panel shows
  presence/posture live; warnings appear as gentle nudges. The **Parent Live
  View** toggle lets the parent see consented snapshots during the session.
- **Parent side**: open `/parent` and unlock with your PIN. Closing the tab
  locks the portal again; if a session expires mid-use it re-locks itself
  automatically. Overview shows live status + real metrics (today's time,
  streak, XP/level, last measured focus), the warning timeline for the
  selected student, and the tunnel banner. Use **Vault → Seal Now** to encrypt
  staged captures with your PIN, and **Analytics → Recent Sessions → Report**
  to read a finished session's report.

## How notifications work

Warnings (phone detected, looking away, absence, identity mismatch…) pass
three gates before ever reaching you: confidence ≥ 80%, 60-second cooldown
per type, max 5 per 10 minutes. They are stored locally **and** queued for
Telegram — if internet drops, delivery retries automatically when it returns.

## Security notes

- Every parent API route requires a server-side passcode token; the
  student's own login cannot read or change parent settings.
- Access tokens last 15 minutes; refresh tokens **rotate** on every renewal
  (a replayed old refresh token is rejected) and locking the portal revokes
  both.
- Vault files use AES-256-GCM with a key derived from your PIN
  (600k iterations); wrong-PIN attempts are rejected before decryption.
- All security events (PIN changes, wrong attempts, lockouts, tunnel starts,
  vault seals/opens, pairing) are written to a local audit log — see
  **Settings → Security Activity Log** in the portal.
- Live camera streams are opt-in, session-scoped, and never recorded raw.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Tunnel shows `local_only` | Install `cloudflared` or `ngrok`, ensure it's on PATH, Start again |
| No Telegram messages | Re-run **Save & Send Test Alert**; check token/chat-id; internet required |
| Locked out of portal | Wait 5 minutes, then retry PIN |
| "Wrong passcode" in Vault | Vault items are PIN-sealed — enter the current parent PIN |
| Portal unreachable remotely | Confirm tunnel status is `active`; the public link must start with `https://` |
| Analytics shows zeros / — | Real data appears after monitored study sessions complete on the student PC |

*Developer details: backend router `deeptutor/api/routers/parent.py`,
services under `deeptutor/services/remote/`, monitoring glue in
`deeptutor/services/monitoring/dispatch.py`.*
