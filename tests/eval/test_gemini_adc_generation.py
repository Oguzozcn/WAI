import os
import sys
from pathlib import Path

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.services.curriculum_service import generate_remedial_course
from src.core.config import DEFAULT_DEPARTMENT

@pytest.mark.llm
def test_gemini_adc_remedial_generation():
    """
    Check Test: Verifies that the existing learning module generation
    functions correctly using gemini-3.5-flash and ADC.
    """
    
    mock_incorrect_answers = [
        {
            "question_id": "q1",
            "question_text": "What is the primary role of a Kubernetes Pod?",
            "user_answer": "To route external traffic to nodes.",
            "correct_answer": "It is the smallest deployable computing unit that you can create and manage in Kubernetes.",
            "concept_tags": ["kubernetes_pods", "container_orchestration"]
        },
        {
            "question_id": "q2",
            "question_text": "Why do we use load balancers?",
            "user_answer": "To store container images.",
            "correct_answer": "To distribute network traffic across multiple servers.",
            "concept_tags": ["networking", "load_balancing"]
        }
    ]
    
    result = generate_remedial_course(
        incorrect_answers=mock_incorrect_answers,
        user_id="test_user_001",
        source_course_id="test_course_123",
        department=DEFAULT_DEPARTMENT
    )
    
    print("REMEDIAL GENERATION RESULT:", result)
    
    assert result is not None
    assert "title" in result
    assert "lessons" in result
    assert len(result["lessons"]) > 0
    
if __name__ == "__main__":
    print("Running ADC check test for Gemini Curriculum Generation...")
    test_gemini_adc_remedial_generation()
    print("Test passed successfully! ADC integration is fully functional.")
