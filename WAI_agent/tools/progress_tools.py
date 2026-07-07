"""
TEAP Progress Tools
====================
ADK function tools for tracking user progress, readiness scores,
and department-level reporting.
"""

import json
from datetime import datetime

from ..shared.persistence import DepartmentScopedStore
from ..shared.constants import DEFAULT_DEPARTMENT, PASS_THRESHOLD, AT_RISK_READINESS_THRESHOLD


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
    active_gaps = sum(1 for v in error_matrix.values() if v >= 2)

    progress["summary"] = {
        "courses_completed": completed_count,
        "total_quizzes_taken": total_quizzes,
        "active_knowledge_gaps": active_gaps,
        "is_at_risk": progress.get("readiness_score", 0) < AT_RISK_READINESS_THRESHOLD,
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

    elif event_type == "state_changed":
        progress["current_state"] = event_data.get("new_state", progress["current_state"])

    elif event_type == "bypass_locked":
        progress["bypass_locked"] = True
        progress["current_state"] = "bypass_locked"

    elif event_type == "path_assigned":
        progress["entry_path"] = event_data.get("entry_path", "")
        progress["learning_path_id"] = event_data.get("learning_path_id", "")
        progress["current_state"] = event_data.get("initial_state", "enrolled")

    elif event_type == "assessment_passed":
        progress["current_state"] = "passed"
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
    at_risk = sum(1 for s in scores if s < AT_RISK_READINESS_THRESHOLD)
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
        if score < AT_RISK_READINESS_THRESHOLD:
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
    total_courses = 10  # MAX_COURSES

    # Base readiness from course completion (50% weight)
    course_readiness = (completed_courses / total_courses) * 0.5 if total_courses > 0 else 0.0

    # Quiz performance (30% weight)
    quiz_attempts = progress.get("quiz_attempts", [])
    if quiz_attempts:
        recent_scores = [a.get("score", 0.0) for a in quiz_attempts[-5:]]  # Last 5
        avg_quiz = sum(recent_scores) / len(recent_scores)
        quiz_readiness = avg_quiz * 0.3
    else:
        quiz_readiness = 0.0

    # State bonus (20% weight)
    state = progress.get("current_state", "enrolled")
    state_bonuses = {
        "completed": 0.2,
        "passed": 0.2,
        "validation_assessment": 0.15,
        "gap_review": 0.05,
        "enrolled": 0.0,
    }
    state_readiness = state_bonuses.get(state, 0.05)

    # Don't override if they've already passed
    if progress.get("current_state") == "passed" or progress.get("current_state") == "completed":
        progress["readiness_score"] = 1.0
    else:
        progress["readiness_score"] = round(
            min(course_readiness + quiz_readiness + state_readiness, 0.99), 2
        )

    progress["is_at_risk"] = progress["readiness_score"] < AT_RISK_READINESS_THRESHOLD
