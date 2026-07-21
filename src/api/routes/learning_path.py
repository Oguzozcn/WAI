from fastapi import APIRouter, HTTPException
from src.services.curriculum_service import generate_learning_path, generate_daily_agenda, get_pending_remedial_courses
from src.services.quiz_service import generate_gap_review
from src.services.user_service import update_progress
from src.core.database import DepartmentScopedStore
from src.core.config import DEFAULT_DEPARTMENT

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

def _merge_remedial_courses(path: dict, progress: dict) -> dict:
    """Inject a user's pending remedial courses into a path's course list,
    each placed right after the source course it targets. Shared by every
    route that renders a learning path, so a remedial course is visible
    wherever a learner actually looks — not just from one code path."""
    if not progress.get("remedial_courses"):
        return path

    pending_remedial = get_pending_remedial_courses(progress)
    if not pending_remedial:
        return path

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
            path = _merge_remedial_courses(path, progress)

    return path

@router.get("/api/learning-path/enrolled")
async def api_enrolled_learning_paths(user_id: str, department: str = DEFAULT_DEPARTMENT):
    """List every path the user is enrolled in, each with its own progress,
    sorted by progress descending (most-progressed first)."""
    store = DepartmentScopedStore(department)
    progress = store.read_user_progress(user_id) or {}
    completed = set(progress.get("completed_courses", []))
    # No fallback to "whatever path was most recently generated department-wide" —
    # that could surface another user's private draft as if this user were
    # enrolled in it. No explicit enrollment means no enrolled paths, period.
    enrolled_ids = progress.get("enrolled_path_ids", [])

    results = []
    for path_id in enrolled_ids:
        path = store.read_learning_path(path_id)
        if not path:
            continue
        course_ids = [c["course_id"] for c in path.get("courses", [])]
        completed_in_path = [cid for cid in course_ids if cid in completed]
        total = len(course_ids)
        progress_pct = round((len(completed_in_path) / total) * 100) if total else 0
        results.append({
            "path_id": path_id,
            "title": path.get("title") or (path.get("courses") or [{}])[0].get("title", ""),
            "path_type": path.get("path_type", "official"),
            "total_courses": total,
            "completed_courses": len(completed_in_path),
            "progress_pct": progress_pct,
        })

    results.sort(key=lambda r: r["progress_pct"], reverse=True)
    return {"enrolled_paths": results, "count": len(results)}

@router.get("/api/learning-path/{path_id}")
async def api_get_learning_path_by_id(path_id: str, user_id: str = None, department: str = DEFAULT_DEPARTMENT):
    """Fetch one specific enrolled/activated path by id, injecting any
    pending remedial courses for user_id if given."""
    store = DepartmentScopedStore(department)
    path = store.read_learning_path(path_id)
    if not path:
        raise HTTPException(status_code=404, detail=f"Path '{path_id}' not found.")

    if user_id:
        progress = store.read_user_progress(user_id)
        if progress:
            path = _merge_remedial_courses(path, progress)

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

@router.post("/api/learning-path/{path_id}/enroll")
async def api_enroll_learning_path(
    path_id: str,
    path_type: str = "official",
    user_id: str | None = None,
    department: str = DEFAULT_DEPARTMENT,
):
    """Enroll the user in an existing catalog path (official or unofficial).
    Multiple paths can be enrolled at once — this never disturbs other
    already-enrolled paths' stored data."""
    store = DepartmentScopedStore(department)
    if path_type == "unofficial":
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required to enroll in an unofficial path.")
        data = store.read_unofficial_path(user_id, path_id)
    else:
        data = store.read_standard_path(path_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Path '{path_id}' not found.")
    store.write_learning_path(path_id, data)
    if user_id:
        update_progress(user_id=user_id, event_type="path_enrolled", event_data={"path_id": path_id}, department=department)
    return {"status": "enrolled", "path_id": path_id}

@router.get("/api/search")
async def api_search(q: str, department: str = DEFAULT_DEPARTMENT, user_id: str | None = None, limit: int = 6):
    """Search catalog learning paths and their courses by title/description substring match."""
    query = q.strip().lower()
    if not query:
        return {"courses": [], "paths": []}

    store = DepartmentScopedStore(department)
    official = store.list_standard_paths()
    unofficial = store.list_unofficial_paths(user_id=user_id) if user_id else []
    # Newest first, so when duplicate-titled paths/courses collapse below, the
    # most recently generated one is the one that survives.
    all_meta = sorted(official + unofficial, key=lambda p: p.get("created_at", ""), reverse=True)

    matched_paths = []
    seen_path_titles = set()
    for p in all_meta:
        title_key = p["title"].strip().lower()
        if query in title_key and title_key not in seen_path_titles:
            seen_path_titles.add(title_key)
            matched_paths.append(p)
        if len(matched_paths) >= limit:
            break

    matched_courses = []
    seen_course_titles = set()
    for meta in all_meta:
        if len(matched_courses) >= limit:
            break
        if meta["path_type"] == "unofficial":
            full = store.read_unofficial_path(meta["created_by"], meta["path_id"])
        else:
            full = store.read_standard_path(meta["path_id"])
        if not full:
            continue
        for course in full.get("courses", []):
            title = course.get("title", "") or ""
            desc = course.get("description", "") or ""
            title_key = title.strip().lower()
            if (query in title_key or query in desc.lower()) and title_key not in seen_course_titles:
                seen_course_titles.add(title_key)
                lessons = course.get("lessons", [])
                matched_courses.append({
                    "course_id": course.get("course_id"),
                    "title": title,
                    "description": desc,
                    "path_id": meta["path_id"],
                    "path_type": meta["path_type"],
                    "first_lesson_id": lessons[0]["lesson_id"] if lessons else None,
                })
                if len(matched_courses) >= limit:
                    break

    return {"courses": matched_courses, "paths": matched_paths}
