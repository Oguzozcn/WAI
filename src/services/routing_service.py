"""
TEAP Routing Tools
===================
ADK function tools for adaptive path routing.
Determines entry paths, handles assessment failures, and manages bypass eligibility.
"""

from src.core.database import DepartmentScopedStore
from src.core.state_machine import (
    determine_entry_path,
    get_mandatory_courses,
    get_state_description,
)
from src.core.remediation_policy import decide_remediation
from src.core.config import (
    DEFAULT_DEPARTMENT, ENTRY_PATH_VETERAN, ENTRY_PATH_INTERMEDIATE, ENTRY_PATH_STANDARD,
    STATE_PASSED,
)
from src.core.dev_config import get_param, get_logic_param

class AdaptiveMetacognitiveRouter:
    """
    Implements Howell's Conscious-Competence matrix for routing.
    """

    @staticmethod
    def evaluate_competence(accuracy: float, average_confidence: float) -> str:
        confidence_threshold = get_logic_param("adaptive_routing", "confidence_threshold")
        accuracy_threshold = get_logic_param("adaptive_routing", "accuracy_threshold")
        # High confidence, low accuracy
        if average_confidence > confidence_threshold and accuracy < accuracy_threshold:
            return "hidden_knowledge_gaps"
        # Low confidence, low accuracy
        elif average_confidence <= confidence_threshold and accuracy < accuracy_threshold:
            return "conscious_incompetence"
        # Low confidence, high accuracy
        elif average_confidence <= confidence_threshold and accuracy >= accuracy_threshold:
            return "unconscious_competence"
        # High confidence, high accuracy
        else:
            return "conscious_competence"
            
    @staticmethod
    def get_recommended_path(competence_state: str) -> str:
        if competence_state == "hidden_knowledge_gaps":
            return ENTRY_PATH_STANDARD  # Immediate supportive remediation
        elif competence_state == "conscious_incompetence":
            return ENTRY_PATH_STANDARD
        elif competence_state == "unconscious_competence":
            return ENTRY_PATH_INTERMEDIATE
        else:
            return ENTRY_PATH_VETERAN
def determine_user_entry_path(
    user_id: str,
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Determine the learning entry path for a user based on their competency profile.

    Routes the user to one of three paths:
    - Veteran: Fast-track directly to validation assessment
    - Intermediate: Choice of gap rerun or validation test
    - Standard: Full learning path (all configured courses)

    Args:
        user_id: The user to evaluate
        department: The department scope

    Returns:
        Entry path recommendation with state and explanation.
    """
    store = DepartmentScopedStore(department)
    progress = store.read_user_progress(user_id)

    if progress is None:
        return {
            "status": "not_found",
            "message": (
                f"No profile found for user '{user_id}'. "
                f"Please provide the user's experience level: "
                f"'veteran', 'intermediate', or 'standard'."
            ),
        }

    # Determine path from profile or metacognitive router
    experience_level = progress.get("entry_path", "")
    
    # If not set explicitly, but we have quiz history
    if not experience_level and "average_confidence" in progress and "overall_accuracy" in progress:
        competence_state = AdaptiveMetacognitiveRouter.evaluate_competence(
            accuracy=progress["overall_accuracy"],
            average_confidence=progress["average_confidence"]
        )
        experience_level = AdaptiveMetacognitiveRouter.get_recommended_path(competence_state)
        progress["entry_path"] = experience_level
        store.write_user_progress(user_id, progress)

    if not experience_level:
        return {
            "status": "needs_assessment",
            "user_id": user_id,
            "message": (
                "No experience level set for this user. "
                "Please assess their background and set entry_path to "
                "'veteran', 'intermediate', or 'standard'."
            ),
        }

    initial_state = determine_entry_path(experience_level)
    state_desc = get_state_description(initial_state)

    return {
        "user_id": user_id,
        "experience_level": experience_level,
        "entry_path": experience_level,
        "initial_state": initial_state,
        "description": state_desc,
        "options": _get_path_options(experience_level),
    }


def handle_user_assessment_failure(
    user_id: str,
    score: float,
    was_bypass_attempt: bool = False,
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Handle the logic when a user fails a validation assessment.

    Implements Case 1 (bypass lockout) and Case 2 (iterative retake):
    - Case 1: User tried to skip learning path and failed (below the configured
              pass threshold) → bypass locked, full learning path becomes
              mandatory (minus completed courses)
    - Case 2: User went through courses and failed → gap review + retake allowed

    Args:
        user_id: The user who failed
        score: The assessment score (0.0 to 1.0)
        was_bypass_attempt: Whether the user tried to bypass the learning path
        department: The department scope

    Returns:
        Next steps including state transition and required actions.
    """
    store = DepartmentScopedStore(department)
    progress = store.read_user_progress(user_id)

    if progress is None:
        return {
            "status": "not_found",
            "message": f"No progress record found for user '{user_id}'.",
        }

    # Thin wrapper around the single remediation decision point — this is the
    # bypass-lockout entry point (chat-only; the quiz UI's own /api/quiz/evaluate
    # calls the same decide_remediation via evaluate_answers, so the two can
    # never disagree about whether a given failure locks the bypass).
    remediation = decide_remediation(
        score=score,
        quiz_type="validation_assessment",
        was_bypass_attempt=was_bypass_attempt,
        bypass_already_locked=progress.get("bypass_locked", False),
        error_retention_matrix=progress.get("error_retention_matrix", {}),
    )

    result = {
        # Derived from next_state (not re-evaluated against score) so this can
        # never disagree with the threshold decide_remediation actually used.
        "passed": remediation.next_state == STATE_PASSED,
        "next_state": remediation.next_state,
        "lock_bypass": remediation.lock_bypass,
        "reason": remediation.reason,
    }

    # If bypass is being locked (Case 1), calculate mandatory courses
    if remediation.lock_bypass:
        # All configured courses minus completed ones
        all_courses = [f"course_{i:02d}" for i in range(1, get_param("MAX_COURSES") + 1)]
        completed = progress.get("completed_courses", [])
        mandatory = get_mandatory_courses(all_courses, completed)

        result["mandatory_courses"] = mandatory
        result["completed_courses_kept"] = completed
        result["total_mandatory"] = len(mandatory)

        # Update progress
        progress["bypass_locked"] = True
        progress["bypass_attempts"] = progress.get("bypass_attempts", 0) + 1
        progress["current_state"] = remediation.next_state
        store.write_user_progress(user_id, progress)

    return {
        "user_id": user_id,
        "score": score,
        "score_percentage": f"{score:.0%}",
        **result,
    }


def check_bypass_eligibility(
    user_id: str,
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Check if a user is eligible for fast-track bypass assessment.

    A user can bypass the learning path IF:
    - Their entry path is "veteran" or "intermediate"
    - Their bypass has not been previously locked (from Case 1 failure)

    Args:
        user_id: The user to check
        department: The department scope

    Returns:
        Eligibility status and explanation.
    """
    store = DepartmentScopedStore(department)
    progress = store.read_user_progress(user_id)

    if progress is None:
        return {
            "status": "not_found",
            "message": f"No progress record found for user '{user_id}'.",
        }

    bypass_locked = progress.get("bypass_locked", False)
    entry_path = progress.get("entry_path", "standard")
    current_state = progress.get("current_state", "enrolled")

    if bypass_locked:
        return {
            "user_id": user_id,
            "eligible": False,
            "reason": (
                "Bypass is LOCKED. You previously attempted to skip the learning path "
                f"and did not meet the {get_param('PASS_THRESHOLD'):.0%} threshold. You must "
                "complete the mandatory courses before taking the assessment again."
            ),
            "bypass_attempts": progress.get("bypass_attempts", 0),
        }

    if entry_path == ENTRY_PATH_STANDARD:
        return {
            "user_id": user_id,
            "eligible": False,
            "reason": (
                "Standard-path users must complete the full learning path "
                "before taking the validation assessment."
            ),
        }

    if current_state in ("passed", "completed"):
        return {
            "user_id": user_id,
            "eligible": False,
            "reason": "You have already passed the validation assessment.",
        }

    return {
        "user_id": user_id,
        "eligible": True,
        "entry_path": entry_path,
        "reason": (
            f"As a {entry_path} learner, you can attempt the validation "
            f"assessment directly. Warning: scoring below {get_param('PASS_THRESHOLD'):.0%} "
            f"will lock bypass and make the full learning path mandatory."
        ),
    }


def _get_path_options(experience_level: str) -> list[dict]:
    """Get the available options for a given entry path."""
    pass_pct = f"{get_param('PASS_THRESHOLD'):.0%}"
    if experience_level == ENTRY_PATH_VETERAN:
        return [
            {
                "option": "Take Validation Assessment",
                "description": f"Skip directly to the final assessment. Score ≥{pass_pct} to pass.",
                "warning": f"Scoring below {pass_pct} will lock this bypass option.",
            },
        ]
    elif experience_level == ENTRY_PATH_INTERMEDIATE:
        return [
            {
                "option": "Take Validation Assessment",
                "description": "Attempt the assessment directly.",
                "warning": f"Scoring below {pass_pct} will lock bypass and require full courses.",
            },
            {
                "option": "Review Gap Areas",
                "description": "Review identified weak areas before attempting assessment.",
            },
        ]
    else:  # standard
        return [
            {
                "option": "Start Learning Path",
                "description": f"Begin the {get_param('MAX_COURSES')}-course structured learning path.",
            },
        ]
