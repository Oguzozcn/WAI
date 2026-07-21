# Learning Paths & Courses

## Content hierarchy

```
LearningPath  (data/learning_paths/<dept>/<path_id>.json)
└── courses[]           # Course: course_id, title, description
    └── lessons[]       # Lesson: lesson_id, title, content (markdown-ish)
        └── short quiz  # pre-generated, data/quizzes/<dept>/
    └── final assessment (per course, pre-generated)
```

Remedial courses are the exception: they live inside the *user's* progress record (`progress["remedial_courses"]`), not the path store, because they're per-user, on-demand, and unbounded. The by-id path endpoint merges them in at read time (see below).

## Lifecycle: document → published path

1. **Upload** — manager drops a document in the Knowledge Vault (`POST /api/kb/upload`, multipart). An async job record is created in `kb_jobs/`; the UI polls `GET /api/kb/upload/status/{job_id}`.
2. **Ingestion** (`curriculum_service.process_kb_upload_job`) — parse → `recursive_character_splitter` → conflict detection against existing KB (overlap-ratio ≥ 0.5 with ≥ 2 overlapping chunks → a pending `ConflictAlert`, *soft-flag*, never a hard reject) → store in `knowledge_base/`.
3. **Curriculum generation** (`process_document_to_curriculum`, Gemini) — sections become courses/lessons with teaching content; `_generate_course_quizzes` pre-generates each lesson's short quiz (3 questions) and each course's final assessment (6 questions). Counts tunable in `logic_params.curriculum_generation`.
4. **Draft → publish** — drafts appear in the manager's Learning Paths page; `POST /api/kb/learning-path/{path_id}/publish` makes them enrollable. Managers can edit titles/lessons/quizzes (`PATCH` endpoints, `edit-learning-path.html`) or regenerate individual lessons/quizzes with the LLM.

## Enrollment & consumption

- Employees browse published paths in `/catalog` and enroll via `POST /api/learning-path/{path_id}/enroll` → `path_enrolled` event → `enrolled_path_ids` in their progress record.
- The dashboard's **Courses tab** shows one card per *lesson* across all enrolled paths; the **Paths tab** shows one card per enrolled *path*. Cards beyond the first 5 are hidden behind "View all courses".
- Lesson pages mark progress via `course_started` / `course_completed` events (`POST /api/user/{id}/progress`).

## The remedial-course merge (important, easy to miss)

`GET /api/learning-path/{path_id}?user_id=…` calls `_merge_remedial_courses` (learning_path.py): the user's `remedial_courses` whose `source_course_id` belongs to this path are injected into the returned `courses` list with `is_remedial: true` — the UI renders them with a "TARGETED REVIEW" badge. The **list** endpoint (`/api/learning-path/enrolled`) does *not* merge; only the by-id endpoint does. The dashboard fetches each enrolled path by id specifically so the merge applies.

## Heuristic vs LLM generation

`generate_learning_path`, `generate_daily_agenda`, and `identify_content_gaps` are **rule-based** (doc counts, length checks, overlap matching) — a known roadmap item if LLM-backing them becomes a goal. The LLM-backed generation paths are `process_document_to_curriculum`, `generate_quiz`, and `generate_remedial_course`.

## Search

`GET /api/search?q=…` powers the sidebar global search (`frontend/js/global-search.js`) across paths and lessons, scoped to the user's department.
