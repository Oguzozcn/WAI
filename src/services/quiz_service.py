"""
TEAP Quiz Tools
================
ADK function tools for the Knowledge Coach agent.
Handles quiz generation, evaluation, metacognitive reflection, and gap review.
"""

import uuid
from datetime import datetime, timezone

from src.core.database import DepartmentScopedStore
from src.core.config import DEFAULT_DEPARTMENT
from src.core.dev_config import get_param, get_config, get_logic_param
from src.core.luck_elimination import LuckEliminationEngine, calculate_hlr_retention
from src.core.remediation_policy import decide_remediation
from src.core.state_machine import get_mandatory_courses
from src.services.llm_client import call_gemini_json
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
        learning_rate = get_logic_param("assessment_scoring", "irt_learning_rate")
        theta_clamp = get_logic_param("assessment_scoring", "irt_theta_clamp")
        default_a = get_logic_param("assessment_scoring", "irt_default_discrimination")
        default_b = 0.0
        default_c = get_logic_param("assessment_scoring", "irt_default_guessing")
        default_d = get_logic_param("assessment_scoring", "irt_default_slip")
        gradient = 0.0
        fisher_information = 0.0

        for index, item in enumerate(administered_items):
            a = item.get("discrimination", default_a)
            b = item.get("difficulty", default_b)
            c = item.get("guessing", default_c)
            d = item.get("slip", default_d)
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
        return max(-theta_clamp, min(theta_clamp, new_theta))


def generate_quiz(
    topic: str,
    difficulty: str = "medium",
    question_count: int = 5,
    quiz_type: str = "short_quiz",
    department: str = DEFAULT_DEPARTMENT,
    extra_context: str = "",
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
        extra_context: Optional additional grounding text prepended ahead of
            any knowledge-base matches (e.g. a learner's stored misconception
            for this topic) — also forces the LLM-grounded path even when no
            knowledge-base document matches the topic.

    Returns:
        A quiz object with questions, options, and metadata.
    """
    store = DepartmentScopedStore(department)
    knowledge_base = store.read_knowledge_base()

    # Cap question count based on quiz type
    max_questions = get_param("MAX_ASSESSMENT_QUESTIONS") if quiz_type == "validation_assessment" else get_param("MAX_QUIZ_QUESTIONS")
    question_count = min(question_count, max_questions)

    quiz_id = f"quiz_{uuid.uuid4().hex[:8]}"

    def _build_template_question(i: int) -> dict:
        """Deterministic fallback question (unchanged legacy behavior)."""
        correct_idx = i % 4

        # All 4 options share identical neutral phrasing so none of them leaks
        # the answer through wording -- only correct_answer_index (never sent
        # to the client) marks which one is right.
        letters = "ABCD"
        options = [
            f"Statement {letters[j]}: a description related to {topic}, part {i+1}."
            for j in range(4)
        ]

        # Generate mock rationale for each option
        rationale = {}
        for j in range(4):
            if j == correct_idx:
                rationale[str(j)] = f"Correct! This option accurately defines the core concept of {topic} part {i+1}."
            else:
                rationale[str(j)] = f"This is incorrect. It focuses on the wrong aspect of {topic} and misses the main point."

        return {
            "question_id": f"q_{uuid.uuid4().hex[:6]}",
            "text": f"Regarding '{topic}', which of the following represents the core concept for part {i+1}?",
            "options": options,
            "correct_answer_index": correct_idx,
            "rationale": rationale,
            "concept_tags": [topic.lower().replace(" ", "_"), f"concept_{i+1}"],
        }

    # ── Gather grounding content from the knowledge base ──
    # Keep docs whose topics/title/content relate to the requested topic
    # (simple case-insensitive substring match — no new search infra).
    topic_lower = topic.lower()
    topic_words = {w for w in topic_lower.split() if len(w) > 2}
    grounding_parts: list[str] = []
    grounding_len = 0
    GROUNDING_CAP = 4000
    for doc in knowledge_base:
        topics = [str(t).lower() for t in (doc.get("topics") or [])]
        title = str(doc.get("title", "")).lower()
        content = str(doc.get("content", ""))
        content_lower = content.lower()

        related = (
            any(topic_lower in t or t in topic_lower for t in topics)
            or any(w in title for w in topic_words)
            or any(w in content_lower for w in topic_words)
            or topic_lower in title
            or topic_lower in content_lower
        )
        if not related or not content.strip():
            continue

        remaining = GROUNDING_CAP - grounding_len
        if remaining <= 0:
            break
        snippet = content[:remaining]
        grounding_parts.append(snippet)
        grounding_len += len(snippet)

    grounding_context = "\n\n".join(grounding_parts).strip()
    if extra_context.strip():
        grounding_context = (
            f"{extra_context.strip()}\n\n{grounding_context}" if grounding_context else extra_context.strip()
        )

    # ── Generate questions: LLM (grounded) with heuristic fallback ──
    questions = []
    if grounding_context:
        try:
            tool_config = get_config()["tools"]["generate_quiz"]
            prompt = tool_config["prompt_template"].format(
                question_count=question_count,
                topic=topic,
                difficulty=difficulty,
                grounding_context=grounding_context,
            )

            llm_data = call_gemini_json(prompt, model=tool_config.get("model"))
            llm_questions = llm_data.get("questions")
            if not isinstance(llm_questions, list) or not llm_questions:
                raise ValueError("LLM response missing a non-empty 'questions' list.")

            # Truncate to question_count; assign our own IDs (LLM must not invent them).
            for q in llm_questions[:question_count]:
                if not isinstance(q, dict):
                    continue
                q["question_id"] = f"q_{uuid.uuid4().hex[:6]}"
                questions.append(q)

            # Pad any shortfall with heuristic questions.
            for i in range(len(questions), question_count):
                questions.append(_build_template_question(i))

        except Exception as e:
            print(f"[generate_quiz] LLM call failed ({e}), using fallback.")
            questions = [_build_template_question(i) for i in range(question_count)]
    else:
        # No grounding content — fall back to the deterministic template loop.
        questions = [_build_template_question(i) for i in range(question_count)]

    quiz = {
        "quiz_id": quiz_id,
        "topic": topic,
        "quiz_type": quiz_type,
        "difficulty": difficulty,
        "question_count": question_count,
        "knowledge_base_available": len(knowledge_base) > 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "questions": questions,
    }

    return quiz


def evaluate_answers(
    quiz_id: str,
    user_id: str,
    answers: list[dict],
    quiz_type: str = "short_quiz",
    was_bypass_attempt: bool = False,
    course_id: str = "",
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Evaluate a user's quiz answers and update their progress.

    Scores responses, identifies knowledge gaps, and runs the single
    remediation policy decision (bypass lockout, gap review, or mandatory
    path) against the updated error retention matrix — see
    src.core.remediation_policy.decide_remediation for the fused logic. When
    the policy calls for it, this ALSO generates the gap review and/or
    remedial course itself (not left to the caller, and not something the
    agent decides via a separate tool call) — so a chat-invoked evaluation
    and an /api/quiz/evaluate-invoked one always produce the same outcome.

    Args:
        quiz_id: The ID of the quiz being evaluated
        user_id: The user whose answers are being evaluated
        answers: List of answer dicts, each with:
                 {"question_id": str, "user_answer": str, "correct_answer": str,
                  "is_correct": bool, "concept_tags": [str]}
        quiz_type: "short_quiz" | "validation_assessment" | "final_assessment"
                   | "gap_review" — only a failed final_assessment can spawn
                   a remedial course.
        was_bypass_attempt: Whether this was a veteran/intermediate fast-track
                             bypass attempt of the standard learning path —
                             failing one locks the bypass option.
        course_id: The course this quiz belongs to, if any — used as the
                   remedial course's source_course_id when one is spawned.
        department: The department scope

    Returns:
        Evaluation results with score, gap analysis, a `remediation` decision
        object (see RemediationDecision), and — when triggered —
        gap_review_triggered/gap_review/gap_review_mandatory and/or
        remedial_course_generated/remedial_course_id/remedial_message.
    """
    store = DepartmentScopedStore(department)

    # Calculate score
    total = len(answers)
    correct = sum(1 for a in answers if a.get("is_correct", False))
    score = correct / total if total > 0 else 0.0
    pass_threshold = get_param("PASS_THRESHOLD")
    passed = score >= pass_threshold

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
        "attempted_at": datetime.now(timezone.utc).isoformat(),
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

    # Run luck elimination check (drives luck_elimination_status/message below)
    engine = LuckEliminationEngine()
    luck_result = engine.evaluate_user_progression(error_matrix)

    # Single remediation decision — fuses the state machine's bypass-lockout
    # verdict with the luck-elimination verdict above into one policy object
    # every entry point (this call, the quiz route, the agent hook) agrees on.
    remediation = decide_remediation(
        score=score,
        quiz_type=quiz_type,
        was_bypass_attempt=was_bypass_attempt,
        bypass_already_locked=progress.get("bypass_locked", False),
        error_retention_matrix=error_matrix,
    )
    if remediation.lock_bypass:
        all_courses = [f"course_{i:02d}" for i in range(1, get_param("MAX_COURSES") + 1)]
        completed = progress.get("completed_courses", [])
        remediation.mandatory_courses = get_mandatory_courses(all_courses, completed)
        progress["bypass_locked"] = True
        progress["bypass_attempts"] = progress.get("bypass_attempts", 0) + 1
        progress["current_state"] = remediation.next_state

    # Run IRT Psychometric update
    current_ability = progress.get("psychometric_ability", 0.0)
    default_item_params = {
        "discrimination": get_logic_param("assessment_scoring", "irt_default_discrimination"),
        "difficulty": 0.0,
        "guessing": get_logic_param("assessment_scoring", "irt_default_guessing"),
        "slip": get_logic_param("assessment_scoring", "irt_default_slip"),
    }
    administered_items = [dict(default_item_params) for _ in answers]
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

    result = {
        "quiz_id": quiz_id,
        "user_id": user_id,
        "score": round(score, 2),
        "score_percentage": f"{score:.0%}",
        "passed": passed,
        "total_questions": total,
        "correct_answers": correct,
        "incorrect_answers": len(incorrect_answers),
        "pass_threshold": f"{pass_threshold:.0%}",
        "gaps": gaps,
        "luck_elimination_status": luck_result,
        "remediation": remediation.to_dict(),
        "message": (
            f"You scored {score:.0%} ({correct}/{total}). "
            + ("Congratulations, you passed! " if passed else f"You need {pass_threshold:.0%} to pass. ")
            + luck_result["reason"]
        ),
    }

    # Act on the remediation decision — generation happens here (not via a
    # separate agent tool call, not duplicated in the HTTP route) so a
    # chat-invoked evaluation and a web-quiz-invoked one always produce the
    # same remediation content for the same failure.
    if remediation.spawn_gap_review:
        try:
            gap_review = generate_gap_review(user_id=user_id, department=department)
            if gap_review.get("exercises"):
                result["gap_review_triggered"] = True
                result["gap_review"] = gap_review
                result["gap_review_mandatory"] = (
                    remediation.luck_action == "FORCE_MANDATORY_LEARNING_PATH"
                )
        except Exception as e:
            print(f"[evaluate_answers] Gap review generation failed: {e}")

    if remediation.spawn_remedial_course and incorrect_answers:
        # Best-effort question_text enrichment from the persisted quiz record
        # (chat-invoked evaluations may not have one — generate_remedial_course
        # falls back to question_id when question_text is missing).
        cached_quiz = store.read_quiz(quiz_id)
        if cached_quiz:
            q_lookup = {q["question_id"]: q for q in cached_quiz.get("questions", [])}
            for ans in incorrect_answers:
                q = q_lookup.get(ans.get("question_id", ""))
                if q:
                    ans["question_text"] = q.get("text", "")

        try:
            from src.services.curriculum_service import generate_remedial_course
            remedial = generate_remedial_course(
                incorrect_answers=incorrect_answers,
                user_id=user_id,
                source_course_id=course_id,
                department=department,
            )
            result["remedial_course_generated"] = True
            result["remedial_course_id"] = remedial.get("course_id")
            result["remedial_message"] = (
                f"A personalized remedial course \"{remedial.get('title')}\" has been "
                "added to your learning path based on your gap analysis."
            )
        except Exception as e:
            print(f"[evaluate_answers] Remedial course generation failed: {e}")
            result["remedial_course_generated"] = False

    return result


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

    concept_diagnoses = progress.get("concept_diagnoses", {})
    mastery_vectors = progress.get("mastery_vectors", {})
    retention_threshold = get_logic_param("luck_elimination", "hlr_retention_threshold")
    ability_threshold = get_logic_param("luck_elimination", "hlr_ability_threshold")

    # Build targeted review exercises
    exercises = []
    scheduled_for_later = []
    for concept_info in concept_summary:
        if concept_info["status"] == "ok":
            continue

        concept = concept_info["concept"]

        # HLR due-filtering: a concept with a mastery vector is only deferred
        # ("not due yet") when BOTH retention is still high (recently/well
        # seen) AND ability is decent (they've actually been getting it
        # right) — a concept that was just failed has its ability_score
        # freshly lowered, so it never gets silently deferred right after
        # the failure that flagged it in the first place. No vector at all
        # keeps the original immediate-inclusion behavior (nothing to gate on).
        vector = mastery_vectors.get(concept)
        if vector:
            retention = calculate_hlr_retention(vector)
            ability = vector.get("ability_score", 0.5)
            if retention >= retention_threshold and ability >= ability_threshold:
                scheduled_for_later.append({
                    "concept": concept,
                    "failure_count": concept_info["failures"],
                    "retention": round(retention, 2),
                    "reason": "Still well-retained — not due for review yet.",
                })
                continue

        diagnosis_entries = concept_diagnoses.get(concept, [])
        misconception = diagnosis_entries[-1].get("misconception", "") if diagnosis_entries else ""
        instructions = (
            f"Review the concept '{concept}'. Your known misconception: {misconception} "
            f"You've missed this {concept_info['failures']} time(s). After reviewing, "
            f"you'll be quizzed again on this topic."
            if misconception else
            f"Review the concept '{concept}' thoroughly. "
            f"You've missed this {concept_info['failures']} time(s). "
            f"After reviewing, you'll be quizzed again on this topic."
        )

        exercises.append({
            "concept": concept,
            "failure_count": concept_info["failures"],
            "severity": concept_info["status"],
            "review_type": "spaced_repetition",
            "instructions": instructions,
        })

    return {
        "user_id": user_id,
        "total_gap_areas": len(exercises),
        "exercises": exercises,
        "scheduled_for_later": scheduled_for_later,
        "strategy": (
            "Duolingo-style spaced repetition: Each gap area will be "
            "revisited with varied question formats until mastered. "
            "Critical gaps are addressed first."
        ),
    }
