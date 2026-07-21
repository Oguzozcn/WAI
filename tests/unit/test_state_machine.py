"""Unit tests for handle_assessment_result's Case 1 / Case 2 branching."""

from src.core.state_machine import (
    STATE_PASSED,
    STATE_GAP_REVIEW,
    STATE_BYPASS_LOCKED,
    handle_assessment_result,
    get_mandatory_courses,
)
from src.core.config import PASS_THRESHOLD


def test_passing_score_returns_passed_regardless_of_bypass_flags():
    result = handle_assessment_result(
        score=PASS_THRESHOLD, was_bypass_attempt=True, bypass_already_locked=False
    )
    assert result["passed"] is True
    assert result["next_state"] == STATE_PASSED
    assert result["lock_bypass"] is False


def test_case_1_bypass_attempt_failure_locks_bypass():
    result = handle_assessment_result(
        score=PASS_THRESHOLD - 0.01, was_bypass_attempt=True, bypass_already_locked=False
    )
    assert result["passed"] is False
    assert result["next_state"] == STATE_BYPASS_LOCKED
    assert result["lock_bypass"] is True


def test_case_1_does_not_relock_an_already_locked_bypass():
    """Once bypass is already locked, a further failure (even a bypass
    attempt) falls through to Case 2 — there's nothing left to lock."""
    result = handle_assessment_result(
        score=PASS_THRESHOLD - 0.01, was_bypass_attempt=True, bypass_already_locked=True
    )
    assert result["passed"] is False
    assert result["next_state"] == STATE_GAP_REVIEW
    assert result["lock_bypass"] is False


def test_case_2_standard_path_failure_spawns_gap_review_not_lockout():
    result = handle_assessment_result(
        score=PASS_THRESHOLD - 0.01, was_bypass_attempt=False, bypass_already_locked=False
    )
    assert result["passed"] is False
    assert result["next_state"] == STATE_GAP_REVIEW
    assert result["lock_bypass"] is False


def test_get_mandatory_courses_excludes_completed():
    all_courses = ["course_01", "course_02", "course_03"]
    completed = ["course_02"]
    mandatory = get_mandatory_courses(all_courses, completed)
    assert mandatory == ["course_01", "course_03"]


def test_get_mandatory_courses_empty_when_all_completed():
    all_courses = ["course_01", "course_02"]
    assert get_mandatory_courses(all_courses, all_courses) == []
