"""
TEAP Quiz Tools
================
ADK function tools for the Knowledge Coach agent.
Handles quiz generation, evaluation, metacognitive reflection, and gap review.
"""

import json
import uuid
from datetime import datetime

from src.core.database import DepartmentScopedStore
from src.core.config import (
    DEFAULT_DEPARTMENT, PASS_THRESHOLD,
    MAX_QUIZ_QUESTIONS, MAX_ASSESSMENT_QUESTIONS,
)
from src.core.luck_elimination import LuckEliminationEngine
import math

class EnterprisePsychometricEngine:
    """
    Implements a 4-Parameter Logistic (4PL) Item Response Theory model.
    """

    @staticmethod
    def calculate_item_probability(theta: float, a: float, b: float, c: float, d: float) -> float:
        try:
            exponent = -a * (theta - b)
            exponent = max(-50.0, min(50.0, exponent))
            return c + ((d - c) / (1.0 + math.exp(exponent)))
        except (ValueError, OverflowError):
            return 0.5

    @staticmethod
    def update_learner_ability(
        current_theta: float,
        administered_items: list[dict],
        user_responses: list[int]
    ) -> float:
        learning_rate = 0.5
        gradient = 0.0
        fisher_information = 0.0

        for index, item in enumerate(administered_items):
            a = item.get("discrimination", 1.0)
            b = item.get("difficulty", 0.0)
            c = item.get("guessing", 0.25)
            d = item.get("slip", 0.95)
            response = user_responses[index]

            probability = EnterprisePsychometricEngine.calculate_item_probability(current_theta, a, b, c, d)
            complement = 1.0 - probability

            if probability <= 0.0 or complement <= 0.0:
                continue

            derivative = a * (probability - c) * (d - probability) / (d - c) if (d - c) != 0.0 else 0.1
            gradient += (derivative / (probability * complement)) * (response - probability)
            fisher_information += (derivative ** 2) / (probability * complement)

        if fisher_information == 0.0:
            return current_theta

        new_theta = current_theta + (gradient / fisher_information) * learning_rate
        return max(-4.0, min(4.0, new_theta))


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

    # Generate heuristic/mock questions for the demo
    questions = []
    for i in range(question_count):
        correct_idx = i % 4
        
        # Build 4 options: 1 correct, 3 obviously incorrect
        options = []
        for j in range(4):
            if j == correct_idx:
                options.append(f"Correct Concept: This is the accurate definition for part {i+1} of {topic}.")
            else:
                options.append(f"Incorrect Option: This is a completely unrelated or wrong statement regarding part {i+1}.")

        # Generate mock rationale for each option
        rationale = {}
        for j in range(4):
            if j == correct_idx:
                rationale[str(j)] = f"Correct! This option accurately defines the core concept of {topic} part {i+1}."
            else:
                rationale[str(j)] = f"This is incorrect. It focuses on the wrong aspect of {topic} and misses the main point."

        questions.append({
            "question_id": f"q_{uuid.uuid4().hex[:6]}",
            "text": f"Regarding '{topic}', which of the following represents the core concept for part {i+1}?",
            "options": options,
            "correct_answer_index": correct_idx,
            "rationale": rationale,
            "concept_tags": [topic.lower().replace(" ", "_"), f"concept_{i+1}"]
        })

    quiz = {
        "quiz_id": quiz_id,
        "topic": topic,
        "quiz_type": quiz_type,
        "difficulty": difficulty,
        "question_count": question_count,
        "knowledge_base_available": len(knowledge_base) > 0,
        "created_at": datetime.utcnow().isoformat(),
        "questions": questions,
    }

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

    # Run IRT Psychometric update
    current_ability = progress.get("psychometric_ability", 0.0)
    administered_items = [{"discrimination": 1.0, "difficulty": 0.0, "guessing": 0.25, "slip": 0.95} for _ in answers]
    user_responses = [1 if a.get("is_correct", False) else 0 for a in answers]
    new_ability = EnterprisePsychometricEngine.update_learner_ability(current_ability, administered_items, user_responses)
    progress["psychometric_ability"] = new_ability

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
