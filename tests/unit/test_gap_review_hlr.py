"""Unit tests for generate_gap_review's HLR due-for-review filtering.

A flagged concept is only deferred to `scheduled_for_later` when its mastery
vector shows BOTH high retention (still remembered) AND decent ability
(they've actually been getting it right) — otherwise it stays in `exercises`
immediately, exactly like before this filtering existed.
"""

from datetime import datetime, timedelta, timezone

from src.core.database import DepartmentScopedStore
from src.services.quiz_service import generate_gap_review


def _seed(data_dir, user_id, error_retention_matrix, mastery_vectors=None, concept_diagnoses=None):
    from tests.conftest import seed_user_progress
    seed_user_progress(
        data_dir, "operations", user_id,
        error_retention_matrix=error_retention_matrix,
        mastery_vectors=mastery_vectors or {},
        concept_diagnoses=concept_diagnoses or {},
    )


def test_concept_with_no_mastery_vector_stays_immediate(test_data_dir):
    """No vector at all -> nothing to gate on -> original immediate-inclusion
    behavior (matches pre-HLR-wiring behavior for a never-quizzed-via-route concept)."""
    _seed(test_data_dir, "u1", {"concept_a": 2})
    result = generate_gap_review(user_id="u1", department="operations")
    concepts = [ex["concept"] for ex in result["exercises"]]
    assert "concept_a" in concepts
    assert result["scheduled_for_later"] == []


def test_high_retention_and_high_ability_defers_to_scheduled(test_data_dir):
    """Well-retained AND performing well -> not due yet -> deferred, not dumped."""
    ten_minutes_ago = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    _seed(
        test_data_dir, "u2", {"concept_b": 2},
        mastery_vectors={
            "concept_b": {
                "concept_id": "concept_b", "ability_score": 0.9,
                "last_seen": ten_minutes_ago, "half_life_days": 7.0,
            }
        },
    )
    result = generate_gap_review(user_id="u2", department="operations")
    concepts = [ex["concept"] for ex in result["exercises"]]
    assert "concept_b" not in concepts
    scheduled_concepts = [s["concept"] for s in result["scheduled_for_later"]]
    assert "concept_b" in scheduled_concepts


def test_high_retention_but_low_ability_stays_immediate(test_data_dir):
    """Recently seen (high retention) but ability_score is low (just failed) ->
    must NOT be deferred — this is exactly the just-failed-twice scenario."""
    just_now = datetime.now(timezone.utc).isoformat()
    _seed(
        test_data_dir, "u3", {"concept_c": 2},
        mastery_vectors={
            "concept_c": {
                "concept_id": "concept_c", "ability_score": 0.3,
                "last_seen": just_now, "half_life_days": 7.0,
            }
        },
    )
    result = generate_gap_review(user_id="u3", department="operations")
    concepts = [ex["concept"] for ex in result["exercises"]]
    assert "concept_c" in concepts
    assert result["scheduled_for_later"] == []


def test_low_retention_but_high_ability_stays_immediate(test_data_dir):
    """Long-decayed (low retention) even with decent ability -> due for review
    again -> must stay immediate, not deferred."""
    long_ago = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    _seed(
        test_data_dir, "u4", {"concept_d": 2},
        mastery_vectors={
            "concept_d": {
                "concept_id": "concept_d", "ability_score": 0.9,
                "last_seen": long_ago, "half_life_days": 7.0,
            }
        },
    )
    result = generate_gap_review(user_id="u4", department="operations")
    concepts = [ex["concept"] for ex in result["exercises"]]
    assert "concept_d" in concepts


def test_exercise_instructions_use_stored_misconception_when_available(test_data_dir):
    _seed(
        test_data_dir, "u5", {"concept_e": 2},
        concept_diagnoses={
            "concept_e": [{"misconception": "Confuses X with Y.", "resolved": False}]
        },
    )
    result = generate_gap_review(user_id="u5", department="operations")
    exercise = next(ex for ex in result["exercises"] if ex["concept"] == "concept_e")
    assert "Confuses X with Y." in exercise["instructions"]


def test_exercise_instructions_fall_back_to_generic_template(test_data_dir):
    _seed(test_data_dir, "u6", {"concept_f": 2})
    result = generate_gap_review(user_id="u6", department="operations")
    exercise = next(ex for ex in result["exercises"] if ex["concept"] == "concept_f")
    assert "Review the concept 'concept_f' thoroughly" in exercise["instructions"]
