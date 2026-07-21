# Introduction

WisdomAI (internal codename **TEAP** — Transition Execution AI Platform) is an AI-powered corporate training platform. The core loop:

1. A **manager** uploads training documents (process docs, DTPs) into the Knowledge Vault.
2. The system auto-generates a structured **learning path** (courses → lessons → quizzes) from those documents using Gemini.
3. **Employees** are adaptively coached through the path — an 80% mastery threshold is enforced, lucky guessing is detected and eliminated, and personalized remedial courses are generated when a final assessment is failed.
4. Anonymized metrics roll up to **manager and executive dashboards** through a three-tier, PII-stripped KPI pipeline.

The MVP ships one learning theme (**Vertex AI Engineer**) scoped to a single department (`operations`).

## The three roles

| Role | What they see | Landing page |
|------|---------------|--------------|
| Employee (`individual_contributor`) | Dashboard, learning path, catalog, chat coach, quizzes | `/` |
| Manager | Everything employees see, plus Knowledge Vault, Team Dashboards, learning-path editing | `/manager-dashboard` |
| Developer | Employee pages plus the Agent Console (`/dev-console`) and this Documentation section | `/dev-console` |

## Design principles

- **AI-first, human-in-the-loop only when needed.** Content generation, coaching, remediation, and reporting are automated; humans intervene at defined points (KB conflict resolution, GDPR compliance sign-off, manager review).
- **Modular and department-scoped.** Every read/write goes through a `DepartmentScopedStore` that physically cannot construct a path into another department's data (Tier A namespace isolation). Adding a department means adding a namespace, not new code.
- **Deterministic policy, LLM content.** Decisions (pass/fail, remediation, lockouts) are made by deterministic code with tunable parameters; the LLM only generates *content* (lessons, quizzes, remedial courses, coaching replies). See [Remediation System](/documentation?page=learning-engine/remediation).

## Two entry points, one service layer

- **Web app** — FastAPI (`src.api.main:app`) serving the HTML frontend and JSON API. This is the live product.
- **ADK agent** — `src/agents/agent.py` `root_agent`, a google-adk 2.x orchestrator that routes chat conversations to declarative skills. It is wired into the product through `POST /api/chat` (the Coach page).

Both call the same functions in `src/services/`, so business logic exists exactly once.

## Where to go next

- New to the codebase? Read [Quick Start](/documentation?page=getting-started/quick-start), then [Project Structure](/documentation?page=getting-started/project-structure), then [System Overview](/documentation?page=architecture/system-overview).
- Reviewing the architecture? Start at [System Overview](/documentation?page=architecture/system-overview) and [Data & Persistence](/documentation?page=architecture/data-and-persistence).
- Debugging learning behavior? [Remediation System](/documentation?page=learning-engine/remediation) explains every state transition and threshold.
