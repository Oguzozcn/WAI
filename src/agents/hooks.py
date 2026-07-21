"""
TEAP Agent Hooks — ADK 2.3
============================
Intercepts agent tool calls to enforce the Luck Elimination policy: a user who
has repeatedly failed the same concept must not be allowed to fast-track past
it via check_bypass_eligibility / determine_user_entry_path.

Consults the same LuckEliminationEngine that backs src.core.remediation_policy
rather than re-deriving its own threshold check, so this gate can't silently
drift from the policy every other remediation entry point agrees on.
"""

from src.core.luck_elimination import LuckEliminationEngine

_GATED_TOOLS = ("check_bypass_eligibility", "determine_user_entry_path")


def luck_elimination_hook(tool, args: dict, tool_context) -> dict | None:
    """ADK before_tool_callback: block fast-track tools for users stuck on a concept.

    Returning a dict short-circuits the tool call with that dict as its result;
    returning None lets the tool execute normally. ADK invokes this callback
    with keyword arguments tool=, args=, tool_context= (confirmed against the
    installed SDK's call site in flows/llm_flows/functions.py).
    """
    if tool.name not in _GATED_TOOLS:
        return None

    user_progress = (getattr(tool_context, "state", None) or {}).get("user_progress", {})
    error_matrix = user_progress.get("error_retention_matrix", {})

    luck_result = LuckEliminationEngine().evaluate_user_progression(error_matrix)
    if luck_result["flagged_concepts"]:
        concepts = ", ".join(luck_result["flagged_concepts"])
        return {
            "error": "luck_elimination_policy_triggered",
            "message": (
                f"Luck Elimination Policy Triggered: user has repeatedly failed "
                f"concept(s) '{concepts}'. Fast-tracking is denied — route "
                f"the user to the mandatory learning path instead."
            ),
        }

    return None
