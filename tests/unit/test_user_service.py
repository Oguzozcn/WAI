"""Unit tests for src.services.user_service — the module that reads and
mutates a learner's progress record (state, readiness score, at-risk flags).

No test in the suite referenced this file before; these lock down the
existing behavior of get_user_progress/update_progress/_recalculate_readiness
so future changes to the readiness formula or event handling can't silently
break what determines a learner's state.
"""

from src.services.user_service import (
    get_user_progress,
    update_progress,
    get_department_readiness,
    flag_at_risk_users,
    _recalculate_readiness,
)
from tests.conftest import seed_user_progress


# ── get_user_progress ────────────────────────────────────────────────────────

def test_get_user_progress_not_found_for_missing_user(test_data_dir):
    result = get_user_progress("ghost", department="operations")
    assert result["status"] == "not_found"


def test_get_user_progress_computes_summary_fields(test_data_dir):
    seed_user_progress(
        test_data_dir, "operations", "u1",
        completed_courses=["course_01"],
        quiz_attempts=[{"score": 0.9}, {"score": 0.4}],
        error_retention_matrix={"concept_a": 2, "concept_b": 1},
        readiness_score=0.3,
    )
    result = get_user_progress("u1", department="operations")
    assert result["summary"]["courses_completed"] == 1
    assert result["summary"]["total_quizzes_taken"] == 2
    # LUCK_FAILURE_THRESHOLD is 2 -> only concept_a (count=2) counts as an active gap.
    assert result["summary"]["active_knowledge_gaps"] == 1
    assert result["summary"]["is_at_risk"] is True


# ── update_progress: event handling ─────────────────────────────────────────

def test_update_progress_creates_new_record_when_none_exists(test_data_dir):
    result = update_progress("new_user", "course_started", {"course_id": "course_01"}, department="operations")
    assert result["status"] == "updated"
    assert result["current_state"] == "course_in_progress"

    stored = get_user_progress("new_user", department="operations")
    assert stored["current_course_id"] == "course_01"


def test_course_started_sets_current_course_and_transitions_state(test_data_dir):
    seed_user_progress(test_data_dir, "operations", "u2", current_state="enrolled")
    update_progress("u2", "course_started", {"course_id": "course_05"}, department="operations")
    stored = get_user_progress("u2", department="operations")
    assert stored["current_course_id"] == "course_05"
    assert stored["current_state"] == "course_in_progress"


def test_course_started_ignores_an_already_completed_course(test_data_dir):
    seed_user_progress(
        test_data_dir, "operations", "u3",
        completed_courses=["course_01"], current_state="course_in_progress",
    )
    update_progress("u3", "course_started", {"course_id": "course_01"}, department="operations")
    stored = get_user_progress("u3", department="operations")
    assert stored.get("current_course_id", "") != "course_01"


def test_course_completed_appends_and_clears_current_course_id(test_data_dir):
    seed_user_progress(
        test_data_dir, "operations", "u4",
        completed_courses=[], current_course_id="course_02",
    )
    update_progress("u4", "course_completed", {"course_id": "course_02"}, department="operations")
    stored = get_user_progress("u4", department="operations")
    assert "course_02" in stored["completed_courses"]
    assert stored["current_course_id"] == ""


def test_course_completed_does_not_duplicate_existing_entry(test_data_dir):
    seed_user_progress(test_data_dir, "operations", "u5", completed_courses=["course_02"])
    update_progress("u5", "course_completed", {"course_id": "course_02"}, department="operations")
    stored = get_user_progress("u5", department="operations")
    assert stored["completed_courses"].count("course_02") == 1


def test_path_enrolled_appends_without_duplicates(test_data_dir):
    seed_user_progress(test_data_dir, "operations", "u6", enrolled_path_ids=["lp_aaa"])
    update_progress("u6", "path_enrolled", {"path_id": "lp_aaa"}, department="operations")
    update_progress("u6", "path_enrolled", {"path_id": "lp_bbb"}, department="operations")
    stored = get_user_progress("u6", department="operations")
    assert stored["enrolled_path_ids"] == ["lp_aaa", "lp_bbb"]


def test_path_assigned_sets_entry_fields(test_data_dir):
    seed_user_progress(test_data_dir, "operations", "u7")
    update_progress(
        "u7", "path_assigned",
        {"entry_path": "fast_track", "learning_path_id": "lp_xyz", "initial_state": "course_in_progress"},
        department="operations",
    )
    stored = get_user_progress("u7", department="operations")
    assert stored["entry_path"] == "fast_track"
    assert stored["learning_path_id"] == "lp_xyz"
    assert stored["current_state"] == "course_in_progress"


def test_bypass_locked_sets_flag_and_state(test_data_dir):
    seed_user_progress(test_data_dir, "operations", "u8", bypass_locked=False)
    update_progress("u8", "bypass_locked", {}, department="operations")
    stored = get_user_progress("u8", department="operations")
    assert stored["bypass_locked"] is True
    assert stored["current_state"] == "bypass_locked"


# ── update_progress: GDPR compliance gate on state transitions ──────────────

def test_state_changed_to_passed_without_signature_is_blocked(test_data_dir):
    seed_user_progress(test_data_dir, "operations", "u9", current_state="validation_assessment")
    result = update_progress(
        "u9", "state_changed", {"new_state": "passed", "context": {}}, department="operations",
    )
    assert result["current_state"] == "PENDING_VERIFIED_HUMAN_APPROVAL"


def test_state_changed_to_passed_with_signature_and_dpia_is_allowed(test_data_dir):
    seed_user_progress(test_data_dir, "operations", "u10", current_state="validation_assessment")
    result = update_progress(
        "u10", "state_changed",
        {"new_state": "passed", "context": {"human_controller_signature": "mgr_1", "dpia_completed": True}},
        department="operations",
    )
    assert result["current_state"] == "passed"


def test_assessment_passed_without_signature_is_held_for_approval(test_data_dir):
    seed_user_progress(test_data_dir, "operations", "u11", current_state="validation_assessment")
    result = update_progress("u11", "assessment_passed", {}, department="operations")
    assert result["current_state"] == "PENDING_VERIFIED_HUMAN_APPROVAL"
    # readiness_score is set to 1.0 by the event handler itself, before the
    # compliance gate's state decision — and _recalculate_readiness leaves it
    # alone only when current_state ends up "passed"/"completed", which it
    # didn't here. This documents that (currently) surprising interaction.
    stored = get_user_progress("u11", department="operations")
    assert stored["readiness_score"] != 1.0


# ── get_department_readiness ─────────────────────────────────────────────────

def test_department_readiness_no_data(test_data_dir):
    result = get_department_readiness(department="operations")
    assert result["status"] == "no_data"


def test_department_readiness_aggregates_across_users(test_data_dir):
    seed_user_progress(test_data_dir, "operations", "a1", readiness_score=0.9, current_state="completed")
    seed_user_progress(test_data_dir, "operations", "a2", readiness_score=0.2, current_state="enrolled")
    result = get_department_readiness(department="operations")
    assert result["total_enrolled"] == 2
    assert result["at_risk_count"] == 1
    assert result["completed_count"] == 1
    assert result["avg_readiness_score"] == 0.55


# ── flag_at_risk_users ────────────────────────────────────────────────────────

def test_flag_at_risk_users_identifies_biggest_gap(test_data_dir):
    seed_user_progress(
        test_data_dir, "operations", "r1",
        readiness_score=0.3,
        error_retention_matrix={"concept_a": 1, "concept_b": 3},
    )
    result = flag_at_risk_users(department="operations")
    assert result["total_at_risk"] == 1
    assert result["at_risk_users"][0]["blocked_by"] == "concept_b"


def test_flag_at_risk_users_defaults_blocked_by_when_no_gaps_recorded(test_data_dir):
    seed_user_progress(test_data_dir, "operations", "r2", readiness_score=0.1, error_retention_matrix={})
    result = flag_at_risk_users(department="operations")
    assert result["at_risk_users"][0]["blocked_by"] == "general"


def test_flag_at_risk_users_excludes_users_above_threshold(test_data_dir):
    seed_user_progress(test_data_dir, "operations", "r3", readiness_score=0.95)
    result = flag_at_risk_users(department="operations")
    assert result["total_at_risk"] == 0


# ── _recalculate_readiness ───────────────────────────────────────────────────

def test_recalculate_readiness_zero_progress_gives_zero_score():
    progress = {"completed_courses": [], "quiz_attempts": [], "current_state": "enrolled"}
    _recalculate_readiness(progress)
    assert progress["readiness_score"] == 0.0
    assert progress["is_at_risk"] is True


def test_recalculate_readiness_passed_state_short_circuits_to_full_score():
    progress = {"completed_courses": [], "quiz_attempts": [], "current_state": "passed"}
    _recalculate_readiness(progress)
    assert progress["readiness_score"] == 1.0


def test_recalculate_readiness_only_uses_last_n_quiz_attempts():
    """quiz_window_size is 5 — a long run of perfect scores should outweigh
    a handful of old failures once they roll off the window."""
    progress = {
        "completed_courses": [],
        "quiz_attempts": [{"score": 0.0}] * 3 + [{"score": 1.0}] * 5,
        "current_state": "enrolled",
    }
    _recalculate_readiness(progress)
    # quiz_readiness = avg(last 5 scores=1.0) * 0.3 = 0.3; course/state readiness = 0.
    assert progress["readiness_score"] == 0.3


def test_recalculate_readiness_blends_course_and_quiz_components():
    progress = {
        "completed_courses": ["c1", "c2"],  # 2/10 courses
        "quiz_attempts": [{"score": 0.8}],
        "current_state": "course_in_progress",
    }
    _recalculate_readiness(progress)
    # course: (2/10)*0.5 = 0.10; quiz: 0.8*0.3 = 0.24; state: 0.25*0.2 = 0.05
    assert progress["readiness_score"] == round(0.10 + 0.24 + 0.05, 2)
