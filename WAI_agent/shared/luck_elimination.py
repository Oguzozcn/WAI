"""
TEAP Luck Elimination Engine
==============================
Tracks failure patterns per concept tag across quiz attempts.
If a concept tag fails ≥ LUCK_FAILURE_THRESHOLD times,
the user is forced into mandatory learning path.

This prevents users from guessing their way through assessments.

Logic:
  - Attempts 1-2 on same concept: Log to error matrix, local retake variation
  - Attempts 3-5: Halt standard testing, spawn Duolingo-style gap review
  - Attempts 5+: Core concept drift → force mandatory path, lock progression
"""

from .constants import LUCK_FAILURE_THRESHOLD


# ── HLR (Half-Life Regression) Engine (Phase 7) ──

import math
from datetime import datetime, timezone


def calculate_hlr_retention(vector: dict) -> float:
    """Compute the Duolingo HLR memory recall probability: p = 2^(-Δt / h).

    Args:
        vector: A MasteryVector dict with 'last_seen' (ISO str) and 'half_life_days' (float).

    Returns:
        Float in [0.0, 1.0] representing estimated recall probability right now.
    """
    try:
        last_seen_dt = datetime.fromisoformat(vector.get("last_seen", ""))
        if last_seen_dt.tzinfo is None:
            last_seen_dt = last_seen_dt.replace(tzinfo=timezone.utc)
        delta_t = (datetime.now(timezone.utc) - last_seen_dt).days
    except (ValueError, TypeError):
        delta_t = 0

    h = vector.get("half_life_days", 7.0)
    h = h if h > 0 else 1.0
    return max(0.0, min(1.0, 2 ** (-delta_t / h)))


def evaluate_luck_and_decay(user_progress: dict, concept_token_id: str) -> str:
    """Upgraded routing decision fusing raw failure counts with HLR predictive decay.

    Decision logic:
      1. If luck_failures[token] >= LUCK_FAILURE_THRESHOLD → mandatory lockout (raw counter).
      2. If HLR retention < 0.40 AND ability_score < 0.50 → mandatory lockout (predictive).
      3. Otherwise → continue adaptive gap assessment.

    Returns:
        One of ACTION_FORCE_MANDATORY or ACTION_CONTINUE.
    """
    fail_count = user_progress.get("luck_failures", {}).get(concept_token_id, 0)

    # 1. Strict failure threshold check
    if fail_count >= LUCK_FAILURE_THRESHOLD:
        return ACTION_FORCE_MANDATORY

    # 2. HLR predictive check
    vector = user_progress.get("mastery_vectors", {}).get(concept_token_id)
    if vector:
        retention = calculate_hlr_retention(vector)
        ability = vector.get("ability_score", 1.0)
        if retention < 0.40 and ability < 0.50:
            return ACTION_FORCE_MANDATORY

    return ACTION_CONTINUE



# Return action constants
ACTION_CONTINUE = "MAINTAIN_ADAPTIVE_GAP_ASSESSMENT"
ACTION_FORCE_MANDATORY = "FORCE_MANDATORY_LEARNING_PATH"
ACTION_SPAWN_GAP_REVIEW = "SPAWN_GAP_REVIEW"


class LuckEliminationEngine:
    """
    Analyzes historical quiz patterns to identify guessing behavior
    and enforce mastery requirements.
    """

    def __init__(self, mandatory_threshold: int = LUCK_FAILURE_THRESHOLD):
        """
        Args:
            mandatory_threshold: Number of failures on the same concept
                                 before forcing mandatory learning. Default: 2.
        """
        self.mandatory_threshold = mandatory_threshold

    def evaluate_user_progression(
        self,
        error_retention_matrix: dict[str, int],
        new_attempts: list[dict] | None = None,
    ) -> dict:
        """
        Analyze a user's error retention matrix and new quiz attempts.
        
        Args:
            error_retention_matrix: {concept_tag: failure_count} from user progress
            new_attempts: Optional list of new quiz attempt dicts, each with:
                          {"concept_tags": [str], "is_correct": bool}
        
        Returns:
            dict with:
              - "action": One of ACTION_CONTINUE, ACTION_FORCE_MANDATORY, ACTION_SPAWN_GAP_REVIEW
              - "flagged_concepts": list of concept tags that triggered the action
              - "updated_matrix": Updated error retention matrix
              - "reason": Human-readable explanation
        """
        matrix = dict(error_retention_matrix)  # Don't mutate the original
        flagged_concepts = []

        # Process new attempts if provided
        if new_attempts:
            for attempt in new_attempts:
                if not attempt.get("is_correct", True):
                    for tag in attempt.get("concept_tags", []):
                        matrix[tag] = matrix.get(tag, 0) + 1

        # Check for concepts exceeding the threshold
        for tag, count in matrix.items():
            if count >= self.mandatory_threshold:
                flagged_concepts.append(tag)

        # Determine action based on severity
        if len(flagged_concepts) >= 3:
            # 3+ concepts failing repeatedly → core concept drift
            action = ACTION_FORCE_MANDATORY
            reason = (
                f"Core concept drift detected: {len(flagged_concepts)} concepts "
                f"have failed ≥{self.mandatory_threshold} times each "
                f"({', '.join(flagged_concepts)}). "
                f"Mandatory learning path enforced to eliminate guessing."
            )
        elif len(flagged_concepts) >= 1:
            # 1-2 concepts failing → targeted gap review
            action = ACTION_SPAWN_GAP_REVIEW
            reason = (
                f"Recurring failures detected on: {', '.join(flagged_concepts)}. "
                f"Spawning targeted gap review with Duolingo-style repetition."
            )
        else:
            action = ACTION_CONTINUE
            reason = "No recurring failure patterns detected. Adaptive assessment continues."

        return {
            "action": action,
            "flagged_concepts": flagged_concepts,
            "updated_matrix": matrix,
            "reason": reason,
        }

    def get_concept_failure_summary(
        self,
        error_retention_matrix: dict[str, int],
    ) -> list[dict]:
        """
        Generate a summary of concept failures for reporting.
        
        Returns list of dicts sorted by failure count (descending):
          [{"concept": str, "failures": int, "status": "critical"|"warning"|"ok"}]
        """
        summary = []
        for concept, count in sorted(
            error_retention_matrix.items(),
            key=lambda x: x[1],
            reverse=True
        ):
            if count >= self.mandatory_threshold * 2:
                status = "critical"
            elif count >= self.mandatory_threshold:
                status = "warning"
            else:
                status = "ok"

            summary.append({
                "concept": concept,
                "failures": count,
                "status": status,
            })

        return summary
