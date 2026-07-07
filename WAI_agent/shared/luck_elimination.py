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
