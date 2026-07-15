"""Training Curriculum Builder Sub-Agent."""

from google.adk.agents.llm_agent import Agent

from .prompt import CURRICULUM_BUILDER_PROMPT
from src.services.curriculum_service import (
    generate_learning_path,
    generate_daily_agenda,
    identify_content_gaps,
)

curriculum_builder_agent = Agent(
    model="gemini-3.5-flash",
    name="curriculum_builder",
    description=(
        "Training Curriculum Builder — Analyzes documentation (DTPs, process flows) "
        "and generates structured learning paths, daily agendas, and gap analysis. "
        "Use this agent when the user wants to create or modify a training plan."
    ),
    instruction=CURRICULUM_BUILDER_PROMPT,
    tools=[
        generate_learning_path,
        generate_daily_agenda,
        identify_content_gaps,
    ],
)
