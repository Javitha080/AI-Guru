# AI Guru — Comprehensive Architecture Audit & System Specification

> **Document Version**: 2.0.0  
> **Status**: Authoritative Architectural Baseline  
> **Classification**: Technical Architecture & System Audit  
> **Target Transformation**: DeepTutor 1.5.11 $\rightarrow$ **AI Guru** Local-First Privacy-Preserving Intelligent Tutoring & Study Monitoring Platform

---

## 1. Executive Summary & Brand Transformation

### 1.1 Mission & Product Vision
**AI Guru** is a next-generation, local-first, privacy-centric AI tutoring and intelligent study-monitoring platform designed for students, parents, and self-directed learners. Building upon the agent-native foundation of DeepTutor 1.5.11, AI Guru expands the ecosystem by coupling multi-stage cognitive reasoning capabilities with an edge-computed, privacy-preserving Computer Vision (CV) study monitoring engine, a dual-mode local/cloud AI provider abstraction, automated study session lifecycle management, gamification mechanics, and a zero-configuration secure outbound tunnel for remote parent visibility.

### 1.2 Transformation Philosophy: Evolution Without Regression
The transformation from DeepTutor to AI Guru adheres to four core architectural tenets:
1. **Preservation of Core Agent-Native Strengths**: All 7 multi-stage capabilities (`chat`, `deep_solve`, `deep_question`, `deep_research`, `visualize`, `math_animator`, `mastery_path`), all 43 registered tools, and all 33 existing API router endpoints are 100% retained and fully functional.
2. **Zero-Biometric-Egress & Local-First Mandate**: All computer vision inference (face detection, identity verification, anti-spoof liveness, gaze/pose estimation, distraction classification) runs entirely on the user's local machine. Raw camera frames, audio recordings, face crops, and biometric embedding vectors are never transmitted to external cloud services.
3. **Dual-Mode AI & Hardware Self-Adaptation**: The platform operates seamlessly across Cloud APIs (OpenAI, Claude, DashScope, DeepSeek, Gemini, Perplexity) and Local On-Device LLMs (Ollama with quantized Qwen-2.5, Llama-3.2, DeepSeek-R1), adapting runtime behavior based on active hardware profiling (`LOW`, `MEDIUM`, `HIGH`).
4. **Clean Brand Transformation Boundary**: All user-visible surfaces (HTML metadata, page titles, localized translation bundles, navigation docks, CLI banners, user documentation) are rebranded to **AI Guru**, while internal Python package namespaces (`deeptutor.*`) remain stable to prevent dependency breakage and packaging drift.

---

## 2. High-Level System Architecture

The following diagram illustrates the complete end-to-end architecture of AI Guru, showing the integration of existing agentic capabilities with new local-first subsystems:

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       STUDENT & PARENT CLIENT SURFACES                                 │
│                                                                                                        │
│   ┌──────────────────────────────────────────────────┐      ┌───────────────────────────────────────┐  │
│   │           Student Portal (Next.js 16)            │      │       Parent Portal / Remote App      │  │
│   │  - LiquidGlass UI / FloatingDock / Study Room    │      │  - Real-time Study Telemetry Cards    │  │
│   │  - Local Camera Video & MediaPipe WASM (30 FPS)  │      │  - Daily / Weekly / Monthly Trends    │  │
│   │  - AI Chat, Solve, Research & Math Animator UI   │      │  - Opt-in E2E Live Video Supervision  │  │
│   └────────────────────────┬─────────────────────────┘      └───────────────────┬───────────────────┘  │
└────────────────────────────┼────────────────────────────────────────────────────┼──────────────────────┘
                             │ Local HTTP / WS (127.0.0.1)                        │ Encrypted WSS / WebRTC
                             ▼                                                    ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   AI GURU LOCAL RUNTIME (FastAPI Backend)                              │
│                                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                                      API Gateway & Unified WS                                    │  │
│  │   /api/v1/chat  ·  /api/v1/ws  ·  /api/v1/monitoring  ·  /api/v1/parent  ·  /api/v1/health       │  │
│  └───────┬───────────────────────────────┬───────────────────────────────┬──────────────────────────┘  │
│          │                               │                               │                             │
│          ▼                               ▼                               ▼                             │
│  ┌─────────────────────────┐  ┌────────────────────────┐  ┌─────────────────────────────────────────┐  │
│  │   ChatOrchestrator      │  │  StudyMonitoringEngine │  │          TutorProvider Manager          │  │
│  │  - 7 Capabilities       │  │  - 5-10 FPS Analysis   │  │  - Mode A: External Cloud APIs          │  │
│  │  - 43 Built-in Tools    │  │  - Face & Liveness     │  │  - Mode B: Local Ollama LLMs            │  │
│  │  - StreamBus Fan-Out    │  │  - Presence & Posture  │  │  - Mode C: Offline Rule Engine          │  │
│  │  - Token Budget Manager │  │  - Distraction Filter  │  │  - Hardware Profiler & Governor         │  │
│  │  - 3-Layer Memory       │  │  - Warning Cooldown    │  │  - Local Encrypted Key Vault            │  │
│  └────────────┬────────────┘  └───────────┬────────────┘  └────────────────────┬────────────────────┘  │
│               │                           │                                    │                       │
│               └───────────────────────────┼────────────────────────────────────┘                       │
│                                           ▼                                                            │
│                         ┌───────────────────────────────────┐                                          │
│                         │   Session & Gamification Engine   │                                          │
│                         │   - Study Session Lifecycle       │                                          │
│                         │   - Real-Time Telemetry Logging   │                                          │
│                         │   - XP Points & Streak Tracker    │                                          │
│                         │   - Badge & Level Progression     │                                          │
│                         └─────────────────┬─────────────────┘                                          │
│                                           ▼                                                            │
│                         ┌───────────────────────────────────┐                                          │
│                         │  Local Relational Database Store  │                                          │
│                         │    (aiosqlite SQLite in WAL Mode) │                                          │
│                         │   - 11 Core Relational Tables     │                                          │
│                         │   - Schema Version Migrations     │                                          │
│                         │   - Lock-Free Concurrent Access   │                                          │
│                         └─────────────────┬─────────────────┘                                          │
│                                           │                                                            │
│  ┌────────────────────────────────────────┴─────────────────────────────────────────────────────────┐  │
│  │  Parent Remote Access Gateway (Outbound Encrypted Tunnel + JWT Auth + Short-Lived Tokens)          │  │
│  └────────────────────────────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Full Existing DeepTutor Codebase Audit

### 3.1 Backend Entry Points & CLI Subsystem
The backend entry points are cleanly separated into CLI, Server, and SDK layers:

1. **CLI Root (`deeptutor_cli/main.py`)**:
   - Built on `typer.Typer(name="deeptutor")` with rich formatting.
   - Commands: `start` (spawns supervised backend + frontend), `serve` (launches Uvicorn API server), `run` (single-turn capability invocation), `chat` (interactive REPL), `kb` (knowledge base management), `skill` / `skills` (agent skills management), `memory` (3-layer memory inspection), `plugin` (plugin management), `config` (system configuration), `session` (session branching), `notebook` (markdown notebook sync), `provider` (OAuth provider management), `book` (BookEngine textbook interactive reader).
   - Platform compatibility: Enforces `WindowsProactorEventLoopPolicy` on `win32` platforms to enable robust child process handling.

2. **Application Facade (`deeptutor/app.py`)**:
   - Exposes `DeepTutorApp`, encapsulating the `ChatOrchestrator`, runtime registry bootstrapping, and turn execution pipelines.

3. **API Gateway (`deeptutor/api/main.py`)**:
   - `lifespan(app: FastAPI)` lifecycle manager initializing config validation, LLM client connections, `EventBus`, `PartnerManager`, `CronService`, and connection pool teardown.
   - Dynamic CORS configuration with support for custom origins and localhost bindings.
   - Selective access logging middleware filtering noisy health polls while capturing non-200 responses.

### 3.2 Runtime Orchestration & Streaming Architecture
1. **`ChatOrchestrator` (`deeptutor/runtime/orchestrator.py`)**:
   - Receives `UnifiedContext` carrying user message, session history, mounted tools, attachments, and capability configurations.
   - Dispatches turns to the requested capability resolved via `CapabilityRegistry` (defaults to `chat`).
   - Allocates a dedicated `StreamBus` per turn, broadcasting granular stream events to async iterators.
   - Emits `EventType.CAPABILITY_COMPLETE` upon turn finalization with comprehensive token usage and cost metrics.

2. **Launcher Supervisor (`deeptutor/runtime/launcher.py`)**:
   - Supervised multi-process launcher orchestrating the FastAPI backend and Next.js frontend.
   - Intelligent port conflict detection and automatic fallback assignment (default backend: 8001, frontend: 3782/3000).
   - Production Next.js build detection serving pre-built `.next-deeptutor` bundles.
   - Cross-platform process termination (`taskkill /T /F` on Windows, `killpg` on Unix).

3. **Streaming Protocol (`deeptutor/core/stream.py`, `stream_bus.py`)**:
   - `StreamEvent` structured events: `CHUNK` (token text), `THINKING` (reasoning thought stream), `TOOL_CALL` (invoked tool + arguments), `TOOL_RESULT` (tool output), `STAGE` (pipeline stage transition), `STATUS` (transient status label), `ERROR` (handled exception envelope), `DONE` (turn completion payload), `SESSION` (session metadata updates), `METRIC` (latency and token statistics), `ATTACHMENT` (media outputs).

---

### 3.3 Preserved Capabilities Inventory (All 7 Capabilities)

All 7 multi-stage capabilities are strictly preserved and registered in `deeptutor/runtime/bootstrap/builtin_capabilities.py`:

| # | Capability ID | Class Path | Pipeline Stages | Detailed Functionality |
|---|---------------|------------|-----------------|------------------------|
| 1 | `chat` | `deeptutor.agents.chat.capability:ChatCapability` | `exploring` $\rightarrow$ `responding` | Standard agentic tutoring conversation with autonomous tool selection, context budgeting, and dynamic memory integration. |
| 2 | `deep_solve` | `deeptutor.capabilities.solve.capability:DeepSolveCapability` | `planning` $\rightarrow$ `reasoning` $\rightarrow$ `writing` | Multi-step formal problem solving with structured solution plans, checkpoint verification, and step compression. |
| 3 | `deep_question` | `deeptutor.agents.question.capability:DeepQuestionCapability` | `ideation` $\rightarrow$ `generation` | Socratic quiz generation, misconception diagnostics, and question paper emulation based on uploaded textbooks. |
| 4 | `deep_research` | `deeptutor.agents.research.capability:DeepResearchCapability` | `rephrasing` $\rightarrow$ `decomposing` $\rightarrow$ `researching` $\rightarrow$ `reporting` | Multi-query academic research synthesizer with arXiv paper search, citation indexing, and comprehensive report generation. |
| 5 | `visualize` | `deeptutor.agents.visualize.capability:VisualizeCapability` | `analyzing` $\rightarrow$ `generating` $\rightarrow$ `reviewing` | Generation of interactive visual diagrams (Mermaid, Chart.js, SVG, HTML5 Canvas) and mathematical graphs. |
| 6 | `math_animator` | `deeptutor.agents.math_animator.capability:MathAnimatorCapability` | `concept_analysis` $\rightarrow$ `concept_design` $\rightarrow$ `code_generation` $\rightarrow$ `code_retry` $\rightarrow$ `summary` $\rightarrow$ `render_output` | Mathematical animations powered by programmatic Manim script generation, automated syntax validation, and video rendering. |
| 7 | `mastery_path` | `deeptutor.capabilities.mastery.capability:MasteryPathCapability` | `responding` (Guided Learning) | Curriculum mastery progression engine tracking prerequisite dependency graphs, difficulty gating, and spaced repetition. |

---

### 3.4 Preserved Tools Inventory (All 43 Tools Cataloged)

Defined across `deeptutor/tools/builtin/__init__.py` and specialized capability modules:

1. **User-Toggleable Tools (7 Tools)**:
   - `brainstorm`: Breadth-first idea exploration with structured rationale.
   - `web_search`: Live internet search with citation metadata.
   - `paper_search`: arXiv academic paper search and abstract indexing.
   - `reason`: Dedicated high-depth reasoning LLM call.
   - `geogebra_analysis`: Interactive mathematical geometric figure reconstruction.
   - `imagegen`: Text-to-image generation via OpenAI-compatible endpoints.
   - `videogen`: Text-to-video generation via asynchronous task providers.

2. **Context-Gated / Configurable Tools (15 Tools)**:
   - `rag`: Hybrid vector (FAISS) + keyword (BM25) knowledge retrieval.
   - `kb_files`: Inspection and enumeration of attached knowledge base documents.
   - `code_execution`: Sandboxed Python REPL for mathematical computation and data analysis.
   - `read_source`: Extraction of raw text chunks from documents or notebook passages.
   - `read_memory`: Retrieval of facts from the 3-layer user memory profile.
   - `write_memory`: Persistent recording of user preferences, learning pace, and facts.
   - `read_skill`: Execution of specialized domain skills.
   - `list_notebook`: Search and enumeration of user notes.
   - `write_note`: Direct saving of summaries into the student's notebook.
   - `web_fetch`: Fetching and markdown parsing of specific web pages.
   - `github`: Querying repositories, issues, and code on GitHub.
   - `exec`: Controlled CLI/shell command execution in sandboxed environment.
   - `load_tools`: Dynamic discovery and registration of runtime MCP tools.
   - `cron`: Scheduling alarms, study reminders, and recurring tasks.
   - `ask_user`: Interactive pause mechanism requesting student input or clarification.

3. **Mastery Path Tools (5 Tools)**:
   - `mastery_status`: Query current knowledge point mastery scores.
   - `mastery_quiz`: Generate targeted diagnostic assessment questions.
   - `mastery_grade`: Grade student answers against rubric criteria.
   - `mastery_assess`: Re-compute student mastery probability.
   - `mastery_build`: Construct knowledge point dependency trees.

4. **Solve Capability Tools (3 Tools)**:
   - `solve_plan`: Generate structured step-by-step solution plan.
   - `solve_finish_step`: Finalize milestone step and compress context.
   - `solve_replan`: Adjust remaining solution plan when obstacles arise.

5. **Obsidian Vault Tools (9 Tools)**:
   - `obsidian_search`, `obsidian_read`, `obsidian_list`, `obsidian_backlinks`, `obsidian_links`, `obsidian_tags`, `obsidian_create_note`, `obsidian_append`, `obsidian_set_property`.

6. **Subagent Tool (1 Tool)**:
   - `consult_subagent`: Subordinate consultation of external local CLI agents (Claude Code, Codex).

7. **Partner Tools (3 Tools)**:
   - `partner_read`, `partner_memorize`, `partner_search`.

---

### 3.5 Preserved API Router Endpoints Catalog (33 Routers)

Mounted in `deeptutor/api/main.py`:
1. `/api/v1/auth` (`auth.py`) — Authentication, registration, token refresh, status.
2. `/api/outputs` (`outputs.py`) — Static media outputs, generated images, Manim video renders.
3. `/api/v1/settings/ui` (`settings.py:public_router`) — Language bootstrap settings.
4. `/api/v1` (`chat.py`) — Chat session dispatch, turn streaming, cancellation.
5. `/api/v1/sessions` (`sessions.py`) — Session CRUD, title generation, tree branching.
6. `/api/v1/question` (`question.py`) — Question generation & quiz endpoints.
7. `/api/v1/question-notebook` (`question_notebook.py`) — Mistake notebook & practice drills.
8. `/api/v1/knowledge` (`knowledge.py`) — Knowledge base CRUD, document upload, chunking, indexing.
9. `/api/v1/imports` (`imports.py`) — External session importer (Claude Code, Codex).
10. `/api/v1/dashboard` (`dashboard.py`) — Study metrics, learning analytics.
11. `/api/v1/learning` (`mastery_path.py`) — Mastery path tree, node progress, gates.
12. `/api/v1/co_writer` (`co_writer.py`) — Document co-writing & outline generator.
13. `/api/v1/notebook` (`notebook.py`) — Markdown notes & notebook CRUD.
14. `/api/v1/book` (`book.py`) — Interactive BookEngine reader & chapters.
15. `/api/v1/memory` (`memory.py`) — 3-layer memory inspection & manual edits.
16. `/api/v1/capabilities` (`capabilities_settings.py`) — Capability toggles & parameter configs.
17. `/api/v1/settings` (`settings.py`) — System settings, models, providers, UI configuration.
18. `/api/v1/settings/mcp` (`mcp_settings.py`) — Global MCP server configurations.
19. `/api/v1/space/mcp` (`space_mcp.py`) — User-scoped MCP server configurations.
20. `/api/v1/space/cli-apps` (`space_cli_apps.py`) — User CLI applications catalog.
21. `/api/v1/skills` (`skills.py`) — Installed agent skills catalog.
22. `/api/v1/subagents` (`subagents.py`) — Local external agent integration.
23. `/api/v1/personas` (`personas.py`) — Persona profiles & switching.
24. `/api/v1/tools` (`tools.py`) — Tool definitions & user tool toggles.
25. `/api/v1/system` (`system.py`) — System status, memory probe, hardware topology.
26. `/api/v1/voice` (`voice.py`) — TTS voice synthesis & STT transcription.
27. `/api/v1/plugins` (`plugins_api.py`) — Installed plugin extensions.
28. `/api/v1/agent-config` (`agent_config.py`) — Agent behavior hyperparameters.
29. `/api/v1/partners` (`partners.py`) — IM-connected companion channels.
30. `/api/attachments` (`attachments.py`) — File uploads & temporary attachment storage.
31. `/api/v1/multi-user` (`multi_user/router.py`) — Multi-tenant user administration.
32. `/api/v1/ws` (`unified_ws.py`) — Unified realtime WebSocket for streaming turns.
33. `/api/v1/quiz-judge` (`quiz_judge.py`) — Realtime interactive quiz evaluation WebSocket.

---

### 3.6 Frontend Architecture (`web/`)
- **Core Framework**: Next.js 16.2.3 (App Router), React 19.0.0, TypeScript 5.
- **Design System**: LiquidGlass design language (`globals.css`, `glass-surfaces.css`) utilizing CSS variables for theme switching (`snow`, `light`, `cream`, `dark`, `glass`), translucent glassmorphism panels, and fluid micro-animations.
- **Layout Architecture**:
  - `AppShell`: Global responsive layout host managing `HeaderBar` (branding, search, profile), `FloatingDock` (navigation icons, session drawer), and route content viewports.
  - Route Groups: `(workspace)` (interactive working areas: `home`, `playground`, `book`, `co-writer`, `partners`), `(utility)` (management tools: `knowledge`, `notebook`, `memory`, `agents`, `profile`, `settings`), `(auth)` (`login`, `register`), and `(admin)` (`admin/users`).
- **Internationalization**: Full `i18next` client bridge with dynamic locale switching (`en` and `zh`).

---

## 4. AI Guru Extended Subsystems Specifications

### 4.1 Subsystem 1: Local-First Relational Database Schema & Versioned Migrations

#### Database Engine & Concurrency Design
- **Engine**: SQLite via `aiosqlite` (Python async driver).
- **Location**: `data/user/chat_history.db` (preserving existing chat tables) or extended alongside `data/user/aiguru.db`.
- **Journal Mode**: `PRAGMA journal_mode = WAL;` (Write-Ahead Logging) to ensure zero-lock concurrent reading between Next.js UI rendering, background computer vision telemetry logging, and parent dashboard queries.
- **Foreign Keys**: `PRAGMA foreign_keys = ON;` enforcing relational integrity.
- **Busy Timeout**: `PRAGMA busy_timeout = 5000;` preventing lock contention under burst writes.

#### Comprehensive 11-Table Relational Schema DDL
```sql
-- 1. Local User Accounts
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('student', 'parent', 'admin')),
    display_name TEXT NOT NULL,
    avatar_url TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

-- 2. Student Profiles
CREATE TABLE IF NOT EXISTS students (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    grade_level TEXT DEFAULT '',
    school TEXT DEFAULT '',
    learning_style TEXT DEFAULT 'visual',
    target_daily_minutes INTEGER DEFAULT 60,
    streak_count INTEGER DEFAULT 0,
    total_xp INTEGER DEFAULT 0,
    face_embedding_json TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

-- 3. Parent Profiles
CREATE TABLE IF NOT EXISTS parents (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email TEXT DEFAULT '',
    phone_number TEXT DEFAULT '',
    notification_preferences_json TEXT DEFAULT '{"email": false, "warnings": true, "daily_summary": true}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

-- 4. Parent-Student Pairing Links
CREATE TABLE IF NOT EXISTS parent_student_links (
    id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    pairing_code TEXT DEFAULT '',
    pairing_code_expires_at REAL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'revoked')) DEFAULT 'pending',
    permissions_json TEXT DEFAULT '{"can_view_live": true, "can_view_reports": true, "can_manage_goals": true}',
    paired_at REAL,
    created_at REAL NOT NULL,
    UNIQUE(parent_id, student_id)
);

-- 5. Study Sessions
CREATE TABLE IF NOT EXISTS study_sessions (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'Study Session',
    subject TEXT DEFAULT 'General',
    target_duration_seconds INTEGER NOT NULL DEFAULT 1800,
    actual_duration_seconds INTEGER DEFAULT 0,
    start_time REAL NOT NULL,
    end_time REAL,
    status TEXT NOT NULL CHECK (status IN ('in_progress', 'completed', 'paused', 'abandoned')) DEFAULT 'in_progress',
    focus_score REAL DEFAULT 100.0,
    engagement_score REAL DEFAULT 100.0,
    distraction_count INTEGER DEFAULT 0,
    warning_count INTEGER DEFAULT 0,
    ai_summary TEXT DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_study_sessions_student ON study_sessions(student_id, start_time DESC);

-- 6. Monitoring Computer Vision Events
CREATE TABLE IF NOT EXISTS monitoring_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE,
    timestamp REAL NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'PRESENCE_CHANGE', 'LOOKING_AWAY', 'PHONE_DETECTED', 
        'POSTURE_SHIFT', 'IDENTITY_VERIFIED', 'LIVENESS_CHECK', 
        'WARNING_ISSUED', 'SESSION_PAUSED', 'SESSION_RESUMED'
    )),
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'alert')) DEFAULT 'info',
    confidence REAL DEFAULT 1.0,
    duration_seconds REAL DEFAULT 0.0,
    metadata_json TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_monitoring_events_session ON monitoring_events(session_id, timestamp ASC);

-- 7. Session Evaluation Reports
CREATE TABLE IF NOT EXISTS session_reports (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE REFERENCES study_sessions(id) ON DELETE CASCADE,
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    focus_score REAL NOT NULL,
    engagement_score REAL NOT NULL,
    total_study_seconds INTEGER NOT NULL,
    productive_seconds INTEGER NOT NULL,
    distracted_seconds INTEGER NOT NULL,
    topics_covered_json TEXT DEFAULT '[]',
    key_strengths TEXT DEFAULT '',
    areas_for_improvement TEXT DEFAULT '',
    ai_tutor_feedback TEXT DEFAULT '',
    parent_notes TEXT DEFAULT '',
    generated_at REAL NOT NULL
);

-- 8. Rewards & Gamification
CREATE TABLE IF NOT EXISTS rewards (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES study_sessions(id) ON DELETE SET NULL,
    reward_type TEXT NOT NULL CHECK (reward_type IN ('xp', 'badge', 'streak_bonus', 'milestone')),
    amount_xp INTEGER DEFAULT 0,
    badge_id TEXT DEFAULT '',
    badge_name TEXT DEFAULT '',
    badge_icon TEXT DEFAULT '',
    reason TEXT DEFAULT '',
    unlocked_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rewards_student ON rewards(student_id, unlocked_at DESC);

-- 9. Study Goals
CREATE TABLE IF NOT EXISTS study_goals (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    goal_type TEXT NOT NULL CHECK (goal_type IN ('daily_minutes', 'weekly_sessions', 'subject_mastery')),
    target_value REAL NOT NULL,
    current_value REAL DEFAULT 0.0,
    start_date REAL NOT NULL,
    end_date REAL NOT NULL,
    is_completed INTEGER DEFAULT 0,
    reward_xp INTEGER DEFAULT 50,
    created_at REAL NOT NULL
);

-- 10. System & Application Settings
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    updated_at REAL NOT NULL
);

-- 11. Security & Audit Logs
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    actor_id TEXT DEFAULT '',
    actor_role TEXT DEFAULT 'system',
    ip_address TEXT DEFAULT '',
    action TEXT NOT NULL,
    resource_type TEXT DEFAULT '',
    resource_id TEXT DEFAULT '',
    details_json TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp DESC);

-- Schema Migration Version Tracking Table
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at REAL NOT NULL
);
```

---

### 4.2 Subsystem 2: Dual-Mode AI Provider Abstraction (`TutorProvider`) & Resource Governor

#### Abstract Interface (`TutorProvider`)
```python
class TutorProvider(ABC):
    @abstractmethod
    async def stream(
        self, messages: list[dict], params: dict | None = None
    ) -> AsyncIterator[StreamChunk]:
        """Stream response tokens and tool call frames."""
        ...

    @abstractmethod
    async def complete(
        self, messages: list[dict], params: dict | None = None
    ) -> CompletionResponse:
        """Execute single-shot completion."""
        ...

    @abstractmethod
    async def check_health(self) -> ProviderHealth:
        """Verify model endpoint connectivity and latency."""
        ...
```

#### Provider Operational Modes
1. **Mode A (Cloud AI Provider)**:
   - Connects to high-parameter cloud models via OpenAI-compatible endpoints (OpenAI, Anthropic, DashScope, DeepSeek, Gemini, Perplexity).
   - Manages token streaming, reasoning `<think>` tag extraction, and structured JSON tool schemas.
2. **Mode B (Local Ollama Provider)**:
   - Connects to local Ollama daemon (`http://127.0.0.1:11434`).
   - Dynamically polls `/api/tags` to discover available models (e.g. `qwen2.5:7b`, `llama3.2:3b`, `deepseek-r1:8b`).
   - Streams raw tokens and extracts thought chunks without external network access.
3. **Mode C (Offline Rule-Based Engine)**:
   - Activates when both Cloud API and Local Ollama are unreachable.
   - Provides structured offline responses, study timer progression, flashcard retrieval, and local summary aggregation.

#### Automated Fallback Circuit Breaker
```
User Prompt ──► [Mode A: Cloud API] ──(Timeout / Network Error)──► [Mode B: Local Ollama] ──(Ollama Down)──► [Mode C: Offline Mode]
```

#### Hardware Capability Profiler & Resource Governor
On startup, `HardwareProfiler` queries system resources and assigns a classification tier:
- **`HIGH` Tier** (Dedicated NVIDIA GPU $\ge 8\text{GB}$ VRAM / Apple Silicon $\ge 16\text{GB}$):
  - Recommended Models: `qwen2.5:7b-instruct`, `deepseek-r1:8b`, `llama3.1:8b`.
  - Max Context: 16k tokens; CV monitoring at 10 FPS.
- **`MEDIUM` Tier** (GPU $4-6\text{GB}$ VRAM / CPU with $\ge 16\text{GB}$ RAM):
  - Recommended Models: `qwen2.5:3b`, `llama3.2:3b`, `phi-3.5-mini:3.8b`.
  - Max Context: 4k tokens; CV monitoring at 5–8 FPS.
- **`LOW` Tier** (CPU-only $\le 8\text{GB}$ RAM):
  - Recommended Models: `qwen2.5:1.5b`, `llama3.2:1b`, or prompt user to configure Mode A Cloud API.
  - Max Context: 2k tokens; CV monitoring throttled to 3–5 FPS.
- **Dynamic Resource Governor (`psutil`)**:
  - Background monitor evaluates system CPU and RAM utilization every 5 seconds.
  - If CPU $> 85\%$ or RAM $> 90\%$ sustained for $> 10$ seconds:
    * Throttles CV monitoring sampling rate down to 3 FPS.
    * Pauses non-critical background indexing tasks.
    * Prevents student laptop overheating and UI jank.

---

### 4.3 Subsystem 3: Privacy-Preserving Local Computer Vision Monitoring Engine

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             STUDENT BROWSER (Next.js)                       │
│                                                                             │
│  navigator.mediaDevices.getUserMedia() ──► <video> Local Preview (30 FPS)    │
│                     │                                                       │
│                     ▼                                                       │
│          Rate Limiter (5-10 FPS) ──► MediaPipe Vision (WASM / WebWorker)    │
│                     │                - FaceLandmarker (478 3D points)       │
│                     │                - Eye Blendshapes (blink / gaze)       │
│                     │                - Head Pose (yaw, pitch, roll)         │
│                     ▼                                                       │
│          Local WS Stream (/api/v1/monitoring/feed)                          │
└─────────────────────┬───────────────────────────────────────────────────────┘
                      │ Localhost Frames (320x240 @ 5-10 FPS)
                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         BACKEND MONITORING ENGINE (Python)                  │
│                                                                             │
│  ┌────────────────────────┐  ┌───────────────────────┐  ┌────────────────┐  │
│  │ Anti-Spoof / Liveness  │  │ Identity Verification │  │ Pose Classifier│  │
│  │ - Laplacian Texture    │  │ - MobileFaceNet ONNX  │  │ - Pitch/Yaw/Rot│  │
│  │ - Moiré Screen Pattern │  │ - Cosine Sim (>=0.65) │  │ - Reading Desk │  │
│  │ - Dynamic Micro-Blink  │  │ - Reference Vector    │  │ - Writing Pose │  │
│  └───────────┬────────────┘  └───────────┬───────────┘  └────────┬───────┘  │
│              │                           │                       │          │
│              └───────────────────┬───────┴───────────────────────┘          │
│                                  ▼                                          │
│                   PRESENCE & DISTRACTION STATE MACHINE                      │
│                                                                             │
│      ┌─────────────────────────────────────────────────────────────┐        │
│      │ State Matrix:                                               │        │
│      │ - PRESENT (Face valid & active)                             │        │
│      │ - TEMPORARILY_NOT_VISIBLE (Absent < 10s -> Amber Badge)     │        │
│      │ - AWAY (Absent >= 15s -> Pause Timer + Event)               │        │
│      │ - UNKNOWN (Low light < 25 luminance / camera occluded)      │        │
│      │                                                             │        │
│      │ Activity Filter:                                            │        │
│      │ - ALLOWED: Writing/Reading (Pitch down 25°-55° + hands low) │        │
│      │ - ALLOWED: Drinking water / Chair adjustment (< 5s)         │        │
│      │ - FLAGGED: Phone in hand / hand-to-ear (> 3s)               │        │
│      │ - FLAGGED: Looking away (|Yaw| > 35° > 8s)                  │        │
│      └───────────────────────────┬─────────────────────────────────┘        │
│                                  ▼                                          │
│                       WARNING ENGINE WITH COOLDOWN                          │
│     - Confidence threshold >= 0.80 & Duration >= T_trigger                  │
│     - 45-60s debounce cooldown per category (no alert spam)                 │
│     - Max 3 audible warnings per 10-minute interval                         │
│                                  │                                          │
│             ┌────────────────────┴────────────────────┐                     │
│             ▼                                         ▼                     │
│   SQLite `monitoring_events`              WebSocket UI Dispatch             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Detailed Mathematical & Algorithmic Rules:
1. **Face Identity Verification**:
   - Enrollment: At initial onboarding, student captures a reference frame $\mathbf{I}_{ref} \rightarrow$ extracts 128D feature embedding $\mathbf{v}_{enroll}$.
   - Online Verification: Periodically every 60s, sampled frame $\mathbf{v}_{curr}$ is evaluated:
     $$\text{Cosine Similarity} = \frac{\mathbf{v}_{curr} \cdot \mathbf{v}_{enroll}}{\|\mathbf{v}_{curr}\| \|\mathbf{v}_{enroll}\|}$$
   - Threshold: If $\text{Similarity} \ge 0.65 \implies \text{MATCH}$. If $< 0.65$ for $> 30\text{s} \implies \text{IDENTITY\_MISMATCH}$ event.
2. **Anti-Spoof Passive Liveness Detection**:
   - Texture High-Frequency Analysis: Evaluates Laplacian variance $\sigma^2 = \text{Var}(\nabla^2 I)$. Screen replays show telltale high-frequency moiré harmonics; printed paper exhibits low dynamic specular reflectance.
   - Dynamic Eye Aspect Ratio (EAR) Blink Tracking:
     $$\text{EAR} = \frac{\|p_2 - p_6\| + \|p_3 - p_5\|}{2 \|p_1 - p_4\|}$$
     Sliding window (30 frames / 3–5 seconds) verifies natural ocular micro-saccades and blinks ($\text{Var}(\text{EAR}) > \epsilon$). Static photos have $\text{Var}(\text{EAR}) \approx 0 \implies \text{SPOOF\_REJECTED}$.
3. **Presence State Machine (Hysteresis-Based)**:
   - `PRESENT`: Face detected, confidence $\ge 0.70$, valid head pose.
   - `TEMPORARILY_NOT_VISIBLE`: Face absent for $t \in [3\text{s}, 10\text{s})$ (e.g. stretching or bending down). Focus timer continues; amber status displayed.
   - `AWAY`: Face absent for $t \ge 10\text{s}$. Study timer auto-pauses at 60s; `AWAY` event written to database.
   - `UNKNOWN`: Frame mean luminance $< 25$ (room dark) or camera lens occluded.
4. **False-Positive Distraction Filtering (Study Gesture Whitelist)**:
   - Normal student studying involves looking down at textbooks and writing on paper.
   - **Allowed Study Gestures (Focus Score = 100%)**:
     * Writing / Desk Reading: Head Pitch $\theta_p \in [20^\circ, 55^\circ]$ downward, hand landmarks active in lower third of frame.
     * Drinking Water / Beverage: Brief mouth occlusion ($t < 6\text{s}$) with upward arm trajectory.
     * Page Turning / Stretching: Transient head movement ($t < 4\text{s}$).
   - **Flagged Distractions**:
     * Looking Away / Daydreaming: Head Yaw $|\theta_y| > 35^\circ$ for $> 10$ seconds.
     * Smartphone Usage: Detected rectangular handheld object ($w/h \approx 0.5$) or hand-to-ear posture for $> 5$ seconds.
     * Eyes Closed / Sleeping: $\text{EAR} < 0.15$ sustained for $> 4$ seconds.
5. **Warning Cooldown Governor**:
   - Token bucket rate limiter: $T_{cooldown} = 60\text{s}$ per distraction category.
   - Suppresses duplicate alert chimes to prevent student anxiety while maintaining 100% accurate time-accounting in telemetry logs.

---

### 4.4 Subsystem 4: Study Session Lifecycle & Analytics Engine

```
[Create Session] ──► [Pre-flight Wizard] ──► [Identity & Liveness Check] ──► [Active Study Room] ──► [Session Wrap-up] ──► [AI Summary & Report] ──► [XP & Badges Awarded]
```

1. **Pre-flight Hardware Wizard**:
   - Validates camera device availability and WebRTC permissions.
   - Tests ambient illumination histogram (prompts "Please turn on a desk lamp" if dark).
   - Validates face framing alignment with visual bounding oval.
2. **Interactive Study Room**:
   - Split-screen workspace combining countdown Pomodoro/target timer, live focus score gauge, minimized local camera preview with privacy LED indicator, and embedded AI Guru conversation panel.
3. **Session Analytics & AI Summary**:
   - On session completion, the engine aggregates `monitoring_events` to compute:
     * Productive Study Time vs. Distracted Time.
     * Average Focus Score and Engagement Curve.
     * Distraction Incident Frequency & Breakdown.
   - Synthesizes an AI Study Report via LLM prompt highlighting: key topics mastered, focus review, cognitive strengths, improvement suggestions, and recommended next study goals.
   - Generates downloadable PDF and Markdown reports for student portfolios and parent reviews.

---

### 4.5 Subsystem 5: Rewards & Gamification Engine

1. **XP Points Formula**:
   $$\text{XP Earned} = \left( \frac{\text{Duration Minutes}}{10} \times 10 \right) \times \text{Focus Multiplier} + \text{Bonus XP}$$
   where $\text{Focus Multiplier}$ is scaled:
   - Focus Score $\ge 90\% \implies 1.5\times$
   - Focus Score $\ge 75\% \implies 1.2\times$
   - Focus Score $\ge 50\% \implies 1.0\times$
   - Focus Score $< 50\% \implies 0.8\times$
   - Goal Completion Bonus: $+50\text{ XP}$.
2. **Daily Streak Engine**:
   - Evaluates consecutive days of study ($\ge 15\text{ minutes/day}$).
   - Tracks current streak, longest streak, and supports 1 "Streak Freeze" per week to accommodate rest days.
3. **Badge & Achievement System**:
   - Awards milestone badges: "Laser Focus" (100% focus in 45m session), "Night Owl", "Early Bird", "Math Prodigy", "7-Day Streak Master", "Knowledge Explorer".
4. **Level Progression**:
   - 50 Progressive Tiers governed by $\text{XP}_{req} = 100 \times \text{Level}^{1.5}$.

---

### 4.6 Subsystem 6: Parent Dashboard & Secure Remote Access Gateway

```
┌───────────────────────────┐                       ┌───────────────────────────┐
│     STUDENT MACHINE       │                       │       PARENT DEVICE       │
│  (Home NAT / Dynamic IP)  │                       │  (Cellular / Remote WiFi) │
└─────────────┬─────────────┘                       └─────────────┬─────────────┘
              │                                                   │
              │ 1. Outbound TLS WebSocket                         │ 2. Parent Login / Auth
              │    (wss://tunnel.aiguru.app/gateway)              │    (JWT + Pairing Code)
              ▼                                                   ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                          AIGURU RELAY GATEWAY                                 │
│  - No persistent study data stored                                            │
│  - Relays encrypted RPC packets and WebRTC signaling SDP                      │
│  - Enforces rate limits (max 5 failed attempts / 15 min)                      │
└───────────────────────┬───────────────────────────────────┬───────────────────┘
                        │                                   │
                        │ 3. Asymmetric Key Exchange & Mux  │
                        ◄───────────────────────────────────►
                        │
                        ▼
       ┌───────────────────────────────────────────────────────────┐
       │ Channels:                                                 │
       │ 1. Data Channel (WSS Mux):                                │
       │    - Real-time study dashboard (time, focus %, streak)    │
       │    - Session reports, alerts, goals                       │
       │ 2. WebRTC MediaStream (DTLS-SRTP End-to-End Encrypted):   │
       │    - Opt-in live video preview                            │
       │    - Student visual banner: "Parent viewing live session" │
       │    - Auto-terminates immediately when session ends        │
       │    - No video recorded to disk                            │
       └───────────────────────────────────────────────────────────┘
```

#### Security & Access Control Protocols:
1. **Pairing Handshake**: Student generates time-limited 6-character pairing code `GURU-XXXX` (10-minute TTL, SHA-256 hashed in DB). Parent inputs code to establish authenticated link in `parent_student_links`.
2. **Short-Lived JWT Tokens**: Remote API access utilizes 15-minute access tokens carrying student ID and explicit permissions (`can_view_live`, `can_view_reports`), with automatic token refresh rotation.
3. **Opt-in Live Video Supervision**:
   - Requires explicit prior consent from student settings.
   - Prominently displays a glowing status banner on the student interface: *"Parent is viewing live session"*.
   - Automatically kills the video stream upon session completion or parent tab close.
   - Streamed via direct WebRTC DTLS-SRTP encryption without intermediate server recording.
4. **Zero-Cloud Data Principle**: The relay gateway acts solely as an encrypted transit tunnel. No session logs, reports, or camera data reside on the relay. All data stays strictly on the student's local SQLite database.
5. **Comprehensive Audit Logging**: All parent actions (`PAIR`, `LOGIN`, `VIEW_DASHBOARD`, `START_LIVE_FEED`, `STOP_LIVE_FEED`, `EXPORT_REPORT`) are immutably logged to the `audit_logs` table.

---

### 4.7 Subsystem 7: Offline Connectivity & Error Interception

1. **`ConnectivityManager` State Machine**:
   - `ONLINE`: Internet available, Cloud AI and remote parent sync active.
   - `LIMITED`: Internet available with high latency / packet loss; throttles heavy requests.
   - `OFFLINE`: Internet disconnected. Local Ollama LLM, local CV monitoring, SQLite persistence, study timer, and report generation continue without interruption.
   - `RECONNECTING`: Attempting socket reconnect with exponential backoff ($1\text{s}, 2\text{s}, 4\text{s}, \dots, 30\text{s}$).
2. **Visual Connectivity Navbar Badge**:
   - Green: *Online — Cloud AI Active*
   - Yellow: *Offline — Local Ollama Active*
   - Gray: *Offline — Local Study Mode*
3. **Friendly Error Interceptor**:
   - Catches low-level networking exceptions (`ECONNREFUSED`, `ETIMEDOUT`, `500 Internal Server Error`, `SQLite locked`) and displays graceful, non-technical recovery dialogs (e.g. *"AI Guru is currently working offline. Your study progress is being saved locally."*).

---

### 4.8 Subsystem 8: Security, Privacy & Threat Model

1. **Threat Mitigation Matrix**:
   - *Biometric Egress Threat*: Camera frames or embeddings intercepted $\implies$ Mitigated by 100% local in-memory CV inference; no network socket emits image data.
   - *Parent Impersonation Threat*: Unauthorized remote access $\implies$ Mitigated by 6-digit cryptographic pairing, short-lived JWTs (15 min), device fingerprints, and revocation hooks.
   - *Database Tampering*: Local file access $\implies$ Bound strictly to `127.0.0.1`, encrypted backups, and audit logs.
2. **Encrypted Local Backup & Restore**:
   - Exports AES-GCM encrypted database archive (`.aiguru-backup`) protected by a user-chosen passphrase.
   - Guided restore UI with pre-flight schema integrity validation.
3. **Privacy Data Deletion & Purge**:
   - Granular deletion options: Delete individual session telemetry, purge all CV monitoring events, reset student profile, or full factory reset.
4. **Developer Simulation Test Mode (`--mock-camera`, `--dev`)**:
   - Enables headless automated CI/CD and unit testing by injecting synthetic video frame states (`MOCK_PRESENT`, `MOCK_WRITING`, `MOCK_DISTRACTED_PHONE`, `MOCK_AWAY`) without requiring physical webcam hardware.

---

## 5. Comprehensive Requirements Traceability Matrix

The following matrix maps every requirement from `REQ-R1-01` to `REQ-R9-05` to its architectural subsystem, target files, and milestone:

| Requirement ID | Requirement Name | Architectural Subsystem | Target Implementation Files | Milestone |
|----------------|------------------|-------------------------|-----------------------------|-----------|
| `REQ-R1-01` | Architecture Audit Document | Documentation | `docs/AI-GURU-ARCHITECTURE-AUDIT.md` | M1 |
| `REQ-R1-02` | Implementation Phasing Plan | Documentation | `docs/AI-GURU-IMPLEMENTATION-PLAN.md` | M1 |
| `REQ-R1-03` | Web UI Rebranding | Frontend / UI | `web/app/layout.tsx`, `web/components/layout/*` | M1 |
| `REQ-R1-04` | PWA & Metadata Rebranding | Frontend / PWA | `web/public/manifest.json`, `web/app/layout.tsx` | M1 |
| `REQ-R1-05` | CLI & Banner Rebranding | CLI / Runtime | `deeptutor_cli/main.py`, `deeptutor/runtime/banner.py` | M1 |
| `REQ-R1-06` | Internal Code Preservation | Backend Core | `deeptutor/*`, `pyproject.toml` | M1 |
| `REQ-R2-01` | Unified Service Launcher | Runtime Supervisor | `deeptutor/runtime/launcher.py`, `deeptutor_cli/main.py` | M2 |
| `REQ-R2-02` | Comprehensive Health Check | System API | `deeptutor/api/routers/health.py`, `system.py` | M2 |
| `REQ-R2-03` | Localhost Binding & Security | Network / API | `deeptutor/api/main.py`, `runtime_settings.py` | M2 |
| `REQ-R2-04` | 11-Table SQLite Schema | Storage Layer | `deeptutor/services/database/schema.py`, `sqlite_store.py` | M2 |
| `REQ-R2-05` | Non-Destructive Migrations | Storage Layer | `deeptutor/services/database/migrations.py` | M2 |
| `REQ-R2-06` | Windows Auto-Startup Support | Platform Integration | `deeptutor/services/platform/windows_startup.py` | M2 |
| `REQ-R2-07` | Subsystem Recovery | Runtime Supervisor | `deeptutor/runtime/launcher.py` | M2 |
| `REQ-R3-01` | `TutorProvider` Interface | AI Subsystem | `deeptutor/services/llm/tutor_provider.py` | M3 |
| `REQ-R3-02` | Cloud Provider Adapter | AI Subsystem | `deeptutor/services/llm/cloud_adapter.py` | M3 |
| `REQ-R3-03` | Ollama Local Provider Adapter | AI Subsystem | `deeptutor/services/llm/ollama_adapter.py` | M3 |
| `REQ-R3-04` | AI Mode Settings UI | Frontend Settings | `web/components/settings/AISettings.tsx` | M3 |
| `REQ-R3-05` | Auto-Fallback Chain | AI Subsystem | `deeptutor/services/llm/fallback_manager.py` | M3 |
| `REQ-R3-06` | Secure Local API Key Vault | Security / Config | `deeptutor/services/config/key_vault.py` | M3 |
| `REQ-R3-07` | Hardware Profiler | System Diagnostics | `deeptutor/services/hardware/profiler.py` | M3 |
| `REQ-R3-08` | Resource Governor | System Diagnostics | `deeptutor/services/hardware/governor.py` | M3 |
| `REQ-R3-09` | AI Onboarding Setup Wizard | Frontend Onboarding | `web/components/onboarding/AIWizard.tsx` | M3 |
| `REQ-R4-01` | Local-Only CV Pipeline | CV Monitoring Engine | `web/components/monitoring/CVWorker.ts`, `deeptutor/services/monitoring/` | M4 |
| `REQ-R4-02` | Decoupled Sampling (5-10 FPS)| CV Monitoring Engine | `web/components/monitoring/FrameSampler.ts` | M4 |
| `REQ-R4-03` | Face Detection & Landmarks | CV Monitoring Engine | `web/components/monitoring/FaceDetector.ts` | M4 |
| `REQ-R4-04` | Face Identity Verification | CV Monitoring Engine | `deeptutor/services/monitoring/verifier.py` | M4 |
| `REQ-R4-05` | Anti-Spoof Liveness Detector | CV Monitoring Engine | `deeptutor/services/monitoring/liveness.py` | M4 |
| `REQ-R4-06` | Head Pose & Gaze Estimation | CV Monitoring Engine | `deeptutor/services/monitoring/pose.py` | M4 |
| `REQ-R4-07` | Presence State Machine | CV Monitoring Engine | `deeptutor/services/monitoring/state_machine.py` | M4 |
| `REQ-R4-08` | Real-Time Engagement Estimator| CV Monitoring Engine | `deeptutor/services/monitoring/engagement.py` | M4 |
| `REQ-R4-09` | Distraction False-Positive Filter | CV Monitoring Engine | `deeptutor/services/monitoring/distraction_filter.py` | M4 |
| `REQ-R4-10` | Warning System & Cooldown | CV Monitoring Engine | `deeptutor/services/monitoring/warning_governor.py` | M4 |
| `REQ-R5-01` | Study Session Creation Screen | Session Management | `web/components/session/CreateSessionModal.tsx` | M5 |
| `REQ-R5-02` | Pre-flight Hardware Check | Session Management | `web/components/session/PreFlightCheck.tsx` | M5 |
| `REQ-R5-03` | Pre-flight Identity & Liveness | Session Management | `web/components/session/PreFlightVerify.tsx` | M5 |
| `REQ-R5-04` | Interactive Study Room View | Study Workspace | `web/app/(workspace)/study-room/page.tsx` | M5 |
| `REQ-R5-05` | Real-Time Telemetry Logging | Session Management | `deeptutor/services/session/telemetry_logger.py` | M5 |
| `REQ-R5-06` | Session Completion & Aggregation| Session Management | `deeptutor/services/session/session_manager.py` | M5 |
| `REQ-R5-07` | AI Study Summary Report | Analytics & AI | `deeptutor/services/session/report_generator.py` | M5 |
| `REQ-R5-08` | Session Report UI & Export | Analytics / UI | `web/components/session/SessionReportView.tsx` | M5 |
| `REQ-R6-01` | XP Points Calculation Engine | Gamification | `deeptutor/services/gamification/xp_engine.py` | M5 |
| `REQ-R6-02` | Daily Streak Tracker | Gamification | `deeptutor/services/gamification/streak_tracker.py` | M5 |
| `REQ-R6-03` | Badges & Achievement System | Gamification | `deeptutor/services/gamification/badge_engine.py` | M5 |
| `REQ-R6-04` | Level Progression System | Gamification | `deeptutor/services/gamification/level_system.py` | M5 |
| `REQ-R6-05` | Gamification Dashboard Widgets | Frontend UI | `web/components/gamification/RewardCard.tsx` | M5 |
| `REQ-R7-01` | Parent-Student Pairing Protocol | Remote Access | `deeptutor/services/remote/pairing.py` | M6 |
| `REQ-R7-02` | Parent Overview Dashboard | Parent Portal | `web/app/(workspace)/parent/page.tsx` | M6 |
| `REQ-R7-03` | Parent Analytics Views | Parent Portal | `web/components/parent/ParentAnalytics.tsx` | M6 |
| `REQ-R7-04` | Zero-Config Outbound Tunnel | Remote Access | `deeptutor/services/remote/tunnel_gateway.py` | M6 |
| `REQ-R7-05` | Short-Lived Tokens & Revocation | Security / Auth | `deeptutor/services/remote/auth_jwt.py` | M6 |
| `REQ-R7-06` | Opt-in Live Video Supervision | Remote Access | `web/components/parent/LiveVideoView.tsx` | M6 |
| `REQ-R7-07` | Remote Data Privacy Isolation | Architecture Design | `deeptutor/services/remote/proxy_handler.py` | M6 |
| `REQ-R7-08` | Parent Access Audit Logging | Security / Audit | `deeptutor/services/remote/audit_logger.py` | M6 |
| `REQ-R8-01` | `ConnectivityManager` Service | Offline Resilience | `web/context/ConnectivityContext.tsx` | M6 |
| `REQ-R8-02` | Navbar Connectivity Indicator | Frontend Layout | `web/components/layout/ConnectivityBadge.tsx` | M6 |
| `REQ-R8-03` | Offline Study Session Continuity| Offline Resilience | `deeptutor/services/session/offline_sync.py` | M6 |
| `REQ-R8-04` | Local Ollama Offline Tutoring | AI Subsystem | `deeptutor/services/llm/ollama_adapter.py` | M6 |
| `REQ-R8-05` | User-Friendly Error Interceptor | Frontend Error UX | `web/components/common/FriendlyErrorModal.tsx` | M6 |
| `REQ-R9-01` | Zero-Cloud Biometric Privacy | Security Verification | Architectural Guarantee & Verification Test | M7 |
| `REQ-R9-02` | Encrypted Local Backup & Restore | Storage / Backup | `deeptutor/services/backup/backup_manager.py` | M7 |
| `REQ-R9-03` | Privacy Data Deletion Controls | Privacy / Compliance | `deeptutor/services/database/purge_manager.py` | M7 |
| `REQ-R9-04` | Developer Simulation Test Mode | Testing Tools | `deeptutor/services/monitoring/mock_feed.py` | M7 |
| `REQ-R9-05` | Complete Documentation Suite | Documentation | `docs/*`, `README.md` | M7 |

---

## 6. Verification and Audit Confirmation

To independently verify the audit assertions and architecture completeness:
1. **Capability Integrity**: Inspect `deeptutor/runtime/bootstrap/builtin_capabilities.py` confirming 7 registered classes.
2. **Tool Inventory**: Inspect `deeptutor/tools/builtin/__init__.py` lines 1562–1608 confirming all 43 tool identifiers.
3. **API Routing**: Inspect `deeptutor/api/main.py` lines 350–485 confirming 33 registered router mounts.
4. **Database Migration Safety**: Execute SQLite in-memory validation verifying table syntax and foreign keys.
5. **Frontend Compilation**: Execute `npm run build` within `web/` to confirm zero TypeScript compilation errors.
