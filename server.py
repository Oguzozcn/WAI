"""
WisdomAI MVP — FastAPI Server
================================
Serves the Stitch UI pages and exposes REST API endpoints
that call WAI_agent tools directly.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Ensure WAI_agent is importable ──
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Server-side cache for quiz evaluation (to prevent sending answers to frontend)
_active_quizzes = {}

from WAI_agent.tools.quiz_tools import (
    generate_quiz,
    evaluate_answers,
    generate_reflection_prompt,
    generate_gap_review,
)
from WAI_agent.tools.curriculum_tools import (
    generate_learning_path,
    generate_daily_agenda,
    identify_content_gaps,
    trigger_curriculum_generation,
    generate_remedial_course,
)
from WAI_agent.tools.progress_tools import (
    get_user_progress,
    update_progress,
    get_department_readiness,
    flag_at_risk_users,
)
from WAI_agent.shared.persistence import DepartmentScopedStore
from WAI_agent.shared.constants import DEFAULT_DEPARTMENT, MAX_QUIZ_ATTEMPTS, PASS_THRESHOLD


# ── App ──
app = FastAPI(title="WisdomAI MVP", version="0.1.0")

# Mount JS files as static
app.mount("/js", StaticFiles(directory=str(PROJECT_ROOT / "frontend" / "js")), name="js")
app.mount("/assets", StaticFiles(directory=str(PROJECT_ROOT / "frontend" / "assets")), name="assets")

PAGES_DIR = PROJECT_ROOT / "frontend" / "pages"


# ═══════════════════════════════════════════
# PAGE ROUTES — serve Stitch HTML pages
# ═══════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def page_dashboard():
    return _serve_page("dashboard.html")


@app.get("/dashboard-chat", response_class=HTMLResponse)
async def page_dashboard_chat():
    return _serve_page("dashboard-chat.html")


@app.get("/learning-path", response_class=HTMLResponse)
async def page_learning_path():
    return _serve_page("learning-path.html")


@app.get("/lesson", response_class=HTMLResponse)
async def page_lesson():
    return _serve_page("lesson.html")


@app.get("/quiz", response_class=HTMLResponse)
async def page_quiz():
    return _serve_page("quiz.html")


@app.get("/quiz-passed", response_class=HTMLResponse)
async def page_quiz_passed():
    return _serve_page("quiz-passed.html")


@app.get("/quiz-retake", response_class=HTMLResponse)
async def page_quiz_retake():
    return _serve_page("quiz-retake.html")


@app.get("/knowledge-vault", response_class=HTMLResponse)
async def page_knowledge_vault():
    return _serve_page("knowledge-vault.html")


@app.get("/chat", response_class=HTMLResponse)
async def page_chat():
    return _serve_page("chat.html")


def _serve_page(filename: str) -> HTMLResponse:
    """Read and return an HTML page from the frontend/pages directory."""
    filepath = PAGES_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Page '{filename}' not found")
    return HTMLResponse(content=filepath.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════
# API ROUTES — structured data endpoints
# ═══════════════════════════════════════════

# ── User Progress ──

@app.get("/api/user/{user_id}/progress")
async def api_get_progress(user_id: str, department: str = DEFAULT_DEPARTMENT):
    """Get user progress data for the dashboard."""
    result = get_user_progress(user_id=user_id, department=department)
    return result


class ProgressUpdateRequest(BaseModel):
    event_type: str
    event_data: dict = {}


@app.post("/api/user/{user_id}/progress")
async def api_update_progress(user_id: str, body: ProgressUpdateRequest, department: str = DEFAULT_DEPARTMENT):
    """Update user progress with a new event."""
    result = update_progress(
        user_id=user_id,
        event_type=body.event_type,
        event_data=body.event_data,
        department=department,
    )
    return result


# ── Learning Path ──

@app.get("/api/user/{user_id}/learning-path")
async def api_get_learning_path(user_id: str, role: str = "new_joiner", department: str = DEFAULT_DEPARTMENT):
    """Generate a learning path for the user."""
    result = generate_learning_path(role=role, department=department)
    return result


@app.get("/api/user/{user_id}/daily-agenda")
async def api_get_daily_agenda(user_id: str, day: int = 1, department: str = DEFAULT_DEPARTMENT):
    """Generate a daily training agenda."""
    # Use user_id as a proxy for learning_path_id in MVP
    result = generate_daily_agenda(
        learning_path_id=f"lp_{user_id}",
        day_number=day,
        department=department,
    )
    return result


# ── Quiz ──

class QuizGenerateRequest(BaseModel):
    topic: str
    difficulty: str = "medium"
    question_count: int = 5
    quiz_type: str = "short_quiz"


@app.post("/api/quiz/generate")
async def api_generate_quiz(body: QuizGenerateRequest, department: str = DEFAULT_DEPARTMENT):
    """Generate a quiz on a topic."""
    result = generate_quiz(
        topic=body.topic,
        difficulty=body.difficulty,
        question_count=body.question_count,
        quiz_type=body.quiz_type,
        department=department,
    )
    
    _active_quizzes[result["quiz_id"]] = result
    import copy
    sanitized = copy.deepcopy(result)
    for q in sanitized.get("questions", []):
        q.pop("correct_answer_index", None)
        
    return sanitized


# ── Quiz Session Start ──

class QuizStartRequest(BaseModel):
    topic: str
    difficulty: str = "medium"
    question_count: int = 5
    quiz_type: str = "short_quiz"
    user_id: str = "emp_001"


@app.post("/api/quiz/start")
async def api_quiz_start(body: QuizStartRequest, department: str = DEFAULT_DEPARTMENT):
    """Initialize a new quiz session with attempt tracking.

    Returns the full quiz payload including 4-option questions and per-option
    rationale/feedback strings. The correct_answer_index is stripped from the
    response but retained server-side for secure evaluation.
    """
    # Check remaining attempts for this user
    store = DepartmentScopedStore(department)
    progress = store.read_user_progress(body.user_id)
    previous_attempts = 0
    if progress:
        quiz_attempts = progress.get("quiz_attempts", [])
        # Count attempts for the same topic
        previous_attempts = sum(
            1 for a in quiz_attempts
            if a.get("topic", "") == body.topic or a.get("quiz_type", "") == body.quiz_type
        )

    attempts_remaining = max(0, MAX_QUIZ_ATTEMPTS - previous_attempts)

    if attempts_remaining <= 0:
        return {
            "status": "locked",
            "attempts_remaining": 0,
            "max_attempts": MAX_QUIZ_ATTEMPTS,
            "message": "You have used all your attempts. Please complete the remedial learning path.",
        }

    # Generate the quiz
    result = generate_quiz(
        topic=body.topic,
        difficulty=body.difficulty,
        question_count=body.question_count,
        quiz_type=body.quiz_type,
        department=department,
    )

    # Cache the full quiz (with answers) for server-side evaluation
    _active_quizzes[result["quiz_id"]] = result

    # Sanitize: strip correct_answer_index but keep rationale for each option
    import copy
    sanitized = copy.deepcopy(result)
    for q in sanitized.get("questions", []):
        q.pop("correct_answer_index", None)

    sanitized["attempts_remaining"] = attempts_remaining
    sanitized["max_attempts"] = MAX_QUIZ_ATTEMPTS
    sanitized["pass_threshold"] = PASS_THRESHOLD

    return sanitized


# ── Quiz Evaluate (Enhanced with Per-Question Feedback) ──

class QuizEvaluateRequest(BaseModel):
    quiz_id: str
    user_id: str
    answers: list[dict]
    quiz_type: str = "short_quiz"
    course_id: str = ""


class QuizAnswerSingleRequest(BaseModel):
    """Evaluate a single answer for instant feedback."""
    quiz_id: str
    question_id: str
    selected_index: int


@app.post("/api/quiz/evaluate/single")
async def api_evaluate_single_answer(body: QuizAnswerSingleRequest):
    """Evaluate a single answer and return instant feedback.

    Returns whether the answer is correct and the rationale (why right/wrong,
    how to think) for the selected option.
    """
    cached_quiz = _active_quizzes.get(body.quiz_id)
    if not cached_quiz:
        raise HTTPException(status_code=404, detail="Quiz session expired or not found.")

    q_lookup = {q["question_id"]: q for q in cached_quiz.get("questions", [])}
    q = q_lookup.get(body.question_id)
    if not q:
        raise HTTPException(status_code=404, detail="Question not found in this quiz.")

    is_correct = (body.selected_index == q["correct_answer_index"])
    correct_idx = q["correct_answer_index"]
    correct_text = q["options"][correct_idx]
    selected_text = q["options"][body.selected_index] if 0 <= body.selected_index < len(q["options"]) else ""

    # Build per-option rationale feedback
    rationale = q.get("rationale", {})
    feedback_why = rationale.get(str(body.selected_index), "")
    feedback_correct_why = rationale.get(str(correct_idx), "")

    # If no pre-generated rationale, provide a heuristic one
    if not feedback_why:
        if is_correct:
            feedback_why = f"Correct! '{selected_text}' is the right answer because it directly addresses the core concept."
        else:
            feedback_why = f"'{selected_text}' is not the best answer here. While it may seem relevant, it does not fully capture the requirement."
    if not feedback_correct_why:
        feedback_correct_why = f"'{correct_text}' is correct because it most accurately and completely addresses the question."

    how_to_think = (
        "When approaching questions like this, identify the key action or definition the question asks for. "
        "Eliminate options that are partially correct but miss the core requirement, "
        "then select the option that provides the most complete and specific answer."
    )

    return {
        "question_id": body.question_id,
        "selected_index": body.selected_index,
        "is_correct": is_correct,
        "correct_index": correct_idx,
        "correct_answer": correct_text,
        "selected_answer": selected_text,
        "feedback_why": feedback_why,
        "feedback_how_to_think": how_to_think,
        "concept_tags": q.get("concept_tags", []),
    }


@app.post("/api/quiz/evaluate")
async def api_evaluate_quiz(body: QuizEvaluateRequest, department: str = DEFAULT_DEPARTMENT):
    """Evaluate user answers for a complete quiz and return full results."""
    cached_quiz = _active_quizzes.get(body.quiz_id)
    if not cached_quiz:
        raise HTTPException(status_code=404, detail="Quiz session expired or not found.")

    enriched_answers = []
    # Build a lookup for questions
    q_lookup = {q["question_id"]: q for q in cached_quiz.get("questions", [])}

    for user_ans in body.answers:
        q_id = user_ans.get("question_id")
        q = q_lookup.get(q_id)
        if q:
            selected_idx = user_ans.get("selected_index")
            is_correct = (selected_idx == q["correct_answer_index"])
            correct_ans_text = q["options"][q["correct_answer_index"]]
            
            enriched_answers.append({
                "question_id": q_id,
                "user_answer": q["options"][selected_idx] if selected_idx is not None and 0 <= selected_idx < len(q["options"]) else str(selected_idx),
                "correct_answer": correct_ans_text,
                "is_correct": is_correct,
                "concept_tags": q.get("concept_tags", [])
            })

    result = evaluate_answers(
        quiz_id=body.quiz_id,
        user_id=body.user_id,
        answers=enriched_answers,
        department=department,
    )

    # ── Phase 7: Update MasteryVectors per tested_concept_token ──
    store = DepartmentScopedStore(department)
    progress = store.read_user_progress(body.user_id)
    if progress is None:
        progress = {}

    mastery_vectors = progress.get("mastery_vectors", {})
    luck_failures = progress.get("luck_failures", {})
    now_iso = __import__("datetime").datetime.utcnow().isoformat()

    for user_ans in body.answers:
        q_id = user_ans.get("question_id")
        q = q_lookup.get(q_id)
        if not q:
            continue
        token_id = q.get("tested_concept_token") or (q.get("concept_tags") or [""])[0]
        if not token_id:
            continue

        is_correct = (user_ans.get("selected_index") == q["correct_answer_index"])
        vec = mastery_vectors.get(token_id, {
            "concept_id": token_id,
            "ability_score": 0.5,
            "last_seen": now_iso,
            "half_life_days": 7.0,
            "historical_attempts": 0,
            "correct_count": 0,
        })

        vec["historical_attempts"] = vec.get("historical_attempts", 0) + 1
        vec["last_seen"] = now_iso

        if is_correct:
            vec["correct_count"] = vec.get("correct_count", 0) + 1
            vec["ability_score"] = min(1.0, vec.get("ability_score", 0.5) + 0.15)
        else:
            vec["ability_score"] = max(0.0, vec.get("ability_score", 0.5) - 0.20)
            luck_failures[token_id] = luck_failures.get(token_id, 0) + 1

        mastery_vectors[token_id] = vec

    progress["mastery_vectors"] = mastery_vectors
    progress["luck_failures"] = luck_failures
    store.write_user_progress(body.user_id, progress)

    # Add attempt tracking info
    previous_attempts = len(progress.get("quiz_attempts", []))
    result["attempts_used"] = previous_attempts
    result["attempts_remaining"] = max(0, MAX_QUIZ_ATTEMPTS - previous_attempts)
    result["max_attempts"] = MAX_QUIZ_ATTEMPTS

    # If this was a final assessment
    if body.quiz_type == "final_assessment":
        if not result.get("passed", True):
            incorrect = [a for a in enriched_answers if not a.get("is_correct", False)]
            if incorrect:
                # Enrich incorrect answers with question text from the cached quiz
                cached_quiz = _active_quizzes.get(body.quiz_id, {})
                q_lookup = {q["question_id"]: q for q in cached_quiz.get("questions", [])}
                for ans in incorrect:
                    q = q_lookup.get(ans.get("question_id", ""))
                    if q:
                        ans["question_text"] = q.get("text", "")

                try:
                    remedial = generate_remedial_course(
                        incorrect_answers=incorrect,
                        user_id=body.user_id,
                        source_course_id=body.course_id,
                        department=department,
                    )
                    result["remedial_course_generated"] = True
                    result["remedial_course_id"] = remedial.get("course_id")
                    result["remedial_message"] = (
                        f"A personalized remedial course \"{ remedial.get('title') }\" has been "
                        "added to your learning path based on your gap analysis."
                    )
                except Exception as e:
                    print(f"[/api/quiz/evaluate] Remedial course generation failed: {e}")
                    result["remedial_course_generated"] = False
        elif body.course_id.startswith("remedial_"):
            # Mark the remedial course as complete
            completed = progress.get("completed_courses", [])
            if body.course_id not in completed:
                completed.append(body.course_id)
                progress["completed_courses"] = completed
                
            # Check if this resolves the source course
            # Find the remedial course to get its source
            for rc in progress.get("remedial_courses", []):
                if rc.get("course_id") == body.course_id:
                    src_id = rc.get("source_course_id")
                    if src_id and src_id not in completed:
                        completed.append(src_id)
                        progress["completed_courses"] = completed
                    break
                    
            # Check if ALL learning path courses are now complete
            path = store.read_latest_learning_path()
            if path:
                path_course_ids = set(c["course_id"] for c in path.get("courses", []))
                if path_course_ids.issubset(set(completed)):
                    progress["current_state"] = "completed"
                    
            store.write_user_progress(body.user_id, progress)

    return result


class ReflectionRequest(BaseModel):
    question_id: str
    question_text: str
    user_answer: str
    correct_answer: str
    concept_tags: list[str] = []


@app.post("/api/quiz/reflection")
async def api_reflection(body: ReflectionRequest):
    """Generate a metacognitive reflection prompt."""
    result = generate_reflection_prompt(
        question_id=body.question_id,
        question_text=body.question_text,
        user_answer=body.user_answer,
        correct_answer=body.correct_answer,
        concept_tags=body.concept_tags,
    )
    return result


# ── Gap Review ──

@app.get("/api/user/{user_id}/gap-review")
async def api_gap_review(user_id: str, department: str = DEFAULT_DEPARTMENT):
    """Generate a spaced-repetition gap review."""
    result = generate_gap_review(user_id=user_id, department=department)
    return result


# ── Department ──

@app.get("/api/department/readiness")
async def api_department_readiness(department: str = DEFAULT_DEPARTMENT):
    """Get department-level readiness metrics."""
    result = get_department_readiness(department=department)
    return result


@app.get("/api/department/at-risk")
async def api_at_risk(department: str = DEFAULT_DEPARTMENT):
    """Get at-risk users for a department."""
    result = flag_at_risk_users(department=department)
    return result


# ── Knowledge Base ──

@app.get("/api/kb/documents")
async def api_kb_documents(department: str = DEFAULT_DEPARTMENT):
    """List all knowledge base documents."""
    store = DepartmentScopedStore(department)
    docs = store.read_knowledge_base()
    return {"documents": docs, "count": len(docs)}


class ValidateDocumentRequest(BaseModel):
    document_content: str


@app.post("/api/kb/validate")
async def api_kb_validate(body: ValidateDocumentRequest, department: str = DEFAULT_DEPARTMENT):
    """Validate a document against the knowledge base."""
    result = identify_content_gaps(
        document_content=body.document_content,
        department=department,
    )
    return result


# ── File Upload & Curriculum Generation ──

ALLOWED_EXTENSIONS = {".txt", ".md"}

@app.post("/api/kb/upload")
async def api_kb_upload(
    file: UploadFile = File(...),
    department: str = Form(DEFAULT_DEPARTMENT),
    append_to_latest: bool = Form(False)
):
    """Upload a document file, save it to raw/, and generate a curriculum.

    This is the core pipeline endpoint:
    1. Validates file type (.txt, .md only for MVP).
    2. Reads the file content.
    3. Saves the raw file to data/knowledge_base/{dept}/raw/.
    4. Triggers the curriculum generation pipeline (Course Splitter).
    5. Returns the generated learning path.
    """
    # Validate file extension
    ext = Path(file.filename).suffix.lower() if file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Only .txt and .md files are supported in the MVP."
        )

    # Read file content
    content_bytes = await file.read()
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File could not be read as UTF-8 text.")

    if not content.strip():
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Save raw document
    store = DepartmentScopedStore(department)
    store.write_raw_document(file.filename, content)

    # Trigger curriculum generation pipeline
    result = trigger_curriculum_generation(
        filename=file.filename,
        department=department,
        append_to_latest=append_to_latest,
    )

    if result.get("status") != "success":
        raise HTTPException(status_code=500, detail=result.get("message", "Curriculum generation failed."))

    return result


# ── Dynamic Learning Path ──

@app.get("/api/learning-path/latest")
async def api_latest_learning_path(user_id: str = None, department: str = DEFAULT_DEPARTMENT):
    """Get the most recently generated learning path, injecting any remedial courses for the user."""
    store = DepartmentScopedStore(department)
    path = store.read_latest_learning_path()
    if not path:
        # Fallback to generating from existing KB
        path = generate_learning_path(role="new_joiner", department=department)

    # Inject remedial courses AFTER the specific course they were generated for
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
                    # Build a map: source_course_id → list of remedial courses
                    remedial_map = {}
                    unanchored = []
                    for rc in pending_remedial:
                        src = rc.get("source_course_id", "")
                        if src:
                            remedial_map.setdefault(src, []).append(rc)
                        else:
                            unanchored.append(rc)

                    # Rebuild the course list, inserting remedial after their source
                    new_courses = []
                    for c in path.get("courses", []):
                        new_courses.append(c)
                        for rc in remedial_map.get(c["course_id"], []):
                            new_courses.append(rc)
                    # Append any unanchored remedial courses at the end
                    new_courses.extend(unanchored)

                    path = dict(path)
                    path["courses"] = new_courses

    return path


# ── Lesson Content ──

@app.get("/api/lesson/{course_id}/{lesson_id}")
async def api_get_lesson(course_id: str, lesson_id: str, user_id: str = "emp_001", department: str = DEFAULT_DEPARTMENT):
    """Get the content for a specific lesson within a course."""
    store = DepartmentScopedStore(department)

    # 1. Search through all learning paths for this course and lesson
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

    # 2. Search through the user's remedial courses in progress
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

    # 3. Fallback: try KB documents
    docs = store.read_knowledge_base()
    for doc in docs:
        if doc.get("title", "").lower().replace(" ", "_") == course_id.replace("course_", ""):
            return {"course": doc, "lesson": None, "path_id": ""}

    raise HTTPException(status_code=404, detail=f"Lesson '{lesson_id}' in course '{course_id}' not found.")


# ── Quiz by Lesson ──

@app.get("/api/quiz/by-lesson/{course_id}/{lesson_id}")
async def api_quiz_by_lesson(course_id: str, lesson_id: str, user_id: str = "emp_001", department: str = DEFAULT_DEPARTMENT):
    """Generate or retrieve a short quiz for a specific lesson."""
    store = DepartmentScopedStore(department)
    import copy as _copy, json as _json

    # 1. Check user's remedial courses first (they have pre-generated quizzes)
    if user_id:
        progress = store.read_user_progress(user_id)
        if progress:
            for rc in progress.get("remedial_courses", []):
                if rc.get("course_id") == course_id:
                    for lesson in rc.get("lessons", []):
                        if lesson.get("lesson_id") == lesson_id:
                            sq = lesson.get("short_quiz")
                            # Only use pre-generated quiz if it actually has questions
                            if sq and sq.get("questions"):
                                # Cache for secure server-side evaluation
                                _active_quizzes[sq["quiz_id"]] = sq
                                sanitized = _copy.deepcopy(sq)
                                for q in sanitized.get("questions", []):
                                    q.pop("correct_answer_index", None)
                                sanitized["attempts_remaining"] = 3
                                sanitized["max_attempts"] = 3
                                sanitized["pass_threshold"] = PASS_THRESHOLD
                                return sanitized
                            # If quiz is empty/stub, fall through to generate from lesson content

    # 2. Search through learning path files
    lesson_content = None
    lesson_title = None
    for path_file in store.learning_paths_path.glob("*.json"):
        path_data = _json.loads(path_file.read_text())
        for course in path_data.get("courses", []):
            if course["course_id"] == course_id:
                for lesson in course.get("lessons", []):
                    if lesson["lesson_id"] == lesson_id:
                        lesson_content = lesson.get("content", "")
                        lesson_title = lesson.get("title", "")
                        break

    # 3. If still not found, search remedial courses in user progress
    if not lesson_content and user_id:
        progress = store.read_user_progress(user_id)
        if progress:
            for rc in progress.get("remedial_courses", []):
                if rc.get("course_id") == course_id:
                    for lesson in rc.get("lessons", []):
                        if lesson.get("lesson_id") == lesson_id:
                            # Remedial lessons use content_summary + key_points
                            parts = []
                            if lesson.get("content_summary"):
                                parts.append(lesson["content_summary"])
                            if lesson.get("key_points"):
                                parts.append("\n".join(f"- {p}" for p in lesson["key_points"]))
                            if lesson.get("content"):
                                parts.append(lesson["content"])
                            if lesson.get("body"):
                                parts.append(lesson["body"])
                            lesson_content = "\n\n".join(parts) if parts else lesson.get("title", "Remedial Review")
                            lesson_title = lesson.get("title", "Remedial Review")
                            break

    if not lesson_content:
        raise HTTPException(status_code=404, detail="Lesson not found for quiz generation.")

    # Generate quiz scoped to this lesson's content
    quiz = generate_quiz(
        topic=lesson_title,
        difficulty="medium",
        question_count=3,
        quiz_type="short_quiz",
        department=department,
    )

    quiz["lesson_context"] = lesson_content
    quiz["lesson_id"] = lesson_id
    quiz["course_id"] = course_id

    # Cache for secure evaluation
    _active_quizzes[quiz["quiz_id"]] = quiz

    sanitized_quiz = _copy.deepcopy(quiz)
    for q in sanitized_quiz.get("questions", []):
        q.pop("correct_answer_index", None)

    return sanitized_quiz


# ── Quiz by Course ──

@app.get("/api/quiz/by-course/{course_id}")
async def api_quiz_by_course(course_id: str, type: str = "final_assessment", user_id: str = "emp_001", department: str = DEFAULT_DEPARTMENT):
    """Retrieve or generate a final assessment for a course."""
    store = DepartmentScopedStore(department)
    import copy as _copy, json as _json

    # 1. Check user's remedial courses for pre-generated final assessment
    if user_id and type == "final_assessment":
        progress = store.read_user_progress(user_id)
        if progress:
            for rc in progress.get("remedial_courses", []):
                if rc.get("course_id") == course_id:
                    fa = rc.get("final_assessment")
                    if fa and fa.get("questions"):
                        _active_quizzes[fa["quiz_id"]] = fa
                        sanitized = _copy.deepcopy(fa)
                        for q in sanitized.get("questions", []):
                            q.pop("correct_answer_index", None)
                        sanitized["attempts_remaining"] = 3
                        sanitized["max_attempts"] = 3
                        sanitized["pass_threshold"] = PASS_THRESHOLD
                        return sanitized

    # 2. Get course title for generation fallback
    course_title = course_id.replace("course_", "").replace("_", " ").title()
    for path_file in store.learning_paths_path.glob("*.json"):
        path_data = _json.loads(path_file.read_text())
        for course in path_data.get("courses", []):
            if course["course_id"] == course_id:
                course_title = course.get("title", course_title)
                break
                
    # 3. Generate new assessment
    quiz = generate_quiz(
        topic=course_title,
        difficulty="medium",
        question_count=10 if type == "final_assessment" else 5,
        quiz_type=type,
        department=department,
    )
    quiz["course_id"] = course_id
    
    _active_quizzes[quiz["quiz_id"]] = quiz
    sanitized_quiz = _copy.deepcopy(quiz)
    for q in sanitized_quiz.get("questions", []):
        q.pop("correct_answer_index", None)
    return sanitized_quiz


# ═══════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
