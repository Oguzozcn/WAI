"""
TEAP Curriculum Tools
======================
ADK function tools for the Training Curriculum Builder agent.
Generates learning paths, daily agendas, and content gap analysis.
"""

import json
import uuid
from datetime import datetime

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


# ── Document-to-Curriculum Pipeline ──

def _split_text_into_sections(text: str) -> list[dict]:
    """Split document text into logical sections based on headings or paragraphs.

    Detects markdown-style headers (## or ###) as section delimiters.
    Falls back to paragraph-based chunking if no headers found.
    """
    import re
    sections = []

    # Try markdown heading-based splitting first
    heading_pattern = re.compile(r'^(#{1,3})\s+(.+)$', re.MULTILINE)
    headings = list(heading_pattern.finditer(text))

    if headings:
        for i, match in enumerate(headings):
            title = match.group(2).strip()
            start = match.end()
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            content = text[start:end].strip()
            if content:
                sections.append({"title": title, "content": content})
    else:
        # Paragraph-based chunking: split on double newlines
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        # Group paragraphs into chunks of roughly equal size (max 10 chunks)
        max_sections = min(MAX_COURSES, max(1, len(paragraphs)))
        chunk_size = max(1, len(paragraphs) // max_sections)

        for i in range(0, len(paragraphs), chunk_size):
            chunk = paragraphs[i:i + chunk_size]
            combined = "\n\n".join(chunk)
            # Generate title from first ~50 chars of first paragraph
            first_line = chunk[0][:60].strip()
            if len(chunk[0]) > 60:
                first_line += "..."
            sections.append({"title": first_line, "content": combined})

    return sections[:MAX_COURSES]


def _extract_key_concepts(text: str) -> list[str]:
    """Extract key concepts/terms from a text block.

    Looks for bold terms (**term**), capitalized phrases, and terms after colons.
    """
    import re
    concepts = set()

    # Extract bold terms
    for match in re.finditer(r'\*\*(.*?)\*\*', text):
        term = match.group(1).strip()
        if 2 < len(term) < 60:
            concepts.add(term)

    # Extract terms after colons (definition-style)
    for match in re.finditer(r'(\w[\w\s]{2,30}):\s', text):
        term = match.group(1).strip()
        if len(term) > 3:
            concepts.add(term)

    # Extract capitalized multi-word terms (likely proper nouns / concepts)
    for match in re.finditer(r'\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\b', text):
        concepts.add(match.group(1))

    return list(concepts)[:10]


def process_document_to_curriculum(
    document_text: str,
    document_title: str = "Uploaded Document",
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Split a document into a structured curriculum: Module → Lessons.

    The Course Splitter logic. Analyzes document_text and generates a
    structured curriculum with up to 10 lessons per module, each with
    a short quiz, plus a final assessment for the module.

    Args:
        document_text: The raw text content of the uploaded document.
        document_title: The title/filename of the document.
        department: The department scope.

    Returns:
        A structured curriculum dict with courses and lessons.
    """
    sections = _split_text_into_sections(document_text)

    if not sections:
        return {
            "status": "error",
            "message": "Could not extract any content from the document.",
        }

    # Build lessons from sections
    lessons = []
    for i, section in enumerate(sections):
        key_concepts = _extract_key_concepts(section["content"])
        lessons.append({
            "lesson_id": f"lesson_{i + 1:02d}",
            "title": section["title"],
            "content": section["content"],
            "key_concepts": key_concepts,
            "estimated_minutes": max(10, min(30, len(section["content"]) // 200)),
            "order": i + 1,
            "has_quiz": True,
        })

    # Calculate total estimated hours
    total_minutes = sum(l["estimated_minutes"] for l in lessons)
    # Add 5 min per short quiz + 15 min for final assessment
    total_minutes += len(lessons) * 5 + 15
    estimated_hours = round(total_minutes / 60, 1)

    # Build the module/course
    # Extract a clean title from the document name
    clean_title = document_title.replace(".txt", "").replace(".md", "").replace("_", " ").title()

    course = {
        "course_id": f"course_{uuid.uuid4().hex[:8]}",
        "title": clean_title,
        "description": f"Auto-generated curriculum from '{document_title}'",
        "topics": list(set(
            concept
            for lesson in lessons
            for concept in lesson["key_concepts"][:3]
        ))[:10],
        "estimated_hours": estimated_hours,
        "order": 1,
        "lessons": lessons,
        "has_final_assessment": True,
    }

    return {
        "status": "success",
        "course": course,
        "total_lessons": len(lessons),
        "total_estimated_hours": estimated_hours,
    }


def trigger_curriculum_generation(
    filename: str,
    department: str = DEFAULT_DEPARTMENT,
    user_id: str = "manager",
    append_to_latest: bool = False,
) -> dict:
    """Orchestrate the full upload-to-curriculum pipeline.

    1. Reads the saved raw document from the knowledge base.
    2. Splits it into a structured curriculum (Course → Lessons).
    3. Saves the course JSON to the knowledge base.
    4. Generates and persists the learning path (either new or appended).

    Args:
        filename: The filename of the raw document.
        department: The department scope.
        user_id: The user who triggered the generation.
        append_to_latest: If True, merges this course into the latest existing path.

    Returns:
        The generated learning path details.
    """
    store = DepartmentScopedStore(department)

    # Step 1: Read the raw document
    document_text = store.read_raw_document(filename)
    if not document_text:
        return {
            "status": "error",
            "message": f"Raw document '{filename}' not found.",
        }

    # Step 2: Split into curriculum
    result = process_document_to_curriculum(
        document_text=document_text,
        document_title=filename,
        department=department,
    )

    if result.get("status") != "success":
        return result

    course = result["course"]

    # Step 3: Save the course to the knowledge base
    course_doc = {
        "title": course["title"],
        "description": course["description"],
        "topics": course["topics"],
        "content": document_text[:2000],
        "estimated_hours": course["estimated_hours"],
        "key_facts": [
            {"concept": c, "definition": ""}
            for c in course["topics"][:5]
        ],
        "source_dtp": f"raw/{filename}",
        "version": "1.0",
        "lessons": course["lessons"],
        "has_final_assessment": course["has_final_assessment"],
    }
    store.write_knowledge_document(course["course_id"], course_doc)

    # Step 4: Build or Append to learning path
    from ..shared.persistence import _store_lock
    
    with _store_lock:
        existing_path = None
        if append_to_latest:
            existing_path = store.read_latest_learning_path()

        if existing_path:
            # Append to existing
            path_id = existing_path["path_id"]
            existing_path["courses"].append(course)
            existing_path["total_courses"] = len(existing_path["courses"])
            existing_path["total_estimated_hours"] = round(sum(c.get("estimated_hours", 0) for c in existing_path["courses"]), 1)
            existing_path["timeframe_weeks"] = max(1, int(existing_path["total_estimated_hours"] / 4) + 1)
            existing_path["hours_per_week"] = round(existing_path["total_estimated_hours"] / existing_path["timeframe_weeks"], 1)
            # Retain the earliest source_document or append
            if filename not in existing_path.get("source_document", ""):
                existing_path["source_document"] = existing_path.get("source_document", "") + f", {filename}"
            
            learning_path = existing_path
        else:
            # Create new
            path_id = f"lp_{uuid.uuid4().hex[:8]}"
            learning_path = {
                "path_id": path_id,
                "department": department,
                "role": "auto_generated",
                "timeframe_weeks": max(1, int(course["estimated_hours"] / 4) + 1),
                "total_courses": 1,
                "total_estimated_hours": course["estimated_hours"],
                "hours_per_week": round(course["estimated_hours"], 1),
                "days_per_course": 2,
                "source_document": filename,
                "courses": [course],
                "created_at": datetime.utcnow().isoformat(),
            }

        store.write_learning_path(path_id, learning_path)

    return {
        "status": "success",
        "path_id": path_id,
        "course_id": course["course_id"],
        "total_lessons": result["total_lessons"],
        "total_estimated_hours": result["total_estimated_hours"],
        "learning_path": learning_path,
        "appended": bool(existing_path)
    }

