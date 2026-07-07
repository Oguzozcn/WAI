"""Corporate Report Agent (Tier 3 — AGGREGATE side)."""

from google.adk.agents.llm_agent import Agent

from .prompt import CORPORATE_REPORT_PROMPT
from ...tools.reporting_tools import (
    read_kpi_payloads,
    generate_executive_email,
)

corporate_report_agent = Agent(
    model="gemini-3.5-flash",
    name="corporate_report_agent",
    description=(
        "Corporate Report Agent — Reads ONLY from the central KPI store to compile "
        "cross-department executive summaries and email-ready reports. Has ZERO access "
        "to individual user data, agent sessions, or departmental internals. "
        "Use this agent for executive reporting, corporate summaries, or email drafts."
    ),
    instruction=CORPORATE_REPORT_PROMPT,
    tools=[
        read_kpi_payloads,
        generate_executive_email,
    ],
)
