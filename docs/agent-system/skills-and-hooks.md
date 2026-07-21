# Skills & Hooks

## The five declarative skills (`.agents/skills/`)

Each skill is a directory containing a single `SKILL.md`: YAML frontmatter (`name`, `description`) plus a markdown instruction body — the persona the orchestrator adopts when it routes a conversation there. All five are editable live in the Agent Console (writes go through `PATCH /api/dev/config/skill/{skill_id}` → `_write_skill_file`).

| Skill | Persona / job |
|-------|---------------|
| `curriculum-builder` | Turns uploaded documents into learning paths; plans daily agendas; identifies content gaps. |
| `knowledge-coach` | The employee-facing tutor: quizzes, progress checks, entry-path routing, encouragement. Explicitly instructed to call `evaluate_answers` and act on its returned `remediation` verdict rather than choosing remediation itself. |
| `kb-validator` | Reviews knowledge-base uploads, surfaces conflicts with existing content for human resolution. |
| `department-reporter` | Synthesizes department KPIs; answers manager questions from aggregates, never raw records. |
| `corporate-report-agent` | Executive tier: reads only the PII-stripped KPI store (Tier 3), drafts executive summaries/emails. |

Skills are re-read from disk on every agent build, so a persona edit is live on the next chat message.

### Editing rules

- Keep frontmatter to `name:` and `description:` — the loader expects exactly that shape.
- The body is instruction text, not documentation: write imperatives ("When the user asks X, call tool Y").
- Never instruct a skill to decide remediation — that is code policy (see below and [Remediation System](/documentation?page=learning-engine/remediation)).

## luck_elimination_hook (`src/agents/hooks.py`)

Attached as `before_tool_callback` on the root agent — ADK invokes it before **every** tool execution.

What it does: for bypass-related tool calls (`check_bypass_eligibility`, bypass-flavored `update_progress`), it loads the user's progress and consults the same remediation policy path as the quiz route. If the user is bypass-locked (or the policy says they should be), the hook returns a rejection payload instead of letting the tool run — the model receives that as the tool result and must relay the lockout to the user.

Why it exists: chat is a *second* entry point to state-changing tools. Without the hook, a locked-out learner could talk the agent into re-attempting a bypass even though the quiz UI would refuse. The hook enforces the same policy at the framework level, so the guarantee doesn't depend on prompt wording.

Design note: the hook consults the shared policy/threshold source (`LUCK_FAILURE_THRESHOLD` via dev_config) — it must never grow its own inline threshold, or it will drift from the rest of the system (this exact bug existed before the 2026-07 remediation rework).

## Adding a new skill

1. Create `.agents/skills/<skill-id>/SKILL.md` with frontmatter + instruction body.
2. Nothing to register — discovery is directory-based on the next agent build.
3. If the skill needs new tools, add the service functions to `_FUNCTION_TOOLS` in `src/agents/agent.py` (see the exposure rules in [ADK Orchestrator Agent](/documentation?page=agent-system/adk-agent)).
4. It will appear automatically in the Agent Console graph and config editor (`_known_skill_ids` scans the directory).
