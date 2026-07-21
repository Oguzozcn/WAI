# ADK Orchestrator Agent

`src/agents/agent.py` defines the platform's single root agent (`WAI_root_orchestrator`), built on google-adk 2.x. It powers the Coach chat page via `POST /api/chat`.

## Construction: fresh on every request

`build_root_agent()` is called **per chat request** (`chat.py: _get_runner`) rather than using a module-level singleton. Construction only reads small local files (dev_config + SKILL.md files), so this is cheap — and it means every Agent Console edit (orchestrator instruction, model, skill personas) is live on the *next message* with no restart. A module-level `root_agent` still exists solely because `adk web` expects to import one.

```python
Agent(
    model=orchestrator_cfg.get("model", "gemini-3.5-flash"),
    name="WAI_root_orchestrator",
    instruction=orchestrator_cfg["instruction"],   # editable in Agent Console
    tools=[skill_toolset],
    before_tool_callback=luck_elimination_hook,
)
```

## SkillToolset: declarative personas + concrete tools

The `SkillToolset` bundles two things:

1. **Skills** — every directory under `.agents/skills/` is loaded via `list_skills_in_dir`/`load_skill_from_dir` on each build. A skill is a SKILL.md file: YAML frontmatter (`name`, `description`, `metadata.adk_additional_tools`) + a markdown instruction body (the persona). The orchestrator selects a skill by intent (calling ADK's `load_skill` meta-tool), then follows its instructions.
2. **Function tools** (`_FUNCTION_TOOLS`) — plain Python functions from `src/services/`, grouped by primary skill:
   - *curriculum-builder*: `generate_learning_path`, `generate_daily_agenda`, `identify_content_gaps`, `trigger_curriculum_generation`
   - *knowledge-coach*: `generate_quiz`, `evaluate_answers`, `generate_reflection_prompt`, `get_user_progress`, `update_progress`, `determine_user_entry_path`, `check_bypass_eligibility`
   - *department-reporter*: `synthesize_department_kpi`, `get_department_readiness`, `flag_at_risk_users`
   - *corporate-report-agent*: `read_kpi_payloads`, `generate_executive_email`
   - *documentation-master*: `generate_project_documentation`

**A tool in this list is only actually callable once its skill's frontmatter declares it under `metadata.adk_additional_tools`** — this installed ADK version gates `additional_tools` behind skill activation, it doesn't flatly attach them. See [Skills & Hooks](/documentation?page=agent-system/skills-and-hooks)'s "Critical gotcha" section; `dev_console.py: _write_skill_file` keeps this metadata in sync with the grouping above automatically.

## Deliberately NOT exposed as tools

`generate_gap_review`, `generate_remedial_course`, and `handle_user_assessment_failure` are intentionally absent from `_FUNCTION_TOOLS`. They used to be directly LLM-callable, which meant the model itself chose whether (and how many!) remediation mechanisms to fire after a failure — nothing stopped it from calling two or three for the same failed quiz. Remediation is now decided in exactly one place (`src/core/remediation_policy.decide_remediation`, consulted inside `evaluate_answers`) and executed deterministically by the service/route layer. The agent calls `evaluate_answers` and *reads* the `remediation` field of the result.

**Rule for future work: never add a tool that lets the model make a remediation decision.** Tools may gather information or generate content; policy stays in code.

## Chat request lifecycle

1. `POST /api/chat` with `{user_id, message}`.
2. `build_root_agent()` → `Runner` → `run_async` streams model turns.
3. Any tool call the model makes first passes through `luck_elimination_hook` (see [Skills & Hooks](/documentation?page=agent-system/skills-and-hooks)) — bypass-related tools are blocked for locked-out users at the framework level, before execution.
4. Final text reply returns as `{reply}`; the frontend renders it as plain text (no markdown parsing in chat).

## Debugging tips

- `python verify_agents.py` smoke-tests that the agent constructs with current config/skills.
- The Agent Console's graph view (`GET /api/dev/graph`) introspects `_FUNCTION_TOOLS` and skills live — if a tool doesn't appear there, it isn't registered.
- Chat misbehaving after a config edit? `get_config()` self-heals missing keys, but a malformed orchestrator instruction is used verbatim — check `data/dev_config.json` first.
