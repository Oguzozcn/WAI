"""Unit tests for the ADK before_tool_callback luck-elimination gate."""

from types import SimpleNamespace

from src.agents.hooks import luck_elimination_hook
from src.core.config import LUCK_FAILURE_THRESHOLD


def _fake_tool(name):
    return SimpleNamespace(name=name)


def _fake_context(failures):
    state = {"user_progress": {"error_retention_matrix": {"concept_x": failures}}}
    return SimpleNamespace(state=state)


def test_hook_blocks_gated_tool_at_threshold():
    result = luck_elimination_hook(
        _fake_tool("check_bypass_eligibility"),
        {},
        _fake_context(LUCK_FAILURE_THRESHOLD),
    )
    assert isinstance(result, dict)
    assert result["error"] == "luck_elimination_policy_triggered"


def test_hook_allows_gated_tool_below_threshold():
    result = luck_elimination_hook(
        _fake_tool("check_bypass_eligibility"),
        {},
        _fake_context(LUCK_FAILURE_THRESHOLD - 1),
    )
    assert result is None


def test_hook_ignores_non_gated_tool_even_over_threshold():
    result = luck_elimination_hook(
        _fake_tool("generate_quiz"),
        {},
        _fake_context(LUCK_FAILURE_THRESHOLD + 10),
    )
    assert result is None
