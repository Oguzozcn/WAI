import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.services.routing_service import AdaptiveMetacognitiveRouter
from src.services.quiz_service import EnterprisePsychometricEngine
from WAI_agent.shared.data_compliance_gate import DataComplianceGate

def check_metacognitive_router():
    print("--- Checking AdaptiveMetacognitiveRouter ---")
    
    # High confidence, low accuracy (Hidden Knowledge Gaps -> Standard)
    state = AdaptiveMetacognitiveRouter.evaluate_competence(0.5, 0.8)
    path = AdaptiveMetacognitiveRouter.get_recommended_path(state)
    print(f"High Conf, Low Acc: State='{state}', Path='{path}' (Expected: hidden_knowledge_gaps, standard)")
    assert state == "hidden_knowledge_gaps"
    assert path == "standard"
    
    # Low confidence, high accuracy (Unconscious Competence -> Intermediate)
    state = AdaptiveMetacognitiveRouter.evaluate_competence(0.9, 0.6)
    path = AdaptiveMetacognitiveRouter.get_recommended_path(state)
    print(f"Low Conf, High Acc: State='{state}', Path='{path}' (Expected: unconscious_competence, intermediate)")
    assert state == "unconscious_competence"
    assert path == "intermediate"
    print("AdaptiveMetacognitiveRouter Check Passed.\n")

def check_psychometric_engine():
    print("--- Checking EnterprisePsychometricEngine ---")
    items = [{"discrimination": 1.0, "difficulty": 0.0, "guessing": 0.25, "slip": 0.95}]
    
    # Correct Answer
    new_theta_correct = EnterprisePsychometricEngine.update_learner_ability(0.0, items, [1])
    print(f"Theta after Correct: {new_theta_correct}")
    assert new_theta_correct > 0.0
    
    # Incorrect Answer
    new_theta_incorrect = EnterprisePsychometricEngine.update_learner_ability(0.0, items, [0])
    print(f"Theta after Incorrect: {new_theta_incorrect}")
    assert new_theta_incorrect < 0.0
    
    print("EnterprisePsychometricEngine Check Passed.\n")

def check_compliance_gate():
    print("--- Checking DataComplianceGate ---")
    
    # Attempting to pass without signature or DPIA
    result_blocked = DataComplianceGate.audit_state_transition("user_1", "passed", {})
    print("Blocked State:", result_blocked)
    assert result_blocked["allowed"] is False
    assert result_blocked["enforced_state"] == "PENDING_VERIFIED_HUMAN_APPROVAL"
    
    # Attempting to pass with signature and DPIA
    context = {"human_controller_signature": "admin_sig_123", "dpia_completed": True}
    result_allowed = DataComplianceGate.audit_state_transition("user_1", "passed", context)
    print("Allowed State:", result_allowed)
    assert result_allowed["allowed"] is True
    assert result_allowed["enforced_state"] == "passed"
    
    print("DataComplianceGate Check Passed.\n")

if __name__ == "__main__":
    try:
        check_metacognitive_router()
        check_psychometric_engine()
        check_compliance_gate()
        print("ALL CHECKS PASSED SUCCESSFULLY.")
    except Exception as e:
        print("CHECK FAILED:", str(e))
        sys.exit(1)
