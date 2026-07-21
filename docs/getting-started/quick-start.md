# Quick Start

## Prerequisites

- Python ≥ 3.11 (the checked-in `.venv` uses 3.14)
- A Google Cloud project with Vertex AI enabled (for live LLM calls; the app degrades to deterministic fallbacks without it)

## Setup and run

```bash
# 1. Bootstrap: creates .venv, installs deps, writes a .env template
python setup.py

# 2. Configure Google Cloud (Vertex AI via Application Default Credentials)
#    Edit .env:
#      GOOGLE_GENAI_USE_VERTEXAI=TRUE
#      GOOGLE_CLOUD_PROJECT=<your-gcp-project-id>
#      GOOGLE_CLOUD_LOCATION=global
gcloud auth application-default login   # ADC — no API key needed

# 3. Run the server
uvicorn src.api.main:app --reload       # → http://localhost:8000
```

## Seeded demo accounts

Credentials live in `data/credentials.json` (plaintext — demo only, see [Known Limitations](/documentation?page=operations/limitations)).

| User ID | Password | Display name | Role |
|---------|----------|--------------|------|
| `manager` | `manager123` | Jordan Lee | Manager |
| `emp_001` | `alex123` | Alex Chen | Employee |
| `emp_002` | `maria123` | Maria Santos | Employee |
| `emp_003` | `james123` | James Wilson | Employee |
| `emp_004` | `priya123` | Priya Patel | Employee |
| `emp_005` | `david123` | David Kim | Employee |
| `developer` | `dev123` | Sam Rivera | Developer |

All employees report to `manager` (their `manager_id` field in `data/user_progress/operations/`).

## Key URLs

| URL | What it is |
|-----|------------|
| `http://localhost:8000/` | Employee dashboard (login first at `/login`) |
| `http://localhost:8000/manager-dashboard` | Manager team view |
| `http://localhost:8000/dev-console` | Agent Console (developer role) |
| `http://localhost:8000/documentation` | This documentation (developer role) |
| `http://localhost:8000/docs` | FastAPI auto-generated Swagger UI (all API endpoints) |

## Running tests

```bash
python3 -m pytest tests/ -q        # full suite: unit + integration (+ eval, mostly skipped without ADC)
python3 -m pytest tests/unit -q    # fast, no server needed
python verify_agents.py            # smoke-test the ADK root_agent builds
```

Tests use FastAPI's `TestClient` and a temporary data directory (see `tests/conftest.py`), so they never touch your real `data/` files.

## A five-minute product tour

1. Log in as `manager` → Knowledge Vault → upload a text document → watch the async ingestion job produce a draft learning path.
2. Learning Paths → publish the draft.
3. Log out, log in as `emp_005` → Catalog → enroll in the path → open a lesson → take the short quiz.
4. Fail a final assessment on purpose (score < 80%) → observe the gap-review banner and remedial course appear on the dashboard ("TARGETED REVIEW" badge).
5. Log in as `manager` → Team Dashboards → see the readiness scores and the Excel export.
6. Log in as `developer` → Agent Console → edit a prompt template → changes apply on the next LLM call, no restart.
