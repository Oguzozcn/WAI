# WisdomAI / TEAP — Roadmap

This is the single authoritative status tracker for the project, built by cross-referencing three sources: the raw planning notes in [`AI_Research/Brain/`](AI_Research/Brain/), the project's own living spec [`scope_project.md`](scope_project.md), and a direct audit of what's actually in `src/`, `.agents/skills/`, `tests/`, and `data/` right now. Where those three disagreed, this document sides with the code — every claim below cites the file/function backing it so you can verify it yourself.

**Status legend:** ✅ Done &nbsp;·&nbsp; 🚧 Built but not exercised &nbsp;·&nbsp; 📋 Planned &nbsp;·&nbsp; 💡 Idea only &nbsp;·&nbsp; 🗑️ Superseded/abandoned

---

## 1. Product Vision

WisdomAI (internally "TEAP" — Transition Execution AI Platform) is an AI-first corporate knowledge-transition platform. A manager uploads training documents (DTPs, process docs); the system generates a structured learning path (courses → lessons → quizzes); employees are adaptively coached through it with an 80% mastery threshold, a "luck elimination" mechanism that prevents guessing to a pass, and personalized remedial courses on failure; progress rolls up through an anonymized, three-tier reporting pipeline to manager and executive dashboards. Design principles from the original brief: minimal human intervention (AI-first, human-in-the-loop only when needed), modular/reusable across departments, and able to run multiple simultaneous "transition waves" with aggregated multi-layer reporting.

*Source: `AI_Research/Brain/Business requirements.txt`, `AI_Research/Brain/brainstorming.md`.*

---

## 2. Core Platform — ✅ Done

These are built, wired up, and running in the live FastAPI app.

- **5-agent architecture as declarative skills.** `.agents/skills/{curriculum-builder, knowledge-coach, kb-validator, department-reporter, corporate-report-agent}/SKILL.md` define the personas; the shared logic they describe lives in `src/services/*.py` and is exposed as ADK function tools via `src/agents/agent.py`'s `SkillToolset`.
- **`root_agent` is wired into the live product**, not just a standalone construct. `src/api/routes/chat.py`'s `POST /api/chat` calls `build_root_agent()` and drives it through `google.adk.runners.Runner`/`run_async` — this is a real, exercised request path, not dead scaffolding.
- **`LuckEliminationHook` is attached.** `src/agents/agent.py:139` passes `before_tool_callback=luck_elimination_hook` into the live `Agent(...)` construction — confirmed via direct import, the hook fires on every tool call, not just defined-and-unused.
- **Quiz generation is LLM-backed**, grounded on real KB content. `src/services/quiz_service.py`'s `generate_quiz` calls Gemini using the `generate_quiz` prompt template (editable live via the Agent Console, `src/core/dev_config.py`); the heuristic `_build_template_question` path only fires as a fallback on empty grounding or an LLM failure — it's a safety net, not the primary path.
- **Document ingestion and remedial-course generation are also LLM-backed.** `src/services/curriculum_service.py`: `process_document_to_curriculum` (turns document sections into teaching material) and `generate_remedial_course` (targeted lesson + quiz from a learner's wrong answers) both call Gemini directly — 3 real LLM call sites platform-wide (`generate_quiz`, `process_document_to_curriculum`, `generate_remedial_course`), all with developer-editable prompts.
- **Tier A namespace isolation.** `src/core/database.py: DepartmentScopedStore` — every path is constructed as `data/<store>/<department_id>/...`; there is no code path that can construct a cross-department path. `KPIStoreReader` gives Tier 3 read-only access with no route to `user_progress`.
- **Adaptive state machine.** `src/core/state_machine.py` — full `ENROLLED → veteran/intermediate/standard → ... → PASSED/FAILED` transition graph, Case 1 (bypass-lockout → full mandatory path) and Case 2 (iterative retake with gap review) both implemented in `handle_assessment_result`.
- **Luck elimination + memory decay.** `src/core/luck_elimination.py` — `LuckEliminationEngine` forces a mandatory path after enough fails on the same concept (`core_drift_concept_count`, developer-tunable via the Agent Console); `calculate_hlr_retention` implements a Duolingo-style half-life-regression decay model (`p = 2^(-Δt/h)`) — noted as defined-but-uncalled in the reporting path, see section 3.
- **Phase 9 competitive-logic integration** (per `project_documentation2.md`, confirmed live in code):
  - `src/services/quiz_service.py: EnterprisePsychometricEngine` — 4-Parameter Logistic IRT ability estimation (`calculate_item_probability`, `update_learner_ability`), with learning-rate/clamp/item-default parameters developer-tunable via the Agent Console's logic-params panels.
  - `src/services/routing_service.py: AdaptiveMetacognitiveRouter` — Howell conscious-competence matrix routing (`evaluate_competence`, `get_recommended_path`), replacing the old "wait for N fails" rule with same-attempt confidence+accuracy classification.
  - `src/core/data_compliance_gate.py: DataComplianceGate` — blocks automatic transitions to `passed`/`completed`/`authorized` without a human controller signature + DPIA flag, per the GDPR Art. 32(4)/DPD Poland precedent cited in `AI_Research/Brain/WisdomAI Competitive Logic Check.txt`. Wired into `src/services/user_service.py: update_progress`.
- **KB conflict detection has a real, end-to-end async review workflow** — resolves what was previously an open contradiction (see section 8). `write_conflict` (`src/core/database.py:571`) is called from both the upload path (`curriculum_service.py:388`) and the resolution path (`knowledge_base.py:184,190`); conflicts persist with `status: "pending"`, are listed via `GET /api/kb/conflicts`, and resolved via `POST /api/kb/conflicts/{id}/resolve` (approve/reject + `resolved_by`). No hard-reject-on-upload path remains anywhere in the codebase.
- **`synthesize_department_kpi` is triggered, not just defined.** Called lazily via `ensure_kpi_payload_for_today()` from the manager dashboard's `GET /api/manager/{manager_id}/strategic` route, and separately exposed as an agent tool. Real payloads now exist in `data/kpi_store/` (e.g. `operations_daily_2026-07-19.json`) — the strategic-benchmarking bucket has actually read a stored baseline, not only the live-recalculation fallback.
- **Manager dashboard** (`src/api/routes/manager.py`) implements the three specced buckets (`team-kpis`, `reports`, `strategic`) plus a new formatted-Excel export (`/reports/export`, `openpyxl`-backed). All read/write course-completion math routes through the developer-tunable `MAX_COURSES` param (fixed a hardcoded-`/10` drift bug across all three buckets this session).
- **Agent Console** (`/dev-console`, developer-role-only) — live editing of the orchestrator routing instruction, all 5 skill personas, the 3 Gemini prompt templates, 10 platform parameters, and ~20 fine-grained deterministic-logic parameters (IRT scoring, readiness-score weights, luck-elimination thresholds, adaptive-routing cut-points, curriculum-generation counts), all self-healing/read-every-call, no deploy needed.
- **A real test suite exists** — this reverses the previous "tests/ is empty" finding. `tests/unit/` (`test_luck_elimination_hook.py`, `test_llm_generation.py`, `test_ingestion.py`) and `tests/integration/` (`test_manager_routes.py`, `test_kb_routes.py`, `test_chat_route.py`) both have real test files, plus `tests/eval/` and `tests/conftest.py`. **Caveat:** existence isn't the same as comprehensive coverage — nobody has audited *what* these tests actually assert or how much of the codebase they touch. Worth a dedicated coverage pass before leaning on them as a full regression safety net.
- **FastAPI app + frontend.** `src/api/main.py` mounts routers (`pages, progress, learning_path, quiz, department, knowledge_base, manager, chat, dev_console, auth`); vanilla HTML/CSS/JS frontend, 13+ pages served from `frontend/pages/`.
- **ADK 2.0 / SDK hierarchy migration.** Legacy `WAI_agent/` flat layout fully deleted; code lives in `src/core/`, `src/agents/`, `src/services/`; standardized on `gemini-3.5-flash` as the default model, developer-overridable per-tool.
- **Quiz session persistence.** `src/core/database.py: write_quiz/read_quiz` — sessions survive restarts and multi-worker deployments (`data/quizzes/<dept>/`).

---

## 3. Built but not exercised — 🚧

Narrower than before — most of this section moved to "Done" in the 2026-07-19 re-audit. What's left is real.

- **Learning-path and gap-analysis generation are still heuristic, not LLM-backed.** `src/services/curriculum_service.py`: `generate_learning_path`, `generate_daily_agenda`, `identify_content_gaps` — all rule-based (length checks, doc counts, overlap-ratio matching), no model call. Unlike the roadmap's previous claim, this is *not* true of the whole file anymore — `process_document_to_curriculum` and `generate_remedial_course` in the same file are LLM-backed (see section 2). If LLM-backing these three is still a goal, scope it as its own item rather than assuming the whole file is heuristic.
- **Manager dashboard seed data only covers 2 of 7 employees.** `data/user_progress/operations/`: `emp_001.json` and `emp_002.json` have `manager_id="manager"` set; `emp_003`, `emp_004`, `emp_005`, `manager.json`, and `test_user_001.json` all have `manager_id=""`. The manager dashboard works end-to-end for the one populated manager, but 5 of 7 seed employees are invisible to any manager view — worth a real seed script if UAT needs to exercise more than one manager or a larger team.
- **KB conflict workflow is wired but currently has nothing to review.** `data/conflicts/operations/` is empty in the current data snapshot — the code path exists and is called correctly, there's just no pending conflict right now to exercise it end-to-end. Needs a deliberate test upload that actually collides with existing KB content to verify the full flag → list → resolve loop live.
- **`calculate_hlr_retention` (spaced-repetition decay) is defined but not called from the live progression path** — noted in `src/core/luck_elimination.py`; `evaluate_user_progression` doesn't invoke it. Not re-verified in the 2026-07-19 audit beyond a static read; worth confirming directly if spaced repetition matters for the next milestone.

---

## 4. Planned (a doc exists, no code yet) — 📋

*Not re-verified in the 2026-07-19 audit — carried forward from the prior pass. Re-check before relying on this section.*

- **`scope_project.md`'s own "Phase 7" — file-upload async job/polling UX.** Marked ❌ TODO in that doc: `job_id`-based async processing with UI polling, duplicate-filename overwrite-vs-v2 prompting. **Note:** this is a *different* Phase 7 from `AI_Research/Brain/ingestion_phase7.md`, whose Parse→Validate→Chunk→Save pipeline **is** implemented. Two docs use "Phase 7" for two different things — see open item #2 below.
- **Anti-cheating / rapid-guessing detection (CHIPS / M-CHIPS).** Full reference implementation given in `WisdomAI Competitive Logic Check.txt` (`validate_response_telemetry`, minimum-comprehension-time check); nothing matching this was found in `quiz_service.py` as of the last full read.
- **True spaced repetition (SM-2).** The current HLR decay model isn't SuperMemo-2; SM-2's easiness-factor/interval tracking per concept isn't implemented.
- **LMS/SSO interoperability.** LTI 1.3 Advantage (OAuth2/OIDC, grade passback, roster sync via NRPS), Workday/SAP SuccessFactors/SCORM integration — all idea/plan stage only.
- **Hierarchical Semantic RAG (HiSem-RAG).** Layout-aware chunking with heading-hierarchy context, proposed to replace the current simple recursive-character splitter to reduce hallucination risk.
- **AI Gateway / FinOps governance.** Per-department cost attribution, prompt-cache reuse, cost-based model tiering — proposed, not built. (Partial groundwork now exists: the Agent Console lets you set a different Gemini model per tool, which is the mechanism cost-based tiering would build on.)
- **Human Validator role + async conflict-review workflow.** Superseded — see section 2 and the resolved contradiction in section 8. The simpler soft-flag + any-authorized-reviewer model is what's actually implemented, not a manager-assigned Human Validator with Pub/Sub alerting.

---

## 5. Idea-only / exploratory — 💡

Brainstormed, never turned into an implementation plan:

- Hub-and-spoke multi-tenant model — per-department GCS ingest + Vertex AI Search data store + isolated service account, with a full RBAC matrix (Employee / Human Validator / Manager).
- Model Armor-style prompt-injection and PII-egress policies.
- Session-level "employee can't query another employee's records" guardrail.
- Live-document grounding research (`Copilot ve Gemini Kurumsal Karşılaştırması.txt`) — background reading on how Copilot/Gemini Enterprise ground answers in shared drives; no derived WisdomAI requirement yet.

---

## 6. Superseded / abandoned — 🗑️

- **Capital Cities demo theme** → replaced by the current Vertex AI Engineer theme (per `implementation_plan.md`'s v2.0 changelog entry).
- **Hybrid Agentic Portal** (Next.js/React + Google Stitch + Gemini Enterprise chat sidebar), described in `brainstorming.md` → never adopted; the real build is vanilla HTML/CSS/JS with no framework.
- **`WAI_agent/` flat directory layout** → fully deleted; replaced by the `src/` domain-driven layout.
- **Blocking-loading-overlay upload UX** (an early draft plan) → superseded by the async job/polling design in `implementation_plan.md` v2.0 (the polling *implementation* itself is still 📋 planned, per section 4).
- **Manager-assigned Human Validator conflict workflow** → superseded by the simpler soft-flag + any-authorized-reviewer model that's actually implemented (see section 2, section 8).

---

## 7. Out of scope / misfiled

Found in `AI_Research/Brain/` but unrelated to this project — flagged so they don't get mistaken for WisdomAI requirements in a future pass:

- `implementation_plan.txt` — a plan to migrate an unrelated "QuizMaker" app to native macOS/SwiftUI. Not WisdomAI.
- `Antigravity ve Claude Geliştirme Analizi.txt` — comparative research on AI coding agents/IDEs (Antigravity, Claude Code, Codex). Dev-tooling background, not a product requirement.
- `Copilot ve Gemini Kurumsal Karşılaştırması.txt` — general Copilot vs. Gemini Enterprise technical comparison. Background reading only (see section 5).

---

## 8. Open items — need a decision, not silently resolved

1. ~~**KB conflict handling:** hard-reject vs. soft-flag+Human-Validator~~ — **RESOLVED as of 2026-07-19.** The soft-flag + async any-authorized-reviewer workflow is fully implemented (section 2); no hard-reject path remains in code. No further decision needed here.
2. **Rapid-guessing penalty:** `WisdomAI Competitive Logic Check.txt` specifies a punitive CHIPS penalty (`penalty_applied: True`, forced item re-routing); `project_documentation2.md` claims the shipped 4PL engine works "without adversarial rapid-guessing penalties." Neither is currently in code (CHIPS isn't built at all — section 4), but the docs disagree with each other on intent. *Not re-verified 2026-07-19.*
3. **Duplicate "Phase 7"/"Phase 8" numbering:** `scope_project.md` and `AI_Research/Brain/{ingestion_phase7,kpi_phase8}.md` use the same phase numbers for different things. Recommend renaming one set (e.g. `scope_project.md`'s Phase 7 → "Phase 7b: Async Upload UX") to stop the collision. *Not re-verified 2026-07-19.*

---

## 9. Recommended next steps (as of 2026-07-19)

Given how much of section 3 turned out to already be done, the platform is closer to UAT-ready than the prior version of this document suggested. Before a full human UAT pass, in priority order:

1. **Seed the remaining 5 employees with a `manager_id`** (section 3) — otherwise any UAT tester other than "manager" sees an empty/404 dashboard, which will read as a bug rather than a data gap.
2. **Manually trigger one real KB conflict** (section 3) to verify the flag → list → resolve loop works end-to-end with live data, not just by code inspection.
3. **Spot-check what the existing tests actually assert** (section 2's caveat) — a coverage pass, not a full suite build-out, since the suite already exists.
4. *Then* run UAT — at that point it's testing real gaps, not rediscovering known ones.

---

*Last built: 2026-07-17. Re-audited 2026-07-19 against a live re-verification of every "Built but not exercised" and "Open contradiction" claim (see section 3, 8) — most items moved to Done. Re-run this audit whenever a claim here starts to feel stale; several already didn't match the code twice now.*
