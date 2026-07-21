# System Overview

## The big picture

```
Browser (vanilla JS pages)
      │  fetch, same origin
      ▼
FastAPI  src/api/routes/*  ────────►  src/services/*  ────────►  src/core/database.py
      │                                    │                     DepartmentScopedStore
      │  POST /api/chat                    │  LLM content only        │
      ▼                                    ▼                          ▼
ADK root_agent  ◄── SkillToolset ── .agents/skills/*/SKILL.md    data/<store>/operations/*.json
(gemini-3.5-flash)                                               data/kpi_store/ (Tier 2)
```

Two entry points share one service layer:

1. **HTTP routes** (`src/api/routes/`) — every page interaction. Routes are thin: they parse/validate the request, call one or two service functions, and shape the JSON response.
2. **The ADK agent** (`src/agents/agent.py`) — chat coaching via `POST /api/chat`. The agent's function tools *are* the same service functions the routes call, so both paths produce identical state changes.

## Request flow: a typical page

`GET /learning-path` (browser) → `pages.py` serves `frontend/pages/learning-path.html` → the page's inline JS calls `window.WisdomAuth.requireAuth()` → fetches `/api/learning-path/enrolled?user_id=…` → renders cards client-side. There is no server-side templating; every page is a static HTML file plus fetch calls.

## Request flow: a graded quiz (the most important path)

1. Frontend (`quiz-controller.js`) posts answers to `POST /api/quiz/evaluate`.
2. `quiz_service.evaluate_answers` grades deterministically against the stored quiz (correct answers never leave the server), updates the IRT ability estimate, and consults **`remediation_policy.decide_remediation`** — the single decision point that fuses the state machine and the luck-elimination engine.
3. The route acts on the returned `remediation` verdict: persists state changes, spawns a gap review and/or a remedial course *only if the policy says to*.
4. The response carries `remediation.reason`, a human-readable explanation the UI shows the learner.

This is deliberate: **the LLM never decides whether remediation happens** — it only writes the content of the remedial course after deterministic code has decided one is needed. See [Remediation System](/documentation?page=learning-engine/remediation).

## Request flow: chat coaching

1. `POST /api/chat` (`chat.py`) calls `build_root_agent()` **per request** — agent construction is cheap (local file reads only) and this makes Agent Console edits take effect instantly with no restart.
2. The agent is driven through `google.adk.runners.Runner.run_async`.
3. `before_tool_callback=luck_elimination_hook` intercepts every tool call, blocking bypass-related tools for users the policy has locked out.
4. Tools invoked by the model are the same `src/services/` functions the HTTP routes use.

## Three-tier reporting (privacy boundary)

- **Tier A (department)**: raw, PII-bearing progress records, readable only through that department's `DepartmentScopedStore`.
- **Tier 2 (KPI store)**: `reporting_service.synthesize_department_kpi` pushes **PII-stripped**, schema-validated (`validate_kpi_schema`, schema v1.0) aggregate payloads to the central `data/kpi_store/`.
- **Tier 3 (corporate)**: `KPIStoreReader` is read-only over the KPI store and has *no code path* to `user_progress`. The corporate-report agent only ever sees Tier 2 data.

## Live-tunable configuration

Nearly every threshold and prompt is read per-call from `data/dev_config.json` via `src/core/dev_config.py` (`get_param`, `get_logic_param`, `get_config`). The Agent Console (`/dev-console`) edits that file through `PATCH /api/dev/*` endpoints. There is no caching layer, so an edit is live on the next request — this "read every call" philosophy is used consistently instead of restarts or cache invalidation.

## What is deliberately NOT here

- No database server — JSON files behind `DepartmentScopedStore` (GCP migration planned; see [Data & Persistence](/documentation?page=architecture/data-and-persistence)).
- No server-side sessions or token auth — client-trusted role model, demo scope (see [Auth & Roles](/documentation?page=backend/auth-and-roles)).
- No frontend framework or build step — vanilla JS + Tailwind CDN (see [Tech Stack](/documentation?page=architecture/tech-stack)).
