# API Reference

All routers are registered in `src/api/main.py`. Interactive Swagger docs for every endpoint: `http://localhost:8000/docs`. Unless noted, endpoints take an optional `department` query param defaulting to `operations`.

## Pages (`src/api/routes/pages.py`, no prefix)

Serves the HTML files in `frontend/pages/` at top-level URLs: `/login`, `/` (dashboard), `/learning-path`, `/lesson`, `/quiz`, `/knowledge-vault`, `/chat`, `/learning-materials`, `/learning-paths`, `/edit-learning-path`, `/catalog`, `/manager-dashboard`, `/dev-console`, `/settings`, `/documentation`, `/team-documentation`, `/support`, `/support-console`, `/qa-console`. No server-side auth — role gating happens client-side on each page (see [Auth & Roles](/documentation?page=backend/auth-and-roles)).

## Auth (`/api/auth`)

| Endpoint | Purpose |
|----------|---------|
| `POST /api/auth/login` | Body `{user_id, password}` → `{user_id, display_name, role, manager_id}` or 401. Plaintext comparison against `data/credentials.json` (demo only). |
| `GET /api/auth/directory/{user_id}` | `{user_id, display_name, role}` or 404 — never includes the password. Used by `profile.html` to resolve a `manager_id` into a display name. |

## Progress (`/api/user`)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/user/{user_id}/progress` | Full progress record + computed summary fields. |
| `POST /api/user/{user_id}/progress` | Event-based update (`event_type`: `course_started`, `course_completed`, `path_enrolled`, `path_assigned`, `state_changed`, `assessment_passed`, `bypass_locked` …) → `user_service.update_progress`. |

## Learning paths (`src/api/routes/learning_path.py`, mixed paths)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/user/{user_id}/learning-path` | Generate/fetch a path for the user (role-based). |
| `GET /api/user/{user_id}/daily-agenda?day=N` | Daily agenda breakdown. |
| `GET /api/user/{user_id}/gap-review` | Current gap-review payload for the user. |
| `GET /api/learning-path/latest` | Most recent published path. |
| `GET /api/learning-path/enrolled?user_id=…` | All paths the user is enrolled in (list view; remedial courses are NOT merged here). |
| `GET /api/learning-path/{path_id}?user_id=…` | One path by id; **merges the user's `remedial_courses`** into `courses` (marked `is_remedial: true`) via `_merge_remedial_courses`. |
| `GET /api/lesson/{course_id}/{lesson_id}` | Lesson content. |
| `POST /api/learning-path/{path_id}/enroll` | Enroll a user. |
| `GET /api/search?q=…` | Global search across paths/lessons for the sidebar search. |

## Quiz (`/api/quiz`)

| Endpoint | Purpose |
|----------|---------|
| `POST /generate` | LLM-generate a quiz (falls back to template questions). |
| `POST /start` | Start/resume a quiz session (persisted server-side). |
| `POST /evaluate/single` | Grade one answer mid-quiz (drives inline feedback + reflection). |
| `POST /evaluate` | Grade the full attempt. Consults `decide_remediation`; response includes the `remediation` verdict and acts on it (gap review / remedial course / lockout). |
| `POST /reflection` | LLM metacognitive reflection prompt for a wrong answer. |
| `POST /gap-review/retry` | Build a 3-question targeted retry quiz from stored concept diagnoses. |
| `GET /session/{quiz_id}` | Fetch a stored session (correct answers stripped). |
| `GET /by-lesson/{course_id}/{lesson_id}` | Get-or-create the short quiz for a lesson. |
| `GET /by-course/{course_id}?type=final_assessment` | Get-or-create a course-level assessment. |

## Department (`/api/department`)

| Endpoint | Purpose |
|----------|---------|
| `GET /readiness` | Aggregate readiness for the department. |
| `GET /at-risk` | Users below the at-risk threshold with their biggest gap. |

## Knowledge base (`/api/kb`) — manager-facing

Upload & ingestion: `POST /upload` (multipart; async job), `GET /upload/status/{job_id}`, `POST /generate-from-input`, `GET /generate-status/{job_id}`. Supported types are `src/core/config.py: SUPPORTED_MIME_TYPES` — text-family (`.txt/.md/.html/.htm/.xml/.csv`), spreadsheets (`.xlsx/.xls`, extracted to text via `openpyxl` at upload time so they join the same chunking pipeline), and native binary media Gemini reads directly (PDF, images, audio, video).
Documents: `GET /documents`, `POST /validate`, `DELETE /documents/{filename}`, `GET /documents/{filename}/versions`, `POST /documents/{filename}/versions/{version}/restore`.
Conflicts: `GET /conflicts?status=pending`, `POST /conflicts/{conflict_id}/resolve` (approve/reject + `resolved_by`).
Path authoring: `POST /learning-path/{path_id}/publish`, `PATCH /learning-path/{path_id}`, `DELETE /learning-path/{path_id}`, `GET /learning-path/{path_id}/full`, `PATCH …/course/{course_id}`, `PATCH …/lesson/{lesson_id}`, `PATCH /quiz/{quiz_id}`, `POST /lesson/{lesson_id}/regenerate`, `POST /quiz/{quiz_id}/regenerate`, `GET /catalog/inputs`, `GET /catalog/learning-paths`.

Write endpoints carry a client-supplied `role` and call `_require_manager(role)` — client-trusted gating.

## Manager (`/api/manager`)

| Endpoint | Purpose |
|----------|---------|
| `GET /{manager_id}/team-kpis` | Team aggregates for the dashboard cards. |
| `GET /{manager_id}/reports` | Per-report-row table incl. `current_course_title` (id resolved to a human title via `_resolve_course_title`). |
| `GET /{manager_id}/reports/export` | Formatted Excel download (openpyxl, in-memory, `Content-Disposition: attachment`). Values pass `_formula_safe` to block formula injection. |
| `GET /{manager_id}/strategic` | Strategic bucket; lazily ensures today's KPI payload exists. |

All require `role=manager` (query param, client-trusted).

## Chat (`/api/chat`)

`POST /api/chat` — body `{user_id, message}`. Builds a fresh `root_agent`, runs it via ADK `Runner.run_async`, returns `{reply}`.

## Dev console (`/api/dev`) — developer-facing

`GET /graph` (agent topology for the console UI), `GET /config`, `PATCH /config/orchestrator`, `PATCH /config/skill/{skill_id}`, `PATCH /config/tool/{tool_name}` (dry-run validates `{placeholders}`), `PATCH /config/platform-params`, `PATCH /config/logic-params/{category}`. PATCH bodies carry `role` and call `_require_developer(role)`.

## Documentation (`/api/docs`) — developer-facing

| Endpoint | Purpose |
|----------|---------|
| `GET /api/docs/tree` | The docs manifest (sections → pages) + per-page `updated_at`. |
| `GET /api/docs/page/{section_id}/{page_id}` | One page: `{title, content (markdown), updated_at}`. |
| `PUT /api/docs/page/{section_id}/{page_id}` | Save edited markdown. Body `{content, role}`; developer-gated. |
| `GET /api/docs/export?format=txt|pdf&scope=all|<section>/<page>` | Download one page or the whole set as TXT (raw markdown) or PDF (fpdf2-rendered). |

Page ids are validated against the manifest — they are never used to build filesystem paths directly, so path traversal is structurally impossible.

## Support tickets (`/api/support`)

ITSM-style ticket lifecycle: `new → in_progress → on_hold → resolved → closed` (closed can only reopen to `in_progress`). Priorities: `critical/high/medium/low`. Every mutation appends to the ticket's `activity` log. Ticket ids are sequential and human-readable (`TKT-0001`), one JSON file per ticket under `data/support_tickets/{department}/`.

| Endpoint | Purpose |
|----------|---------|
| `POST /tickets` | Submit a ticket. Body `{user_id, display_name, role, area, issue_type, subject, description, additional_comments}`. Vocabulary-validated; starts as `new`/`medium`. |
| `GET /tickets?user_id=…&role=…` | Developer sees the whole department queue; anyone else only tickets they reported. |
| `GET /tickets/{ticket_id}?user_id=…&role=…` | One ticket; 403 unless reporter or developer. |
| `PATCH /tickets/{ticket_id}` | Developer-only triage: `status`, `priority`, `assignee`, `resolution_note` (each change → activity entry). |
| `POST /tickets/{ticket_id}/comments` | Reporter or developer adds a comment to the activity log. |
| `GET /meta` | The vocabulary (areas, issue types, statuses, priorities) mirrored by the frontend dropdowns. |

## UAT (`/api/uat`) — developer-facing

Manual acceptance testing: a **predefined whole-app checklist** (`UAT_CHECKLIST` in `src/api/routes/uat.py`, 27 items across auth, dashboard, lessons, quiz, catalog, chat, manager tools, Team Documentation, developer tools, support, global UI — including the header avatar / Profile page). Starting a run snapshots the checklist into a persistent run doc (`data/uat_runs/<dept>/UAT-<n>.json`), the tester marks each item `pass`/`fail`/`blocked` (+ note), and the report endpoint finalizes the run and writes an AI summary. Every endpoint that touches runs requires `role=developer` (client-trusted).

| Endpoint | Purpose |
|----------|---------|
| `GET /checklist` | The predefined checklist + result/verdict vocabularies (open read, like `/meta`). |
| `POST /runs` | Start a run; items seeded from the checklist as `pending`. Sequential ids (`UAT-0001`). |
| `GET /runs?role=…` | Run history, newest first (overview projection: status, summary counts, verdict). |
| `GET /runs/{run_id}?role=…` | One full run (items + report). |
| `PATCH /runs/{run_id}/items/{item_id}` | Body `{role, result, note}`. Vocabulary-validated; recomputes the summary; rejected (400) once the run is completed. |
| `POST /runs/{run_id}/report` | Finalizes the run (`status=completed`) and generates the report via the `generate_uat_report` prompt template (dev_config `tools`) → `call_gemini_json`; **falls back to a deterministic report** (verdict from pass/fail/blocked/pending counts) when the LLM is unavailable. Re-callable to regenerate. |

Report shape: `{verdict: go|conditional-go|no-go, headline, summary, key_risks[], recommendations[], source: llm|fallback, generated_at}`. Fallback verdict rules: nothing executed → `no-go`; clean and complete → `go`; ≥25% failed → `no-go`; otherwise `conditional-go`.

## Team Documentation (`/api/team-docs`) — manager/employee-facing

A team's own project documentation (`src/api/routes/team_docs.py`): any number of **projects** per department (`data/team_docs/<dept>/PROJ-<n>.json`), each holding markdown **pages** that start blank or are built from a Knowledge Vault upload. Every endpoint requires `role=manager` or `role=individual_contributor` (client-trusted, `_require_team_member`) — developers are excluded (they have `/documentation`). Creating and deleting a whole project additionally requires the manager role — an employee can open, edit, and add pages to any existing project, but cannot start or remove one.

| Endpoint | Purpose |
|----------|---------|
| `GET /projects?role=…` | Project overviews (name, description, page_count, created_by, updated_at), latest-updated first. |
| `POST /projects` | **Manager-only.** Create a project. Body `{name, description?, role, user_id, display_name}`. Sequential ids (`PROJ-0001`); 400 on a blank name. |
| `GET /projects/{id}?role=…` | One full project (metadata + all pages). |
| `PATCH /projects/{id}` | Rename / re-describe. Body `{role, name?, description?}`. |
| `DELETE /projects/{id}?role=…` | **Manager-only.** Removes the project and all of its pages. |
| `GET /sources?role=…` | Knowledge Vault uploads usable as page material — the `*_chunks` docs written at upload time (`{doc_id, filename, uploaded_at, chunk_count, topics}`); generated course docs are excluded. |
| `PUT /projects/{id}/sources` | Replace a project's `linked_sources` list wholesale (the set of Knowledge Vault uploads its documentation should be synthesized from — independent of which already have their own page). Body `{role, source_doc_ids}`; 404 on an unknown doc id. |
| `POST /projects/{id}/pages` | Add a page. Body `{role, user_id, display_name, mode, title?, content?, source_doc_id?}`. `mode=blank` needs a title; `mode=import` copies the upload's text (original raw file when readable, else the chunk text — media uploads store their Gemini summary there); `mode=ai_draft` runs the source through the `draft_team_doc_page` prompt template → `call_gemini_json` and **falls back to a plain import** when the LLM is unavailable. Sequential per-project ids (`page-0001`); pages carry `source` + `drafted_by` (`manual`/`import`/`ai`) provenance. |
| `PUT /projects/{id}/pages/{page_id}` | Save an edit. Body `{role, content, title?}`; 400 on empty content. |
| `DELETE /projects/{id}/pages/{page_id}?role=…` | Remove a page (any team member). |
| `POST /projects/{id}/generate-documentation` | **Documentation Master.** Synthesizes the project's full documentation set from every source in `linked_sources` via `generate_project_documentation` (`src/services/documentation_service.py`) — the same function the ADK orchestrator calls from chat. 400 if no sources are linked; 502 if the LLM call fails or returns an unusable shape (there's no sound deterministic fallback for writing a whole document from scratch). On success, replaces any pages from a previous synthesis run (`drafted_by == "ai_synthesis"`) while leaving manually-written/imported pages untouched. |
| `GET /projects/{id}/export?format=txt|pdf&scope=all|<page_id>&role=…` | Download one page or the whole project via the shared `src/core/doc_export.py` renderer (same TXT/PDF output as `/api/docs/export`). |
