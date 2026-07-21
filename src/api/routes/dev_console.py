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
    # generate_gap_review, generate_remedial_course, and handle_user_assessment_failure
    # are NOT directly agent-callable anymore (see agent.py's _FUNCTION_TOOLS
    # comment) — evaluate_answers invokes the first two itself, driven by the
    # single remediation_policy decision, so they no longer need their own
    # tool nodes here.
    "knowledge-coach": [
        "generate_quiz", "evaluate_answers", "generate_reflection_prompt",
        "get_user_progress", "update_progress", "determine_user_entry_path",
        "check_bypass_eligibility",
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

# Deterministic (non-LLM) tools whose behavior is still driven by tunable
# numeric constants. Maps tool name -> logic_params category (see
# dev_config.DEFAULT_CONFIG["logic_params"]), or the sentinel "platform_params"
# for tools that only read knobs already exposed via Platform Parameters.
TOOL_LOGIC_CATEGORY = {
    "evaluate_answers": "assessment_scoring",
    "update_progress": "readiness_scoring",
    "determine_user_entry_path": "adaptive_routing",
    "trigger_curriculum_generation": "curriculum_generation",
    "identify_content_gaps": "curriculum_generation",
    "flag_at_risk_users": "platform_params",
    "get_user_progress": "platform_params",
}

# Known fields per logic_params category — used to validate PATCH bodies so a
# typo'd key fails loudly instead of silently no-op'ing.
LOGIC_PARAM_FIELDS = {
    "assessment_scoring": {
        "irt_learning_rate", "irt_theta_clamp", "irt_default_discrimination",
        "irt_default_guessing", "irt_default_slip",
    },
    "readiness_scoring": {
        "course_completion_weight", "quiz_performance_weight",
        "state_progress_weight", "quiz_window_size",
    },
    "luck_elimination": {"core_drift_concept_count", "hlr_retention_threshold", "hlr_ability_threshold"},
    "adaptive_routing": {"confidence_threshold", "accuracy_threshold"},
    "curriculum_generation": {
        "conflict_overlap_ratio", "conflict_min_overlap_count",
        "pregenerated_short_quiz_questions", "pregenerated_final_assessment_questions",
        "remedial_short_quiz_questions", "remedial_final_assessment_questions",
    },
}


def _validate_logic_params(category: str, merged: dict) -> str | None:
    """Return an error message if `merged` (current values with the patch
    already applied) is out of range, else None. Runs on the POST-merge state
    so a partial update is checked in the shape it will actually be saved."""
    if category == "assessment_scoring":
        if not (0 < merged["irt_learning_rate"] <= 2):
            return "irt_learning_rate must be greater than 0 and at most 2."
        if not (1 <= merged["irt_theta_clamp"] <= 10):
            return "irt_theta_clamp must be between 1 and 10."
        if not (merged["irt_default_discrimination"] > 0):
            return "irt_default_discrimination must be greater than 0."
        if not (0 <= merged["irt_default_guessing"] < merged["irt_default_slip"] <= 1):
            return "irt_default_guessing must be less than irt_default_slip, and both must be within 0-1."
    elif category == "readiness_scoring":
        weights = (
            merged["course_completion_weight"],
            merged["quiz_performance_weight"],
            merged["state_progress_weight"],
        )
        if not all(0 <= w <= 1 for w in weights):
            return "All three readiness weights must be between 0 and 1."
        total = sum(weights)
        if abs(total - 1.0) > 0.02:
            return f"course_completion_weight + quiz_performance_weight + state_progress_weight must sum to ~1.0 (currently {total:.2f})."
        if merged["quiz_window_size"] < 1:
            return "quiz_window_size must be at least 1."
    elif category == "luck_elimination":
        if merged["core_drift_concept_count"] < 1:
            return "core_drift_concept_count must be at least 1."
        if not (0 <= merged["hlr_retention_threshold"] <= 1):
            return "hlr_retention_threshold must be between 0 and 1."
        if not (0 <= merged["hlr_ability_threshold"] <= 1):
            return "hlr_ability_threshold must be between 0 and 1."
    elif category == "adaptive_routing":
        if not (0 <= merged["confidence_threshold"] <= 1):
            return "confidence_threshold must be between 0 and 1."
        if not (0 <= merged["accuracy_threshold"] <= 1):
            return "accuracy_threshold must be between 0 and 1."
    elif category == "curriculum_generation":
        if not (0 <= merged["conflict_overlap_ratio"] <= 1):
            return "conflict_overlap_ratio must be between 0 and 1."
        if merged["conflict_min_overlap_count"] < 1:
            return "conflict_min_overlap_count must be at least 1."
        platform_params = get_config()["platform_params"]
        max_quiz_q = platform_params["MAX_QUIZ_QUESTIONS"]
        max_assess_q = platform_params["MAX_ASSESSMENT_QUESTIONS"]
        for key in ("pregenerated_short_quiz_questions", "remedial_short_quiz_questions"):
            if not (1 <= merged[key] <= max_quiz_q):
                return f"{key} must be between 1 and the configured MAX_QUIZ_QUESTIONS ({max_quiz_q})."
        for key in ("pregenerated_final_assessment_questions", "remedial_final_assessment_questions"):
            if not (1 <= merged[key] <= max_assess_q):
                return f"{key} must be between 1 and the configured MAX_ASSESSMENT_QUESTIONS ({max_assess_q})."
    return None


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
            "logic_category": TOOL_LOGIC_CATEGORY.get(name),
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
        "generate_remedial_course": {
            "gap_text": "1. Sample gap",
            "short_quiz_question_count": 3,
            "final_assessment_question_count": 5,
        },
        "generate_uat_report": {
            "run_summary": "Run UAT-0001: 20 pass, 2 fail, 1 blocked, 0 not run, out of 23 checks.",
            "results_json": '[{"id": "AUTH-01", "result": "pass"}]',
        },
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
    MAX_COURSES: int | None = None
    DEFAULT_TIMEFRAME_WEEKS: int | None = None
    AT_RISK_READINESS_THRESHOLD: float | None = None
    AT_RISK_PERCENTAGE_THRESHOLD: float | None = None
    LUCK_FAILURE_THRESHOLD: int | None = None


@router.patch("/config/platform-params")
async def api_dev_update_platform_params(body: PlatformParamsUpdate):
    _require_developer(body.role)
    patch = body.model_dump(exclude={"role"}, exclude_none=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No parameters provided.")
    if "PASS_THRESHOLD" in patch and not (0 < patch["PASS_THRESHOLD"] <= 1):
        raise HTTPException(status_code=400, detail="PASS_THRESHOLD must be between 0 and 1.")
    if "AT_RISK_READINESS_THRESHOLD" in patch and not (0 <= patch["AT_RISK_READINESS_THRESHOLD"] <= 1):
        raise HTTPException(status_code=400, detail="AT_RISK_READINESS_THRESHOLD must be between 0 and 1.")
    if "AT_RISK_PERCENTAGE_THRESHOLD" in patch and not (0 <= patch["AT_RISK_PERCENTAGE_THRESHOLD"] <= 100):
        raise HTTPException(status_code=400, detail="AT_RISK_PERCENTAGE_THRESHOLD must be between 0 and 100.")
    if "MAX_COURSES" in patch and patch["MAX_COURSES"] < 1:
        raise HTTPException(status_code=400, detail="MAX_COURSES must be at least 1.")
    if "DEFAULT_TIMEFRAME_WEEKS" in patch and patch["DEFAULT_TIMEFRAME_WEEKS"] < 1:
        raise HTTPException(status_code=400, detail="DEFAULT_TIMEFRAME_WEEKS must be at least 1.")
    if "LUCK_FAILURE_THRESHOLD" in patch and patch["LUCK_FAILURE_THRESHOLD"] < 1:
        raise HTTPException(status_code=400, detail="LUCK_FAILURE_THRESHOLD must be at least 1.")

    config = update_config(["platform_params"], patch)
    return config["platform_params"]


class LogicParamsUpdate(BaseModel):
    role: str = ""
    values: dict[str, float] = {}


@router.patch("/config/logic-params/{category}")
async def api_dev_update_logic_params(category: str, body: LogicParamsUpdate):
    _require_developer(body.role)
    if category not in LOGIC_PARAM_FIELDS:
        raise HTTPException(status_code=404, detail=f"Unknown logic-params category '{category}'.")
    if not body.values:
        raise HTTPException(status_code=400, detail="No values provided.")

    unknown_keys = set(body.values) - LOGIC_PARAM_FIELDS[category]
    if unknown_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown field(s) for '{category}': {', '.join(sorted(unknown_keys))}. "
                   f"Valid fields: {', '.join(sorted(LOGIC_PARAM_FIELDS[category]))}.",
        )

    current = get_config()["logic_params"][category]
    merged = {**current, **body.values}
    error = _validate_logic_params(category, merged)
    if error:
        raise HTTPException(status_code=400, detail=error)

    config = update_config(["logic_params", category], body.values)
    return config["logic_params"][category]
