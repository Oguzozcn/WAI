# Skills & Hooks

## The six declarative skills (`.agents/skills/`)

Each skill is a directory containing a single `SKILL.md`: YAML frontmatter (`name`, `description`) plus a markdown instruction body — the persona the orchestrator adopts when it routes a conversation there. All six are editable live in the Agent Console (writes go through `PATCH /api/dev/config/skill/{skill_id}` → `_write_skill_file`).

**Frontmatter gotcha**: the loader parses `name:`/`description:` with a real YAML parser, so a bare `: ` (colon-space) anywhere inside the `description` value breaks it ("mapping values are not allowed here") — use an em dash or rephrase instead of a colon in that one line.

| Skill | Persona / job |
|-------|---------------|
| `curriculum-builder` | Turns uploaded documents into learning paths; plans daily agendas; identifies content gaps. |
| `knowledge-coach` | The employee-facing tutor: quizzes, progress checks, entry-path routing, encouragement. Explicitly instructed to call `evaluate_answers` and act on its returned `remediation` verdict rather than choosing remediation itself. |
| `kb-validator` | Reviews knowledge-base uploads, surfaces conflicts with existing content for human resolution. |
| `department-reporter` | Synthesizes department KPIs; answers manager questions from aggregates, never raw records. |
| `corporate-report-agent` | Executive tier: reads only the PII-stripped KPI store (Tier 3), drafts executive summaries/emails. |
| `documentation-master` | Synthesizes a Team Documentation project's full doc set (overview, business context, requirements, process flow, glossary, code snippets where genuinely present) from every Knowledge Vault source linked to the project — any project domain, not just software. |

Skills are re-read from disk on every agent build, so a persona edit is live on the next chat message.

### Editing rules

- Frontmatter is `name:`, `description:`, and (if the skill has tools) a `metadata: { adk_additional_tools: [...] }` block — see the gotcha below before touching this by hand.
- The body is instruction text, not documentation: write imperatives ("When the user asks X, call tool Y").
- Never instruct a skill to decide remediation — that is code policy (see below and [Remediation System](/documentation?page=learning-engine/remediation)).

### Critical gotcha: `adk_additional_tools` — without it, a skill's tools are invisible to the model

The installed `google-adk` version's `SkillToolset` does **not** flatly expose every `additional_tools` function to the model on every turn. A function tool only becomes callable once the model has activated its skill (via the `load_skill` meta-tool) **and** that skill's frontmatter lists the tool under `metadata.adk_additional_tools`. Omit that key and the model can still route to the skill (it reads the persona fine) but any attempt to call its tool fails with `Tool '<name>' not found` — or, worse, the model just improvises a plausible-sounding answer in chat instead of actually calling the tool, so nothing looks broken until you check whether real work happened server-side (a stored quiz, a written page, etc.).

`_write_skill_file` (`dev_console.py`) always re-derives this metadata from `SKILL_TOOL_GROUPS` — the same mapping the graph view uses — rather than trusting whatever was on disk, so a persona edit through the Agent Console can never silently drop it. **If you add a tool to `SKILL_TOOL_GROUPS`, the fix is automatic on the next console save; if you're hand-editing a SKILL.md file directly, add the block yourself:**
```yaml
---
name: my-skill
description: ...
metadata:
  adk_additional_tools:
    - my_tool_function
---
```
This was discovered (and every existing skill's SKILL.md fixed) while building Documentation Master (July 2026) — chat-driven tool calls for all six skills were silently non-functional before this fix, not just the new one.

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
