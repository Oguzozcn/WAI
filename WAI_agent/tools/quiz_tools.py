"""
TEAP Quiz Tools
================
ADK function tools for the Knowledge Coach agent.
Handles quiz generation, evaluation, metacognitive reflection, and gap review.
"""

import json
import uuid
from datetime import datetime

from ..shared.persistence import DepartmentScopedStore
from ..shared.constants import (
    DEFAULT_DEPARTMENT, PASS_THRESHOLD,
    MAX_QUIZ_QUESTIONS, MAX_ASSESSMENT_QUESTIONS,
)
from ..shared.luck_elimination import LuckEliminationEngine


def generate_quiz(
    topic: str,
    difficulty: str = "medium",
    question_count: int = 5,
    quiz_type: str = "short_quiz",
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Generate a quiz on a specific topic from the department's knowledge base.

    Creates multiple-choice and scenario-based questions tailored to the
    specified topic and difficulty level.

    Args:
        topic: The topic to generate quiz questions about (e.g., "European capitals")
        difficulty: Question difficulty - "easy", "medium", or "hard"
        question_count: Number of questions to generate (max 10 for quizzes, 20 for assessments)
        quiz_type: Type of quiz - "short_quiz", "validation_assessment", or "gap_review"
        department: The department scope

    Returns:
        A quiz object with questions, options, and metadata.
    """
    store = DepartmentScopedStore(department)
    knowledge_base = store.read_knowledge_base()

    # Cap question count based on quiz type
    max_questions = MAX_ASSESSMENT_QUESTIONS if quiz_type == "validation_assessment" else MAX_QUIZ_QUESTIONS
    question_count = min(question_count, max_questions)

    quiz_id = f"quiz_{uuid.uuid4().hex[:8]}"

    # Build quiz structure — the LLM will fill in actual questions
    # based on the knowledge base content and topic
    quiz = {
        "quiz_id": quiz_id,
        "topic": topic,
        "quiz_type": quiz_type,
        "difficulty": difficulty,
        "question_count": question_count,
        "knowledge_base_available": len(knowledge_base) > 0,
        "created_at": datetime.utcnow().isoformat(),
        "instructions": (
            f"Generate {question_count} {difficulty} questions about '{topic}'. "
            f"Quiz type: {quiz_type}. "
            f"Include multiple-choice options (A, B, C, D) for each question. "
            f"Tag each question with relevant concept tags for gap tracking."
        ),
    }

    # If knowledge base content is available, include relevant material
    if knowledge_base:
        relevant_content = []
        for doc in knowledge_base:
            doc_topics = [t.lower() for t in doc.get("topics", [])]
            if topic.lower() in doc.get("title", "").lower() or \
               any(topic.lower() in t for t in doc_topics):
                relevant_content.append({
                    "title": doc.get("title", ""),
                    "content": doc.get("content", ""),
                    "topics": doc.get("topics", []),
                })
        quiz["source_material"] = relevant_content

    return quiz


def evaluate_answers(
    quiz_id: str,
    user_id: str,
    answers: list[dict],
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Evaluate a user's quiz answers and update their progress.

    Scores responses, identifies knowledge gaps, and updates the
    error retention matrix for luck elimination tracking.

    Args:
        quiz_id: The ID of the quiz being evaluated
        user_id: The user whose answers are being evaluated
        answers: List of answer dicts, each with:
                 {"question_id": str, "user_answer": str, "correct_answer": str,
                  "is_correct": bool, "concept_tags": [str]}
        department: The department scope

    Returns:
        Evaluation results with score, gap analysis, and next steps.
    """
    store = DepartmentScopedStore(department)

    # Calculate score
    total = len(answers)
    correct = sum(1 for a in answers if a.get("is_correct", False))
    score = correct / total if total > 0 else 0.0
    passed = score >= PASS_THRESHOLD

    # Update user progress
    progress = store.read_user_progress(user_id)
    if progress is None:
        progress = {"user_id": user_id, "department": department}

    # Update error retention matrix
    error_matrix = progress.get("error_retention_matrix", {})
    incorrect_answers = [a for a in answers if not a.get("is_correct", False)]

    for answer in incorrect_answers:
        for tag in answer.get("concept_tags", []):
            error_matrix[tag] = error_matrix.get(tag, 0) + 1

    progress["error_retention_matrix"] = error_matrix

    # Record the quiz attempt
    quiz_attempts = progress.get("quiz_attempts", [])
    quiz_attempts.append({
        "quiz_id": quiz_id,
        "score": score,
        "total_questions": total,
        "correct_answers": correct,
        "attempted_at": datetime.utcnow().isoformat(),
    })
    progress["quiz_attempts"] = quiz_attempts

    # Record assessment score
    assessment_scores = progress.get("assessment_scores", [])
    assessment_scores.append({
        "quiz_id": quiz_id,
        "score": score,
        "type": "quiz",
    })
    progress["assessment_scores"] = assessment_scores

    if score > progress.get("best_assessment_score", 0):
        progress["best_assessment_score"] = score

    # Run luck elimination check
    engine = LuckEliminationEngine()
    luck_result = engine.evaluate_user_progression(error_matrix)

    # Save updated progress
    store.write_user_progress(user_id, progress)

    # Build gap analysis
    gaps = []
    for answer in incorrect_answers:
        gaps.append({
            "question_id": answer.get("question_id", ""),
            "concept_tags": answer.get("concept_tags", []),
            "user_answer": answer.get("user_answer", ""),
            "correct_answer": answer.get("correct_answer", ""),
        })

    return {
        "quiz_id": quiz_id,
        "user_id": user_id,
        "score": round(score, 2),
        "score_percentage": f"{score:.0%}",
        "passed": passed,
        "total_questions": total,
        "correct_answers": correct,
        "incorrect_answers": len(incorrect_answers),
        "pass_threshold": f"{PASS_THRESHOLD:.0%}",
        "gaps": gaps,
        "luck_elimination_status": luck_result,
        "message": (
            f"You scored {score:.0%} ({correct}/{total}). "
            + ("Congratulations, you passed! " if passed else f"You need {PASS_THRESHOLD:.0%} to pass. ")
            + luck_result["reason"]
        ),
    }


def generate_reflection_prompt(
    question_id: str,
    question_text: str,
    user_answer: str,
    correct_answer: str,
    concept_tags: list[str],
) -> dict:
    """Generate a metacognitive reflection prompt for a failed question.

    Instead of just showing the correct answer, this prompts the user to
    explain WHY they failed, HOW they approached the question, and WHAT
    makes the correct answer right.

    Args:
        question_id: The ID of the failed question
        question_text: The original question text
        user_answer: What the user answered
        correct_answer: The correct answer
        concept_tags: Concept tags associated with this question

    Returns:
        A reflection prompt structure for the coach to present.
    """
    return {
        "type": "metacognitive_reflection",
        "question_id": question_id,
        "original_question": question_text,
        "your_answer": user_answer,
        "correct_answer": correct_answer,
        "concept_areas": concept_tags,
        "reflection_prompts": [
            "Why do you think you chose that answer? Walk me through your reasoning.",
            f"What is the key difference between '{user_answer}' and '{correct_answer}'?",
            "What concept or rule should you remember to avoid this mistake next time?",
            "Can you explain in your own words why the correct answer is right?",
        ],
        "instructions": (
            "Please respond to the reflection prompts above. "
            "The Knowledge Coach will evaluate your understanding "
            "before clearing this gap from your record."
        ),
    }


def generate_gap_review(
    user_id: str,
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Generate a Duolingo-style gap review for the user's weak areas.

    Reads the user's error retention matrix and creates targeted
    spaced repetition exercises focusing on persistent knowledge gaps.

    Args:
        user_id: The user to generate a gap review for
        department: The department scope

    Returns:
        A gap review plan with targeted exercises for each weak concept.
    """
    store = DepartmentScopedStore(department)
    progress = store.read_user_progress(user_id)

    if progress is None:
        return {
            "status": "no_data",
            "message": f"No progress data found for user '{user_id}'. Cannot generate gap review.",
        }

    error_matrix = progress.get("error_retention_matrix", {})

    if not error_matrix:
        return {
            "status": "no_gaps",
            "message": "No knowledge gaps detected. You're doing great!",
        }

    # Sort concepts by failure count (worst first)
    engine = LuckEliminationEngine()
    concept_summary = engine.get_concept_failure_summary(error_matrix)

    # Build targeted review exercises
    exercises = []
    for concept_info in concept_summary:
        if concept_info["status"] == "ok":
            continue

        exercises.append({
            "concept": concept_info["concept"],
            "failure_count": concept_info["failures"],
            "severity": concept_info["status"],
            "review_type": "spaced_repetition",
            "instructions": (
                f"Review the concept '{concept_info['concept']}' thoroughly. "
                f"You've missed this {concept_info['failures']} time(s). "
                f"After reviewing, you'll be quizzed again on this topic."
            ),
        })

    return {
        "user_id": user_id,
        "total_gap_areas": len(exercises),
        "exercises": exercises,
        "strategy": (
            "Duolingo-style spaced repetition: Each gap area will be "
            "revisited with varied question formats until mastered. "
            "Critical gaps are addressed first."
        ),
    }
