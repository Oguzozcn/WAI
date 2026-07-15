"""
TEAP Root Orchestrator Agent
==============================
Routes users to the appropriate declarative skill based on intent.
"""

from google.adk.agents.llm_agent import Agent

# In a real environment, this imports from the SDK
class SkillToolset:
    """Mock SkillToolset to load declarative SKILL.md files."""
    def __init__(self):
        pass

root_agent = Agent(
    model="gemini-3.5-flash",
    name="WAI_agent",
    description="Transition Execution AI Platform — Root Orchestrator",
    instruction="""You are the Root Orchestrator for the Transition Execution AI Platform (TEAP).

Your job is to understand the user's intent and invoke the correct declarative skill.
You have access to a variety of skills via the SkillToolset.

IMPORTANT RULES:
- The platform operates within the "operations" department for the MVP
- Always greet the user and help them understand what the platform can do
- If the user's intent is unclear, ask a clarifying question
"""
)
