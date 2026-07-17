"""
TEAP Agent Hooks — ADK 2.0
============================
Intercepts agent decisions to enforce corporate policies.
Refactored from src/agents/hooks.py to import from src/core/ only.
"""

from typing import Any

# In a real environment, you would import this from google.adk
# from google.adk.hooks import PreToolCallDecideHook

class PreToolCallDecideHook:
    """Base class placeholder for PreToolCallDecideHook until SDK hook API is stable."""
    def __init__(self, **kwargs):
        pass


from src.core.luck_elimination import evaluate_luck_and_decay, ACTION_FORCE_MANDATORY
from src.core.config import LUCK_FAILURE_THRESHOLD


class LuckEliminationHook(PreToolCallDecideHook):
    """
    Intercepts routing tool calls (e.g. check_bypass_eligibility, determine_user_entry_path)
    to check if the user has failed a concept too many times. If so, denies the tool call
    and forces the LLM to route them to the mandatory path.
    """

    def on_pre_tool_call(self, tool_name: str, args: dict, context: Any) -> dict:
        # We only care about fast-track/routing tools
        if tool_name not in ("check_bypass_eligibility", "determine_user_entry_path"):
            return {"allow": True}

        # In ADK, the context holds session state (e.g., user_progress)
        user_progress = getattr(context, "state", {}).get("user_progress", {})

        # Check error retention matrix via the luck elimination engine
        error_matrix = user_progress.get("error_retention_matrix", {})

        for concept, failures in error_matrix.items():
            if failures >= LUCK_FAILURE_THRESHOLD:
                return {
                    "allow": False,
                    "reason": (
                        f"Luck Elimination Policy Triggered: User has failed concept '{concept}' "
                        f"{failures} times. Fast-tracking is denied. You must force the mandatory "
                        f"learning path."
                    )
                }

        return {"allow": True}
