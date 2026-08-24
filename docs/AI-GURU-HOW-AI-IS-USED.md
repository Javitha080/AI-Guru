# How AI Is Used in AI Guru

> Technical document — explains every place artificial intelligence is used in AI Guru,
> which models/techniques power it, where inference runs, and what data (if any) leaves
> the device. Companion to `AI-GURU-AI-MODELS.md` (provider setup) and `SYSTEM_DESIGN.md`.

---

## 1. Executive Summary

AI Guru applies AI in **three distinct ways**, each chosen deliberately:

1. **Language-model tutoring (generative AI).** Large language models (LLMs) act as the
   tutor: answering questions grounded in the student's own documents, generating practice
   questions, running guided research, writing and executing visualization code, animating
   math concepts, grading essay answers, and writing post-session study reports.
2. **On-device computer vision (perception AI).** A browser-side face landmark model
   observes the study session to estimate presence, attention, engagement, and distractions.
   This runs **entirely on the student's machine** — video frames never leave it.
3. **Retrieval-augmented generation (RAG).** The student's uploaded PDFs and notes are
   parsed, embedded, and indexed so the tutor answers from *their* material instead of
   guessing.

The governing design rule is **privacy-first, local-first**: LLM inference can run fully
offline through a local Ollama model, all computer-vision processing happens in the
browser, and cloud providers are opt-in. Where a decision affects the student (a warning,
a grade, an XP award), the system prefers **deterministic, auditable logic** over opaque
model output — AI drafts, rules decide.

---

## 2. AI at a Glance

| # | Feature | AI technique | Inference runs on | Data leaving device |
|---|---------|--------------|-------------------|---------------------|
| 1 | Chat tutor (`agents/chat`) | Tool-using LLM agent loop | Cloud API *or* local Ollama | Prompt text only if cloud mode |
| 2 | Document Q&A / RAG (`services/rag`) | Parsing + embedding + vector retrieval | Local or cloud embedding models | Text chunks if cloud embedder |
| 3 | Practice question generation (`agents/question`) | LLM generation + LLM answer judging | Same tri-mode as chat | Question context if cloud mode |
| 4 | Research agent (`agents/research`) | Multi-step LLM search-and-synthesize pipeline | Same tri-mode | Search queries if cloud mode |
| 5 | Visualization agent (`agents/visualize`) | LLM code generation → sandboxed execution | Same tri-mode + local sandbox | None beyond prompt |
| 6 | Math animator (`agents/math_animator`) | LLM-generated animation code with visual review loop | Same tri-mode | None beyond prompt |
| 7 | Notebook analysis (`agents/notebook`) | LLM summarize/analyze of notes | Same tri-mode | Note text if cloud mode |
| 8 | Exam Room (`services/exams`) | PDF extraction, batch answer-key solving, LLM essay grading | Same tri-mode | Exam text if cloud mode |
| 9 | Study monitoring CV (`web/lib/monitoring/visionPipeline.ts`, `services/monitoring/`) | Face landmarks, liveness, pose/gaze, FSM scoring | **Browser only** (MediaPipe WASM) | **Nothing — frames never leave the machine** |
| 10 | Session reports (`services/study/report_generator.py`) | Real metric aggregation + one bounded LLM summary call | Same tri-mode | Anonymized session stats |

---

## 3. The LLM Provider Layer — Tri-Mode, Privacy-Switchable

All text AI funnels through one abstraction so the same feature can run in the cloud or
fully offline.

**Interface.** `services/llm/tutor_provider.py` defines `TutorProvider(ABC)` with
`stream()`, `complete()`, `check_health()` and a hardware tier. Every consumer calls the
unified entrypoints `services/llm/factory.py` → `complete()` / `stream()`.

**Three modes:**

| Mode | Backend | When used |
|------|---------|-----------|
| Cloud API | OpenAI / Anthropic / Groq / others via provider registry | User opts in with a locally-stored API key |
| Local Ollama | `http://127.0.0.1:11434`, quantized open models (Phi-3 Mini, Llama-3 8B, Mixtral by hardware tier) | Default for privacy/offline; zero data egress |
| Offline rule engine | Non-LLM fallbacks | No network, no local model available |

**Auto-fallback chain.** If the primary provider times out or returns a malformed
response, the request transparently retries down the chain (cloud → local → offline), so
tutoring continues through network cuts.

**Supporting intelligence:**

- **Hardware profiler** (`services/llm/hardware_profiler.py`) classifies the machine
  LOW/MEDIUM/HIGH to pick a model size that fits RAM/GPU.
- **Resource governor** throttles background work and generation when CPU/RAM approach
  saturation.
- **Capability-aware calls**: the factory probes whether a provider supports vision input
  and structured `response_format` before using them, handles `<think>` reasoning tags,
  multimodal message preparation, retries with exponential backoff, and error mapping to
  user-friendly messages.

---

## 4. The Agentic Chat Tutor (Core)

The main chat is not a single prompt-response call — it is an **agent loop**
(`deeptutor/agents/chat/agent_loop.py`, `agentic_pipeline.py`):

1. The student's message plus retrieved document context enters the loop with a budgeted
   context window (`context_budget.py`).
2. The LLM may emit tool calls (DSML format, `dsml_tool_calls.py`) drawn from ~30
   built-in tools (`deeptutor/tools/builtin/`): searching the knowledge base, reading
   attachments, creating notebooks, plotting, and more.
3. Tools execute server-side; results feed back into the loop until the model produces a
   final answer, streamed token-by-token to the browser over WebSocket.

**Loop capabilities** (`deeptutor/capabilities/`) extend the loop with higher-order
skills: `solve` (step-by-step problem solving), `mastery` (knowledge tracking),
`explore_context` (document exploration), `subagent` (delegated sub-tasks), and
`obsidian` (knowledge-graph notes).

Prompts are versioned YAML under `agents/*/prompts/en/` so tutor behavior is auditable
and editable without code changes.

---

## 5. Retrieval-Augmented Generation (RAG) — Grounding in the Student's Material

So answers come from the student's actual textbooks rather than model memory:

1. **Parsing** — uploaded files go through `services/parsing` (mineru, docling,
   markitdown, pymupdf4llm backends, content-addressed cached).
2. **Embedding** — chunks are converted to vectors by `services/embedding`, with adapters
   for local Ollama embeddings or cloud providers (OpenAI-compatible, Cohere, Gemini,
   Jina, DashScope).
3. **Indexing & retrieval** — `services/rag` manages knowledge bases with index
   versioning and embedding-signature checks so stale indexes are rebuilt correctly;
   retrieved passages are injected into the chat agent's context.

This is why the tutor can cite and explain *the student's own pages* — the RAG layer is
what makes tutoring personal rather than generic.

---

## 6. Specialized Tutor Agents

Each pipeline is a dedicated multi-agent flow built on the same LLM layer:

- **Question agent** (`agents/question`) — generates deep practice questions and
  follow-ups from material, then judges free-text answers via a WebSocket quiz judge
  (`routers/quiz_judge.py`).
- **Research agent** (`agents/research`) — plans searches, gathers sources, and
  synthesizes a structured report.
- **Visualize agent** (`agents/visualize`) — turns a concept into executable chart/plot
  code, generated by the LLM, reviewed, then run in the local sandbox so students see real
  rendered output.
- **Math animator** (`agents/math_animator`) — a five-agent relay (concept analysis →
  concept design → code generation → visual review → summary) that produces step-by-step
  mathematical animations.
- **Notebook agents** (`agents/notebook`) — summarize and analyze saved notes.
- **Vision solver** (`agents/vision_solver`) — solves photo-based problems (multimodal
  image understanding routed through `services/llm/multimodal.py`).

---

## 7. Exam Room — Extraction, Answer Keys, Grading

`services/exams/` uses AI at exactly three points, keeping grading fair and explainable:

1. **Paper ingestion** — an uploaded past-paper PDF is parsed and an LLM extracts the
   questions *verbatim* into structured JSON; regex templating splits options
   (`A) ... B) ...`) into a playable paper stored in `exams` / `exam_answers`.
2. **Answer-key completion** — if the paper has no mark scheme, **one** batched LLM call
   solves the missing answers (failure is tolerated; the exam still runs).
3. **Grading split by determinism**:
   - MCQ, true/false, fill-in-the-blank → **deterministic string/key matching** (no model
     in the loop — grades are reproducible).
   - Essay/long-answer → LLM judge returning strict JSON `{verdict, score, feedback}`
     with a 120 s timeout; results hidden until status = `graded`.

Correct answers earn XP and badges through the gamification engine afterward.

---

## 8. On-Device Computer Vision — Study Monitoring

The most privacy-sensitive AI in the product, and the one kept **100% local**:

**Where it runs:** in the browser tab itself. `web/lib/monitoring/visionPipeline.ts`
loads Google **MediaPipe FaceLandmarker** (WebAssembly, GPU delegate with CPU fallback).
The webcam preview renders at 30 FPS, while inference is throttled to ~5 FPS. Each tick
produces 478 3D facial landmarks, eye/mouth subsets, brightness, and a compressed JPEG —
all in page memory.

**What the backend computes from those signals** (`services/monitoring/cv_pipeline`,
8-stage):

- **Identity verification** — facial geometry compared against the enrolled baseline
  (cosine similarity ≥ 0.65) so a sibling can't study for the student.
- **Anti-spoof liveness** — eye-aspect-ratio blink dynamics (EAR < 0.18 close / > 0.25
  open), frame-difference motion variance, and Laplacian texture analysis reject printed
  photos and screen replays.
- **Head pose & gaze** — yaw/pitch/roll angles classify looking-at-screen vs away, plus
  posture classes.
- **Presence state machine** — PRESENT → TEMPORARILY_NOT_VISIBLE (≥5 s) → AWAY (≥20 s)
  with hysteresis so brief glances don't fire alerts.
- **Distraction filter** — benign acts (reading, writing, drinking ≤6 s, turning a page
  ≤4 s) are whitelisted; phones (≥4 s), identity mismatch (≥15 s), drowsiness (≥4 s) are
  flagged.
- **Engagement score** — exponential moving average blending pose/gaze/posture
  (45/35/20 weights) into a continuous 0–100 gauge shown live in the Study Room.
- **Warning gates** — a distraction becomes a parent Telegram alert only above
  confidence ≥ 0.80, with 60 s cooldown and max 5 warnings per 10 min (profiles:
  gentle 90 s/0.85 · balanced 60 s/0.80 · strict 30 s/0.75).

**Privacy guarantee:** frames, landmarks, and embeddings stay on-device; nothing
biometric is persisted or transmitted. The optional parent live view requires the
student's explicit toggle, holds at most one ~1.5 s-throttled frame in RAM with a 60 s
TTL, and is purged when the socket closes.

---

## 9. AI Study Reports — Metrics First, Prose Second

At session end, `services/study/report_generator.py` builds the report in two steps:

1. **Deterministic aggregation** — focus %, engagement %, productive/distracted seconds
   and totals are computed by SQL/logic from real `monitoring_events` telemetry. These
   numbers are never invented; hardcoded demo metrics are explicitly banned project-wide,
   and frontend gaps render an honest `—`.
2. **Bounded LLM narrative** — one small `factory.complete()` call (6-second timeout,
   output capped at 600 characters) turns those real numbers into a short strengths /
   improvement recap (`ai_tutor_feedback`). If the LLM is unavailable, the report ships
   with metrics intact and no fabricated commentary.

---

## 10. Deliberately *Not* AI

For trust and auditability, several subsystems are intentionally rule-based:

- **XP, streaks, levels, badges** — pure arithmetic on sessions and events.
- **Warning issuance gates** — fixed confidence/cooldown thresholds, not a model opinion.
- **Parent security** — PIN hashing (PBKDF2), JWT lifecycle, tunnel gateway, AES-GCM
  incident vault, and audit logging are cryptographic/procedural, not learned.

AI proposes (flags a distraction, drafts feedback); deterministic code disposes (decides
the warning, computes the reward). This keeps every consequential action explainable to
a parent or auditor.

---

## 11. Model Choices

Local model sizing by hardware tier (details in `AI-GURU-AI-MODELS.md`):

| Tier | Typical machine | Local model |
|------|-----------------|-------------|
| LOW | CPU-only, <16 GB RAM | Phi-3 Mini (4-bit) |
| MEDIUM | Entry GPU / Apple M-series, 16 GB+ | Llama-3 8B |
| HIGH | High-end GPU, 32 GB+ | Mistral / Mixtral |

Cloud mode supports OpenAI-, Anthropic-, and Groq-compatible APIs; API keys are stored
only in local settings and delivered masked to the UI. Embeddings mirror the same
local/cloud choice via adapter selection.

---

## 12. Responsible-AI Posture (Summary)

- **Data minimization** — CV never leaves the device; cloud LLM use is explicit opt-in.
- **Grounding over hallucination** — RAG ties answers to the student's documents.
- **Human-meaningful transparency** — supervision rules, thresholds, and prompts are
  documented and configurable; parents see raw event history, not just AI summaries.
- **Explainable consequences** — grades for objective question types and all rewards are
  computed deterministically.
- **Fail-safe defaults** — offline mode keeps monitoring and rewards working without any
  cloud dependency.
