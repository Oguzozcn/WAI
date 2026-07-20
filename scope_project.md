# WisdomAI Implementation Plan

> **Version:** 2.2  
> **Last Updated:** 2026-07-17  
> **Archived Plans:** `archive/catalog_implementation_plan.md`

> [!NOTE]
> **v2.2 — Domain-driven refactor.** The codebase was reorganized from the flat
> `WAI_agent/` + root `server.py` layout into a `src/` package (`src/api`,
> `src/agents`, `src/core`, `src/services`) targeting **google-adk 2.3**.
> Sections below that still describe `WAI_agent/…` or `server.py` are historical;
> the **Directory Structure** and **Runtime** sections reflect the current code.

---

## Decisions Lock

| Decision | Answer |
|----------|--------|
| App Name | **WisdomAI** |
| Sub-agents in MVP | All 5: Curriculum Builder, Knowledge Coach, KB Validator, Department Reporter, Corporate Report Agent |
| Department isolation | **Tier A: Namespace Isolation** (department_id path prefixes, future-proofed for GCP service account migration) |
| Persistence | Local JSON files with GCP-compatible schemas (DepartmentScopedStore) |
| Training theme | **Vertex AI Engineer Path** (10 courses) |
| Model | `gemini-3.5-flash` for all agents |
| Reporting architecture | Push & Aggregate (3-tier, strict isolation, KPI schema v1.0) |
| File upload types (MVP) | `.txt` and `.md` only (PDF deferred to on-premise Flash 3.5). No strict client-side validation needed for now. |
| Course granularity | Up to 10 lessons per module, determined dynamically by agent |
| Quiz cadence | 1 Short Quiz per lesson, 1 Final Assessment per module |
| Baseline Generation | Learning path AND quizzes are generated **upfront** upon document upload. This serves as the team baseline. |
| Dynamic Gap Paths | Gap analysis generates personalized paths. Gap modules are **cached by topic** to reuse across employees and save Gemini costs. |
| Processing UX | **Asynchronous**. File upload returns immediately; UI polls status until processing completes. |
| File Idempotency | If duplicate filename is uploaded, prompt user to **Overwrite** or **Create New Version (v2)**. |

---

## Architecture Overview

```
╔═══════════════════════════════════════════════════════════════════════╗
║  TIER 1: DEPARTMENT SCOPE (Namespace Isolated)                       ║
║                                                                       ║
║  Session: department_id="operations"                                  ║
║  ┌─────────────────┐ ┌──────────────────┐ ┌────────────────────┐     ║
║  │ curriculum_      │ │ knowledge_       │ │ kb_validator       │     ║
║  │ builder          │ │ coach            │ │                    │     ║
║  │                  │ │                  │ │ Validates DTPs     │     ║
║  │ Reads DTPs from  │ │ Reads/writes     │ │ against existing   │     ║
║  │ knowledge_base/  │ │ user_progress/   │ │ knowledge_base/    │     ║
║  │ operations/      │ │ operations/      │ │ operations/        │     ║
║  └────────┬─────────┘ └────────┬─────────┘ └─────────┬──────────┘     ║
║           └────────────────────┼──────────────────────┘               ║
║                                │                                      ║
║                    ┌───────────▼───────────┐                          ║
║                    │  KPI Synthesizer      │                          ║
║                    │  (reporting_tools.py) │                          ║
║                    │  Strips PII, enforces │                          ║
║                    │  schema v1.0          │                          ║
║                    └───────────┬───────────┘                          ║
╠════════════════════════════════╪══════════════════════════════════════╣
║  TIER 2: SECURE BOUNDARY      │                                      ║
║  data/kpi_store/               │ ONE-WAY PUSH                        ║
║  Schema-validated JSON         ▼                                      ║
║  ┌────────────────────────────────────────────────────────────────┐   ║
║  │  operations_daily_2026-07-02.json                              │   ║
║  │  hr_daily_2026-07-02.json           (future departments)      │   ║
║  │  technology_daily_2026-07-02.json   (future departments)      │   ║
║  └────────────────────────────┬───────────────────────────────────┘   ║
╠════════════════════════════════╪══════════════════════════════════════╣
║  TIER 3: CORPORATE REPORTING  │ READ-ONLY                            ║
║                                ▼                                      ║
║  ┌────────────────────────────────────────────────────────────────┐   ║
║  │  corporate_report_agent                                        │   ║
║  │  Tools: read_kpi_payloads() + generate_executive_email()      │   ║
║  │  Access: ONLY data/kpi_store/ — never user_progress/          │   ║
║  └────────────────────────────────────────────────────────────────┘   ║
╚═══════════════════════════════════════════════════════════════════════╝
```

---

## Directory Structure

```
WisdomAI_MVP/
├── requirements.txt                     ← Python dependencies (fastapi, uvicorn, google-adk)
├── setup.py                             ← Bootstraps .venv, installs deps, runs uvicorn
├── scope_project.md                     ← THIS FILE
├── README.md                            ← Quick-start + architecture overview
├── verify_agents.py                     ← Smoke-test for the ADK root_agent
├── archive/                             ← Archived plans
│
├── frontend/
│   ├── assets/                          ← Static assets (images, icons)
│   ├── js/
│   │   ├── api-client.js               ← WisdomAPI fetch wrapper (same-origin)
│   │   ├── quiz-controller.js          ← Quiz UI flow controller
│   │   └── theme-toggle.js             ← Light/dark mode toggle
│   └── pages/                           ← 15 HTML pages (dashboard, lesson, quiz,
│                                          knowledge-vault, manager-dashboard, …)
│
├── src/
│   ├── api/
│   │   ├── main.py                      ← FastAPI app; mounts static + 7 routers
│   │   └── routes/                      ← pages, progress, learning_path, quiz,
│   │                                       department, knowledge_base, manager
│   │
│   ├── agents/
│   │   ├── agent.py                     ← Root Orchestrator (ADK 2.0 SkillToolset)
│   │   └── hooks.py                     ← LuckEliminationHook (pre-tool-call policy)
│   │
│   ├── core/                            ← Framework-agnostic domain layer
│   │   ├── config.py                    ← Thresholds & state constants
│   │   ├── models.py                    ← Dataclass models (Course, Quiz, KPIPayload…)
│   │   ├── database.py                  ← DepartmentScopedStore + KPIStoreReader (Tier A)
│   │   ├── state_machine.py             ← Adaptive learning states
│   │   ├── luck_elimination.py          ← Luck elimination + HLR memory decay
│   │   └── data_compliance_gate.py      ← GDPR Art. 35 human-approval gate
│   │
│   └── services/                        ← Business logic (also exposed as agent tools)
│       ├── curriculum_service.py        ← Path gen, chunking, remedial (Gemini)
│       ├── quiz_service.py              ← Quiz gen/scoring + 4PL IRT engine
│       ├── routing_service.py           ← Entry-path routing, bypass logic
│       ├── reporting_service.py         ← Tier 1 KPI push + Tier 3 exec email
│       └── user_service.py              ← Progress, readiness, at-risk flagging
│
├── .agents/skills/                      ← Declarative ADK skills (SKILL.md pers. defs)
│   ├── curriculum-builder/ knowledge-coach/ kb-validator/
│   └── department-reporter/ corporate-report-agent/
│
└── data/                                ← Department-namespaced JSON persistence
    ├── knowledge_base/operations/       ← KB docs, raw/, catalog/, gap_cache/
    ├── user_progress/operations/        ← Per-user JSON (dept-scoped)
    ├── learning_paths/operations/       ← Generated learning paths
    ├── quizzes/operations/              ← Active quiz sessions (persisted, v2.2)
    ├── conflicts/operations/            ← KB conflict alerts
    └── kpi_store/                       ← Tier 2 central KPI payloads (boundary)
```

---

## Runtime

```bash
# One-time setup: creates .venv, installs deps, writes .env template
python setup.py

# Run the server (either works):
python setup.py                          # then answer "y" to start
uvicorn src.api.main:app --reload        # direct — serves http://localhost:8000
```

- **App name / entry point:** FastAPI app is `src.api.main:app` (there is no root `server.py`).
- **Model:** `gemini-3.5-flash` for all LLM calls (root agent + remedial generation), via Vertex AI ADC — no API key; configured through `.env` (`GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GOOGLE_GENAI_USE_VERTEXAI=TRUE`).
- **ADK:** google-adk **2.3**. Skills are declarative — each `.agents/skills/<name>/SKILL.md` is loaded via `load_skill_from_dir` and exposed through a `SkillToolset` on `root_agent`; the concrete Python function tools are attached as `additional_tools`.
- **Quiz sessions:** persisted to `data/quizzes/<dept>/` (survive restarts & multiple workers) rather than an in-process dict.

---

## Vertex AI Learning Path — Course Sequence (v1.1)

| # | Course ID | Title | Hours | Status |
|---|-----------|-------|-------|--------|
| 1 | course_01 | Vertex AI Fundamentals | 1.0h | ✅ Completed (emp_001) |
| 2 | course_02 | Vertex AI Studio | 1.5h | ✅ Completed (emp_001) |
| 3 | course_03 | **Gemini API in Vertex AI** | 2.0h | 🔧 Current (emp_001) |
| 4 | course_04 | Retrieval-Augmented Generation (RAG) | 2.0h | 🔒 Locked |
| 5 | course_05 | Vertex AI Vector Search | 2.0h | 🔒 Locked |
| 6 | course_06 | Model Training & Tuning | 2.5h | 🔒 Locked |
| 7 | course_07 | Vertex AI Model Registry | 1.0h | 🔒 Locked |
| 8 | course_08 | Vertex AI Feature Store | 2.0h | 🔒 Locked |
| 9 | course_09 | Model Deployment & Endpoints | 1.5h | 🔒 Locked |
| 10 | course_10 | Vertex AI Pipelines | 2.5h | 🔒 Locked |

**Total:** 18.0 hours | **Completed:** 2.5h (14%) | **Current:** Gemini API (2.0h)

---

## Core Learning & Agent Logic (Ported from v1)

To ensure the adaptive learning system is strictly defined, the following core business logic rules apply:

### 1. State Machine Transitions (`shared/state_machine.py`)
- `ENROLLED` → `FAST_TRACK` | `INTERMEDIATE` | `STANDARD_PATH` (based on profile)
- `STANDARD_PATH` → `COURSE_IN_PROGRESS` → `SHORT_QUIZ` → `VALIDATION_ASSESSMENT`
- `VALIDATION_ASSESSMENT` → `PASSED` (≥80%) | `FAILED`
- `FAILED` + bypass attempt → `BYPASS_LOCKED` → mandatory path (Case 1)
- `FAILED` + standard path → `GAP_REVIEW` → retake allowed (Case 2)
- `GAP_REVIEW` → `METACOGNITIVE_REFLECTION` → `SPACED_REPETITION`

### 2. Luck Elimination Engine (`shared/luck_elimination.py`)
- Tracks failure count per concept tag across quiz attempts.
- If any concept tag fails ≥ `LUCK_FAILURE_THRESHOLD` times → returns `FORCE_MANDATORY_LEARNING_PATH`.
- Otherwise → returns `MAINTAIN_ADAPTIVE_GAP_ASSESSMENT`.

### 3. Adaptive Path Routing (`tools/routing_tools.py`)
- `determine_entry_path(user_id)`: Returns VETERAN / INTERMEDIATE / STANDARD based on competency matrix.
- `handle_assessment_failure(user_id, score, attempt_type)`: Executes Case 1 (bypass lockout) or Case 2 (iterative retake) logic.
- `check_bypass_eligibility(user_id)`: Checks if fast-track is locked/available.

### 4. Sub-Agent Personas
- **Curriculum Builder**: Structured, methodical planner.
- **Knowledge Coach**: Encouraging but rigorous coach, enforces 80% threshold.
- **KB Validator**: Strict auditor, flags conflicts for human review.
- **Department Reporter**: Anonymous data synthesizer, produces schema v1.0 payloads. (Session flushed after each invocation).
- **Corporate Report Agent**: Executive communicator, generates email-ready summaries. (Flags departments with avg_readiness_score < 0.60 as HIGH PRIORITY).

---

## Build Phases

### Phase 1 — Foundation: Shared Logic & Persistence ✅ DONE

Build order: constants → models → persistence → state_machine → luck_elimination

| File | Description | Status |
|------|-------------|--------|
| `shared/constants.py` | Thresholds (80% pass, luck failure ≥2), department config | ✅ Done |
| `shared/models.py` | Pydantic models: Course, LearningPath, Quiz, UserProgress, KPIPayload | ✅ Done |
| `shared/persistence.py` | `DepartmentScopedStore` — dept-scoped read/write for all data | ✅ Done |
| `shared/state_machine.py` | Enum states: ENROLLED → FAST_TRACK/STANDARD → PASSED/FAILED | ✅ Done |
| `shared/luck_elimination.py` | Tracks failure count per concept, forces mandatory path at ≥2 | ✅ Done |

---

### Phase 2 — Tools ✅ DONE

| File | Functions | Status |
|------|-----------|--------|
| `tools/curriculum_tools.py` | `generate_learning_path`, `generate_daily_agenda`, `identify_content_gaps` | ✅ Done |
| `tools/quiz_tools.py` | `generate_quiz`, `evaluate_answers`, `generate_reflection_prompt`, `generate_gap_review` | ✅ Done |
| `tools/progress_tools.py` | `get_user_progress`, `update_progress`, `get_department_readiness`, `flag_at_risk_users` | ✅ Done |
| `tools/routing_tools.py` | `determine_entry_path`, `handle_assessment_failure`, `check_bypass_eligibility` | ✅ Done |
| `tools/reporting_tools.py` | `synthesize_department_kpi` (Tier 1), `read_kpi_payloads` + `generate_executive_email` (Tier 3) | ✅ Done |

---

### Phase 3 — Sub-Agents ✅ DONE

| Agent | Tools | Scope | Status |
|-------|-------|-------|--------|
| Root Orchestrator (`agent.py`) | Routes to sub-agents by intent | Injects `department_id` | ✅ Done |
| `curriculum_builder` | generate_learning_path, daily_agenda, content_gaps | KB read only | ✅ Done |
| `knowledge_coach` | quiz, evaluate, reflection, gap_review, routing tools | user_progress read/write | ✅ Done |
| `kb_validator` | identify_content_gaps | KB read only | ✅ Done |
| `department_reporter` | synthesize_department_kpi | user_progress → kpi_store | ✅ Done |
| `corporate_report_agent` | read_kpi_payloads, generate_executive_email (ONLY 2 tools) | kpi_store read only | ✅ Done |

---

### Phase 4 — Sample Data (Vertex AI) ✅ DONE

| File | Description | Status |
|------|-------------|--------|
| `data/vertex_ai_dtp.json` | 10-course Vertex AI curriculum (v1.1, reordered) | ✅ Done |
| `data/sample_competency_matrix.json` | 5 mock users (veteran, intermediate, standard, locked, mid-stream) | ✅ Done |
| `data/seed_vertex.py` | Seeds KB + user progress from DTP | ✅ Done |
| `data/knowledge_base/operations/` | 10 KB docs (course_03 enriched with multi-paragraph + code examples) | ✅ Done |
| `data/user_progress/operations/emp_001.json` | Mocked: 2 completed, current = course_03 (Gemini API), 20% readiness | ✅ Done |

---

### Phase 5 — FastAPI Server & Frontend Pages ✅ DONE

| Component | Description | Status |
|-----------|-------------|--------|
| `server.py` | 13 API endpoints (progress, learning path, quiz, KB, department) | ✅ Done |
| 9 HTML pages | Dashboard, learning-path, lesson, quiz, quiz-passed, quiz-retake, knowledge-vault, chat, dashboard-chat | ✅ Done |
| `js/api-client.js` | WisdomAPI wrapper for all fetch calls | ✅ Done |
| `js/theme-toggle.js` | Light/dark mode persistence | ✅ Done |

---

### Phase 6 — Vertex AI Frontend Integration ✅ DONE

Dynamic JavaScript injection to wire all frontend pages to the backend API.

| Page | Feature | Status |
|------|---------|--------|
| **Dashboard** | Welcome text: "You're 20% through Vertex AI Engineer Path" | ✅ Done |
| **Dashboard** | Serpentine map: 2 checked, 1 active ("START HERE"), future locked | ✅ Done |
| **Dashboard** | Resume lesson button links to current course | ✅ Done |
| **Learning Path** | Title: "Vertex AI Engineer Path" | ✅ Done |
| **Learning Path** | Dynamic nodes: completed/active/locked rendering | ✅ Done |
| **Learning Path** | Section headers every 3 courses | ✅ Done |
| **Learning Path** | Stats tile: progress %, time invested/remaining | ✅ Done |
| **Lesson** | Dynamic title, breadcrumb, module label | ✅ Done |
| **Lesson** | Content rendered from KB (markdown → HTML conversion) | ✅ Done |
| **Lesson** | Sidebar timeline: completed (struck), current, locked | ✅ Done |
| **Lesson** | Hero card: progress bar, estimated time | ✅ Done |
| **Lesson** | "Start Quiz" button → generates quiz via API → redirects | ✅ Done |
| **Course Order** | DTP reordered: Fundamentals → Studio → Gemini API → RAG → Vector Search → Training → Registry → Feature Store → Deployment → Pipelines | ✅ Done |
| **KB Enrichment** | course_03 (Gemini API) has multi-paragraph content with code examples | ✅ Done |

---

### Phase 7 — File Upload Pipeline & Dynamic Curriculums ❌ TODO

> [!IMPORTANT]
> **Demo Flow:** Upload acts as a manager. The system async-processes the document, applies chunking, generates a baseline learning path AND all quizzes upfront. 

#### 7.1 Async Upload & Idempotency
- **UX:** `POST /api/kb/upload` initiates background processing and returns a `job_id`. UI polls `GET /api/kb/upload/status/{job_id}` showing a progress bar. No blocking timeouts.
- **Duplicate Handling:** If a file exists, UI warns user and asks: "Overwrite" or "Create v2".

#### 7.2 Chunking & Indexing Logic
- Large `.txt` and `.md` files must be split logically (e.g., by Markdown headers `##` or semantic breaks) before being passed to Gemini. This prevents hitting token limits and improves curriculum structure quality.

#### 7.3 Baseline vs. Dynamic Generation
- **Baseline (Upfront):** During upload, the entire Learning Path and all quizzes are generated. This takes time, but it's acceptable because it establishes the unified baseline for the whole team.
- **Dynamic Gap Analysis (On-the-fly):** If an employee fails a final assessment, a personalized dynamic learning path and gap-quizzes are generated for them.
- **Cost-Optimization (Caching):** Dynamic gaps are hashed/stored by topic. If Employee B fails the same topic as Employee A, we distribute the cached dynamic path to Employee B, saving Gemini API costs.

#### 7.4 Data Integrity & Scope Exclusions
- `content_reference` added to Pydantic models will be `Optional`. Existing mock data (`course_01`, etc.) will not break.
- *Deferred:* The Knowledge Vault page will NOT display a list of previously uploaded documents in this MVP (planned for future).
- *Deferred:* Client-side file validation (PDF rejection, size limits) is deferred until GCP migration.

| Component | Change | Status |
|-----------|--------|--------|
| `shared/persistence.py` | `write_raw_document(filename, content)`, collision detection (v2 vs overwrite) | ❌ TODO |
| `shared/models.py` | Add `Optional[str]` `content_reference` to LearningPath/Course/Lesson | ❌ TODO |
| `tools/curriculum_tools.py` | Add header/semantic chunking logic to split large files safely | ❌ TODO |
| `tools/curriculum_tools.py` | Add `trigger_async_curriculum_generation(file_path)` (Background task) | ❌ TODO |
| `tools/quiz_tools.py` | Update `generate_quiz` to run upfront during upload; add caching for dynamic gap quizzes | ❌ TODO |
| `server.py` | `POST /api/kb/upload` (returns job_id), `GET /api/kb/upload/status/{job_id}` | ❌ TODO |
| `knowledge-vault.html` | Drag-drop zone, duplicate warning modal, progress bar polling | ❌ TODO |

---

### Phase 8 — Knowledge Base Vault Catalog UI ✅ DONE

> **Note:** The `archive/catalog_implementation_plan.md` has been implemented successfully. We can now continue with the next step.

| Component | Change | Status |
|-----------|--------|--------|
| `frontend/pages/knowledge-vault.html` | Added tabs, stats, and catalog UI | ✅ Done |
| `frontend/pages/learning-materials.html` | Created page, added file list & existing file generation | ✅ Done |
| `frontend/pages/learning-paths-catalog.html` | Created page, grid of learning paths | ✅ Done |
| `server.py` | Added `/api/kb/catalog/inputs`, `/api/kb/catalog/learning-paths`, `/api/kb/generate-from-input` | ✅ Done |

---

## Tier A Namespace Isolation — Key Guarantees

| What | How |
|------|-----|
| **Data scoping** | Every tool call goes through `DepartmentScopedStore(department_id)`. File paths are always `data/{entity}/{department_id}/...` |
| **Cross-dept prevention** | `DepartmentScopedStore` only constructs paths within its own dept. No API exists to query another department. |
| **Session isolation** | Each department's agents run in a session with `department_id` baked into state. Sub-agents inherit this scope. |
| **Corporate agent boundary** | Has exactly 2 tools. Neither can access `user_progress/`. Schema validation rejects PII. |
| **Future migration** | Swap `DepartmentScopedStore` backend from local JSON → BigQuery/GCS with service accounts. Zero changes to agent code. |

---

## Verification Plan

### Backend State
```bash
# Verify user progress
curl http://localhost:8000/api/user/emp_001/progress
# → Should show 2 completed courses, current_course_id = "course_03" (Gemini API)

# Verify learning path order
curl http://localhost:8000/api/user/emp_001/learning-path
# → Courses array: Fundamentals, Studio, Gemini API, RAG, Vector Search, ...

# Verify KB content
curl http://localhost:8000/api/kb/documents
# → course_03 should have enriched multi-paragraph content
```

### Frontend Verification
1. **Dashboard:** Shows "20% through Vertex AI Engineer Path", serpentine map has 2 checks + 1 active
2. **Learning Path:** Title = "Vertex AI Engineer Path", stats = 20%, nodes rendered dynamically
3. **Lesson:** Load `/lesson?course=course_03` → "Gemini API in Vertex AI" with rich content, sidebar accurate

### Agent Test Scenarios
1. **Curriculum Flow:** "Create a learning path for Vertex AI" → 10-course structured plan
2. **Quiz Flow:** "Quiz me on Gemini API" → multiple choice → scoring → reflection
3. **Adaptive Routing:** Test emp_001 (veteran), emp_002 (intermediate), emp_003 (standard)
4. **Failure Handling:** Fail bypass as emp_004 → lockout to mandatory path
5. **Luck Elimination:** Fail same concept twice → forced to mandatory learning
6. **KB Validation:** Present conflicting DTP → conflict flagged
7. **KPI Push:** "Generate daily report for operations" → anonymized JSON in `data/kpi_store/`
8. **Corporate Report:** "Executive summary" → reads ONLY from kpi_store, produces email
9. **Isolation Test:** Ask corporate agent for emp_001's quiz scores → REFUSAL

### File Upload Verification (Phase 7 — when implemented)
1. **Upload:** Drag `.md`/`.txt` file into Knowledge Vault drop zone
2. **Processing:** Loading overlay blocks interaction until generation completes
3. **Generation:** Learning Path updates with new modules/lessons
4. **Interaction:** Click lesson node → routes to correct content
5. **Assessment:** Click quiz node → contextual questions from uploaded document

---

## Changelog

| Date | Change |
|------|--------|
| 2026-07-17 | **v2.2** — Domain-driven refactor to `src/` package (api/agents/core/services) on google-adk 2.3. Root agent rewired to the ADK 2.0 `SkillToolset` (declarative `.agents/skills/`), broken tool imports fixed, model unified to `gemini-3.5-flash`. Quiz sessions persisted to `data/quizzes/` instead of an in-memory dict. Docs + `setup.py` runner updated to `uvicorn src.api.main:app`. |
| 2026-07-07 | **v2.0** — Consolidated from 3 separate plans into unified document. Switched theme from Capital Cities to Vertex AI. Reordered DTP courses (Gemini API → position 3). Enriched Gemini API KB content. Added Phase 6 (frontend integration) and Phase 7 (file upload pipeline). Archived v1 plans. |
| 2026-07-02 | **v1.0** — Original TEAP plan: 5 agents, 3-tier reporting, Capital Cities theme |
| 2026-07-05 | **v1.1** — File upload extension plan (separate doc, now merged into Phase 7) |
| 2026-07-06 | **v1.2** — Vertex AI frontend integration plan (inline notes, now merged into Phase 6) |
