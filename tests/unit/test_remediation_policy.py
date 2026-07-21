"""Unit tests for the single remediation decision point.

decide_remediation fuses handle_assessment_result (state machine) with
LuckEliminationEngine (cross-attempt pattern detection) into one
RemediationDecision — these tests pin down the fusion rules themselves,
independent of any HTTP route or service that calls it.
"""

from src.core.config import PASS_THRESHOLD
from src.core.remediation_policy import RemediationDecision, decide_remediation


def test_passing_short_quiz_never_spawns_remedial_course():
    decision = decide_remediation(
        score=1.0,
        quiz_type="short_quiz",
        was_bypass_attempt=False,
        bypass_already_locked=False,
        error_retention_matrix={},
    )
    assert decision.spawn_remedial_course is False
    assert decision.lock_bypass is False


def test_failing_short_quiz_never_spawns_remedial_course():
    """Only a failed final_assessment can spawn a remedial course — a failed
    short_quiz never does, even though it's still a failure."""
    decision = decide_remediation(
        score=0.0,
        quiz_type="short_quiz",
        was_bypass_attempt=False,
        bypass_already_locked=False,
        error_retention_matrix={},
    )
    assert decision.spawn_remedial_course is False


def test_failing_final_assessment_spawns_remedial_course():
    decision = decide_remediation(
        score=PASS_THRESHOLD - 0.01,
        quiz_type="final_assessment",
        was_bypass_attempt=False,
        bypass_already_locked=False,
        error_retention_matrix={},
    )
    assert decision.spawn_remedial_course is True


def test_passing_final_assessment_never_spawns_remedial_course():
    decision = decide_remediation(
        score=1.0,
        quiz_type="final_assessment",
        was_bypass_attempt=False,
        bypass_already_locked=False,
        error_retention_matrix={},
    )
    assert decision.spawn_remedial_course is False


def test_bypass_attempt_failure_locks_bypass_regardless_of_luck_state():
    decision = decide_remediation(
        score=0.1,
        quiz_type="validation_assessment",
        was_bypass_attempt=True,
        bypass_already_locked=False,
        error_retention_matrix={},
    )
    assert decision.lock_bypass is True
    assert decision.mandatory_courses is None  # caller fills this in, not the policy


def test_gap_review_spawns_even_on_a_passed_attempt_if_other_concepts_flagged():
    """A learner can pass THIS quiz while still having stale flagged concepts
    from earlier failures — gap review should still surface those."""
    decision = decide_remediation(
        score=1.0,
        quiz_type="short_quiz",
        was_bypass_attempt=False,
        bypass_already_locked=False,
        error_retention_matrix={"stale_concept": 5},
    )
    assert decision.spawn_gap_review is True
    assert "stale_concept" in decision.flagged_concepts


def test_no_flagged_concepts_means_no_gap_review():
    decision = decide_remediation(
        score=1.0,
        quiz_type="short_quiz",
        was_bypass_attempt=False,
        bypass_already_locked=False,
        error_retention_matrix={},
    )
    assert decision.spawn_gap_review is False
    assert decision.luck_action == "MAINTAIN_ADAPTIVE_GAP_ASSESSMENT"


def test_reason_fuses_state_machine_and_luck_narratives():
    """The single `reason` string carries both halves of the decision, so a
    caller never has to stitch two separate reasons back together."""
    decision = decide_remediation(
        score=0.1,
        quiz_type="validation_assessment",
        was_bypass_attempt=True,
        bypass_already_locked=False,
        error_retention_matrix={"concept_x": 5, "concept_y": 5, "concept_z": 5},
    )
    assert "LOCKED" in decision.reason
    assert "drift" in decision.reason.lower() or "concept" in decision.reason.lower()


def test_returns_a_remediation_decision_instance():
    decision = decide_remediation(
        score=1.0,
        quiz_type="short_quiz",
        was_bypass_attempt=False,
        bypass_already_locked=False,
        error_retention_matrix={},
    )
    assert isinstance(decision, RemediationDecision)
    as_dict = decision.to_dict()
    assert set(as_dict.keys()) == {
        "next_state", "lock_bypass", "luck_action", "flagged_concepts",
        "spawn_gap_review", "spawn_remedial_course", "mandatory_courses", "reason",
    }
