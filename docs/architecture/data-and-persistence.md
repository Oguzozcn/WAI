# Data & Persistence

## DepartmentScopedStore (Tier A isolation)

`src/core/database.py: DepartmentScopedStore(department_id)` is the only way application code touches persisted data. Every relative key it builds is prefixed with its department id (`<store>/<department_id>/…`); constructing a key for another department raises `IsolationViolationError`. There is no code path that can read across departments — that's the "Tier A namespace isolation" guarantee.

`DepartmentScopedStore` holds the *domain* logic; the actual leaf I/O goes through a pluggable **storage backend** chosen by the `STORAGE` env var (see "Storage backend" below). Base directory resolution order (local mode): explicit constructor arg → `WAI_DATA_DIR` env var (this is how tests point the store at a temp dir) → `data/` at project root.

> Product code must go through the store's **methods** — it must not reach into the store's `*_path` `Path` attributes (those exist for local mode / tests only and are meaningless in cloud mode). Need to list or delete something the store doesn't expose yet? Add a method (e.g. `list_learning_paths`, `next_ticket_id`, `list_knowledge_document_ids`) rather than globbing the filesystem from a route.

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
| `support_tickets/<dept>/TKT-<n>.json` | Support tickets incl. activity log | support routes |
| `uat_runs/<dept>/UAT-<n>.json` | Manual UAT runs (checklist snapshot, per-item results, AI report) | uat routes |
| `team_docs/<dept>/PROJ-<n>.json` | Team Documentation projects (metadata + `linked_sources` doc-id list + all markdown pages, each with `source`/`drafted_by` provenance — `drafted_by: "ai_synthesis"` pages come from Documentation Master and are the only ones a regeneration replaces) | team_docs routes, documentation_service |

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

Writes are whole-document `json.dumps(indent=2)` replacements. A module-level `threading.Lock` exists but individual helpers don't hold it; the demo runs single-worker uvicorn where request handlers don't interleave writes in practice. **This is a known demo-scope simplification** in local mode; Firestore document writes in cloud mode are atomic per document.

## Storage backend (`STORAGE=local|cloud`)

The migration seam is implemented (July 2026). `src/core/storage_backend.py` defines a small primitive interface (`read_text`/`write_text`, `read_bytes`/`write_bytes`, `exists`, `delete`, `list_files`/`list_files_meta`, `list_dirs`, `delete_dir`) keyed by POSIX-style relative paths. `DepartmentScopedStore` builds those relpaths and calls the backend; a factory (`get_backend`) picks the implementation from the `STORAGE` env var:

| `STORAGE` | Text/JSON | Binary blobs | Notes |
|-----------|-----------|--------------|-------|
| `local` (default) | files under `data/` | files under `data/` | Byte-identical to the app's historical behavior — this is what the whole test suite exercises, and what runs offline on any laptop. |
| `cloud` | Firestore documents | GCS objects | `FirestoreGcsBackend`; requires `WAI_GCS_BUCKET` (+ `GOOGLE_CLOUD_PROJECT`, optional `WAI_FIRESTORE_DATABASE`/`WAI_FIRESTORE_PREFIX`). Used on Cloud Run. |

**Cloud mapping.** Each text/JSON relpath becomes one Firestore document (deterministic id = sha1 of the relpath, so writes are idempotent upserts) carrying `{path, parent, name, text, _updated}` — listings are plain `parent ==` / path-range queries. Each binary relpath becomes one GCS object (object name == relpath); GCS's native prefix+delimiter listing gives the file/subdir split. A single directory can hold both (e.g. catalog inputs: binary files + `.meta.json` sidecars); `list_files` unions Firestore and GCS. Firestore's 1 MiB/document limit applies to text docs (the JSON this app stores sits well under it).

**Deploying / seeding.** See `RUNBOOK.md` — `deploy.sh` provisions Firestore + the GCS bucket and deploys to Cloud Run with `STORAGE=cloud`; `scripts/seed_cloud_storage.py` copies the committed `data/` demo dataset up on first deploy (JSON→Firestore, binary→GCS, via the same backends). The cloud path is verified with the Firestore emulator (runbook §7); the local path is proven by the full test suite.

Non-namespaced areas at the root: `credentials.json` (demo accounts, bcrypt-hashed), `dev_config.json` (live config), `kpi_store/` (Tier 2 — see above).
