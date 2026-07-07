"""
TEAP Adaptive Learning State Machine
======================================
Manages state transitions for the learning journey.

Three entry paths:
  - Veteran: Fast-track → direct validation assessment
  - Intermediate: Choice of gap rerun OR validation test
  - Standard: 10-course track → short quizzes → validation assessment

Two failure cases:
  - Case 1 (Bypass Fail): Score <80% on direct assessment → mandatory path, bypass locked
  - Case 2 (Standard Fail): Can retake iteratively, gaps targeted via spaced repetition
"""

from .constants import (
    PASS_THRESHOLD,
    STATE_ENROLLED, STATE_FAST_TRACK, STATE_INTERMEDIATE_CHOICE,
    STATE_STANDARD_PATH, STATE_COURSE_IN_PROGRESS, STATE_SHORT_QUIZ,
    STATE_VALIDATION_ASSESSMENT, STATE_PASSED, STATE_FAILED,
    STATE_BYPASS_LOCKED, STATE_MANDATORY_PATH, STATE_GAP_REVIEW,
    STATE_METACOGNITIVE_REFLECTION, STATE_SPACED_REPETITION, STATE_COMPLETED,
    ENTRY_PATH_VETERAN, ENTRY_PATH_INTERMEDIATE, ENTRY_PATH_STANDARD,
)


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


# Valid state transitions map
_VALID_TRANSITIONS: dict[str, list[str]] = {
    STATE_ENROLLED: [STATE_FAST_TRACK, STATE_INTERMEDIATE_CHOICE, STATE_STANDARD_PATH],
    STATE_FAST_TRACK: [STATE_VALIDATION_ASSESSMENT],
    STATE_INTERMEDIATE_CHOICE: [STATE_GAP_REVIEW, STATE_VALIDATION_ASSESSMENT],
    STATE_STANDARD_PATH: [STATE_COURSE_IN_PROGRESS],
    STATE_COURSE_IN_PROGRESS: [STATE_SHORT_QUIZ, STATE_COURSE_IN_PROGRESS],  # Next course
    STATE_SHORT_QUIZ: [STATE_COURSE_IN_PROGRESS, STATE_VALIDATION_ASSESSMENT, STATE_METACOGNITIVE_REFLECTION],
    STATE_VALIDATION_ASSESSMENT: [STATE_PASSED, STATE_FAILED],
    STATE_PASSED: [STATE_COMPLETED],
    STATE_FAILED: [STATE_BYPASS_LOCKED, STATE_GAP_REVIEW],
    STATE_BYPASS_LOCKED: [STATE_MANDATORY_PATH],
    STATE_MANDATORY_PATH: [STATE_COURSE_IN_PROGRESS],
    STATE_GAP_REVIEW: [STATE_SPACED_REPETITION, STATE_VALIDATION_ASSESSMENT],
    STATE_METACOGNITIVE_REFLECTION: [STATE_SPACED_REPETITION, STATE_COURSE_IN_PROGRESS],
    STATE_SPACED_REPETITION: [STATE_GAP_REVIEW, STATE_VALIDATION_ASSESSMENT, STATE_COURSE_IN_PROGRESS],
    STATE_COMPLETED: [],  # Terminal state
}


def determine_entry_path(experience_level: str) -> str:
    """
    Determine which entry path a user should follow based on their experience.
    
    Args:
        experience_level: One of "veteran", "intermediate", "standard"
    
    Returns:
        The initial state after enrollment.
    """
    path_map = {
        ENTRY_PATH_VETERAN: STATE_FAST_TRACK,
        ENTRY_PATH_INTERMEDIATE: STATE_INTERMEDIATE_CHOICE,
        ENTRY_PATH_STANDARD: STATE_STANDARD_PATH,
    }

    if experience_level not in path_map:
        raise ValueError(
            f"Unknown experience level: '{experience_level}'. "
            f"Must be one of: {list(path_map.keys())}"
        )

    return path_map[experience_level]


def validate_transition(current_state: str, target_state: str) -> bool:
    """
    Check if a state transition is valid.
    
    Returns True if the transition is allowed, raises InvalidTransitionError otherwise.
    """
    valid_targets = _VALID_TRANSITIONS.get(current_state, [])

    if target_state not in valid_targets:
        raise InvalidTransitionError(
            f"Cannot transition from '{current_state}' to '{target_state}'. "
            f"Valid targets: {valid_targets}"
        )

    return True


def handle_assessment_result(
    score: float,
    was_bypass_attempt: bool,
    bypass_already_locked: bool,
) -> dict:
    """
    Determine the next state after a validation assessment.
    
    Args:
        score: Assessment score as a decimal (0.0 - 1.0)
        was_bypass_attempt: True if the user skipped the learning path
        bypass_already_locked: True if the user's bypass was previously locked
    
    Returns:
        dict with:
          - "passed": bool
          - "next_state": str
          - "lock_bypass": bool (whether to lock bypass for this user)
          - "reason": str (explanation for the transition)
    """
    passed = score >= PASS_THRESHOLD

    if passed:
        return {
            "passed": True,
            "next_state": STATE_PASSED,
            "lock_bypass": False,
            "reason": f"Score {score:.0%} meets the {PASS_THRESHOLD:.0%} threshold. Proceeding to completion.",
        }

    # FAILED — determine Case 1 or Case 2
    if was_bypass_attempt and not bypass_already_locked:
        # Case 1: Bypass Failure → Lock bypass, mandatory learning path
        return {
            "passed": False,
            "next_state": STATE_BYPASS_LOCKED,
            "lock_bypass": True,
            "reason": (
                f"Score {score:.0%} below {PASS_THRESHOLD:.0%} on bypass attempt. "
                f"Bypass is now LOCKED. Full learning path is mandatory. "
                f"Completed modules will be excluded."
            ),
        }
    else:
        # Case 2: Standard Failure → Gap review, iterative retakes allowed
        return {
            "passed": False,
            "next_state": STATE_GAP_REVIEW,
            "lock_bypass": False,
            "reason": (
                f"Score {score:.0%} below {PASS_THRESHOLD:.0%}. "
                f"Entering gap review mode. You can review weak areas "
                f"and retake the assessment."
            ),
        }


def get_mandatory_courses(
    all_course_ids: list[str],
    completed_course_ids: list[str],
) -> list[str]:
    """
    After a bypass lockout (Case 1), determine which courses are mandatory.
    Removes already-completed courses from the full path.
    
    Args:
        all_course_ids: All course IDs in the learning path
        completed_course_ids: Course IDs the user has already completed
    
    Returns:
        List of course IDs that must be completed before reassessment.
    """
    completed_set = set(completed_course_ids)
    return [cid for cid in all_course_ids if cid not in completed_set]


def get_state_description(state: str) -> str:
    """Return a human-readable description of a learning state."""
    descriptions = {
        STATE_ENROLLED: "Enrolled and awaiting path assignment",
        STATE_FAST_TRACK: "Fast-track: proceeding directly to validation assessment",
        STATE_INTERMEDIATE_CHOICE: "Choose: rerun gap areas or take validation test",
        STATE_STANDARD_PATH: "Starting the standard 10-course learning path",
        STATE_COURSE_IN_PROGRESS: "Currently working through a course module",
        STATE_SHORT_QUIZ: "Taking a short quiz on the current module",
        STATE_VALIDATION_ASSESSMENT: "Taking the full validation assessment",
        STATE_PASSED: "Assessment passed! Updating competency matrix",
        STATE_FAILED: "Assessment not passed — determining next steps",
        STATE_BYPASS_LOCKED: "Bypass locked — full learning path is now mandatory",
        STATE_MANDATORY_PATH: "Completing mandatory courses before reassessment",
        STATE_GAP_REVIEW: "Reviewing identified knowledge gaps",
        STATE_METACOGNITIVE_REFLECTION: "Reflecting on why specific answers were wrong",
        STATE_SPACED_REPETITION: "Duolingo-style spaced repetition on weak areas",
        STATE_COMPLETED: "All requirements met — transition complete",
    }
    return descriptions.get(state, f"Unknown state: {state}")
