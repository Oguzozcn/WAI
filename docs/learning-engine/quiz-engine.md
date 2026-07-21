# Quiz Engine

## Quiz types

| `quiz_type` | When | Questions | Spawns remedial course on fail? |
|-------------|------|-----------|-------------------------------|
| `short_quiz` | After each lesson | 3 (pregenerated) | No |
| `validation_assessment` | Bypass/fast-track validation | up to 20 | No (but Case 1/2 applies) |
| `final_assessment` | End of a course | 6 (pregenerated) | **Yes** (the only type that does) |
| `gap_review` | Targeted retry after flagged concepts | 3 | No |

## Session model (server-authoritative)

Quizzes are persisted server-side (`data/quizzes/<dept>/quiz_<id>.json`) **including** `correct_answer_index`. Clients only ever receive the stripped version (`GET /api/quiz/session/{quiz_id}` removes answers). Grading happens exclusively on the server, so the frontend can't be tricked into self-grading. Sessions survive restarts and multi-worker deployments.

Get-or-create endpoints (`/api/quiz/by-lesson/...`, `/api/quiz/by-course/...`) return the existing pregenerated quiz or generate one on first request.

## Generation

`quiz_service.generate_quiz` builds questions with Gemini, grounded on the lesson/KB content, using the `generate_quiz` prompt template from dev_config (editable live). Each question carries `concept_tags` — these tags are the currency of the whole adaptive system (failure tracking, gap review, mastery vectors). On LLM failure or empty grounding, `_build_template_question` produces deterministic fallback questions so the flow never breaks.

## Evaluation flow (`POST /api/quiz/evaluate`)

`evaluate_answers` does, in order:

1. Grade each answer against the stored session.
2. Append per-question `QuizAttempt` records (with `concept_tags`, `is_correct`) to the user's progress.
3. Update `error_retention_matrix` — every concept tag of every wrong answer gets +1 (all-time counts).
4. Update `mastery_vectors` for **all** concept tags of each question (same key namespace as the error matrix — keep it that way; a historical single-tag-vs-all-tags mismatch silently broke HLR filtering).
5. Update the 4PL IRT ability estimate (`EnterprisePsychometricEngine.update_learner_ability`).
6. Call `decide_remediation(...)` and attach the verdict as `result["remediation"]`.

The route then *acts* on the verdict — persists `next_state`, locks bypass, generates the gap review and/or remedial course. Content generation is downstream of the decision, never part of it.

## Mid-quiz feedback

`POST /api/quiz/evaluate/single` grades one answer immediately (drives the green/red option highlight). On a wrong answer, the frontend follows up with `POST /api/quiz/reflection` and renders the returned metacognitive prompt inline as an expandable panel (`quiz-controller.js`).

## IRT in one paragraph

The `EnterprisePsychometricEngine` implements a 4-parameter logistic model: probability of a correct response given ability θ, item discrimination (default 1.0), guessing floor (0.25 — four options), and slip ceiling (0.95). After each answer, θ moves by `irt_learning_rate` (0.5) times the surprise (actual − predicted), clamped to ±`irt_theta_clamp` (4.0). θ feeds routing decisions and reporting; the pass/fail verdict itself stays a plain score ≥ 80% check for explainability.

## Anti-cheating measures

- Correct answers never leave the server (see session model).
- Luck elimination: passing by guessing is caught across attempts via the error-retention matrix (see [Remediation System](/documentation?page=learning-engine/remediation)).
- Excel-formula injection is sanitized on export (`_formula_safe`).
- Rapid-guessing telemetry (CHIPS-style minimum comprehension time) is **not** implemented — documented as a roadmap item.
