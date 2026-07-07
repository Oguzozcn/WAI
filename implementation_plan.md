# Transition Execution AI Platform (TEAP) — Final Implementation Plan

## Decisions Lock

| Decision | Answer |
|----------|--------|
| Sub-agents in MVP | All 5: Curriculum Builder, Knowledge Coach, KB Validator, Department Reporter, Corporate Report Agent |
| Department isolation | **Tier A: Namespace Isolation** (department_id path prefixes, future-proofed for GCP service account migration) |
| Persistence | Local JSON files with GCP-compatible schemas (DepartmentScopedStore) |
| Mock data theme | Capital Cities of the World |
| Model | `gemini-3.5-flash` for all agents |
| Reporting architecture | Push & Aggregate (3-tier, strict isolation, KPI schema v1.0) |

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
first_agent/
├── __init__.py                          ← Package init (exists)
├── .env                                 ← Environment config (exists)
├── agent.py                             ← Root Orchestrator (MODIFY)
│
├── sub_agents/
│   ├── __init__.py
│   │
│   ├── curriculum_builder/
│   │   ├── __init__.py
│   │   ├── agent.py                     ← Curriculum sub-agent
│   │   └── prompt.py                    ← System instruction
│   │
│   ├── knowledge_coach/
│   │   ├── __init__.py
│   │   ├── agent.py                     ← Coach sub-agent
│   │   └── prompt.py                    ← System instruction
│   │
│   ├── kb_validator/
│   │   ├── __init__.py
│   │   ├── agent.py                     ← Validator sub-agent
│   │   └── prompt.py                    ← System instruction
│   │
│   ├── department_reporter/
│   │   ├── __init__.py
│   │   ├── agent.py                     ← Dept reporter (Tier 1 PUSH)
│   │   └── prompt.py                    ← System instruction
│   │
│   └── corporate_report_agent/
│       ├── __init__.py
│       ├── agent.py                     ← Corporate agent (Tier 3 AGGREGATE)
│       └── prompt.py                    ← System instruction
│
├── tools/
│   ├── __init__.py
│   ├── curriculum_tools.py              ← Learning path generation
│   ├── quiz_tools.py                    ← Quiz generation & scoring
│   ├── progress_tools.py               ← Readiness tracking
│   ├── routing_tools.py                ← Adaptive path routing
│   └── reporting_tools.py              ← KPI synthesis + executive reports
│
├── shared/
│   ├── __init__.py
│   ├── persistence.py                   ← DepartmentScopedStore (Tier A)
│   ├── state_machine.py                ← Adaptive learning states
│   ├── luck_elimination.py             ← Luck elimination engine
│   ├── models.py                        ← Pydantic data models
│   └── constants.py                     ← Thresholds and config
│
└── data/
    ├── sample_dtp.json                  ← Capital cities DTP
    ├── sample_competency_matrix.json    ← Mock user profiles
    ├── kpi_store/                       ← Tier 2 central KPI payloads
    │   └── .gitkeep
    ├── user_progress/                   ← Per-user JSON (dept-scoped)
    │   └── operations/
    │       └── .gitkeep
    └── knowledge_base/                  ← DTPs per department
        └── operations/
            └── .gitkeep
```

---

## Build Phases (File-by-File)

### Phase 1 — Foundation: Shared Logic & Persistence

Build order: constants → models → persistence → state_machine → luck_elimination

#### [NEW] shared/constants.py
```python
PASS_THRESHOLD = 0.80          # 80% to pass assessments
LUCK_FAILURE_THRESHOLD = 2     # ≥2 failures on same concept → mandatory path
MAX_COURSES = 10               # Standard learning path length
DEPARTMENTS = ["operations"]   # MVP: single department, add more later
DEFAULT_DEPARTMENT = "operations"
SCHEMA_VERSION = "1.0"
```

#### [NEW] shared/models.py
Pydantic models for the entire platform:
- `Course`, `LearningPath`, `DailyAgenda`
- `QuizQuestion`, `Quiz`, `QuizAttempt`
- `UserProgress` (scores, completed modules, gap map, bypass status)
- `KPIPayload` (matches Tier 2 JSON schema v1.0 exactly)
- `ConflictAlert` (KB validation results)
- `ReadinessReport` (individual + team level)

#### [NEW] shared/persistence.py
`DepartmentScopedStore` — every read/write is scoped to `department_id`:
- `read_user_progress(user_id)` → reads from `data/user_progress/{dept}/{user_id}.json`
- `write_user_progress(user_id, data)` → writes to same scoped path
- `read_knowledge_base()` → reads from `data/knowledge_base/{dept}/`
- `write_kpi_payload(date, payload)` → validates schema, writes to `data/kpi_store/{dept}_daily_{date}.json`
- `read_kpi_payloads(date, departments)` → reads from `data/kpi_store/` (used by corporate agent only)

Cross-department access raises `IsolationViolationError`. Interface stays identical when swapping backend to BigQuery/GCS later.

#### [NEW] shared/state_machine.py
Enum-based state transitions:
- `ENROLLED` → `FAST_TRACK` | `INTERMEDIATE` | `STANDARD_PATH` (based on profile)
- `STANDARD_PATH` → `COURSE_IN_PROGRESS` → `SHORT_QUIZ` → `VALIDATION_ASSESSMENT`
- `VALIDATION_ASSESSMENT` → `PASSED` (≥80%) | `FAILED`
- `FAILED` + bypass attempt → `BYPASS_LOCKED` → mandatory path (Case 1)
- `FAILED` + standard path → `GAP_REVIEW` → retake allowed (Case 2)
- `GAP_REVIEW` → `METACOGNITIVE_REFLECTION` → `SPACED_REPETITION`

#### [NEW] shared/luck_elimination.py
`LuckEliminationEngine`:
- Tracks failure count per concept tag across quiz attempts
- If any concept tag fails ≥ `LUCK_FAILURE_THRESHOLD` times → returns `FORCE_MANDATORY_LEARNING_PATH`
- Otherwise → returns `MAINTAIN_ADAPTIVE_GAP_ASSESSMENT`

---

### Phase 2 — Tools

#### [NEW] tools/curriculum_tools.py
Function tools for the Curriculum Builder agent:
- `generate_learning_path(role, department, timeframe_weeks)` — reads DTPs from dept-scoped knowledge base, returns structured 10-course plan
- `generate_daily_agenda(learning_path_id, day_number)` — returns day-specific training agenda
- `identify_content_gaps(document_content)` — scans for missing/unclear content in DTPs

#### [NEW] tools/quiz_tools.py
Function tools for the Knowledge Coach agent:
- `generate_quiz(topic, difficulty, question_count)` — creates multiple-choice and scenario-based questions from knowledge base content
- `evaluate_answers(quiz_id, user_answers)` — scores responses, returns pass/fail + error retention matrix
- `generate_reflection_prompt(failed_question_id)` — metacognitive open-text prompt ("Why did you fail?")
- `generate_gap_review(user_id)` — Duolingo-style spaced repetition exercises targeting persistent gaps

#### [NEW] tools/progress_tools.py
Function tools for readiness tracking:
- `get_user_progress(user_id)` — reads dept-scoped progress (via DepartmentScopedStore)
- `update_progress(user_id, event_type, event_data)` — records completions, scores, failures
- `get_department_readiness(department)` — aggregated team readiness
- `flag_at_risk_users(department)` — identifies individuals below 80% threshold

#### [NEW] tools/routing_tools.py
Function tools for adaptive path routing:
- `determine_entry_path(user_id)` — returns VETERAN/INTERMEDIATE/STANDARD based on competency matrix
- `handle_assessment_failure(user_id, score, attempt_type)` — executes Case 1 (bypass lockout) or Case 2 (iterative retake) logic
- `check_bypass_eligibility(user_id)` — checks if fast-track is locked/available

#### [NEW] tools/reporting_tools.py
Function tools split across two tiers:

**For Department Reporter (Tier 1 — PUSH):**
- `synthesize_department_kpi(department, date)` — reads all user progress in dept scope, strips PII, validates against schema v1.0, writes to `data/kpi_store/`

**For Corporate Report Agent (Tier 3 — AGGREGATE):**
- `read_kpi_payloads(date, departments)` — reads from `data/kpi_store/` only (read-only)
- `generate_executive_email(kpi_data, period)` — formats cross-department executive email

---

### Phase 3 — Sub-Agents

#### [MODIFY] agent.py
Root Orchestrator — routes to sub-agents based on intent:
- "Create a learning path" → `curriculum_builder`
- "Take a quiz" / "I want to be assessed" → `knowledge_coach`
- "Validate this document" / "Check for conflicts" → `kb_validator`
- "Generate daily report" → `department_reporter`
- "Executive summary" / "Corporate report" → `corporate_report_agent`

Injects `department_id` into session state for all Tier 1 agents.

#### [NEW] sub_agents/curriculum_builder/agent.py + prompt.py
- Tools: `generate_learning_path`, `generate_daily_agenda`, `identify_content_gaps`
- Scope: reads from `data/knowledge_base/{dept}/`
- Persona: structured, methodical planner

#### [NEW] sub_agents/knowledge_coach/agent.py + prompt.py
- Tools: `generate_quiz`, `evaluate_answers`, `generate_reflection_prompt`, `generate_gap_review`, `determine_entry_path`, `handle_assessment_failure`, `check_bypass_eligibility`, `get_user_progress`, `update_progress`
- Scope: reads/writes `data/user_progress/{dept}/`
- Persona: encouraging but rigorous coach, enforces 80% threshold

#### [NEW] sub_agents/kb_validator/agent.py + prompt.py
- Tools: `identify_content_gaps` (reused from curriculum_tools)
- Scope: reads from `data/knowledge_base/{dept}/`
- Persona: strict auditor, flags conflicts for human review

#### [NEW] sub_agents/department_reporter/agent.py + prompt.py
- Tools: `synthesize_department_kpi`
- Scope: reads user_progress/{dept}/, writes to kpi_store/
- Persona: anonymous data synthesizer, produces schema v1.0 payloads
- **Session flushed after each invocation** — no persistent memory

#### [NEW] sub_agents/corporate_report_agent/agent.py + prompt.py
- Tools: `read_kpi_payloads`, `generate_executive_email` (ONLY these 2)
- Scope: reads ONLY from `data/kpi_store/` — **ZERO access to user_progress/ or agent sessions**
- Persona: executive communicator, generates email-ready summaries
- Flags departments with `avg_readiness_score < 0.60` as HIGH PRIORITY

---

### Phase 4 — Sample Data (Capital Cities)

#### [NEW] data/sample_dtp.json
Desktop Procedure: "Capital Cities of the World" training manual
- 10 courses: Europe, Asia, Americas, Africa, Oceania, Middle East, Edge Cases (multiple capitals), Historical Capitals, Capital City Geography, Final Comprehensive Review
- Each course has 5-8 knowledge items (e.g., "France → Paris", "South Africa → Pretoria/Bloemfontein/Cape Town")

#### [NEW] data/sample_competency_matrix.json
5 mock users in "operations" department:
- `emp_001`: Veteran (Geography professor) → should route to fast-track
- `emp_002`: Intermediate (traveled extensively) → choice of gap rerun or test
- `emp_003`: Standard (new to geography) → full 10-course path
- `emp_004`: Standard (failed bypass attempt) → locked, mandatory path
- `emp_005`: Standard (in progress, Course 6/10) → mid-stream learner

#### [NEW] data/knowledge_base/operations/ (populated with sample DTP content)

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

### Automated
```bash
cd /Users/ozzy/Desktop/WAI && adk web
```
Verify all agents load and the web UI shows the root orchestrator with all 5 sub-agents available.

### Manual Test Scenarios

1. **Curriculum Flow:** "Create a learning path for a new joiner about world capitals" → 10-course structured plan returned
2. **Quiz Flow:** "Quiz me on European capitals" → multiple choice → scoring → reflection on wrong answers
3. **Adaptive Routing:** Test all 3 entry paths with emp_001 (veteran), emp_002 (intermediate), emp_003 (standard)
4. **Failure Handling:** Fail a bypass assessment as emp_004 → verify lockout to mandatory path (Case 1)
5. **Luck Elimination:** Fail same concept twice → verify forced to mandatory learning
6. **KB Validation:** Present conflicting DTP ("Myanmar capital: Yangon vs Naypyidaw") → conflict flagged
7. **KPI Push:** "Generate daily report for operations" → verify anonymized JSON in `data/kpi_store/`
8. **Corporate Report:** "Give me an executive summary" → verify it reads ONLY from kpi_store, produces email draft
9. **Isolation Test:** Ask corporate agent "Show me emp_001's quiz scores" → verify REFUSAL
