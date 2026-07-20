"""
TEAP Progress Tools
====================
ADK function tools for tracking user progress, readiness scores,
and department-level reporting.
"""

import json
from datetime import datetime

from src.core.database import DepartmentScopedStore
from src.core.config import DEFAULT_DEPARTMENT
from src.core.dev_config import get_param, get_logic_param
from src.core.data_compliance_gate import DataComplianceGate


def get_user_progress(
    user_id: str,
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Get the current progress record for a user.

    Returns the user's learning state, completed courses, quiz scores,
    readiness score, and any active knowledge gaps.

    Args:
        user_id: The user ID to look up
        department: The department scope

    Returns:
        The user's complete progress record, or an error if not found.
    """
    store = DepartmentScopedStore(department)
    progress = store.read_user_progress(user_id)

    if progress is None:
        return {
            "status": "not_found",
            "message": f"No progress record found for user '{user_id}' in department '{department}'.",
        }

    # Calculate derived fields
    completed_count = len(progress.get("completed_courses", []))
    total_quizzes = len(progress.get("quiz_attempts", []))
    error_matrix = progress.get("error_retention_matrix", {})
    active_gaps = sum(1 for v in error_matrix.values() if v >= get_param("LUCK_FAILURE_THRESHOLD"))

    progress["summary"] = {
        "courses_completed": completed_count,
        "total_quizzes_taken": total_quizzes,
        "active_knowledge_gaps": active_gaps,
        "is_at_risk": progress.get("readiness_score", 0) < get_param("AT_RISK_READINESS_THRESHOLD"),
        "current_state_description": progress.get("current_state", "unknown"),
    }

    return progress


def update_progress(
    user_id: str,
    event_type: str,
    event_data: dict,
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Update a user's progress record with a new event.

    Handles various event types: course_completed, quiz_taken,
    assessment_passed, assessment_failed, state_changed, etc.

    Args:
        user_id: The user to update
        event_type: Type of event - "course_completed", "quiz_taken",
                    "assessment_passed", "assessment_failed", "state_changed",
                    "bypass_locked", "path_assigned"
        event_data: Event-specific data dict
        department: The department scope

    Returns:
        Updated progress summary.
    """
    store = DepartmentScopedStore(department)
    progress = store.read_user_progress(user_id)

    if progress is None:
        # Create new progress record
        progress = {
            "user_id": user_id,
            "department": department,
            "current_state": "enrolled",
            "enrolled_path_ids": [],
            "completed_courses": [],
            "quiz_attempts": [],
            "assessment_scores": [],
            "error_retention_matrix": {},
            "bypass_locked": False,
            "bypass_attempts": 0,
            "readiness_score": 0.0,
            "enrolled_at": datetime.utcnow().isoformat(),
        }

    # Apply event
    progress["last_activity_at"] = datetime.utcnow().isoformat()

    if event_type == "course_completed":
        course_id = event_data.get("course_id", "")
        if course_id and course_id not in progress.get("completed_courses", []):
            progress.setdefault("completed_courses", []).append(course_id)
        if progress.get("current_course_id") == course_id:
            progress["current_course_id"] = ""

    elif event_type == "course_started":
        course_id = event_data.get("course_id", "")
        if course_id and course_id not in progress.get("completed_courses", []):
            progress["current_course_id"] = course_id
            if progress.get("current_state") == "enrolled":
                progress["current_state"] = "course_in_progress"

    elif event_type == "path_enrolled":
        path_id = event_data.get("path_id", "")
        if path_id and path_id not in progress.get("enrolled_path_ids", []):
            progress.setdefault("enrolled_path_ids", []).append(path_id)

    elif event_type == "state_changed":
        proposed_state = event_data.get("new_state", progress["current_state"])
        audit_result = DataComplianceGate.audit_state_transition(user_id, proposed_state, event_data.get("context", {}))
        progress["current_state"] = audit_result["enforced_state"]

    elif event_type == "bypass_locked":
        progress["bypass_locked"] = True
        progress["current_state"] = "bypass_locked"

    elif event_type == "path_assigned":
        progress["entry_path"] = event_data.get("entry_path", "")
        progress["learning_path_id"] = event_data.get("learning_path_id", "")
        progress["current_state"] = event_data.get("initial_state", "enrolled")

    elif event_type == "assessment_passed":
        proposed_state = "passed"
        audit_result = DataComplianceGate.audit_state_transition(user_id, proposed_state, event_data.get("context", {}))
        progress["current_state"] = audit_result["enforced_state"]
        progress["readiness_score"] = 1.0
        progress["completed_at"] = datetime.utcnow().isoformat()

    elif event_type == "assessment_failed":
        score = event_data.get("score", 0.0)
        progress["readiness_score"] = score

    # Recalculate readiness score based on progress
    _recalculate_readiness(progress)

    # Save
    store.write_user_progress(user_id, progress)

    return {
        "status": "updated",
        "user_id": user_id,
        "event_type": event_type,
        "current_state": progress.get("current_state", "unknown"),
        "readiness_score": progress.get("readiness_score", 0.0),
    }


def get_department_readiness(
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Get aggregated readiness metrics for a department.

    Calculates team-level readiness based on all user progress records
    in the department scope.

    Args:
        department: The department to analyze

    Returns:
        Department-level readiness report with aggregate metrics.
    """
    store = DepartmentScopedStore(department)
    all_progress = store.read_all_user_progress()

    if not all_progress:
        return {
            "department": department,
            "status": "no_data",
            "message": f"No user progress data found for department '{department}'.",
        }

    total = len(all_progress)
    scores = [p.get("readiness_score", 0.0) for p in all_progress]
    avg_score = sum(scores) / total if total > 0 else 0.0
    at_risk = sum(1 for s in scores if s < get_param("AT_RISK_READINESS_THRESHOLD"))
    completed = sum(1 for p in all_progress if p.get("current_state") == "completed")

    return {
        "department": department,
        "total_enrolled": total,
        "avg_readiness_score": round(avg_score, 2),
        "at_risk_count": at_risk,
        "at_risk_percentage": round((at_risk / total) * 100, 1) if total > 0 else 0.0,
        "completed_count": completed,
        "completion_rate_pct": round((completed / total) * 100, 1) if total > 0 else 0.0,
    }


def flag_at_risk_users(
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Identify users at risk of not meeting readiness threshold.

    Flags individuals with readiness scores below the threshold
    and identifies their blocking topics.

    Args:
        department: The department to analyze

    Returns:
        List of at-risk users with their blocking factors.
        NOTE: This data stays within the department scope and is
        NEVER included in KPI payloads (PII protection).
    """
    store = DepartmentScopedStore(department)
    all_progress = store.read_all_user_progress()

    at_risk_users = []
    for progress in all_progress:
        score = progress.get("readiness_score", 0.0)
        if score < get_param("AT_RISK_READINESS_THRESHOLD"):
            # Find the biggest gap area
            error_matrix = progress.get("error_retention_matrix", {})
            top_gap = max(error_matrix, key=error_matrix.get) if error_matrix else "general"

            at_risk_users.append({
                "user_id": progress.get("user_id", "unknown"),
                "readiness_score": round(score, 2),
                "current_state": progress.get("current_state", "unknown"),
                "blocked_by": top_gap,
                "bypass_locked": progress.get("bypass_locked", False),
            })

    return {
        "department": department,
        "total_at_risk": len(at_risk_users),
        "at_risk_users": at_risk_users,
        "note": "This data is for departmental use only. It is NOT included in KPI payloads.",
    }


def _recalculate_readiness(progress: dict) -> None:
    """Recalculate a user's readiness score based on their progress."""
    completed_courses = len(progress.get("completed_courses", []))
    total_courses = get_param("MAX_COURSES")

    course_weight = get_logic_param("readiness_scoring", "course_completion_weight")
    quiz_weight = get_logic_param("readiness_scoring", "quiz_performance_weight")
    quiz_window = int(get_logic_param("readiness_scoring", "quiz_window_size"))

    # Base readiness from course completion
    course_readiness = (completed_courses / total_courses) * course_weight if total_courses > 0 else 0.0

    # Quiz performance (rolling window of most recent attempts)
    quiz_attempts = progress.get("quiz_attempts", [])
    if quiz_attempts:
        recent_scores = [a.get("score", 0.0) for a in quiz_attempts[-quiz_window:]]
        avg_quiz = sum(recent_scores) / len(recent_scores)
        quiz_readiness = avg_quiz * quiz_weight
    else:
        quiz_readiness = 0.0

    # State bonus, scaled to the configured state-progress weight (default bonuses
    # below assume a 0.2 weight; scale proportionally if it's been retuned)
    state_weight = get_logic_param("readiness_scoring", "state_progress_weight")
    state = progress.get("current_state", "enrolled")
    state_bonus_ratios = {
        "completed": 1.0,
        "passed": 1.0,
        "validation_assessment": 0.75,
        "gap_review": 0.25,
        "enrolled": 0.0,
    }
    state_readiness = state_bonus_ratios.get(state, 0.25) * state_weight

    # Don't override if they've already passed
    if progress.get("current_state") == "passed" or progress.get("current_state") == "completed":
        progress["readiness_score"] = 1.0
    else:
        progress["readiness_score"] = round(
            min(course_readiness + quiz_readiness + state_readiness, 0.99), 2
        )

    progress["is_at_risk"] = progress["readiness_score"] < get_param("AT_RISK_READINESS_THRESHOLD")
