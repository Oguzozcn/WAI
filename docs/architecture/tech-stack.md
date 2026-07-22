# Tech Stack & Decisions

## Stack at a glance

| Concern | Choice | Where |
|---------|--------|-------|
| API server | FastAPI + uvicorn | `src/api/main.py` |
| Agent framework | google-adk 2.x (`SkillToolset`, `Runner`) | `src/agents/agent.py` |
| LLM | `gemini-3.5-flash` via Vertex AI ADC | `src/services/llm_client.py` |
| Persistence | Pluggable: JSON files (local) or Firestore + GCS (cloud), department-namespaced | `src/core/database.py`, `src/core/storage_backend.py` |
| Frontend | Vanilla HTML/JS, Tailwind Play CDN, Material Symbols | `frontend/` |
| Auth | bcrypt-hashed credentials; IAP-ready for company SSO | `src/api/routes/auth.py`, `src/core/auth_store.py` |
| Deploy | Docker → Cloud Run (`$PORT`), `deploy.sh` / `cloudbuild.yaml` | `Dockerfile`, `RUNBOOK.md` |
| Excel export | openpyxl (in-memory workbook) | `src/api/routes/manager.py` |
| PDF export (docs) | fpdf2 (pure Python) | `src/api/routes/docs.py` |
| Tests | pytest + FastAPI TestClient + httpx | `tests/` |

## Key decisions and their rationale

### JSON files by default, Firestore + GCS for cloud

The MVP runs as a local, single-department demo on plain JSON files — `DepartmentScopedStore` gives namespace isolation and human-readable state you can inspect with a text editor, no infra required. That store API is the migration seam, and it's now backed by a pluggable backend (`src/core/storage_backend.py`): `STORAGE=local` keeps the file behavior (the default, what tests and offline dev use); `STORAGE=cloud` swaps in Firestore (JSON) + GCS (binary) with **no change to services or routes**. See [Data & Persistence](/documentation?page=architecture/data-and-persistence) for the mapping and `RUNBOOK.md` for deploying. **Decision (2026-07): the cloud backend is opt-in via `STORAGE`; local file mode stays the zero-dependency default so the app is always runnable offline.**

### Vanilla JS instead of a framework

An early Next.js/React concept ("Hybrid Agentic Portal") was explicitly abandoned. Pages are self-contained HTML files with inline scripts, sharing behavior through a handful of `window.*` globals (`WisdomAuth`, `WisdomSidebar`, `WisdomMarkdown`). No build step means every change is refresh-to-see. The cost — some duplication between pages — is accepted for the MVP.

### Tailwind Play CDN + inline config

Each page carries the same `<head>` boilerplate: the anti-flash theme snippet, Google Fonts (Hanken Grotesk / Inter / JetBrains Mono), the Tailwind CDN script, an inline `tailwind.config` with the Material Design 3 color tokens, and `/css/dark-mode.css`. When creating a new page, copy the head from `dev-console.html` and keep the token palette identical.

### Declarative agent skills instead of Python sub-agents

Personas live in `.agents/skills/<name>/SKILL.md` (frontmatter + instruction body) and are loaded fresh on every agent build. Behavior tuning is a text edit in the Agent Console, not a code deploy. The concrete function tools are plain Python functions from `src/services/`, attached via `SkillToolset(additional_tools=…)`.

### Deterministic policy, tunable at runtime

Thresholds (pass mark, luck-failure counts, IRT parameters, readiness weights) live in `data/dev_config.json` and are read on every call — `get_param()` / `get_logic_param()`. Code-level constants in `src/core/config.py` serve as defaults/fallbacks. This keeps demo tuning (e.g. lowering `PASS_THRESHOLD` during a walkthrough) out of the codebase.

### LLM calls: one helper, deterministic fallbacks

All three content-generation call sites (`generate_quiz`, `process_document_to_curriculum`, `generate_remedial_course`) go through `llm_client.call_gemini_json`, which strips markdown fences and enforces a dict result. Every call site has a deterministic fallback (template questions, heuristic sectioning) so the app remains fully demoable with no GCP credentials.

## Dependencies (`requirements.txt`)

Pins are **exact (`==`)** on purpose: the project is developed on a personal laptop and deployed/continued from a different (company) machine + the container, so "works here" must equal "works there." Regenerate with `pip freeze`. Groups: web (fastapi/starlette/uvicorn/pydantic/python-multipart), Google AI (google-adk, google-genai), cloud persistence (google-cloud-firestore, google-cloud-storage), auth (bcrypt, python-dotenv), documents (openpyxl, fpdf2), and test (pytest, pytest-asyncio, httpx).

Anything that needs system binaries (weasyprint, wkhtmltopdf) is still deliberately avoided. The container base is `python:3.12-slim` (see `Dockerfile`); local dev may be on 3.14 — the container is the source of truth for what ships.

## Containerization & deploy

`Dockerfile` builds a non-root `python:3.12-slim` image that runs `uvicorn src.api.main:app --port ${PORT}` (Cloud Run injects `$PORT`). `deploy.sh` is a one-shot, idempotent Cloud Run deploy (provisions Firestore, the GCS bucket, and the credentials secret, then builds + deploys with `STORAGE=cloud`); `cloudbuild.yaml` is the CI equivalent. Full step-by-step lives in `RUNBOOK.md`, written to need no AI assistance to follow.
