# Core Modules

`src/core/` is the deterministic heart of the platform: no LLM calls, no HTTP, importable from anywhere. If you're debugging *why* the system made a decision, the answer is in this directory.

## config.py — platform constants

Code-level defaults for every threshold: `PASS_THRESHOLD = 0.80`, `LUCK_FAILURE_THRESHOLD = 2`, `MAX_COURSES = 10`, `MAX_QUIZ_QUESTIONS = 10`, `MAX_ASSESSMENT_QUESTIONS = 20`, `MAX_QUIZ_ATTEMPTS = 3`, `AT_RISK_READINESS_THRESHOLD = 0.60`, plus the 15 state constants (`STATE_ENROLLED` … `STATE_COMPLETED`) and entry paths (`veteran`/`intermediate`/`standard`). At runtime most numeric values are read through `dev_config.get_param()` instead, which overlays `data/dev_config.json` on these defaults.

`SUPPORTED_MIME_TYPES` (extension → `(mime_type, content_category)`) also lives here rather than in `knowledge_base.py` — it's shared by the upload route and `documentation_service.py`, which both need to resolve a filename's category without a route↔service layering violation. Spreadsheets (`.xlsx`/`.xls`) map to `content_category = "text"`: they're extracted to a readable text dump at upload time (`knowledge_base._extract_spreadsheet_text`, via `openpyxl`) rather than getting their own category, so they join the exact same chunking/gap-analysis/documentation-synthesis pipeline as any other text-family upload.

## models.py — dataclass schemas

All persisted shapes: `ConceptToken`, `MasteryVector`, `Lesson`, `Course`, `LearningPath`, `DailyAgenda`, `QuizQuestion`, `Quiz`, `QuizAttempt`, `UserProgress` (the big one — see [Data & Persistence](/documentation?page=architecture/data-and-persistence)), and the KPI schema family (`WorkforceMetrics`, `LearningMetrics`, `AssessmentMetrics`, `KnowledgeBaseMetrics`, `RiskIndicators`, `KPIPayload`, `ConflictAlert`). Each has `to_dict()`; `UserProgress.from_dict` tolerates unknown keys so old records survive schema additions.

## database.py — persistence

`DepartmentScopedStore` + `KPIStoreReader` + `validate_kpi_schema`. Holds the domain logic; leaf I/O goes through a pluggable backend. Covered in depth in [Data & Persistence](/documentation?page=architecture/data-and-persistence).

## storage_backend.py — pluggable I/O (local ↔ cloud)

The seam that makes the store portable. `StorageBackend` is a small relpath-keyed primitive interface; `LocalStorageBackend` reproduces the historical filesystem behavior byte-for-byte (so the whole test suite keeps proving nothing regressed), and `FirestoreGcsBackend` stores text/JSON in Firestore and binary blobs in GCS. `get_backend()` chooses between them from the `STORAGE` env var (`local` default). See [Data & Persistence](/documentation?page=architecture/data-and-persistence) for the cloud mapping.

## settings.py — deployment env knobs

One place that reads the env contract from `.env.example` (functions, read at call time so tests can monkeypatch): `storage_backend()`/`is_cloud_storage()`, `gcs_bucket()`, `firestore_database()`/`firestore_prefix()`, `gcp_project()`, `credentials_json_env()`/`credentials_path()`, `trust_iap()`. No side effects — importing it touches no cloud service.

## auth_store.py — credentials + password hashing

`load_credentials()` (Secret Manager env → file), `verify_password` (bcrypt, with legacy-plaintext fallback), `hash_password`, and `public_entry` (identity with the hash stripped). Backs `auth.py`; see [Auth & Roles](/documentation?page=backend/auth-and-roles).

## state_machine.py — the learning journey graph

- `_VALID_TRANSITIONS` — the full graph: `enrolled → {fast_track | intermediate_choice | standard_path}` … `validation_assessment → {passed | failed}` … `completed` (terminal). `validate_transition` raises `InvalidTransitionError` on anything else.
- `handle_assessment_result(score, was_bypass_attempt, bypass_already_locked)` — the pass/fail verdict:
  - **Pass** (score ≥ `PASS_THRESHOLD`) → `passed`.
  - **Case 1** — fail on a bypass attempt → `bypass_locked`, `lock_bypass=True`; the full path becomes mandatory (completed modules excluded via `get_mandatory_courses`).
  - **Case 2** — standard failure → `gap_review`, retake allowed.
- `determine_entry_path(experience_level)` — veteran→fast_track, intermediate→intermediate_choice, standard→standard_path.
- `get_state_description(state)` — human-readable labels used by dashboards.

## luck_elimination.py — guess detection + memory decay

- `LuckEliminationEngine.evaluate_user_progression(error_retention_matrix, new_attempts)` — folds this attempt's wrong answers into the matrix, flags every concept with ≥ `LUCK_FAILURE_THRESHOLD` (2) failures, then:
  - ≥ `core_drift_concept_count` (3) flagged concepts → `FORCE_MANDATORY_LEARNING_PATH`
  - ≥ 1 flagged → `SPAWN_GAP_REVIEW`
  - none → `MAINTAIN_ADAPTIVE_GAP_ASSESSMENT`
- `calculate_hlr_retention(vector)` — Duolingo half-life regression: `p = 2^(-Δt / half_life_days)`, clamped to [0,1]. Used by `generate_gap_review` to skip concepts whose retention is still ≥ `hlr_retention_threshold` (0.6).
- `get_concept_failure_summary` — ok/warning/critical labels for reporting.

## remediation_policy.py — THE single decision point

`decide_remediation(score, quiz_type, was_bypass_attempt, bypass_already_locked, error_retention_matrix, new_attempts)` fuses `handle_assessment_result` + `LuckEliminationEngine` into one `RemediationDecision` (`next_state`, `lock_bypass`, `luck_action`, `flagged_concepts`, `spawn_gap_review`, `spawn_remedial_course`, `reason`). Only a failed `final_assessment` sets `spawn_remedial_course`. Every entry point (quiz route, routing service, agent hook) reads this one verdict — before this module existed, four call sites decided independently and could contradict each other. **If you're changing remediation behavior, change it here and nowhere else.**

## dev_config.py — live configuration

Backs `data/dev_config.json` with self-healing defaults (`_deep_merge_defaults` fills missing keys on read, so deleting the file is safe). API: `get_config()` (whole tree: `orchestrator`, `tools` (5 prompt templates), `platform_params` (10 values), `logic_params` (5 categories, ~20 values)), `update_config(path, patch)`, `get_param(name)`, `get_logic_param(category, name)`. Everything reads per-call — no restart needed after an Agent Console edit.

## doc_export.py — shared TXT/PDF rendering

`export_txt(title, entries)` / `export_pdf(title, entries)` render a list of `{section_title, page_title, content}` markdown pages into a downloadable plain-text bundle or an fpdf2-generated PDF (cover page + TOC when multi-page; latin-1-safe character mapping). Extracted from `docs.py` (July 2026) so the developer docs (`/api/docs/export`) and Team Documentation (`/api/team-docs/projects/{id}/export`) share one renderer. Body text renders left-aligned (`align="L"`) rather than fpdf2's justify default, which stretches word spacing on every wrapped line and reads as broken formatting; markdown tables are collected as a contiguous `|...|` block and rendered as a real bordered `fpdf2` table (`_parse_table_block` splits header/body on the `---|---` separator row) instead of one raw pipe-delimited line at a time.

## data_compliance_gate.py — GDPR gate

`DataComplianceGate` blocks automatic transitions into `passed`/`completed`/`authorized` unless the event carries a human controller signature and a DPIA-completed flag (per the GDPR Art. 32(4) / DPD Poland precedent documented in `AI_Research/Brain/`). Wired into `user_service.update_progress`; a blocked transition is held for approval rather than dropped.
