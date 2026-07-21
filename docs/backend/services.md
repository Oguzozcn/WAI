# Services Layer

`src/services/` holds all business logic. Each public function doubles as an ADK agent tool (registered in `src/agents/agent.py: _FUNCTION_TOOLS`), so routes and the chat agent share one implementation.

## user_service.py — progress & readiness

- `get_user_progress(user_id, department)` — reads the record and computes summary fields (completion %, state description).
- `update_progress(user_id, event_type, event_data, department)` — the single write path for progress. Handles `course_started`, `course_completed` (dedupe + clears `current_course_id`), `path_enrolled`/`path_assigned`, `bypass_locked`, `state_changed`, `assessment_passed`. Guarded by `DataComplianceGate`: transitions to `passed`/`completed` without a human controller signature + DPIA flag are **blocked and held for approval** (GDPR Art. 32(4) precedent). Ends by calling `_recalculate_readiness`.
- `_recalculate_readiness(progress)` — blended score: course completion (weight 0.5, against `MAX_COURSES`) + quiz performance over the last `quiz_window_size=5` attempts (0.3) + state progress (0.2). `current_state == "passed"` short-circuits to 1.0. Weights live in `logic_params.readiness_scoring`.
- `get_department_readiness`, `flag_at_risk_users` — aggregates for dashboards; at-risk = readiness < `AT_RISK_READINESS_THRESHOLD` (0.6), with `blocked_by` set to the concept with the most failures.

## quiz_service.py — generation, grading, psychometrics

- `EnterprisePsychometricEngine` — 4-parameter-logistic IRT: `calculate_item_probability`, `update_learner_ability` (learning rate / clamp / item defaults all tunable via `logic_params.assessment_scoring`).
- `generate_quiz(...)` — Gemini-backed question generation grounded on KB/lesson content (prompt template `generate_quiz` in dev_config); deterministic `_build_template_question` fallback on LLM failure or empty grounding.
- `evaluate_answers(...)` — grades against the stored quiz session, updates `error_retention_matrix` (every concept tag of every wrong answer) and `mastery_vectors`, runs the IRT update, then calls `decide_remediation` and returns its verdict in `result["remediation"]`. **This is the only place remediation is decided.**
- `generate_reflection_prompt(...)` — Socratic reflection for a wrong answer; prefers the stored `concept_diagnoses` misconception text when available.
- `generate_gap_review(...)` — builds the gap-review payload from flagged concepts; filters out concepts whose HLR retention is still above `hlr_retention_threshold` (0.6) so recently-reviewed material isn't immediately re-surfaced.

## curriculum_service.py — ingestion & content generation

- Upload pipeline: `process_kb_upload_job` → parse/validate → `recursive_character_splitter` → conflict detection (overlap-ratio matching against existing KB) → `process_document_to_curriculum` (Gemini turns sections into courses/lessons) → `_generate_course_quizzes` (pre-generates short quizzes + final assessments).
- `generate_learning_path`, `generate_daily_agenda`, `identify_content_gaps` — heuristic (non-LLM) path assembly and gap analysis.
- `generate_remedial_course(...)` — Gemini-generated targeted course from a learner's wrong answers. Persists per-answer `concept_diagnoses` (root-cause misconceptions). Capped at `remedial_course_cap=2` pending courses per `source_course_id`; a third trigger **merges** new gaps into the most recent pending course and regenerates it instead of stacking a new one.
- `get_pending_remedial_courses(progress, source_course_id)` — shared accessor for the cap check and dashboards.
- Versioning: `_archive_current`, `restore_document_version`, `regenerate_lesson_content`.

## routing_service.py — entry paths & bypass

- `AdaptiveMetacognitiveRouter` — Howell conscious-competence matrix: classifies same-attempt confidence + accuracy against `adaptive_routing` thresholds to recommend a path.
- `determine_user_entry_path(...)` — maps experience level → `fast_track` / `intermediate_choice` / `standard_path`.
- `check_bypass_eligibility(...)` — can this user attempt the validation-assessment bypass? Consults lockout state.
- `handle_user_assessment_failure(...)` — thin wrapper over `decide_remediation` that persists `bypass_locked`/`bypass_attempts` when the policy says `lock_bypass`. Kept for chat-agent flows; contains no decision logic of its own.

## reporting_service.py — KPI pipeline

- `synthesize_department_kpi(...)` — aggregates progress records into a PII-stripped `KPIPayload`, validates against schema v1.0, writes to `data/kpi_store/`.
- `ensure_kpi_payload_for_today(...)` — lazy daily trigger, called from the manager strategic endpoint.
- `read_kpi_payloads(...)` — Tier-3 read (via `KPIStoreReader`).
- `generate_executive_email(...)` — formats an executive summary from KPI payloads (+ `_generate_recommendations`).

## llm_client.py — the only Gemini gateway

- `get_gemini_client()` — Vertex AI client via ADC (env: `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`).
- `call_gemini_json(contents, model=None)` — call → strip markdown fences → `json.loads` → require dict → raise on failure. Every LLM call site uses this and wraps it in its own deterministic fallback. Model defaults to `gemini-3.5-flash`, overridable per-tool in dev_config.

## Conventions when adding a service function

1. Pure business logic; take `department: str = DEFAULT_DEPARTMENT`, construct a `DepartmentScopedStore` inside.
2. Return JSON-serializable dicts (these travel through both HTTP and the agent).
3. If the function should be LLM-callable, add it to `_FUNCTION_TOOLS` in `src/agents/agent.py` — but **never** expose a function that makes a remediation decision (see [Remediation System](/documentation?page=learning-engine/remediation) for why).
4. Read tunables via `get_param`/`get_logic_param` at call time, not import time.
