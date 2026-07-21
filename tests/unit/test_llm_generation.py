"""Unit tests for the LLM-backed generation paths, with Gemini mocked.

The ``mock_gemini`` fixture patches ``get_gemini_client`` in both quiz_service
and curriculum_service. Each test configures the fake to return specific JSON
text (proving the LLM branch was taken) or to raise (proving the deterministic
fallback branch was taken). No real Gemini/Vertex call is ever made.
"""

import json

from src.core.database import DepartmentScopedStore
from src.services.quiz_service import generate_quiz
from src.services.curriculum_service import process_document_to_curriculum


def _seed_grounding_doc():
    """Write a KB doc that generate_quiz will treat as grounding for the topic."""
    store = DepartmentScopedStore("operations")
    store.write_knowledge_document(
        "warehouse_doc",
        {
            "title": "Warehouse Safety Handbook",
            "topics": ["warehouse safety", "ppe"],
            "content": (
                "Warehouse safety requires wearing PPE at all times. Operators must "
                "follow forklift safety rules and keep aisles clear during shifts."
            ),
        },
    )


# ── generate_quiz ────────────────────────────────────────────────────────────

def test_generate_quiz_uses_llm_when_grounded(test_data_dir, mock_gemini):
    _seed_grounding_doc()
    llm_json = json.dumps({
        "questions": [
            {
                "text": "LLM question one?",
                "options": ["a", "b", "c", "d"],
                "correct_answer_index": 0,
                "rationale": {"0": "r", "1": "r", "2": "r", "3": "r"},
                "concept_tags": ["safety"],
            },
            {
                "text": "LLM question two?",
                "options": ["a", "b", "c", "d"],
                "correct_answer_index": 1,
                "rationale": {"0": "r", "1": "r", "2": "r", "3": "r"},
                "concept_tags": ["ppe"],
            },
        ]
    })
    mock_gemini(llm_json)

    quiz = generate_quiz(topic="warehouse safety", department="operations", question_count=2)

    assert [q["text"] for q in quiz["questions"]] == [
        "LLM question one?",
        "LLM question two?",
    ]
    for q in quiz["questions"]:
        assert q["question_id"].startswith("q_")


def test_generate_quiz_falls_back_when_llm_raises(test_data_dir, mock_gemini):
    _seed_grounding_doc()
    mock_gemini(RuntimeError("gemini exploded"))

    quiz = generate_quiz(topic="warehouse safety", department="operations", question_count=2)

    assert len(quiz["questions"]) == 2
    assert quiz["questions"][0]["text"] == (
        "Regarding 'warehouse safety', which of the following represents "
        "the core concept for part 1?"
    )


def test_generate_quiz_falls_back_when_no_grounding(test_data_dir, mock_gemini):
    # No KB docs seeded → no grounding context → deterministic template regardless
    # of what the (misconfigured) LLM would return.
    mock_gemini(json.dumps({"questions": [{"text": "should never be used"}]}))

    quiz = generate_quiz(topic="unknown topic", department="operations", question_count=3)

    assert len(quiz["questions"]) == 3
    for i, q in enumerate(quiz["questions"]):
        assert q["text"] == (
            f"Regarding 'unknown topic', which of the following represents "
            f"the core concept for part {i + 1}?"
        )


# ── process_document_to_curriculum ───────────────────────────────────────────

_DOC = "## Section One\nBody one text.\n\n## Section Two\nBody two text."


def test_process_document_uses_llm_content(test_data_dir, mock_gemini):
    llm_json = json.dumps({
        "sections": [
            {"index": 0, "content_summary": "LLM Summary Zero", "key_points": ["k1"]},
            {"index": 1, "content_summary": "LLM Summary One", "key_points": ["k2"]},
        ]
    })
    mock_gemini(llm_json)

    result = process_document_to_curriculum(_DOC, department="operations")
    assert result["status"] == "success"
    lessons = result["course"]["lessons"]
    assert lessons[0]["content"] == "LLM Summary Zero"
    assert lessons[1]["content"] == "LLM Summary One"


def test_process_document_falls_back_to_raw_section_text(test_data_dir, mock_gemini):
    mock_gemini(RuntimeError("gemini exploded"))

    result = process_document_to_curriculum(_DOC, department="operations")
    assert result["status"] == "success"
    lessons = result["course"]["lessons"]
    assert lessons[0]["content"] == "Body one text."
    assert lessons[1]["content"] == "Body two text."
    # No LLM title available -> falls back to the heading-derived heuristic title.
    assert lessons[0]["title"] == "Section One"
    assert lessons[1]["title"] == "Section Two"
    # No LLM course_title -> falls back to the cleaned-up filename.
    assert result["course"]["title"] == "Uploaded Document"


def test_process_document_uses_llm_titles_when_present(test_data_dir, mock_gemini):
    llm_json = json.dumps({
        "course_title": "Warehouse Safety Fundamentals",
        "sections": [
            {"index": 0, "title": "Personal Protective Equipment Basics",
             "content_summary": "LLM Summary Zero", "key_points": ["k1"]},
            {"index": 1, "title": "Forklift Operating Rules",
             "content_summary": "LLM Summary One", "key_points": ["k2"]},
        ],
    })
    mock_gemini(llm_json)

    result = process_document_to_curriculum(
        _DOC, document_title="warehouse_dtp_v2_FINAL.txt", department="operations",
    )
    assert result["status"] == "success"
    assert result["course"]["title"] == "Warehouse Safety Fundamentals"
    lessons = result["course"]["lessons"]
    assert lessons[0]["title"] == "Personal Protective Equipment Basics"
    assert lessons[1]["title"] == "Forklift Operating Rules"


def test_process_document_falls_back_per_field_when_llm_omits_titles(test_data_dir, mock_gemini):
    """An LLM response using the OLD schema (no course_title/title fields) must
    not break — each missing field falls back to its own heuristic independently."""
    llm_json = json.dumps({
        "sections": [
            {"index": 0, "content_summary": "LLM Summary Zero", "key_points": ["k1"]},
            {"index": 1, "content_summary": "LLM Summary One", "key_points": ["k2"]},
        ]
    })
    mock_gemini(llm_json)

    result = process_document_to_curriculum(
        _DOC, document_title="warehouse_dtp.txt", department="operations",
    )
    assert result["course"]["title"] == "Warehouse Dtp"
    lessons = result["course"]["lessons"]
    assert lessons[0]["title"] == "Section One"
    assert lessons[0]["content"] == "LLM Summary Zero"  # content_summary still used


def test_process_document_caps_an_overlong_llm_title(test_data_dir, mock_gemini):
    long_title = "Word " * 40  # far longer than the 100-char course-title cap
    llm_json = json.dumps({
        "course_title": long_title,
        "sections": [
            {"index": 0, "title": long_title, "content_summary": "s0", "key_points": ["k1"]},
            {"index": 1, "content_summary": "s1", "key_points": ["k2"]},
        ],
    })
    mock_gemini(llm_json)

    result = process_document_to_curriculum(_DOC, department="operations")
    assert len(result["course"]["title"]) <= 101  # 100 chars + the ellipsis char
    assert result["course"]["title"].endswith("…")
    assert len(result["course"]["lessons"][0]["title"]) <= 81
