"""
TEAP Luck Elimination Engine
==============================
Tracks failure patterns per concept tag across quiz attempts.

Migrated from WAI_agent/shared/luck_elimination.py → src/core/luck_elimination.py (ADK 2.0)
"""

from src.core.dev_config import get_param, get_logic_param

from datetime import datetime, timezone

# Return action constants
ACTION_CONTINUE = "MAINTAIN_ADAPTIVE_GAP_ASSESSMENT"
ACTION_FORCE_MANDATORY = "FORCE_MANDATORY_LEARNING_PATH"
ACTION_SPAWN_GAP_REVIEW = "SPAWN_GAP_REVIEW"


def calculate_hlr_retention(vector: dict) -> float:
    """Compute the Duolingo HLR memory recall probability: p = 2^(-Δt / h)."""
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


class LuckEliminationEngine:
    """Analyzes historical quiz patterns to identify guessing behavior and enforce mastery."""

    def __init__(self, mandatory_threshold: int | None = None):
        # Read live (not a static default arg) so a developer-console change
        # to LUCK_FAILURE_THRESHOLD takes effect without a restart.
        self.mandatory_threshold = (
            mandatory_threshold if mandatory_threshold is not None
            else get_param("LUCK_FAILURE_THRESHOLD")
        )
        self.core_drift_concept_count = get_logic_param("luck_elimination", "core_drift_concept_count")

    def evaluate_user_progression(
        self,
        error_retention_matrix: dict[str, int],
        new_attempts: list[dict] | None = None,
    ) -> dict:
        """Analyze a user's error retention matrix and new quiz attempts."""
        matrix = dict(error_retention_matrix)
        flagged_concepts = []

        if new_attempts:
            for attempt in new_attempts:
                if not attempt.get("is_correct", True):
                    for tag in attempt.get("concept_tags", []):
                        matrix[tag] = matrix.get(tag, 0) + 1

        for tag, count in matrix.items():
            if count >= self.mandatory_threshold:
                flagged_concepts.append(tag)

        if len(flagged_concepts) >= self.core_drift_concept_count:
            action = ACTION_FORCE_MANDATORY
            reason = (
                f"Core concept drift detected: {len(flagged_concepts)} concepts "
                f"have failed ≥{self.mandatory_threshold} times each "
                f"({', '.join(flagged_concepts)}). "
                f"Mandatory learning path enforced to eliminate guessing."
            )
        elif len(flagged_concepts) >= 1:
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
        """Generate a summary of concept failures for reporting."""
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
