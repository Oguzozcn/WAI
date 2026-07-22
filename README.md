# WisdomAI — Transition Execution AI Platform (TEAP)

An AI-powered corporate training platform. A manager uploads training documents;
the system auto-generates a structured learning path (courses → lessons → quizzes),
then adaptively coaches employees through it — enforcing an 80% mastery threshold,
eliminating lucky guessing, generating personalized remedial courses on failure, and
rolling anonymized metrics up to manager and executive dashboards.

The MVP ships a **Vertex AI Engineer** learning theme, scoped to a single
`operations` department.

## Quick start

```bash
# 1. Bootstrap: creates .venv, installs deps, writes a .env template
python setup.py

# 2. Configure Google Cloud (Vertex AI via Application Default Credentials)
#    Edit .env:
#      GOOGLE_GENAI_USE_VERTEXAI=TRUE
#      GOOGLE_CLOUD_PROJECT=<your-gcp-project-id>
#      GOOGLE_CLOUD_LOCATION=global
gcloud auth application-default login   # provides ADC — no API key needed

# 3. Run the server
uvicorn src.api.main:app --reload       # → http://localhost:8000
```

Requires Python ≥ 3.11.

## Deploying to the cloud

The app runs offline on plain JSON files by default (`STORAGE=local`). For a
durable Google Cloud deployment (Cloud Run + Firestore + GCS, with company SSO via
IAP), everything is scripted — see **[`RUNBOOK.md`](RUNBOOK.md)**: edit three
variables in `deploy.sh` and run it. No AI assistance needed to follow it.

## Architecture

Two entry points share one service layer:

- **Web app** — FastAPI (`src.api.main:app`) serving the HTML frontend + JSON API. This is the live product.
- **ADK agent** — `src/agents/agent.py` `root_agent`, a google-adk 2.3 orchestrator that routes to declarative skills.

```
frontend/ (HTML + vanilla JS)
      │  fetch (same origin)
      ▼
src/api/routes/  ──►  src/services/  ──►  src/core/database.py (DepartmentScopedStore)
      ▲                                            │  department-namespaced JSON
.agents/skills/*.md  ◄── SkillToolset ── src/agents/agent.py (gemini-3.5-flash)
```

| Layer | Path | Responsibility |
|-------|------|----------------|
| API | `src/api/` | FastAPI app + 7 routers (pages, progress, learning_path, quiz, department, knowledge_base, manager) |
| Agents | `src/agents/` | ADK root orchestrator + policy hooks |
| Core | `src/core/` | config, dataclass models, persistence, state machine, luck elimination, GDPR gate |
| Services | `src/services/` | Business logic — also registered as agent function tools |
| Skills | `.agents/skills/` | Declarative personas (curriculum-builder, knowledge-coach, kb-validator, department-reporter, corporate-report-agent) |
| Data | `data/` | Department-scoped JSON stores |

### Key concepts

- **Tier A namespace isolation** — every read/write goes through `DepartmentScopedStore(department_id)`; a store cannot construct paths into another department's data.
- **Three-tier reporting** — departments push PII-stripped KPI payloads (schema v1.0) to a central `kpi_store`; the corporate agent reads only that.
- **Adaptive learning** — state machine + luck-elimination (fail one concept ≥2× → mandatory path) + 4PL IRT ability estimate + Duolingo-style HLR memory decay.
- **Model** — `gemini-3.5-flash` for all LLM calls, via Vertex AI ADC.

## Development

```bash
uvicorn src.api.main:app --reload   # web app
python verify_agents.py             # smoke-test the ADK root_agent
pytest                              # tests/ (eval + integration + unit)
```

See [`scope_project.md`](scope_project.md) for the full implementation plan and phase history, and [`ROADMAP.md`](ROADMAP.md) for what's actually done vs. planned vs. idea-only.
