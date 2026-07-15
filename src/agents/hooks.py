"""
TEAP Lifecycle Hooks
====================
Intercepts agent decisions to enforce corporate policies.
"""

from typing import Any

# In a real environment, you would import this from google.adk
# from google.adk.hooks import PreToolCallDecideHook

class PreToolCallDecideHook:
    """Mock base class for PreToolCallDecideHook until SDK is fully installed."""
    def __init__(self, **kwargs):
        pass

from WAI_agent.shared.luck_elimination import evaluate_luck_and_decay, ACTION_FORCE_MANDATORY

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
        
        # Example logic to intercept based on error retention matrix
        error_matrix = user_progress.get("error_retention_matrix", {})
        
        # Check if any concept exceeds the failure threshold (via the shared logic engine)
        from WAI_agent.shared.constants import LUCK_FAILURE_THRESHOLD
        
        for concept, failures in error_matrix.items():
            if failures >= LUCK_FAILURE_THRESHOLD:
                # Deny the tool call and provide a reason to the agent
                return {
                    "allow": False,
                    "reason": (
                        f"Luck Elimination Policy Triggered: User has failed concept '{concept}' "
                        f"{failures} times. Fast-tracking is denied. You must force the mandatory "
                        f"learning path."
                    )
                }
        
        return {"allow": True}
