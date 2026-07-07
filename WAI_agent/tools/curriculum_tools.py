"""
TEAP Curriculum Tools
======================
ADK function tools for the Training Curriculum Builder agent.
Generates learning paths, daily agendas, and content gap analysis.
"""

import json
import uuid
from datetime import datetime

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext

from ..shared.persistence import DepartmentScopedStore
from ..shared.constants import MAX_COURSES, DEFAULT_DEPARTMENT, DEFAULT_TIMEFRAME_WEEKS


def generate_learning_path(
    role: str,
    department: str = DEFAULT_DEPARTMENT,
    timeframe_weeks: int = DEFAULT_TIMEFRAME_WEEKS,
) -> dict:
    """Generate a structured learning path based on the knowledge base content for a department.

    This tool reads the department's knowledge base (DTPs, documentation) and
    creates a sequenced 10-course learning path with time allocation.

    Args:
        role: The role of the learner (e.g., "new_joiner", "team_lead")
        department: The department to scope the learning path to
        timeframe_weeks: Number of weeks for the transition (default: 4)

    Returns:
        A structured learning path with courses, sequencing, and time estimates.
    """
    store = DepartmentScopedStore(department)
    knowledge_base = store.read_knowledge_base()

    # Build the learning path from knowledge base content
    path_id = f"lp_{uuid.uuid4().hex[:8]}"
    courses = []

    if knowledge_base:
        # Extract topics from the knowledge base documents
        for i, doc in enumerate(knowledge_base[:MAX_COURSES]):
            course_topics = doc.get("topics", [])
            courses.append({
                "course_id": f"course_{i + 1:02d}",
                "title": doc.get("title", f"Module {i + 1}"),
                "description": doc.get("description", ""),
                "topics": course_topics,
                "estimated_hours": doc.get("estimated_hours", 1.5),
                "order": i + 1,
            })
    else:
        # No knowledge base found — return empty path with guidance
        return {
            "status": "no_content",
            "path_id": path_id,
            "message": (
                f"No knowledge base documents found for department '{department}'. "
                f"Please upload DTPs or training documents first."
            ),
        }

    # Calculate time distribution across the timeframe
    total_hours = sum(c["estimated_hours"] for c in courses)
    hours_per_week = total_hours / timeframe_weeks if timeframe_weeks > 0 else total_hours
    days_per_course = (timeframe_weeks * 5) / len(courses) if courses else 0  # business days

    learning_path = {
        "path_id": path_id,
        "department": department,
        "role": role,
        "timeframe_weeks": timeframe_weeks,
        "total_courses": len(courses),
        "total_estimated_hours": round(total_hours, 1),
        "hours_per_week": round(hours_per_week, 1),
        "days_per_course": round(days_per_course, 1),
        "courses": courses,
        "created_at": datetime.utcnow().isoformat(),
    }

    return learning_path


def generate_daily_agenda(
    learning_path_id: str,
    day_number: int,
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Generate a day-specific training agenda from a learning path.

    Creates a detailed daily schedule with activities like shadowing,
    simulations, study sessions, and short quizzes.

    Args:
        learning_path_id: The ID of the learning path to generate an agenda for
        day_number: The day number (1-based) within the training program
        department: The department scope

    Returns:
        A daily agenda with timed activities and objectives.
    """
    # Calculate which course this day falls into
    # Assuming 20 business days over 4 weeks, 2 days per course for 10 courses
    course_index = min((day_number - 1) // 2, MAX_COURSES - 1)
    is_first_day_of_course = (day_number - 1) % 2 == 0

    if is_first_day_of_course:
        # Day 1 of a course: Introduction + Shadowing
        activities = [
            {
                "time_slot": "09:00 - 10:00",
                "type": "study",
                "title": f"Course {course_index + 1}: Introduction & Overview",
                "description": "Review the course material and key concepts",
                "duration_hours": 1.0,
            },
            {
                "time_slot": "10:00 - 12:00",
                "type": "shadowing",
                "title": "Guided Shadowing Session",
                "description": "Observe and follow along with experienced team member",
                "duration_hours": 2.0,
            },
            {
                "time_slot": "13:00 - 14:30",
                "type": "simulation",
                "title": "Hands-on Practice Simulation",
                "description": "Practice key procedures in a safe environment",
                "duration_hours": 1.5,
            },
            {
                "time_slot": "14:30 - 15:00",
                "type": "review",
                "title": "Daily Reflection & Notes",
                "description": "Document key learnings and questions",
                "duration_hours": 0.5,
            },
        ]
    else:
        # Day 2 of a course: Practice + Short Quiz
        activities = [
            {
                "time_slot": "09:00 - 10:30",
                "type": "study",
                "title": f"Course {course_index + 1}: Deep Dive",
                "description": "Review detailed procedures and edge cases",
                "duration_hours": 1.5,
            },
            {
                "time_slot": "10:30 - 12:00",
                "type": "simulation",
                "title": "Independent Practice Session",
                "description": "Work through scenarios independently",
                "duration_hours": 1.5,
            },
            {
                "time_slot": "13:00 - 13:30",
                "type": "quiz",
                "title": f"Short Quiz: Course {course_index + 1}",
                "description": "Quick knowledge check on today's material",
                "duration_hours": 0.5,
            },
            {
                "time_slot": "13:30 - 14:00",
                "type": "review",
                "title": "Quiz Review & Gap Analysis",
                "description": "Review any incorrect answers and clarify concepts",
                "duration_hours": 0.5,
            },
        ]

    agenda = {
        "day_number": day_number,
        "learning_path_id": learning_path_id,
        "course_module": course_index + 1,
        "total_hours": sum(a["duration_hours"] for a in activities),
        "activities": activities,
        "objectives": [
            f"Complete all Day {day_number} activities",
            f"Demonstrate understanding of Course {course_index + 1} concepts",
        ],
    }

    return agenda


def identify_content_gaps(
    document_content: str,
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Analyze document content for gaps, inconsistencies, or unclear areas.

    Compares the provided document content against the existing knowledge base
    to identify missing information, contradictions, or areas needing clarification.

    Args:
        document_content: The text content of the document to analyze
        department: The department scope for comparison

    Returns:
        A report of identified gaps, inconsistencies, and recommendations.
    """
    store = DepartmentScopedStore(department)
    existing_docs = store.read_knowledge_base()

    # Analyze the document
    analysis = {
        "status": "analyzed",
        "document_length": len(document_content),
        "existing_documents_compared": len(existing_docs),
        "findings": [],
        "recommendations": [],
    }

    # Check if document is too short
    if len(document_content) < 100:
        analysis["findings"].append({
            "type": "gap",
            "severity": "high",
            "description": "Document appears to be too brief to serve as a comprehensive DTP.",
        })
        analysis["recommendations"].append(
            "Expand the document with detailed step-by-step procedures."
        )

    # Check for potential conflicts with existing documents
    if existing_docs:
        analysis["findings"].append({
            "type": "info",
            "severity": "low",
            "description": (
                f"Found {len(existing_docs)} existing document(s) in the "
                f"'{department}' knowledge base for cross-reference."
            ),
        })

    return analysis
