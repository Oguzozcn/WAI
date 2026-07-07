"""Department Reporter Sub-Agent (Tier 1 — PUSH side)."""

from google.adk.agents.llm_agent import Agent

from .prompt import DEPARTMENT_REPORTER_PROMPT
from ...tools.reporting_tools import synthesize_department_kpi

department_reporter_agent = Agent(
    model="gemini-3.5-flash",
    name="department_reporter",
    description=(
        "Department Reporter — Reads user progress data within a single department "
        "scope, aggregates it into anonymized KPI metrics, and pushes a schema-validated "
        "payload to the central KPI store. Use this agent to generate daily department "
        "reports. Session is discarded after each invocation."
    ),
    instruction=DEPARTMENT_REPORTER_PROMPT,
    tools=[
        synthesize_department_kpi,
    ],
)
