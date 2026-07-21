"""
TEAP Remediation Policy — the single decision point
======================================================
Fuses the state machine's bypass-lockout verdict (Case 1: bypass attempt
failed → lock bypass, Case 2: standard-path failure → gap review + retake)
with the luck-elimination engine's cross-attempt pattern detection (spawn a
gap review vs. force the mandatory path) into ONE RemediationDecision.

Before this module existed, four call sites (the quiz route, routing_service,
the agent's before_tool_callback hook, and curriculum_service's unconditional
remedial-course trigger) each decided independently whether a failed quiz
needed remediation, with no code-level ordering between them. Every entry
point now calls `decide_remediation` and reads the same verdict instead.

This module does NOT generate content (no gap review text, no remedial
course) — it only decides whether to. The caller acts on the decision.
"""

from dataclasses import asdict, dataclass
from typing import Optional

from src.core.luck_elimination import (
    ACTION_CONTINUE,
    ACTION_FORCE_MANDATORY,
    ACTION_SPAWN_GAP_REVIEW,
    LuckEliminationEngine,
)
from src.core.state_machine import handle_assessment_result


@dataclass
class RemediationDecision:
    next_state: str
    lock_bypass: bool
    luck_action: str
    flagged_concepts: list
    spawn_gap_review: bool
    spawn_remedial_course: bool
    mandatory_courses: Optional[list]
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def decide_remediation(
    *,
    score: float,
    quiz_type: str,
    was_bypass_attempt: bool,
    bypass_already_locked: bool,
    error_retention_matrix: dict,
    new_attempts: Optional[list] = None,
) -> RemediationDecision:
    """Decide what happens after a graded quiz attempt.

    Args:
        score: This attempt's score (0.0-1.0).
        quiz_type: "short_quiz" | "validation_assessment" | "final_assessment"
            | "gap_review". Only a failed "final_assessment" spawns a
            remedial course — short quizzes and gap reviews never do.
        was_bypass_attempt: Whether this attempt was a veteran/intermediate
            fast-track bypass of the standard learning path.
        bypass_already_locked: Whether bypass was already locked from a
            prior failed attempt.
        error_retention_matrix: The user's all-time per-concept failure
            counts (all tags per question, as evaluate_answers builds it).
        new_attempts: This attempt's individual answers (for the luck engine
            to fold into the matrix before flagging), or None to evaluate
            the matrix as-is.

    Returns:
        A RemediationDecision. `mandatory_courses` is always None here — the
        caller fills it in (via `get_mandatory_courses`) when `lock_bypass`
        is True, since computing it needs the user's completed-courses list,
        which this function intentionally doesn't take a dependency on.
    """
    sm_result = handle_assessment_result(
        score=score,
        was_bypass_attempt=was_bypass_attempt,
        bypass_already_locked=bypass_already_locked,
    )

    engine = LuckEliminationEngine()
    luck_result = engine.evaluate_user_progression(
        error_retention_matrix, new_attempts=new_attempts
    )

    spawn_gap_review = luck_result["action"] in (
        ACTION_SPAWN_GAP_REVIEW,
        ACTION_FORCE_MANDATORY,
    )
    spawn_remedial_course = quiz_type == "final_assessment" and not sm_result["passed"]

    reason_parts = [sm_result["reason"]]
    if luck_result["action"] != ACTION_CONTINUE:
        reason_parts.append(luck_result["reason"])
    reason = " ".join(reason_parts)

    return RemediationDecision(
        next_state=sm_result["next_state"],
        lock_bypass=sm_result["lock_bypass"],
        luck_action=luck_result["action"],
        flagged_concepts=luck_result["flagged_concepts"],
        spawn_gap_review=spawn_gap_review,
        spawn_remedial_course=spawn_remedial_course,
        mandatory_courses=None,
        reason=reason,
    )
