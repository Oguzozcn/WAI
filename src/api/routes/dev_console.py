"""Developer Agent Console API.

Backs the developer-only /dev-console page: a node graph of the platform's
orchestrator/skills/tools, and CRUD for the developer-editable config that
drives them (data/dev_config.json via src/core/dev_config.py, plus the
.agents/skills/*/SKILL.md persona files, which stay their own source of truth
rather than being duplicated into dev_config.json).

Role gating mirrors the existing `_require_manager` pattern in
knowledge_base.py / manager.py — client-trusted, not cryptographic, matching
this app's existing trust model everywhere else.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.agents.agent import _FUNCTION_TOOLS
from src.core.dev_config import get_config, update_config

router = APIRouter(prefix="/api/dev", tags=["dev_console"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SKILLS_DIR = PROJECT_ROOT / ".agents" / "skills"

# Curated grouping matching the `# comment` blocks in agent.py's
# _FUNCTION_TOOLS list. ADK itself doesn't partition tools per skill (they're
# all flatly attached to one SkillToolset) — this mapping is informational,
# reflecting how the code is actually organized today.
SKILL_TOOL_GROUPS = {
    "curriculum-builder": [
        "generate_learning_path", "generate_daily_agenda",
        "identify_content_gaps", "trigger_curriculum_generation",
    ],
    "knowledge-coach": [
        "generate_quiz", "evaluate_answers", "generate_reflection_prompt",
        "generate_gap_review", "generate_remedial_course", "get_user_progress",
        "update_progress", "determine_user_entry_path",
        "handle_user_assessment_failure", "check_bypass_eligibility",
    ],
    "kb-validator": [],
    "department-reporter": [
        "synthesize_department_kpi", "get_department_readiness", "flag_at_risk_users",
    ],
    "corporate-report-agent": [
        "read_kpi_payloads", "generate_executive_email",
    ],
}

# Tool names whose prompt is directly editable via dev_config.json's "tools"
# section (i.e. they call Gemini and are ADK-registered function tools).
LLM_ADK_TOOL_NAMES = {"generate_quiz", "generate_remedial_course"}

# process_document_to_curriculum also calls Gemini and has an editable prompt
# template, but it is NOT itself an ADK-registered tool — it's an internal
# helper trigger_curriculum_generation calls. Shown as a satellite node.
INTERNAL_LLM_TOOL = {
    "name": "process_document_to_curriculum",
    "called_by": "trigger_curriculum_generation",
    "description": "Course Splitter — turns each document section into a teaching summary. Internal helper, not itself an ADK tool.",
}


def _require_developer(role: str) -> None:
    if role != "developer":
        raise HTTPException(status_code=403, detail="Only a developer can perform this action.")


def _known_skill_ids() -> list[str]:
    if not SKILLS_DIR.exists():
        return []
    return sorted(p.name for p in SKILLS_DIR.iterdir() if (p / "SKILL.md").exists())


def _read_skill_file(skill_id: str) -> dict:
    """Parse a SKILL.md's YAML-ish frontmatter (name/description) + body."""
    path = SKILLS_DIR / skill_id / "SKILL.md"
    text = path.read_text(encoding="utf-8")

    if not text.startswith("---"):
        return {"skill_id": skill_id, "name": skill_id, "description": "", "instruction": text}

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {"skill_id": skill_id, "name": skill_id, "description": "", "instruction": text}

    frontmatter_raw, body = parts[1], parts[2].lstrip("\n")
    name, description = skill_id, ""
    for line in frontmatter_raw.strip().splitlines():
        if line.startswith("name:"):
            name = line[len("name:"):].strip()
        elif line.startswith("description:"):
            description = line[len("description:"):].strip()

    return {"skill_id": skill_id, "name": name, "description": description, "instruction": body}


def _write_skill_file(skill_id: str, name: str, description: str, instruction: str) -> None:
    path = SKILLS_DIR / skill_id / "SKILL.md"
    content = f"---\nname: {name}\ndescription: {description}\n---\n\n{instruction.strip()}\n"
    path.write_text(content, encoding="utf-8")


@router.get("/graph")
async def api_dev_graph():
    """Node/edge topology for the Agent Console graph.

    Tool nodes are built by introspecting the real `_FUNCTION_TOOLS` objects
    from agent.py (name + first doc line), so this can't silently drift from
    the code the way a hand-maintained copy could.
    """
    tool_by_name = {fn.__name__: fn for fn in _FUNCTION_TOOLS}

    skills = []
    for skill_id in _known_skill_ids():
        meta = _read_skill_file(skill_id)
        tool_names = SKILL_TOOL_GROUPS.get(skill_id, [])
        skills.append({
            "skill_id": skill_id,
            "name": meta["name"],
            "description": meta["description"],
            "tools": tool_names,
        })

    tools = []
    for name, fn in tool_by_name.items():
        doc = (fn.__doc__ or "").strip().splitlines()
        tools.append({
            "name": name,
            "description": doc[0].strip() if doc else "",
            "has_llm_prompt": name in LLM_ADK_TOOL_NAMES,
        })
    # Satellite node: an LLM-calling helper that isn't itself an ADK tool.
    tools.append({
        "name": INTERNAL_LLM_TOOL["name"],
        "description": INTERNAL_LLM_TOOL["description"],
        "has_llm_prompt": True,
        "called_by": INTERNAL_LLM_TOOL["called_by"],
    })

    orchestrator_cfg = get_config()["orchestrator"]

    return {
        "orchestrator": {
            "name": "WAI_root_orchestrator",
            "model": orchestrator_cfg.get("model", ""),
        },
        "skills": skills,
        "tools": tools,
        "llm_tool_names": sorted(LLM_ADK_TOOL_NAMES | {INTERNAL_LLM_TOOL["name"]}),
        "gemini_model": get_config()["platform_params"].get("GEMINI_MODEL", ""),
    }


@router.get("/config")
async def api_dev_get_config():
    """Full current dev_config.json plus the live SKILL.md content for each skill."""
    config = get_config()
    skills = [_read_skill_file(skill_id) for skill_id in _known_skill_ids()]
    return {**config, "skills": skills}


class OrchestratorUpdate(BaseModel):
    role: str = ""
    model: str = ""
    instruction: str = ""


@router.patch("/config/orchestrator")
async def api_dev_update_orchestrator(body: OrchestratorUpdate):
    _require_developer(body.role)
    if not body.instruction.strip():
        raise HTTPException(status_code=400, detail="Instruction cannot be empty.")
    patch = {"instruction": body.instruction}
    if body.model.strip():
        patch["model"] = body.model.strip()
    config = update_config(["orchestrator"], patch)
    return config["orchestrator"]


class SkillUpdate(BaseModel):
    role: str = ""
    name: str = ""
    description: str = ""
    instruction: str = ""


@router.patch("/config/skill/{skill_id}")
async def api_dev_update_skill(skill_id: str, body: SkillUpdate):
    _require_developer(body.role)
    if skill_id not in _known_skill_ids():
        raise HTTPException(status_code=404, detail=f"Unknown skill '{skill_id}'.")
    if not body.name.strip() or not body.instruction.strip():
        raise HTTPException(status_code=400, detail="Name and instruction cannot be empty.")

    _write_skill_file(skill_id, body.name.strip(), body.description.strip(), body.instruction)
    return _read_skill_file(skill_id)


class ToolUpdate(BaseModel):
    role: str = ""
    model: str = ""
    prompt_template: str = ""


@router.patch("/config/tool/{tool_name}")
async def api_dev_update_tool(tool_name: str, body: ToolUpdate):
    _require_developer(body.role)
    config = get_config()
    if tool_name not in config["tools"]:
        raise HTTPException(status_code=404, detail=f"'{tool_name}' has no editable prompt (it's deterministic, or unknown).")
    if not body.prompt_template.strip():
        raise HTTPException(status_code=400, detail="Prompt template cannot be empty.")

    # Dry-run validate: the template must render with dummy values for every
    # placeholder this tool actually uses, so a broken edit never reaches a
    # real user-facing call. Placeholder sets mirror the call sites in
    # quiz_service.py / curriculum_service.py exactly.
    dummy_values = {
        "generate_quiz": {"question_count": 3, "topic": "Sample Topic", "difficulty": "medium", "grounding_context": "Sample grounding text."},
        "process_document_to_curriculum": {"section_count": 2, "sections_text": "--- SECTION 0 ---\nSample"},
        "generate_remedial_course": {"gap_text": "1. Sample gap"},
    }[tool_name]
    try:
        body.prompt_template.format(**dummy_values)
    except (KeyError, IndexError, ValueError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Prompt template is invalid — check your {{placeholders}}. Valid placeholders: {', '.join(dummy_values.keys())}. Error: {e}",
        )

    patch = {"prompt_template": body.prompt_template}
    if body.model.strip():
        patch["model"] = body.model.strip()
    config = update_config(["tools", tool_name], patch)
    return config["tools"][tool_name]


class PlatformParamsUpdate(BaseModel):
    role: str = ""
    GEMINI_MODEL: str | None = None
    PASS_THRESHOLD: float | None = None
    MAX_QUIZ_QUESTIONS: int | None = None
    MAX_ASSESSMENT_QUESTIONS: int | None = None
    MAX_QUIZ_ATTEMPTS: int | None = None


@router.patch("/config/platform-params")
async def api_dev_update_platform_params(body: PlatformParamsUpdate):
    _require_developer(body.role)
    patch = body.model_dump(exclude={"role"}, exclude_none=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No parameters provided.")
    if "PASS_THRESHOLD" in patch and not (0 < patch["PASS_THRESHOLD"] <= 1):
        raise HTTPException(status_code=400, detail="PASS_THRESHOLD must be between 0 and 1.")

    config = update_config(["platform_params"], patch)
    return config["platform_params"]
