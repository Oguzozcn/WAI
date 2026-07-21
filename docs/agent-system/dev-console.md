# Agent Console (Dev)

`/dev-console` (developer role) is the live control panel for everything the LLM side of the platform does. Backing API: `/api/dev/*` (`src/api/routes/dev_console.py`). All edits write to `data/dev_config.json` or `.agents/skills/*/SKILL.md` and take effect on the next request — no restart, ever.

## The graph view

`GET /api/dev/graph` introspects the real system (not a hardcoded diagram): the orchestrator node, the five skills (from disk), and every function tool in `_FUNCTION_TOOLS`, with edges showing which skill primarily uses which tool. Clicking a node opens the matching editor panel. If something you expect is missing from the graph, it isn't registered in code.

## What's editable, exactly

### Orchestrator (`PATCH /api/dev/config/orchestrator`)
- `model` — Gemini model id used by the root agent.
- `instruction` — the routing prompt that decides which skill handles a message.

### Skills (`PATCH /api/dev/config/skill/{skill_id}`)
- `name`, `description` (frontmatter) and the persona `instruction` (body). Written straight to the SKILL.md file.

### Tool prompt templates (`PATCH /api/dev/config/tool/{tool_name}`)
Three LLM call sites have editable templates in `dev_config.tools`:
- `generate_quiz`
- `process_document_to_curriculum`
- `generate_remedial_course`

Each may also override `model` per-tool. The endpoint **dry-run validates** the template by `.format()`-ing it with dummy values — a template referencing an unknown `{placeholder}` is rejected with a 400 rather than breaking the next generation.

### Platform parameters (`PATCH /api/dev/config/platform-params`)
The 10 headline numbers: `GEMINI_MODEL`, `PASS_THRESHOLD` (0.8), `MAX_QUIZ_QUESTIONS` (10), `MAX_ASSESSMENT_QUESTIONS` (20), `MAX_QUIZ_ATTEMPTS` (3), `MAX_COURSES` (10), `DEFAULT_TIMEFRAME_WEEKS` (4), `AT_RISK_READINESS_THRESHOLD` (0.6), `AT_RISK_PERCENTAGE_THRESHOLD` (25.0), `LUCK_FAILURE_THRESHOLD` (2).

### Logic parameters (`PATCH /api/dev/config/logic-params/{category}`)
Fine-grained deterministic-logic tuning, validated per category (`_validate_logic_params`):

| Category | Parameters |
|----------|------------|
| `assessment_scoring` | IRT: `irt_learning_rate` 0.5, `irt_theta_clamp` 4.0, item defaults (discrimination 1.0, guessing 0.25, slip 0.95) |
| `readiness_scoring` | weights: course 0.5 / quiz 0.3 / state 0.2; `quiz_window_size` 5 |
| `luck_elimination` | `core_drift_concept_count` 3, `hlr_retention_threshold` 0.6, `hlr_ability_threshold` 0.5 |
| `adaptive_routing` | `confidence_threshold` 0.7, `accuracy_threshold` 0.6 |
| `curriculum_generation` | conflict overlap ratio 0.5 / min count 2; pregenerated question counts (3 short / 6 final); remedial question counts (3/5); `remedial_course_cap` 2 |

## Trust model

GET endpoints are open; every PATCH carries a client-supplied `role` checked by `_require_developer(role)` — the same client-trusted pattern used platform-wide (see [Auth & Roles](/documentation?page=backend/auth-and-roles)).

## Self-healing config

`get_config()` deep-merges `data/dev_config.json` over code defaults on every read (`_deep_merge_defaults`), so missing keys are backfilled automatically and deleting the file entirely just resets everything to defaults. This makes the config file safe to hand-edit.

## Practical uses during demos

- Lower `PASS_THRESHOLD` to walk through the pass flow quickly.
- Raise `LUCK_FAILURE_THRESHOLD` to keep luck-elimination quiet during scripted runs.
- Edit the `generate_quiz` template to change question style live, mid-demo.
