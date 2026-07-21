"""
TEAP Root Orchestrator Agent — ADK 2.0 (google-adk 2.3+)
=========================================================
Routes users to the appropriate declarative skill based on intent.

Declarative architecture:
  - Personas / instructions live in .agents/skills/<skill-name>/SKILL.md.
  - They are discovered at import time via `list_skills_in_dir` and loaded
    with `load_skill_from_dir`, then exposed to the model through a
    `SkillToolset` (the ADK 2.0 mechanism that replaces imperative
    sub-agent Python classes).
  - The concrete Python function tools the skills rely on are attached to
    the same toolset via `additional_tools`, so the orchestrator can both
    *select a skill* and *call its tools* in one turn.
"""

from pathlib import Path

from google.adk.agents.llm_agent import Agent
from google.adk.skills import list_skills_in_dir, load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset

from src.agents.hooks import luck_elimination_hook
from src.core.dev_config import get_config

# ── Model ──
# Fallback if dev_config.json is somehow missing the key (get_config()
# self-heals, so this should never actually be hit in practice).
MODEL = "gemini-3.5-flash"

# ── Skill Discovery ──
# Resolve the .agents/skills/ path relative to the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SKILLS_DIR = _PROJECT_ROOT / ".agents" / "skills"


def _load_skills() -> list:
    """Load every declarative skill under .agents/skills/.

    Returns an empty list if the directory is missing so the agent can still
    be constructed (tools remain available) in trimmed-down deployments.
    """
    if not _SKILLS_DIR.exists():
        return []
    return [
        load_skill_from_dir(_SKILLS_DIR / skill_id)
        for skill_id in list_skills_in_dir(_SKILLS_DIR)
    ]


# ── Tool Imports (shared across skills and API routes) ──
# NOTE: these names are the *actual* exported functions in src/services/*.
from src.services.curriculum_service import (
    generate_learning_path,
    generate_daily_agenda,
    identify_content_gaps,
    trigger_curriculum_generation,
)
from src.services.quiz_service import (
    generate_quiz,
    evaluate_answers,
    generate_reflection_prompt,
)
from src.services.user_service import (
    get_user_progress,
    update_progress,
    get_department_readiness,
    flag_at_risk_users,
)
from src.services.reporting_service import (
    synthesize_department_kpi,
    read_kpi_payloads,
    generate_executive_email,
)
from src.services.routing_service import (
    determine_user_entry_path,
    check_bypass_eligibility,
)

# Concrete function tools grouped by the skill that primarily uses them.
#
# NOT exposed here (deliberately): generate_gap_review, generate_remedial_course,
# handle_user_assessment_failure. Each of those used to also be a directly
# LLM-callable tool, which meant the model itself decided whether/which
# remediation mechanism to invoke after a failure — nothing stopped it from
# calling two or three for the same failure. That decision is now made in one
# place (src.core.remediation_policy.decide_remediation, consulted inside
# evaluate_answers) and acted on deterministically; the agent just calls
# evaluate_answers and reads its `remediation` field back.
_FUNCTION_TOOLS = [
    # curriculum-builder
    generate_learning_path,
    generate_daily_agenda,
    identify_content_gaps,
    trigger_curriculum_generation,
    # knowledge-coach
    generate_quiz,
    evaluate_answers,
    generate_reflection_prompt,
    get_user_progress,
    update_progress,
    determine_user_entry_path,
    check_bypass_eligibility,
    # department-reporter
    synthesize_department_kpi,
    get_department_readiness,
    flag_at_risk_users,
    # corporate-report-agent
    read_kpi_payloads,
    generate_executive_email,
]

def build_root_agent() -> Agent:
    """Construct a fresh root_agent from the current developer-console config
    and the skill files currently on disk.

    Called on every /api/chat request (see chat.py) instead of relying on a
    static module-level singleton, so edits made through the Agent Console —
    skill personas via `.agents/skills/*/SKILL.md`, or the orchestrator's own
    model/instruction via `data/dev_config.json` — take effect immediately,
    with no server restart. Construction is cheap (no network calls, just
    reading a handful of small local files), matching the read-every-call
    philosophy the rest of the app already uses for its JSON-backed stores.
    """
    orchestrator_cfg = get_config()["orchestrator"]

    # The SkillToolset exposes the declarative skills (list/load/run) plus the
    # function tools above as a single unit attached to the orchestrator.
    # _load_skills() re-reads every SKILL.md from disk on each call, so an
    # edited persona is picked up here too.
    skill_toolset = SkillToolset(
        skills=_load_skills(),
        additional_tools=_FUNCTION_TOOLS,
    )

    return Agent(
        model=orchestrator_cfg.get("model", MODEL),
        name="WAI_root_orchestrator",
        description="Transition Execution AI Platform (TEAP) — Root Orchestrator",
        instruction=orchestrator_cfg["instruction"],
        tools=[skill_toolset],
        before_tool_callback=luck_elimination_hook,
    )


# Module-level singleton kept for any importer that just wants *an* agent
# instance (e.g. `adk web`, which expects to find `root_agent` here). Live
# request paths (chat.py) call build_root_agent() directly instead, so they
# always see the latest console edits rather than this one-time snapshot.
root_agent = build_root_agent()
