from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from src.services.quiz_service import (
    generate_quiz,
    evaluate_answers,
    generate_reflection_prompt,
)
from src.services.curriculum_service import generate_remedial_course
from src.core.database import DepartmentScopedStore
from src.core.config import DEFAULT_DEPARTMENT, MAX_QUIZ_ATTEMPTS, PASS_THRESHOLD

router = APIRouter(prefix="/api/quiz", tags=["quiz"])

_active_quizzes = {}

class QuizGenerateRequest(BaseModel):
    topic: str
    difficulty: str = "medium"
    question_count: int = 5
    quiz_type: str = "short_quiz"

@router.post("/generate")
async def api_generate_quiz(body: QuizGenerateRequest, department: str = DEFAULT_DEPARTMENT):
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

class QuizStartRequest(BaseModel):
    topic: str
    difficulty: str = "medium"
    question_count: int = 5
    quiz_type: str = "short_quiz"
    user_id: str = "emp_001"

@router.post("/start")
async def api_quiz_start(body: QuizStartRequest, department: str = DEFAULT_DEPARTMENT):
    store = DepartmentScopedStore(department)
    progress = store.read_user_progress(body.user_id)
    previous_attempts = 0
    if progress:
        quiz_attempts = progress.get("quiz_attempts", [])
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

    sanitized["attempts_remaining"] = attempts_remaining
    sanitized["max_attempts"] = MAX_QUIZ_ATTEMPTS
    sanitized["pass_threshold"] = PASS_THRESHOLD

    return sanitized

class QuizAnswerSingleRequest(BaseModel):
    quiz_id: str
    question_id: str
    selected_index: int

@router.post("/evaluate/single")
async def api_evaluate_single_answer(body: QuizAnswerSingleRequest):
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

    rationale = q.get("rationale", {})
    feedback_why = rationale.get(str(body.selected_index), "")
    feedback_correct_why = rationale.get(str(correct_idx), "")

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

class QuizEvaluateRequest(BaseModel):
    quiz_id: str
    user_id: str
    answers: list[dict]
    quiz_type: str = "short_quiz"
    course_id: str = ""

@router.post("/evaluate")
async def api_evaluate_quiz(body: QuizEvaluateRequest, department: str = DEFAULT_DEPARTMENT):
    cached_quiz = _active_quizzes.get(body.quiz_id)
    if not cached_quiz:
        raise HTTPException(status_code=404, detail="Quiz session expired or not found.")

    enriched_answers = []
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

    store = DepartmentScopedStore(department)
    progress = store.read_user_progress(body.user_id)
    if progress is None:
        progress = {}

    mastery_vectors = progress.get("mastery_vectors", {})
    luck_failures = progress.get("luck_failures", {})
    now_iso = datetime.now(timezone.utc).isoformat()

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

    previous_attempts = len(progress.get("quiz_attempts", []))
    result["attempts_used"] = previous_attempts
    result["attempts_remaining"] = max(0, MAX_QUIZ_ATTEMPTS - previous_attempts)
    result["max_attempts"] = MAX_QUIZ_ATTEMPTS

    if body.quiz_type == "final_assessment":
        if not result.get("passed", True):
            incorrect = [a for a in enriched_answers if not a.get("is_correct", False)]
            if incorrect:
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
            completed = progress.get("completed_courses", [])
            if body.course_id not in completed:
                completed.append(body.course_id)
                progress["completed_courses"] = completed
                
            for rc in progress.get("remedial_courses", []):
                if rc.get("course_id") == body.course_id:
                    src_id = rc.get("source_course_id")
                    if src_id and src_id not in completed:
                        completed.append(src_id)
                        progress["completed_courses"] = completed
                    break
                    
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

@router.post("/reflection")
async def api_reflection(body: ReflectionRequest):
    result = generate_reflection_prompt(
        question_id=body.question_id,
        question_text=body.question_text,
        user_answer=body.user_answer,
        correct_answer=body.correct_answer,
        concept_tags=body.concept_tags,
    )
    return result

@router.get("/by-lesson/{course_id}/{lesson_id}")
async def api_quiz_by_lesson(course_id: str, lesson_id: str, user_id: str = "emp_001", department: str = DEFAULT_DEPARTMENT):
    store = DepartmentScopedStore(department)
    import copy as _copy, json as _json

    if user_id:
        progress = store.read_user_progress(user_id)
        if progress:
            for rc in progress.get("remedial_courses", []):
                if rc.get("course_id") == course_id:
                    for lesson in rc.get("lessons", []):
                        if lesson.get("lesson_id") == lesson_id:
                            sq = lesson.get("short_quiz")
                            if sq and sq.get("questions"):
                                _active_quizzes[sq["quiz_id"]] = sq
                                sanitized = _copy.deepcopy(sq)
                                for q in sanitized.get("questions", []):
                                    q.pop("correct_answer_index", None)
                                sanitized["attempts_remaining"] = 3
                                sanitized["max_attempts"] = 3
                                sanitized["pass_threshold"] = PASS_THRESHOLD
                                return sanitized

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
    
    if not lesson_content:
        raise HTTPException(status_code=404, detail="Lesson not found.")

    result = generate_quiz(
        topic=lesson_title,
        difficulty="medium",
        question_count=3,
        quiz_type="short_quiz",
        department=department,
    )
    _active_quizzes[result["quiz_id"]] = result
    sanitized = _copy.deepcopy(result)
    for q in sanitized.get("questions", []):
        q.pop("correct_answer_index", None)

    sanitized["attempts_remaining"] = 3
    sanitized["max_attempts"] = 3
    sanitized["pass_threshold"] = PASS_THRESHOLD

    return sanitized
