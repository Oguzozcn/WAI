"""Knowledge Base Validator Sub-Agent."""

from google.adk.agents.llm_agent import Agent

from .prompt import KBVALIDATOR_PROMPT
from ...tools.curriculum_tools import identify_content_gaps

kb_validator_agent = Agent(
    model="gemini-3.5-flash",
    name="kb_validator",
    description=(
        "Knowledge Base Validator — Compares new documents against the existing "
        "knowledge base to detect conflicts, inconsistencies, and gaps. "
        "Flags issues for human review. Use this agent when validating new DTPs, "
        "checking for document conflicts, or auditing knowledge base integrity."
    ),
    instruction=KBVALIDATOR_PROMPT,
    tools=[
        identify_content_gaps,
    ],
)
