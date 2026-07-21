# Known Limitations

Every item here is a **conscious demo-scope decision**, documented so nobody mistakes it for an oversight — and so the GCP migration has a ready checklist. Before "fixing" anything on this list, read the linked pages; several of these are load-bearing simplifications.

## Security (all by design for local demo — see [Auth & Roles](/documentation?page=backend/auth-and-roles))

| Limitation | Detail | Production fix |
|------------|--------|----------------|
| Plaintext credentials | `data/credentials.json`, string comparison | SSO / Identity Platform; no local passwords |
| Client-trusted roles | `role` supplied by the client in query/body; `_require_*` guards are cooperative | Server-derived identity + authz middleware |
| No server-side sessions | `sessionStorage` only; any request is anonymous to the server | Signed tokens / IAP |
| Page routes unauthenticated | HTML is served to anyone; data is gated client-side | Middleware on page routes too |

## Storage & scale

- **JSON files, whole-file rewrites, no locking held during writes** — fine single-worker, unsafe multi-worker. The `DepartmentScopedStore` API is the migration seam to Firestore/GCS. **Decision (July 2026): no database until the GCP migration.**
- Single department (`operations`) seeded; the isolation architecture supports more, but nothing else is seeded or themed.
- No pagination on list endpoints — acceptable at demo data volumes.

## Learning engine

- `generate_learning_path` / `generate_daily_agenda` / `identify_content_gaps` are heuristic, not LLM-backed (roadmap item).
- Spaced repetition uses HLR decay for *filtering*, not full SM-2 scheduling (no easiness factors / interval queues).
- Rapid-guessing telemetry (CHIPS minimum-comprehension-time) not implemented; the two source docs also disagree on whether it should be punitive — see ROADMAP.md open item #2.
- Bypass attempts are chat-only by design — the quiz UI deliberately has no bypass affordance.

## Frontend

- Tailwind Play CDN + Google Fonts require internet even for local use.
- Head boilerplate (tailwind config) is duplicated per page — no build step to deduplicate it.
- Chat renders replies as plain text (no markdown), so LLM formatting shows literally.
- Two legacy mini-markdown renderers (lesson, edit-learning-path) predate `markdown.js` and support less syntax.

## Operational

- No structured logging/observability beyond uvicorn access logs.
- LLM failures fall back silently to deterministic content — good for demos, but means a broken ADC setup can go unnoticed; check for template-looking quiz questions if generation seems bland.
- KPI payload generation is lazy (first manager-strategic view of the day), not scheduled.

## Where the plans live

`ROADMAP.md` at the repo root is the authoritative done/planned/idea tracker (with per-claim code citations). `scope_project.md` is the historical implementation plan. This page tracks *limitations*; those track *intentions*.
