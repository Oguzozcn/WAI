"""Knowledge Coach Sub-Agent."""

from google.adk.agents.llm_agent import Agent

from .prompt import KNOWLEDGE_COACH_PROMPT
from ...tools.quiz_tools import (
    generate_quiz,
    evaluate_answers,
    generate_reflection_prompt,
    generate_gap_review,
)
from ...tools.routing_tools import (
    determine_user_entry_path,
    handle_user_assessment_failure,
    check_bypass_eligibility,
)
from ...tools.progress_tools import (
    get_user_progress,
    update_progress,
)

knowledge_coach_agent = Agent(
    model="gemini-3.5-flash",
    name="knowledge_coach",
    description=(
        "Knowledge Coach — Generates personalized quizzes and assessments, "
        "evaluates understanding, identifies knowledge gaps, and provides "
        "Duolingo-style spaced repetition coaching. Use this agent when the "
        "user wants to take a quiz, be assessed, check their progress, or "
        "review their knowledge gaps."
    ),
    instruction=KNOWLEDGE_COACH_PROMPT,
    tools=[
        generate_quiz,
        evaluate_answers,
        generate_reflection_prompt,
        generate_gap_review,
        determine_user_entry_path,
        handle_user_assessment_failure,
        check_bypass_eligibility,
        get_user_progress,
        update_progress,
    ],
)
