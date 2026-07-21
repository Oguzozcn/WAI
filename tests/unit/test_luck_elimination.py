"""Unit tests for LuckEliminationEngine and the HLR retention math."""

from datetime import datetime, timedelta, timezone

import pytest

from src.core.luck_elimination import (
    ACTION_CONTINUE,
    ACTION_FORCE_MANDATORY,
    ACTION_SPAWN_GAP_REVIEW,
    LuckEliminationEngine,
    calculate_hlr_retention,
)


def test_no_failures_continues():
    engine = LuckEliminationEngine(mandatory_threshold=2)
    result = engine.evaluate_user_progression({})
    assert result["action"] == ACTION_CONTINUE
    assert result["flagged_concepts"] == []


def test_one_concept_at_threshold_spawns_gap_review():
    engine = LuckEliminationEngine(mandatory_threshold=2)
    result = engine.evaluate_user_progression({"concept_a": 2})
    assert result["action"] == ACTION_SPAWN_GAP_REVIEW
    assert result["flagged_concepts"] == ["concept_a"]


def test_below_threshold_never_flags():
    engine = LuckEliminationEngine(mandatory_threshold=2)
    result = engine.evaluate_user_progression({"concept_a": 1})
    assert result["action"] == ACTION_CONTINUE
    assert result["flagged_concepts"] == []


def test_core_drift_concept_count_forces_mandatory_path():
    """core_drift_concept_count distinct concepts each at/above the failure
    threshold forces the mandatory path — one concept failed many times does
    NOT (that's still just a gap review)."""
    engine = LuckEliminationEngine(mandatory_threshold=2)
    engine.core_drift_concept_count = 3

    # One concept failed 10 times -> still just SPAWN_GAP_REVIEW.
    single = engine.evaluate_user_progression({"concept_a": 10})
    assert single["action"] == ACTION_SPAWN_GAP_REVIEW

    # Three distinct concepts each at threshold -> FORCE_MANDATORY.
    triple = engine.evaluate_user_progression(
        {"concept_a": 2, "concept_b": 2, "concept_c": 2}
    )
    assert triple["action"] == ACTION_FORCE_MANDATORY
    assert set(triple["flagged_concepts"]) == {"concept_a", "concept_b", "concept_c"}


def test_new_attempts_fold_into_matrix_before_flagging():
    engine = LuckEliminationEngine(mandatory_threshold=2)
    result = engine.evaluate_user_progression(
        error_retention_matrix={"concept_a": 1},
        new_attempts=[{"is_correct": False, "concept_tags": ["concept_a"]}],
    )
    assert result["action"] == ACTION_SPAWN_GAP_REVIEW
    assert result["updated_matrix"]["concept_a"] == 2


def test_get_concept_failure_summary_status_bands():
    engine = LuckEliminationEngine(mandatory_threshold=2)
    summary = engine.get_concept_failure_summary(
        {"critical_concept": 4, "warning_concept": 2, "ok_concept": 1}
    )
    by_concept = {s["concept"]: s["status"] for s in summary}
    assert by_concept["critical_concept"] == "critical"
    assert by_concept["warning_concept"] == "warning"
    assert by_concept["ok_concept"] == "ok"
    # Sorted worst-first.
    assert summary[0]["concept"] == "critical_concept"


def test_calculate_hlr_retention_at_half_life_is_half():
    ten_days_ago = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    vector = {"last_seen": ten_days_ago, "half_life_days": 10.0}
    retention = calculate_hlr_retention(vector)
    assert retention == pytest.approx(0.5, abs=0.01)


def test_calculate_hlr_retention_just_seen_is_near_one():
    vector = {"last_seen": datetime.now(timezone.utc).isoformat(), "half_life_days": 7.0}
    assert calculate_hlr_retention(vector) == pytest.approx(1.0, abs=0.01)


def test_calculate_hlr_retention_missing_last_seen_defaults_to_zero_days():
    # No parseable last_seen -> delta_t treated as 0 -> full retention.
    assert calculate_hlr_retention({"half_life_days": 7.0}) == pytest.approx(1.0, abs=0.01)


def test_evaluate_luck_and_decay_removed():
    """Dead code removed during the remedial-path rework — it had zero
    callers and duplicated policy that now lives in remediation_policy.py."""
    import src.core.luck_elimination as mod
    assert not hasattr(mod, "evaluate_luck_and_decay")
