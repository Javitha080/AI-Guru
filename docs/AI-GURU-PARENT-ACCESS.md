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

Open **AI Guru → Parent Portal**. The built-in wizard walks you through:

1. **Create your passcode (PIN)** — 4–8 digits. This locks the portal.
   - Changing it later always requires the *current* PIN.
   - 5 wrong attempts = 5-minute lockout.
2. **Connect your Telegram bot** (2 minutes)
   - In Telegram, message **@BotFather** → `/newbot` → follow prompts → copy the **bot token**.
   - Message **@userinfobot** → it replies with your **chat id**.
   - Paste both into wizard step 2 → press **Send Test** → check Telegram.
3. **Choose remote access**
   - **Cloudflare (recommended)**: install `cloudflared`, click Start. No account needed.
   - **Ngrok**: install `ngrok`, paste your auth token, click Start.
   - The portal shows an honest status: `active` (public URL), `local_only`
     (no binary installed — still works on this PC / LAN), or `reconnecting`.
4. **Supervision rules** — student name, daily target minutes, alert strictness.

Finally press **Send Portal Link** in Settings to push
`https://<your-tunnel>/parent` to your Telegram for one-tap access.

> Pairing codes (`GURU-######`) exist for multi-child households:
> Overview → Pairing → Generate, then verify from the second profile.

---

## Daily use

- **Student side**: study as usual in Study Room. A Vision Guard panel shows
  presence/posture live; warnings appear as gentle nudges.
- **Parent side**: open the portal (PIN). You'll see today's status,
  analytics, incidents, and can open the Vault after entering your PIN —
  which also seals any pending encrypted captures.

## How notifications work

Warnings (phone detected, looking away, absence, identity mismatch…) pass
three gates before ever reaching you: confidence ≥ 80%, 60-second cooldown
per type, max 5 per 10 minutes. They are stored locally **and** queued for
Telegram — if internet drops, delivery retries automatically when it returns.

## Security notes

- Every parent API route requires a server-side passcode token; the
  student's own login cannot read or change parent settings.
- Vault files use AES-256-GCM with a key derived from your PIN
  (600k iterations); wrong-PIN attempts are rejected before decryption.
- All security events (PIN changes, tunnel starts, vault opens, pairing)
  are written to a local audit log visible in the portal.
- Live camera streams are opt-in, session-scoped, and never recorded raw.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Tunnel shows `local_only` | Install `cloudflared` or `ngrok`, ensure it's on PATH, Start again |
| No Telegram messages | Re-run **Send Test**; check token/chat-id; internet required |
| Locked out of portal | Wait 5 minutes, then retry PIN |
| "Wrong passcode" in Vault | Vault items are PIN-sealed — enter the current parent PIN |

*Developer details: backend router `deeptutor/api/routers/parent.py`,
services under `deeptutor/services/remote/`, monitoring glue in
`deeptutor/services/monitoring/dispatch.py`.*
