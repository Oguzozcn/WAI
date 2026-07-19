# WisdomAI / TEAP — Roadmap

This is the single authoritative status tracker for the project, built by cross-referencing three sources: the raw planning notes in [`AI_Research/Brain/`](AI_Research/Brain/), the project's own living spec [`scope_project.md`](scope_project.md), and a direct audit of what's actually in `src/`, `.agents/skills/`, and `data/` right now. Where those three disagreed, this document sides with the code — every claim below cites the file/function backing it so you can verify it yourself.

**Status legend:** ✅ Done &nbsp;·&nbsp; 🚧 Built but not exercised &nbsp;·&nbsp; 📋 Planned &nbsp;·&nbsp; 💡 Idea only &nbsp;·&nbsp; 🗑️ Superseded/abandoned

---

## 1. Product Vision

WisdomAI (internally "TEAP" — Transition Execution AI Platform) is an AI-first corporate knowledge-transition platform. A manager uploads training documents (DTPs, process docs); the system generates a structured learning path (courses → lessons → quizzes); employees are adaptively coached through it with an 80% mastery threshold, a "luck elimination" mechanism that prevents guessing to a pass, and personalized remedial courses on failure; progress rolls up through an anonymized, three-tier reporting pipeline to manager and executive dashboards. Design principles from the original brief: minimal human intervention (AI-first, human-in-the-loop only when needed), modular/reusable across departments, and able to run multiple simultaneous "transition waves" with aggregated multi-layer reporting.

*Source: `AI_Research/Brain/Business requirements.txt`, `AI_Research/Brain/brainstorming.md`.*

---

## 2. Core Platform — ✅ Done

These are built, wired up, and running in the live FastAPI app.

- **5-agent architecture as declarative skills.** `.agents/skills/{curriculum-builder, knowledge-coach, kb-validator, department-reporter, corporate-report-agent}/SKILL.md` define the personas; the shared logic they describe lives in `src/services/*.py` and is exposed as ADK function tools via `src/agents/agent.py`'s `SkillToolset`.
- **Tier A namespace isolation.** `src/core/database.py: DepartmentScopedStore` — every path is constructed as `data/<store>/<department_id>/...`; there is no code path that can construct a cross-department path. `KPIStoreReader` gives Tier 3 read-only access with no route to `user_progress`.
- **Adaptive state machine.** `src/core/state_machine.py` — full `ENROLLED → veteran/intermediate/standard → ... → PASSED/FAILED` transition graph, Case 1 (bypass-lockout → full mandatory path) and Case 2 (iterative retake with gap review) both implemented in `handle_assessment_result`.
- **Luck elimination + memory decay.** `src/core/luck_elimination.py` — `LuckEliminationEngine` forces a mandatory path after ≥2 fails on the same concept (`LUCK_FAILURE_THRESHOLD` in `src/core/config.py`); `calculate_hlr_retention` implements a Duolingo-style half-life-regression decay model (`p = 2^(-Δt/h)`).
- **Phase 9 competitive-logic integration** (per `project_documentation2.md`, confirmed live in code):
  - `src/services/quiz_service.py: EnterprisePsychometricEngine` — 4-Parameter Logistic IRT ability estimation (`calculate_item_probability`, `update_learner_ability`).
  - `src/services/routing_service.py: AdaptiveMetacognitiveRouter` — Howell conscious-competence matrix routing (`evaluate_competence`, `get_recommended_path`), replacing the old "wait for 2 fails" rule with same-attempt confidence+accuracy classification.
  - `src/core/data_compliance_gate.py: DataComplianceGate` — blocks automatic transitions to `passed`/`completed`/`authorized` without a human controller signature + DPIA flag, per the GDPR Art. 32(4)/DPD Poland precedent cited in `AI_Research/Brain/WisdomAI Competitive Logic Check.txt`. Wired into `src/services/user_service.py: update_progress`.
- **FastAPI app + frontend.** `src/api/main.py` mounts 7 routers (`pages, progress, learning_path, quiz, department, knowledge_base, manager`); vanilla HTML/CSS/JS frontend, 12 pages served from `frontend/pages/`.
- **ADK 2.0 / SDK hierarchy migration.** Legacy `WAI_agent/` flat layout fully deleted; code lives in `src/core/` (from `WAI_agent/shared/`), `src/agents/`, `src/services/`; confirmed via grep that no functional imports of `WAI_agent` remain. This session also fixed the previously-broken tool imports in `src/agents/agent.py` and standardized the model to `gemini-3.5-flash` everywhere.
- **Quiz session persistence.** `src/core/database.py: write_quiz/read_quiz` — sessions now survive restarts and multi-worker deployments (`data/quizzes/<dept>/`), replacing the earlier in-memory dict (fixed this session).

---

## 3. Built but not exercised — 🚧

This is the most important section. These features exist in code — sometimes matching a "✅ Done" claim in an older doc — but nothing in the running app actually calls them, or there's no data to exercise them with. Each is a real gap between "the code compiles" and "the feature works for a user right now."

- **Quiz generation is a template stub, not LLM-backed.** `src/services/quiz_service.py: generate_quiz` — the code comment literally says *"Generate heuristic/mock questions for the demo"*; options are built from string templates like `"Correct Concept: This is the accurate definition for part 1 of {topic}"`. This directly contradicts the knowledge-coach skill persona and every vision doc, which describe LLM-generated assessments from KB content. The **only** function anywhere in the codebase that calls a live Gemini model is `src/services/curriculum_service.py: generate_remedial_course` (with a full heuristic fallback if the call fails).
- **Learning-path and gap-analysis generation are also heuristic, not LLM-backed.** `src/services/curriculum_service.py: generate_learning_path`, `generate_daily_agenda`, `identify_content_gaps` — all rule-based (length checks, doc counts), no model call.
- **Manager dashboard is code-complete but untestable against current data.** `src/api/routes/manager.py` implements exactly the three buckets `kpi_phase8.md` specced (`team-kpis`, `reports`, `strategic`), each backed by real aggregation logic. But **zero of the 7 seed users in `data/user_progress/operations/` have `manager_id` set** — no seed script populates it — so every manager-dashboard endpoint 404s ("no direct reports found") out of the box.
- **`synthesize_department_kpi` is fully implemented but never triggered.** `src/services/reporting_service.py` — no API route, no scheduled job, no frontend button calls it. `data/kpi_store/` is empty as a result, so the manager "strategic" bucket's department-baseline comparison always falls back to a live recalculation instead of reading a real Tier-2 KPI payload.
- **KB conflict persistence is dead code.** `src/core/database.py: write_conflict` is defined but never called anywhere. The actual `/api/kb/upload` conflict path (`src/api/routes/knowledge_base.py`) builds a contradiction payload inline and returns HTTP 409 — it never writes a `ConflictAlert`, so the "human review queue" the kb-validator skill's persona describes doesn't exist. `data/conflicts/operations/` is empty.
- **The ADK `root_agent` isn't wired into the live product.** `src/agents/agent.py` imports and constructs correctly (verified this session), but no FastAPI route invokes it — the running app calls `src/services/*` directly. The agent is exercised only by the standalone smoke test `verify_agents.py`, which has no assertions (it just checks nothing throws).
- **`LuckEliminationHook` is defined but not attached.** `src/agents/hooks.py` — the hook class exists but `root_agent`'s construction never passes `hooks=[...]`, so it has no effect even when the agent path above is used. It's also built on a local placeholder base class (`PreToolCallDecideHook`), with the real ADK hook import commented out, pending a stable SDK hook API.
- **No real test suite.** `tests/unit/` and `tests/integration/` exist as directories but are completely empty. The only coverage is two manual eval scripts in `tests/eval/` (`check_competitive_logic.py`, `test_gemini_adc_generation.py`) — no tests for API routes, the database layer, or the state machine.

---

## 4. Planned (a doc exists, no code yet) — 📋

- **`scope_project.md`'s own "Phase 7" — file-upload async job/polling UX.** Marked ❌ TODO in that doc: `job_id`-based async processing with UI polling, duplicate-filename overwrite-vs-v2 prompting. **Note:** this is a *different* Phase 7 from `AI_Research/Brain/ingestion_phase7.md`, whose Parse→Validate→Chunk→Save pipeline and custom `recursive_character_splitter` **are** implemented (`src/services/curriculum_service.py`, `src/api/routes/knowledge_base.py`). Two docs use "Phase 7" for two different things — worth renaming one to avoid future confusion.
- **Anti-cheating / rapid-guessing detection (CHIPS / M-CHIPS).** Full reference implementation given in `WisdomAI Competitive Logic Check.txt` (`validate_response_telemetry`, minimum-comprehension-time check); nothing matching this exists in `quiz_service.py`.
- **True spaced repetition (SM-2).** The same doc notes the current HLR decay model isn't SuperMemo-2; SM-2's easiness-factor/interval tracking per concept isn't implemented.
- **LMS/SSO interoperability.** LTI 1.3 Advantage (OAuth2/OIDC, grade passback, roster sync via NRPS), Workday/SAP SuccessFactors/SCORM integration — all idea/plan stage only.
- **Hierarchical Semantic RAG (HiSem-RAG).** Layout-aware chunking with heading-hierarchy context, proposed to replace the current simple recursive-character splitter to reduce hallucination risk.
- **AI Gateway / FinOps governance.** Per-department cost attribution, prompt-cache reuse, cost-based model tiering — proposed, not built.
- **Human Validator role + async conflict-review workflow.** The original `brainstorming.md` design routes KB conflicts to a manager-assigned Human Validator via a Pub/Sub alert and diff log. This conflicts with `ingestion_phase7.md`'s simpler hard-reject-on-upload approach that's actually implemented — see open contradiction #1 below.

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
- **`WAI_agent/` flat directory layout** → fully deleted (`rm -rf`, confirmed via grep of remaining imports); replaced by the `src/` domain-driven layout.
- **Blocking-loading-overlay upload UX** (an early draft plan) → superseded by the async job/polling design in `implementation_plan.md` v2.0 (though note the polling *implementation* itself is still 📋 planned, per section 4).

---

## 7. Out of scope / misfiled

Found in `AI_Research/Brain/` but unrelated to this project — flagged so they don't get mistaken for WisdomAI requirements in a future pass:

- `implementation_plan.txt` — a plan to migrate an unrelated "QuizMaker" app to native macOS/SwiftUI. Not WisdomAI.
- `Antigravity ve Claude Geliştirme Analizi.txt` — comparative research on AI coding agents/IDEs (Antigravity, Claude Code, Codex). Dev-tooling background, not a product requirement.
- `Copilot ve Gemini Kurumsal Karşılaştırması.txt` — general Copilot vs. Gemini Enterprise technical comparison. Background reading only (see section 5).

---

## 8. Open contradictions — need a decision, not silently resolved

1. **KB conflict handling:** current code hard-rejects a conflicting upload outright (HTTP 409, no persistence). The original vision (`brainstorming.md`) instead soft-flags it and routes to a Human Validator for async resolution. These are materially different UX/process — worth deciding which one you actually want long-term before building out section 4's Human Validator workflow.
2. **Rapid-guessing penalty:** `WisdomAI Competitive Logic Check.txt` specifies a punitive CHIPS penalty (`penalty_applied: True`, forced item re-routing); `project_documentation2.md` claims the shipped 4PL engine works "without adversarial rapid-guessing penalties." Neither is currently in code (CHIPS isn't built at all — section 4), but the docs disagree with each other on intent.
3. **Duplicate "Phase 7"/"Phase 8" numbering:** `scope_project.md` and `AI_Research/Brain/{ingestion_phase7,kpi_phase8}.md` use the same phase numbers for different things. Recommend renaming one set (e.g. `scope_project.md`'s Phase 7 → "Phase 7b: Async Upload UX") to stop the collision.

---

*Last built: 2026-07-17, by cross-referencing `AI_Research/Brain/` (16 files), a full audit of `src/`/`.agents/`/`data/`, and `scope_project.md`. Re-run this audit whenever a Brain-dump doc claims something is done — several already didn't match the code.*
