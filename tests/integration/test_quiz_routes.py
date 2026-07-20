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

    assert resp.json()["luck_elimination_status"]["action"] == "SPAWN_GAP_REVIEW"
    assert "drift_concept" in resp.json()["luck_elimination_status"]["flagged_concepts"]


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
