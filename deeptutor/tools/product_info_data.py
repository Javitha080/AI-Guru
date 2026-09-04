"""AI Guru local product knowledge.

Single source of truth for answering user questions about the AI Guru
application itself — its pages, features, tools, and troubleshooting.
The ``aiguru_info`` chat tool serves this data so the model never needs a
web search (which cannot know this fork) and never invents capabilities.

Grounded strictly in the real codebase surfaces (deeptutor/api/routers,
deeptutor/services, web/app). Keep every claim verifiable against code.
"""

from __future__ import annotations

PRODUCT_NAME = "AI Guru"

PRODUCT_OVERVIEW = """\
AI Guru is a local-first AI tutoring platform for students, with an on-device
study monitor and a passcode-protected Parent Portal. It runs entirely on your
machine: the backend (FastAPI, port 8001) and the web UI (Next.js, port 3782).
Study video frames are processed in your browser (MediaPipe on-device); raw
camera frames NEVER go to any cloud provider — only lightweight landmark
geometry numbers reach the local backend ("zero cloud egress" for biometrics).

Main areas:
• Chat tutor — agentic assistant with tools (web_search, paper_search,
  code_execution sandbox, knowledge-base RAG, notebook read/write, memory,
  skills, GeoGebra figure analysis, image/video generation) and a floating
  assistant bubble available anywhere (Alt+Space).
• Study Room — timed study sessions with live on-device vision monitoring:
  presence detection, posture/gaze, distraction & phone detection,
  drowsiness/liveness, focus & engagement scores, gentle warnings.
• Parent Portal (/parent) — PIN-gated dashboard for parents: live status,
  weekly analytics, incident timeline, encrypted evidence vault, Telegram
  alerts, remote-access tunnel, supervision rules, student pairing, audit log.
• Exam Room (/exam) — upload past papers, extract questions verbatim
  (MCQ/structured/essay), sit them under exam conditions, get graded results.
• Knowledge Bases (/knowledge) — attach your own documents; multiple RAG
  pipelines (LlamaIndex default, PageIndex, GraphRAG, LightRAG, LightRAG
  server, IMA) with per-engine preflight checks.
• Memory (/memory) — a three-layer memory workbench (L1 trace → L2 surface
  digests → L3 profile/preferences) with update / audit / dedup runs.
• Space (/space) — unified source picker that lets a chat turn consult your
  notebooks, books, past sessions, question-bank entries and attachments.
• Book (/book), Co-writer, Partners, Achievements, Notebook — study content
  creation and tracking surfaces.
• Settings — AI providers/models, tools toggles, MCP servers, appearance,
  language, document parsing, and more.
"""

# topic key -> (title, body). Matching is case-insensitive substring over keys
# AND title words, so "vault", "video vault", "encryption" all hit the vault
# section while "telegram alerts" hits the telegram section.
_TOPIC_SECTIONS: dict[str, str] = {
    "chat": """\
**Chat tutor**
The home page hosts the main tutoring chat. It runs an agent loop that can
call tools autonomously: web_search, paper_search (arXiv), reason,
brainstorm, code_execution (sandboxed Python/C/C++), rag + kb_files (your
attached knowledge bases), read_source (consult attached Space sources),
list_notebook/write_note (save chat transcripts or notes into notebooks),
read_memory/write_memory (persistent preferences), read_skill, github,
web_fetch, ask_user (clarifying-question cards), load_tools (deferred MCP),
cron (scheduled tasks), geogebra_analysis, imagegen/videogen.
A Floating Guru bubble can be opened from any page (drag it, PiP mode,
select text then use the selection chip, Alt+Space shortcut).""",
    "monitor": """\
**Study monitoring (Study Room)**
Start a session in /study-room: pick subject + duration, run the pre-flight
check (camera + liveness + face enrollment), then study while the monitor
runs fully on-device at ~5 FPS. It detects: presence/absence (5s grace /
20s away state machine), looking away, phone usage, identity mismatch vs
the enrolled face, drowsiness (EAR + texture liveness). Distraction
whitelists avoid false positives for reading/writing poses, drinking,
page turns. Focus & engagement scores stream live; warnings are throttled
(confidence ≥ 0.80, per-category cooldown, max 5 per 10 min, one warning
per continuous episode) with friendly on-screen nudges. Parents see the
same incidents in the portal; students control "Parent Live View" consent.""",
    "parent": """\
**Parent Portal (/parent)**
Protected by a 4–8 digit Parent Passcode (PBKDF2, lockout after repeated
misses, 15-min access tokens + rotating refresh tokens). Tabs:
Overview — live student cards (studying/offline, today minutes, streak,
level/XP, last focus score), Remote Access Gateway tile, incident timeline.
Analytics — weekly study bars, focus trend, session list, report drawer.
Vault — encrypted incident captures (see vault section).
Settings — Telegram bot setup + test alert, change PIN, supervision rules
(student name, daily goal, gentle/balanced/strict strictness), student
pairing codes, security audit log.
Setup wizard runs on first visit (PIN → Telegram → tunnel → rules).""",
    "tunnel": """\
**Remote access tunnel**
Lets a parent open the portal from outside home Wi-Fi without opening router
ports. Start Tunnel (Overview tile or wizard) launches Cloudflare Quick
Tunnel (recommended; free, no account). If cloudflared isn't installed the
app downloads it once (~18 MB, official Cloudflare release) automatically;
ngrok is supported too (needs its own account token). The tile shows honest
status: STARTING / ACTIVE with the https://…trycloudflare.com/parent link,
LOCAL_ONLY when no tunnel is running, ERROR with the reason if start fails.
A watchdog auto-restarts a dropped tunnel (up to 3 attempts).""",
    "telegram": """\
**Telegram alerts**
Configure a BotFather bot token + your chat id in Portal → Settings, then
'Save & Send Test Alert'. The app queues notifications in a durable outbox
(survives internet drops; retries with backoff, expires hour-old backlog so
stale alerts never replay as live). You receive: session started, warning
alerts (phone/away/looking away/identity/drowsy) with confidence, and an
end-of-session report card (duration, focus %, engagement, warnings, XP,
AI summary). When the tunnel is active every message carries a one-tap
'Open Parent Portal' link.""",
    "vault": """\
**Encrypted Video Vault**
When monitoring issues a warning, the trailing seconds of camera frames are
staged locally in pending/. They stay RAW until you open Portal → Vault and
'Seal Now' with your Parent Passcode: each item is sealed with AES-256-GCM
envelope encryption (per-file random content key wrapped by a PBKDF2-600k
key derived from your PIN; format GURUVAULT02). Wrong PIN is rejected via an
HMAC verifier without touching ciphertext. Sealed tiles list event type and
time; 'Decrypt & View' asks for the PIN and shows the snapshot or frame strip.
Students cannot read sealed files; nothing ever leaves the machine.""",
    "exam": """\
**Exam Room (/exam)**
Upload a past paper (PDF/image). The extractor reproduces its questions
verbatim — MCQ options kept exactly as printed, marks preserved — then you
sit the paper under exam conditions. MCQs are auto-graded server-side with
quiz semantics; structured answers are checked against reference answers
(hidden until submitted); essays are judged by the AI with a rubric and
score. Results land in history; XP may be awarded for completed attempts.""",
    "gamification": """\
**Gamification / Achievements**
Sessions award XP based on duration and focus (persisted in a rewards
table — the completion screen shows the actually-stored value). Streaks
count consecutive studying days. Badges unlock via milestones. The
Achievements page shows profile level, badges earned/locked and reward
history — all read from real data, never demo numbers.""",
    "memory": """\
**Memory workbench (/memory)** — note this is the memory DOCS workbench,
distinct from chat's read_memory/write_memory preference tools.
Three layers: L1 trace (raw events per surface: chat, question, research,
solve, book, co-writer…), L2 digest docs per surface, L3 cross-surface
profile (recent / profile / scope / preferences). Runs: update, audit,
dedup — long-running jobs keep running server-side; reattach by polling
run events; undo restores the previous doc version. Requires a working
LLM provider (runs summarize text); if the provider quota is exhausted
runs fail honestly instead of hanging.""",
    "knowledge": """\
**Knowledge bases & RAG (/knowledge)**
Upload documents (PDF, DOCX, PPTX, MD, TXT, images…) into named KBs, then
attach a KB to any chat turn; the rag tool retrieves passages (hybrid BM25 +
vector where available) and kb_files lists what a KB holds. Pipelines:
LlamaIndex (default), PageIndex (API-key service), GraphRAG, LightRAG,
LightRAG server, IMA. Each engine page runs a preflight check showing what
is installed/configured. Model options for LLM + embedding come from the
model catalog; embedding dim must match what the KB was built with.""",
    "space": """\
**Space sources (/space)**
Before sending a chat message you can attach Sources: notebook records,
book references, past chat/history sessions, question-bank entries, or raw
document attachments. The turn receives a manifest of these; the model can
read_source any id to pull full text before answering — answers cite which
source they used. This is how 'explain from my notes' works.""",
    "settings": """\
**Settings**
/settings covers: AI provider & model catalog (Gemini/OpenAI/OpenRouter/
Ollama/Codex…; test button; reasoning-effort overrides), tools toggles
(experience-enhancement tools like web_search/paper_search/reason),
MCP servers (add/edit/enable, per-server tools), appearance & themes,
language (interface vs response language), document parsing options,
and system info. Parent-specific settings live inside the portal instead.""",
    "troubleshoot": """\
**Troubleshooting**
• 'you exceeded your current quota' — your Gemini/API plan ran out; billing
  issue, not an app bug. The app now fails fast instead of retrying ~9 times;
  switch provider in Settings → AI or top up the plan.
• Gemini 'thought_signature' 400 during tool calls — fixed: tool-call
  signatures are preserved across agent rounds.
• Camera/pre-flight fails — allow browser camera permission; MediaPipe
  assets load from web/public/mediapipe with CDN fallback.
• Tunnel stuck LOCAL_ONLY — press Start Tunnel again; first run downloads
  cloudflared (~18 MB). Check the gateway tile for the exact error message.
• Knowledge pipeline preflight 500 for an engine — fixed by the generic
  fallback report; restart the backend if you still see it.""",
}

_SECTION_ALIASES = {
    "monitor": (
        "monitor",
        "study room",
        "vision",
        "camera",
        "focus",
        "distraction",
        "warning",
        "liveness",
        "presence",
    ),
    "chat": ("chat", "assistant", "floating", "tools", "agent"),
    "parent": ("parent", "portal", "pin", "passcode", "dashboard"),
    "tunnel": ("tunnel", "remote", "cloudflare", "ngrok", "gateway"),
    "telegram": ("telegram", "bot", "notification", "alert", "outbox"),
    "vault": ("vault", "encrypt", "snapshot", "clip", "seal"),
    "exam": ("exam", "paper", "mcq", "grade"),
    "gamification": ("xp", "badge", "streak", "achievement", "gamification", "level"),
    "memory": ("memory", "workbench", "digest", "preference"),
    "knowledge": (
        "knowledge",
        "rag",
        "retrieval",
        "embedding",
        "graphrag",
        "lightrag",
        "pageindex",
        "llamaindex",
        "ima",
    ),
    "space": ("space", "source", "attachment", "notebook record"),
    "settings": ("setting", "provider", "model", "mcp", "theme", "language"),
    "troubleshoot": (
        "error",
        "fail",
        "quota",
        "429",
        "problem",
        "broken",
        "not working",
        "fix",
        "troubleshoot",
    ),
}


def search_product_info(topic: str | None = None) -> str:
    """Return the sections relevant to ``topic``, else the full guide.

    Empty/None topic returns the overview plus the section index. Unknown
    topics return the overview with a hint — never an error.
    """
    header = f"# {PRODUCT_NAME} — Product Guide\n\n"
    query = (topic or "").strip().lower()
    if not query:
        index = "\n".join(
            f"- {title.splitlines()[0].strip('* ')}" for title in _TOPIC_SECTIONS.values()
        )
        return header + PRODUCT_OVERVIEW + "\n## Detail sections (ask about any of these)\n" + index

    scored: list[tuple[int, str]] = []
    for key, body in _TOPIC_SECTIONS.items():
        aliases = _SECTION_ALIASES.get(key, (key,))
        score = sum(1 for alias in aliases if alias in query)
        # A direct key hit outweighs several fuzzy alias matches.
        if key in query:
            score += 3
        if score:
            scored.append((score, body))
    if not scored:
        return (
            header
            + PRODUCT_OVERVIEW
            + f"\n(no dedicated section matched {topic!r} — answer from the "
            "overview above; suggest the closest area)"
        )
    scored.sort(key=lambda pair: -pair[0])
    top = scored[0][1]
    extra = [body for score, body in scored[1:] if score >= max(2, scored[0][0] - 1)]
    return header + "\n\n".join([top, *extra])


__all__ = ["PRODUCT_NAME", "PRODUCT_OVERVIEW", "search_product_info"]
