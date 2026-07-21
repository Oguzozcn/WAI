# Project Structure

```
WisdomAI_MVP/
├── src/
│   ├── api/
│   │   ├── main.py              # FastAPI app: static mounts + 11 routers
│   │   └── routes/              # One file per router (see API Reference)
│   │       ├── pages.py         # Serves frontend/pages/*.html at top-level URLs
│   │       ├── auth.py          # POST /api/auth/login
│   │       ├── progress.py      # /api/user/{id}/progress
│   │       ├── learning_path.py # Paths, lessons, enrollment, search
│   │       ├── quiz.py          # Quiz generate/start/evaluate/reflection
│   │       ├── department.py    # Readiness + at-risk aggregates
│   │       ├── knowledge_base.py# KB upload/ingestion/conflicts/path editing
│   │       ├── manager.py       # Team KPIs, reports, Excel export, strategic
│   │       ├── chat.py          # POST /api/chat → ADK agent
│   │       ├── dev_console.py   # /api/dev/* — agent graph + live config editing
│   │       └── docs.py          # /api/docs/* — this documentation system
│   ├── agents/
│   │   ├── agent.py             # build_root_agent(): ADK orchestrator + SkillToolset
│   │   └── hooks.py             # luck_elimination_hook (before_tool_callback)
│   ├── core/                    # Deterministic domain logic, no LLM calls
│   │   ├── config.py            # Platform constants (thresholds, states)
│   │   ├── models.py            # Dataclass schemas (UserProgress, Quiz, KPIPayload…)
│   │   ├── database.py          # DepartmentScopedStore + KPIStoreReader
│   │   ├── state_machine.py     # Learning-journey state transitions
│   │   ├── luck_elimination.py  # Guess detection + HLR memory decay
│   │   ├── remediation_policy.py# THE single decision point after a graded quiz
│   │   ├── dev_config.py        # data/dev_config.json accessors (live-tunable params)
│   │   └── data_compliance_gate.py # GDPR gate: no auto-"passed" without signature
│   └── services/                # Business logic; also registered as agent tools
│       ├── user_service.py      # Progress records, readiness, at-risk flagging
│       ├── quiz_service.py      # Quiz generation/evaluation, IRT, gap review
│       ├── curriculum_service.py# Ingestion, path generation, remedial courses
│       ├── routing_service.py   # Entry-path routing, bypass eligibility
│       ├── reporting_service.py # KPI synthesis, executive email
│       └── llm_client.py        # Gemini client + call_gemini_json helper
├── frontend/
│   ├── pages/                   # One HTML file per page (vanilla JS, Tailwind CDN)
│   ├── js/                      # Shared modules: auth, sidebar, api-client,
│   │                            #   quiz-controller, global-search, markdown
│   └── css/dark-mode.css        # Dark-theme overrides for MD3 token classes
├── .agents/skills/              # 5 declarative agent personas (SKILL.md each)
├── data/                        # Department-scoped JSON stores (see Data & Persistence)
│   ├── credentials.json         # Demo accounts
│   ├── dev_config.json          # Live-editable prompts + parameters
│   ├── user_progress/operations/
│   ├── learning_paths/operations/
│   ├── quizzes/operations/
│   ├── knowledge_base/operations/
│   ├── conflicts/operations/
│   ├── kb_jobs/operations/
│   └── kpi_store/               # Central, PII-stripped KPI payloads (Tier 2)
├── docs/                        # THIS documentation (manifest.json + markdown)
├── tests/
│   ├── unit/                    # Pure-logic tests (state machine, policy, services)
│   ├── integration/             # TestClient route tests with temp data dir
│   └── eval/                    # LLM eval scripts (need ADC; mostly skipped)
├── README.md                    # Short repo landing page
├── ROADMAP.md                   # Authoritative done/planned/idea status tracker
└── scope_project.md             # Original implementation plan + phase history
```

## Layer rules

| Layer | May import from | Never imports from |
|-------|-----------------|--------------------|
| `src/api/routes/` | services, core | frontend (serves it as files) |
| `src/services/` | core, llm_client | api |
| `src/core/` | other core modules only | services, api, agents |
| `src/agents/` | services (as tools), core | api |

`src/core/` is deterministic — it makes no LLM or network calls. All Gemini calls live in `src/services/` and go through `llm_client.call_gemini_json`.

## Where things you'll look for actually live

- **"Where is the pass threshold?"** — `data/dev_config.json` → `platform_params.PASS_THRESHOLD` (live), with code-level defaults in `src/core/config.py`.
- **"Where are prompts?"** — `data/dev_config.json` → `tools.*.prompt_template`, editable in the Agent Console.
- **"Where is a user's state?"** — `data/user_progress/operations/<user_id>.json`.
- **"Why did a learner get a remedial course?"** — `src/core/remediation_policy.py: decide_remediation` returns the reason string that's persisted with the attempt.
