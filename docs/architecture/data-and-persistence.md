# Data & Persistence

## DepartmentScopedStore (Tier A isolation)

`src/core/database.py: DepartmentScopedStore(department_id)` is the only way application code touches `data/`. Every path it builds is prefixed with its department id (`data/<store>/<department_id>/…`); constructing a path for another department raises `IsolationViolationError`. There is no code path that can read across departments — that's the "Tier A namespace isolation" guarantee.

Base directory resolution order: explicit constructor arg → `WAI_DATA_DIR` env var (this is how tests point the store at a temp dir) → `data/` at project root.

### Store areas (all under `data/`, all namespaced by department)

| Directory | Contents | Written by |
|-----------|----------|-----------|
| `user_progress/<dept>/<user_id>.json` | One `UserProgress` record per user | `user_service.update_progress` |
| `learning_paths/<dept>/<path_id>.json` | Published learning paths (courses → lessons) | curriculum service, KB routes |
| `quizzes/<dept>/quiz_<id>.json` | Persisted quiz sessions incl. `correct_answer_index` | quiz service |
| `knowledge_base/<dept>/` | Ingested/validated KB documents | KB upload pipeline |
| `raw/<dept>/` | Raw uploaded document text/bytes | `write_raw_document(_bytes)` |
| `conflicts/<dept>/` | KB conflict alerts (`status: pending/resolved`) | `write_conflict` |
| `kb_jobs/<dept>/` | Async ingestion job status records | upload/generate jobs |
| `version_history/<dept>/` | Document version snapshots (pruned, keep 15) | `archive_document_snapshot` |
| `catalog/<dept>/` | Catalog inputs + drafts with `.meta.json` sidecars | catalog endpoints |

Non-namespaced files at `data/` root: `credentials.json` (demo accounts), `dev_config.json` (live config), `kpi_store/` (Tier 2 — see below), seed scripts.

## The UserProgress record (the most important document)

Defined as a dataclass in `src/core/models.py`. Key fields:

- `current_state` — one of the 15 state-machine states (`enrolled` … `completed`).
- `entry_path` — `veteran` | `intermediate` | `standard`.
- `enrolled_path_ids`, `completed_courses`, `current_course_id` — course tracking.
- `quiz_attempts` (per-question records with `concept_tags`, `is_correct`), `assessment_scores`, `best_assessment_score`.
- `error_retention_matrix` — `{concept_tag: failure_count}`, all-time; the luck-elimination engine's input.
- `mastery_vectors` — `{concept_token: {half_life_days, last_seen, …}}`; HLR memory-decay input. Keyed by **all** concept tags per question (same namespace as `error_retention_matrix`).
- `remedial_courses` — per-user generated remedial courses (list of course dicts with `source_course_id`, `is_remedial`). Kept **inside** the progress record, not the learning-path store, because they're per-user, on-demand, and unbounded.
- `concept_diagnoses` — per-concept LLM misconception diagnoses recorded when a remedial course is generated; reused by gap review and reflection prompts.
- `bypass_locked`, `bypass_attempts` — Case-1 lockout state.
- `readiness_score`, `is_at_risk`, `blocked_by` — computed by `_recalculate_readiness` on every update.
- `manager_id`, `job_level` — reporting relationship for manager dashboards.

## Tier 2: the KPI store

`reporting_service.synthesize_department_kpi` aggregates a department's progress records into a `KPIPayload` (schema v1.0: workforce / learning / assessment / knowledge-base metrics + risk indicators), **strips all PII** (no user ids, no display names), validates it with `validate_kpi_schema`, and writes it to `data/kpi_store/<dept>_daily_<date>.json`. It is triggered lazily by the manager dashboard's `strategic` endpoint (`ensure_kpi_payload_for_today`) and available as an agent tool.

`KPIStoreReader` is a separate read-only class for Tier 3 (corporate) consumers — it can only read `kpi_store/`, so executive reporting is physically incapable of touching individual records.

## Concurrency model

Writes are whole-file `json.dumps(indent=2)` replacements. A module-level `threading.Lock` exists but individual helpers don't hold it; the demo runs single-worker uvicorn where request handlers don't interleave file writes in practice. **This is a known demo-scope simplification** — the GCP migration replaces it with real transactional storage.

## Planned GCP migration (decided, not yet scheduled)

The store API is the migration seam: replace file I/O inside `DepartmentScopedStore` with Firestore documents (progress, paths, quizzes) and GCS objects (raw documents, KB files), keeping method signatures identical. Nothing above `database.py` should need to change. Until then: **no database dependencies in this repo** (explicit product decision, July 2026).
