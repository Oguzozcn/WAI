"""
TEAP Data Compliance Gate
===========================
Security middleware enforcing GDPR Article 35 (DPIA validation) and Labour Code regulations.

Migrated from WAI_agent/shared/data_compliance_gate.py → src/core/data_compliance_gate.py (ADK 2.0)
"""

from datetime import datetime


class DataComplianceGate:
    """
    Security middleware enforcing GDPR Article 35 (DPIA validation) and Labour Code regulations.
    Prevents automatic system-generated completions from granting authorizations without manual
    human validation.
    """

    @staticmethod
    def audit_state_transition(user_id: str, proposed_state: str, context: dict = None) -> dict:
        """
        Intercepts state transitions. If a system tries to automatically move a user to a
        completed/authorized state without a human admin signature, it blocks it and sets
        status to PENDING_VERIFIED_HUMAN_APPROVAL.
        """
        if proposed_state in ["passed", "completed", "authorized"]:
            human_signature = context.get("human_controller_signature") if context else None
            has_dpia = context.get("dpia_completed", False) if context else False

            if not human_signature or not has_dpia:
                return {
                    "allowed": False,
                    "enforced_state": "PENDING_VERIFIED_HUMAN_APPROVAL",
                    "reason": "GDPR Article 32(4)/29 Compliance: Missing human controller signature or DPIA.",
                    "audit_timestamp": datetime.now().isoformat()
                }

        return {
            "allowed": True,
            "enforced_state": proposed_state,
            "reason": "Transition authorized.",
            "audit_timestamp": datetime.now().isoformat()
        }
