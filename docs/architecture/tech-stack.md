# Tech Stack & Decisions

## Stack at a glance

| Concern | Choice | Where |
|---------|--------|-------|
| API server | FastAPI + uvicorn | `src/api/main.py` |
| Agent framework | google-adk 2.x (`SkillToolset`, `Runner`) | `src/agents/agent.py` |
| LLM | `gemini-3.5-flash` via Vertex AI ADC | `src/services/llm_client.py` |
| Persistence | JSON files, department-namespaced | `src/core/database.py` |
| Frontend | Vanilla HTML/JS, Tailwind Play CDN, Material Symbols | `frontend/` |
| Excel export | openpyxl (in-memory workbook) | `src/api/routes/manager.py` |
| PDF export (docs) | fpdf2 (pure Python) | `src/api/routes/docs.py` |
| Tests | pytest + FastAPI TestClient + httpx | `tests/` |

## Key decisions and their rationale

### JSON files instead of a database

The MVP is a local, single-department demo. `DepartmentScopedStore` gives us the two properties that actually matter now — namespace isolation and human-readable state you can inspect with a text editor — without infra. The store's API (read/write per entity type) is deliberately shaped so a GCP-backed implementation (Firestore/GCS) can replace the file I/O without touching services or routes. **Decision (2026-07): storage stays file-based until the GCP cloud migration; do not introduce a database before then.**

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

```
fastapi>=0.115.0        uvicorn[standard]>=0.30.0   python-multipart>=0.0.9
google-adk              python-dotenv>=1.0.0        openpyxl>=3.1
fpdf2>=2.8              pytest>=7.0                 pytest-asyncio>=0.23
httpx>=0.27
```

Keep this list short on purpose. Anything that needs system binaries (weasyprint, wkhtmltopdf) has been deliberately avoided.
