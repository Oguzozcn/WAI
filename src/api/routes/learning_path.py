from fastapi import APIRouter, HTTPException
from src.services.curriculum_service import generate_learning_path, generate_daily_agenda
from src.services.quiz_service import generate_gap_review
from WAI_agent.shared.persistence import DepartmentScopedStore
from WAI_agent.shared.constants import DEFAULT_DEPARTMENT

router = APIRouter(tags=["learning_path"])

@router.get("/api/user/{user_id}/learning-path")
async def api_get_learning_path(user_id: str, role: str = "new_joiner", department: str = DEFAULT_DEPARTMENT):
    """Generate a learning path for the user."""
    result = generate_learning_path(role=role, department=department)
    return result

@router.get("/api/user/{user_id}/daily-agenda")
async def api_get_daily_agenda(user_id: str, day: int = 1, department: str = DEFAULT_DEPARTMENT):
    """Generate a daily training agenda."""
    result = generate_daily_agenda(
        learning_path_id=f"lp_{user_id}",
        day_number=day,
        department=department,
    )
    return result

@router.get("/api/user/{user_id}/gap-review")
async def api_gap_review(user_id: str, department: str = DEFAULT_DEPARTMENT):
    """Generate a spaced-repetition gap review."""
    result = generate_gap_review(user_id=user_id, department=department)
    return result

@router.get("/api/learning-path/latest")
async def api_latest_learning_path(user_id: str = None, department: str = DEFAULT_DEPARTMENT):
    """Get the most recently generated learning path, injecting any remedial courses for the user."""
    store = DepartmentScopedStore(department)
    path = store.read_latest_learning_path()
    if not path:
        path = generate_learning_path(role="new_joiner", department=department)

    if user_id:
        progress = store.read_user_progress(user_id)
        if progress:
            remedial_courses = progress.get("remedial_courses", [])
            if remedial_courses:
                completed = set(progress.get("completed_courses", []))
                pending_remedial = [
                    c for c in remedial_courses
                    if c.get("course_id") not in completed
                ]
                if pending_remedial:
                    remedial_map = {}
                    unanchored = []
                    for rc in pending_remedial:
                        src = rc.get("source_course_id", "")
                        if src:
                            remedial_map.setdefault(src, []).append(rc)
                        else:
                            unanchored.append(rc)

                    new_courses = []
                    for c in path.get("courses", []):
                        new_courses.append(c)
                        for rc in remedial_map.get(c["course_id"], []):
                            new_courses.append(rc)
                    new_courses.extend(unanchored)

                    path = dict(path)
                    path["courses"] = new_courses

    return path

@router.get("/api/lesson/{course_id}/{lesson_id}")
async def api_get_lesson(course_id: str, lesson_id: str, user_id: str = "emp_001", department: str = DEFAULT_DEPARTMENT):
    """Get the content for a specific lesson within a course."""
    store = DepartmentScopedStore(department)

    for path_file in store.learning_paths_path.glob("*.json"):
        import json as _json
        path_data = _json.loads(path_file.read_text())
        for course in path_data.get("courses", []):
            if course["course_id"] == course_id:
                for lesson in course.get("lessons", []):
                    if lesson["lesson_id"] == lesson_id:
                        return {
                            "course": course,
                            "lesson": lesson,
                            "path_id": path_data.get("path_id", ""),
                        }

    progress = store.read_user_progress(user_id)
    if progress:
        for rc in progress.get("remedial_courses", []):
            if rc.get("course_id") == course_id:
                for lesson in rc.get("lessons", []):
                    if lesson.get("lesson_id") == lesson_id:
                        return {
                            "course": rc,
                            "lesson": lesson,
                            "path_id": "",
                            "is_remedial": True,
                        }

    docs = store.read_knowledge_base()
    for doc in docs:
        if doc.get("title", "").lower().replace(" ", "_") == course_id.replace("course_", ""):
            return {"course": doc, "lesson": None, "path_id": ""}

    raise HTTPException(status_code=404, detail=f"Lesson '{lesson_id}' in course '{course_id}' not found.")
