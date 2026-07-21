"""Integration tests for the /api/quiz routes via FastAPI TestClient.

The department's knowledge base is empty in every test's isolated data dir,
so generate_quiz() has no grounding content and always takes its deterministic
template fallback — no Gemini call is made, and mock_gemini is not needed here.
"""

from src.core.database import DepartmentScopedStore


def _seed_quiz(department, quiz_id, questions):
    store = DepartmentScopedStore(department)
    quiz = {
        "quiz_id": quiz_id,
        "topic": "Test Topic",
        "quiz_type": "short_quiz",
        "questions": questions,
    }
    store.write_quiz(quiz_id, quiz)
    return quiz


def _question(question_id, correct_index=0, concept_tags=None):
    return {
        "question_id": question_id,
        "text": f"Question {question_id}?",
        "options": ["A", "B", "C", "D"],
        "correct_answer_index": correct_index,
        "rationale": {"0": "because A", "1": "because B", "2": "because C", "3": "because D"},
        "concept_tags": concept_tags or ["concept_x"],
    }


def test_generate_quiz_returns_sanitized_questions(client):
    resp = client.post(
        "/api/quiz/generate",
        json={"topic": "Onboarding", "question_count": 3},
        params={"department": "operations"},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["question_count"] == 3
    assert len(body["questions"]) == 3
    # correct_answer_index must never leak to the client.
    for q in body["questions"]:
        assert "correct_answer_index" not in q


def test_evaluate_answers_scores_and_updates_progress(client, test_data_dir):
    quiz = _seed_quiz(
        "operations", "quiz_pass",
        [_question("q1", correct_index=0), _question("q2", correct_index=0)],
    )

    resp = client.post(
        "/api/quiz/evaluate",
        json={
            "quiz_id": "quiz_pass",
            "user_id": "emp_001",
            "answers": [
                {"question_id": "q1", "selected_index": 0},
                {"question_id": "q2", "selected_index": 0},
            ],
        },
        params={"department": "operations"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["score"] == 1.0
    assert body["passed"] is True

    store = DepartmentScopedStore("operations")
    progress = store.read_user_progress("emp_001")
    assert progress is not None
    assert len(progress["quiz_attempts"]) == 1


def test_evaluate_answers_unknown_quiz_404(client):
    resp = client.post(
        "/api/quiz/evaluate",
        json={"quiz_id": "does_not_exist", "user_id": "emp_001", "answers": []},
        params={"department": "operations"},
    )
    assert resp.status_code == 404


def test_evaluate_single_answer_correct_and_incorrect(client):
    _seed_quiz(
        "operations", "quiz_single",
        [_question("q1", correct_index=2)],
    )

    correct = client.post(
        "/api/quiz/evaluate/single",
        json={"quiz_id": "quiz_single", "question_id": "q1", "selected_index": 2},
        params={"department": "operations"},
    )
    assert correct.status_code == 200
    assert correct.json()["is_correct"] is True

    incorrect = client.post(
        "/api/quiz/evaluate/single",
        json={"quiz_id": "quiz_single", "question_id": "q1", "selected_index": 0},
        params={"department": "operations"},
    )
    assert incorrect.status_code == 200
    assert incorrect.json()["is_correct"] is False


def test_evaluate_triggers_gap_review_after_repeated_failures(client):
    """Failing the same concept tag twice (LUCK_FAILURE_THRESHOLD=2) spawns a
    gap review — this is the luck-elimination lock the plan's edge case covers."""
    _seed_quiz("operations", "quiz_fail_1", [_question("q1", correct_index=0, concept_tags=["drift_concept"])])
    _seed_quiz("operations", "quiz_fail_2", [_question("q1", correct_index=0, concept_tags=["drift_concept"])])

    for quiz_id in ("quiz_fail_1", "quiz_fail_2"):
        resp = client.post(
            "/api/quiz/evaluate",
            json={
                "quiz_id": quiz_id,
                "user_id": "emp_002",
                "answers": [{"question_id": "q1", "selected_index": 1}],  # wrong every time
            },
            params={"department": "operations"},
        )
        assert resp.status_code == 200

    body = resp.json()
    assert body["luck_elimination_status"]["action"] == "SPAWN_GAP_REVIEW"
    assert "drift_concept" in body["luck_elimination_status"]["flagged_concepts"]
    assert body["gap_review_triggered"] is True
    assert body["gap_review_mandatory"] is False
    concepts = [ex["concept"] for ex in body["gap_review"]["exercises"]]
    assert "drift_concept" in concepts


def test_evaluate_maintain_action_omits_gap_review(client):
    """A single pass, no repeat failures — luck elimination stays in
    MAINTAIN mode and the response must not carry gap_review keys at all."""
    _seed_quiz("operations", "quiz_maintain", [_question("q1", correct_index=0)])

    resp = client.post(
        "/api/quiz/evaluate",
        json={"quiz_id": "quiz_maintain", "user_id": "emp_004", "answers": [{"question_id": "q1", "selected_index": 0}]},
        params={"department": "operations"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["luck_elimination_status"]["action"] == "MAINTAIN_ADAPTIVE_GAP_ASSESSMENT"
    assert "gap_review_triggered" not in body
    assert "gap_review" not in body


def test_evaluate_force_mandatory_attaches_gap_review(client):
    """FORCE_MANDATORY_LEARNING_PATH needs core_drift_concept_count (default 3)
    DISTINCT concepts each failed >= LUCK_FAILURE_THRESHOLD (default 2) times —
    not one concept failed 3x (that's still just SPAWN_GAP_REVIEW)."""
    concepts = ["drift_a", "drift_b", "drift_c"]
    for i, concept in enumerate(concepts):
        _seed_quiz(
            "operations", f"quiz_mand_{i}",
            [_question("q1", correct_index=0, concept_tags=[concept]),
             _question("q2", correct_index=0, concept_tags=[concept])],
        )

    resp = None
    for i in range(len(concepts)):
        resp = client.post(
            "/api/quiz/evaluate",
            json={
                "quiz_id": f"quiz_mand_{i}",
                "user_id": "emp_005",
                "answers": [
                    {"question_id": "q1", "selected_index": 1},
                    {"question_id": "q2", "selected_index": 1},
                ],
            },
            params={"department": "operations"},
        )
        assert resp.status_code == 200

    body = resp.json()
    assert body["luck_elimination_status"]["action"] == "FORCE_MANDATORY_LEARNING_PATH"
    assert body["gap_review_triggered"] is True
    assert body["gap_review_mandatory"] is True


def test_generate_remedial_course_llm_failure_still_has_questions(mock_gemini, test_data_dir):
    """The remedial-course LLM-failure fallback must still be gradeable —
    regression test for the empty-questions bug found during the UAT audit."""
    from src.services.curriculum_service import generate_remedial_course

    mock_gemini(Exception("boom"))
    course = generate_remedial_course(
        incorrect_answers=[{
            "question_text": "What is X?", "user_answer": "A", "correct_answer": "B",
            "concept_tags": ["topic_x"],
        }],
        user_id="emp_001",
        source_course_id="course_1",
        department="operations",
    )

    sq_questions = course["lessons"][0]["short_quiz"]["questions"]
    fa_questions = course["final_assessment"]["questions"]
    assert len(sq_questions) > 0
    assert len(fa_questions) > 0
    for q in sq_questions + fa_questions:
        assert "correct_answer_index" in q
        assert "question_id" in q
        assert len(q["options"]) == 4


def test_evaluate_route_llm_failure_remedial_course_gradeable(client, mock_gemini):
    """End-to-end: a failed final assessment with a broken LLM call still
    produces a remedial course the learner can actually pass."""
    _seed_quiz(
        "operations", "quiz_fa_fail",
        [_question("q1", correct_index=0, concept_tags=["topic_y"])],
    )
    mock_gemini(Exception("boom"))

    resp = client.post(
        "/api/quiz/evaluate",
        json={
            "quiz_id": "quiz_fa_fail",
            "user_id": "emp_001",
            "answers": [{"question_id": "q1", "selected_index": 1}],  # wrong
            "quiz_type": "final_assessment",
            "course_id": "course_source",
        },
        params={"department": "operations"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["remedial_course_generated"] is True

    # The remedial course's quiz is only lazily written to the quiz store the
    # first time /api/quiz/by-lesson fetches it — check the embedded copy on
    # the progress record directly, which is what's persisted at generation time.
    store = DepartmentScopedStore("operations")
    progress = store.read_user_progress("emp_001")
    remedial = next(
        rc for rc in progress["remedial_courses"]
        if rc["course_id"] == body["remedial_course_id"]
    )
    assert len(remedial["lessons"][0]["short_quiz"]["questions"]) > 0
    assert len(remedial["final_assessment"]["questions"]) > 0


def test_gap_review_retry_generates_startable_quiz(client, test_data_dir, seed_progress, mock_gemini):
    """The gap-review banner used to only be instructions text — retry must
    generate a real, immediately-startable quiz for the flagged concept."""
    seed_progress(
        test_data_dir, "operations", "emp_006",
        concept_diagnoses={
            "escalation_procedure": [
                {"misconception": "Confuses ticket severity with escalation priority.", "resolved": False}
            ]
        },
    )
    # extra_context (the misconception above) makes grounding_context non-empty,
    # so generate_quiz takes the LLM path — mock it rather than hitting live Gemini.
    mock_gemini(RuntimeError("no live calls in tests"))

    resp = client.post(
        "/api/quiz/gap-review/retry",
        json={"user_id": "emp_006", "concept_tags": ["escalation_procedure"]},
        params={"department": "operations"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["concept_tags"] == ["escalation_procedure"]
    assert len(body["questions"]) == 3
    for q in body["questions"]:
        assert "correct_answer_index" not in q

    # The quiz is cached and fetchable by ID for the redirect target.
    session_resp = client.get(
        f"/api/quiz/session/{body['quiz_id']}", params={"department": "operations"}
    )
    assert session_resp.status_code == 200
    assert session_resp.json()["quiz_id"] == body["quiz_id"]


def test_gap_review_retry_rejects_empty_concept_tags(client):
    resp = client.post(
        "/api/quiz/gap-review/retry",
        json={"user_id": "emp_006", "concept_tags": []},
        params={"department": "operations"},
    )
    assert resp.status_code == 400


def test_quiz_session_unknown_id_404(client):
    resp = client.get("/api/quiz/session/does_not_exist", params={"department": "operations"})
    assert resp.status_code == 404


def test_quiz_start_locked_after_max_attempts(client, test_data_dir, seed_progress):
    # MAX_QUIZ_ATTEMPTS is 3 — seed 3 prior attempts on the same topic.
    seed_progress(
        test_data_dir, "operations", "emp_003",
        quiz_attempts=[
            {"topic": "Onboarding", "quiz_type": "short_quiz"},
            {"topic": "Onboarding", "quiz_type": "short_quiz"},
            {"topic": "Onboarding", "quiz_type": "short_quiz"},
        ],
    )

    resp = client.post(
        "/api/quiz/start",
        json={"topic": "Onboarding", "user_id": "emp_003"},
        params={"department": "operations"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "locked"
    assert body["attempts_remaining"] == 0
