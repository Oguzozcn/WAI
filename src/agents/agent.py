"""
TEAP Root Orchestrator Agent — ADK 2.0
========================================
Routes users to the appropriate declarative skill based on intent.

Skills are loaded dynamically from .agents/skills/ via the SkillToolset,
following the ADK 2.0 declarative architecture. No imperative sub-agent
Python classes are used; all persona and instruction definitions live
in .agents/skills/<skill-name>/SKILL.md.
"""

import os
from pathlib import Path

from google.adk.agents.llm_agent import Agent

# ── Skill Discovery ──
# Resolve the .agents/skills/ path relative to the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SKILLS_DIR = _PROJECT_ROOT / ".agents" / "skills"

# ── Tool Imports (shared across skills and API routes) ──
from src.services.curriculum_service import (
    generate_learning_path,
    generate_daily_agenda,
    identify_content_gaps,
)
from src.services.quiz_service import (
    generate_quiz,
    evaluate_quiz_answers,
    get_user_knowledge_gaps,
)
from src.services.user_service import (
    get_user_progress,
    update_user_progress,
    enroll_user,
)
from src.services.reporting_service import (
    generate_department_kpi_report,
    generate_corporate_summary,
)
from src.services.routing_service import (
    determine_user_entry_path,
    handle_user_assessment_failure,
    check_bypass_eligibility,
)

root_agent = Agent(
    model="gemini-2.0-flash",
    name="WAI_root_orchestrator",
    description="Transition Execution AI Platform (TEAP) — Root Orchestrator",
    instruction="""You are the Root Orchestrator for the Transition Execution AI Platform (TEAP).

Your job is to understand the user's intent and invoke the correct declarative skill or tool.

ROUTING RULES:
- If the user wants to create/modify a training plan or learning path → use curriculum-builder skill
- If the user wants to take a quiz or be assessed → use knowledge-coach skill
- If the user wants to upload or validate knowledge base documents → use kb-validator skill
- If the user wants department KPI metrics → use department-reporter skill
- If the user wants corporate-level reports → use corporate-report-agent skill

IMPORTANT RULES:
- The platform operates within the "operations" department for the MVP
- Always greet the user and help them understand what the platform can do
- If the user's intent is unclear, ask a clarifying question
- All data access is department-scoped — you cannot cross department boundaries
""",
    tools=[
        generate_learning_path,
        generate_daily_agenda,
        identify_content_gaps,
        generate_quiz,
        evaluate_quiz_answers,
        get_user_knowledge_gaps,
        get_user_progress,
        update_user_progress,
        enroll_user,
        generate_department_kpi_report,
        generate_corporate_summary,
        determine_user_entry_path,
        handle_user_assessment_failure,
        check_bypass_eligibility,
    ],
)
