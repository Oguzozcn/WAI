"""
TEAP Data Models
=================
Pydantic-style dataclass models for the entire platform.
These define the data structures exchanged between tools, agents, and persistence.

Using dataclasses + dict conversion for ADK compatibility (no Pydantic dependency).
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict
from datetime import datetime, date, timezone


# ── Birdbrain / HLR Mastery Models (Phase 7) ──

@dataclass
class ConceptToken:
    """A fine-grained, atomic sub-skill concept extracted from a lesson chunk."""
    token_id: str             # e.g., "gemini_api_safety_settings"
    display_name: str         # e.g., "Configuring Safety Settings in Gemini API"
    parent_course_id: str     # e.g., "course_03"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MasteryVector:
    """Birdbrain-style vector tracking mastery and memory decay for a single ConceptToken.

    Used by the HLR engine to compute recall probability: p = 2^(-Δt / h)
    """
    concept_id: str
    ability_score: float = 0.5   # Moving 0.0 – 1.0 score based on correct/incorrect history
    last_seen: str = ""          # ISO datetime string of last quiz interaction
    half_life_days: float = 7.0  # Estimated memory decay window (default 7 days)
    historical_attempts: int = 0
    correct_count: int = 0

    def __post_init__(self):
        if not self.last_seen:
            self.last_seen = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


# ── Learning Path Models ──

@dataclass
class Lesson:
    """A single lesson within a course module."""
    lesson_id: str
    title: str
    content: str = ""
    key_concepts: list[str] = field(default_factory=list)
    estimated_minutes: int = 15
    order: int = 0
    has_quiz: bool = True  # 1 Short Quiz per lesson (standardized)
    # Phase 7 extensions
    content_reference: Optional[str] = None  # Path to raw uploaded chunk file
    concept_tokens: list[str] = field(default_factory=list)  # Extracted Birdbrain token IDs

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Course:
    """A single course/module within a learning path."""
    course_id: str
    title: str
    description: str
    topics: list[str] = field(default_factory=list)
    estimated_hours: float = 1.0
    order: int = 0
    lessons: list[dict] = field(default_factory=list)  # List of Lesson dicts
    has_final_assessment: bool = True  # 1 Final Assessment per module (standardized)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LearningPath:
    """A structured sequence of courses for a department/role."""
    path_id: str
    department: str
    role: str
    courses: list[Course] = field(default_factory=list)
    timeframe_weeks: int = 4
    created_at: str = ""
    source_document: str = ""  # Reference to the raw uploaded file that generated this path

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DailyAgenda:
    """A day-specific training agenda derived from a learning path."""
    day_number: int
    path_id: str
    activities: list[dict] = field(default_factory=list)
    # Each activity: {"type": "shadowing"|"simulation"|"study", "topic": str, "duration_hours": float}

    def to_dict(self) -> dict:
        return asdict(self)


# ── Quiz & Assessment Models ──

@dataclass
class QuizQuestion:
    """A single quiz question."""
    question_id: str
    question_text: str
    question_type: str = "multiple_choice"  # "multiple_choice" | "scenario" | "open_text"
    options: list[str] = field(default_factory=list)
    correct_answer: str = ""
    concept_tags: list[str] = field(default_factory=list)
    difficulty: str = "medium"  # "easy" | "medium" | "hard"
    # Phase 7: must map to exactly one ConceptToken from the lesson's token list
    tested_concept_token: str = ""  # e.g., "gemini_api_safety_settings"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Quiz:
    """A collection of questions for a specific topic."""
    quiz_id: str
    topic: str
    quiz_type: str = "short_quiz"  # "short_quiz" | "validation_assessment" | "gap_review"
    questions: list[QuizQuestion] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class QuizAttempt:
    """A record of a user's attempt at a quiz question."""
    question_id: str
    concept_tags: list[str] = field(default_factory=list)
    user_answer: str = ""
    is_correct: bool = False
    attempted_at: str = ""

    def __post_init__(self):
        if not self.attempted_at:
            self.attempted_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


# ── User Progress Models ──

@dataclass
class UserProgress:
    """Complete progress record for a single user within a department."""
    user_id: str
    department: str
    display_name: str = ""  # Internal use only, never in KPI payloads
    entry_path: str = ""  # "veteran" | "intermediate" | "standard"
    current_state: str = "enrolled"
    learning_path_id: str = ""

    # Course tracking
    completed_courses: list[str] = field(default_factory=list)
    current_course_id: str = ""

    # Assessment tracking
    quiz_attempts: list[dict] = field(default_factory=list)  # List of QuizAttempt dicts
    assessment_scores: list[dict] = field(default_factory=list)  # [{"quiz_id": str, "score": float, "type": str}]
    best_assessment_score: float = 0.0

    # Failure tracking
    error_retention_matrix: dict = field(default_factory=dict)  # {concept_tag: failure_count}
    luck_failures: dict = field(default_factory=dict)           # {concept_token_id: failure_count} (Phase 7 HLR)
    bypass_locked: bool = False
    bypass_attempts: int = 0

    # Readiness
    readiness_score: float = 0.0
    is_at_risk: bool = False
    blocked_by: str = ""  # Topic causing the block

    # Phase 8: Manager-employee relationship
    manager_id: str = ""   # ID of the direct manager; empty for top-level users
    job_level: str = "individual_contributor"  # "manager" | "individual_contributor"

    # Phase 7: Birdbrain mastery vectors — {concept_token_id: MasteryVector dict}
    mastery_vectors: dict = field(default_factory=dict)

    # Timestamps
    enrolled_at: str = ""
    last_activity_at: str = ""
    completed_at: str = ""

    def __post_init__(self):
        if not self.enrolled_at:
            self.enrolled_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "UserProgress":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── KPI Payload Model (Tier 2 Schema v1.0) ──

@dataclass
class WorkforceMetrics:
    total_enrolled: int = 0
    active_learners: int = 0
    inactive_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LearningMetrics:
    courses_completed_period: int = 0
    avg_completion_rate_pct: float = 0.0
    learning_paths_generated: int = 0
    avg_time_per_course_hours: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AssessmentMetrics:
    quizzes_administered: int = 0
    avg_quiz_score_pct: float = 0.0
    assessments_passed: int = 0
    assessments_failed: int = 0
    pass_rate_pct: float = 0.0
    bypass_attempts: int = 0
    bypass_lockouts: int = 0
    luck_eliminations_triggered: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class KnowledgeBaseMetrics:
    documents_ingested: int = 0
    conflicts_detected: int = 0
    conflicts_resolved: int = 0
    conflicts_pending_review: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RiskIndicators:
    at_risk_employee_count: int = 0
    avg_readiness_score: float = 0.0
    employees_below_threshold_pct: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class KPIPayload:
    """
    Tier 2 KPI Payload — Schema v1.0
    
    This is the ONLY data structure that crosses the department boundary.
    additionalProperties equivalent: we use strict field definitions and
    to_dict() to ensure no extra fields leak through.
    
    CRITICAL: No PII. No employee names/emails. No raw quiz answers.
    """
    schema_version: str = "1.0"
    department_id: str = ""
    report_date: str = ""  # YYYY-MM-DD
    generated_at_utc: str = ""
    reporting_period: str = "daily"
    workforce_metrics: WorkforceMetrics = field(default_factory=WorkforceMetrics)
    learning_metrics: LearningMetrics = field(default_factory=LearningMetrics)
    assessment_metrics: AssessmentMetrics = field(default_factory=AssessmentMetrics)
    knowledge_base_metrics: KnowledgeBaseMetrics = field(default_factory=KnowledgeBaseMetrics)
    risk_indicators: RiskIndicators = field(default_factory=RiskIndicators)
    top_gap_areas: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.generated_at_utc:
            self.generated_at_utc = datetime.now(timezone.utc).isoformat() + "Z"
        if not self.report_date:
            self.report_date = date.today().isoformat()

    def to_dict(self) -> dict:
        """
        Strict serialization. Only defined fields are included.
        This is the structural equivalent of additionalProperties: false.
        """
        return {
            "schema_version": self.schema_version,
            "department_id": self.department_id,
            "report_date": self.report_date,
            "generated_at_utc": self.generated_at_utc,
            "reporting_period": self.reporting_period,
            "workforce_metrics": self.workforce_metrics.to_dict(),
            "learning_metrics": self.learning_metrics.to_dict(),
            "assessment_metrics": self.assessment_metrics.to_dict(),
            "knowledge_base_metrics": self.knowledge_base_metrics.to_dict(),
            "risk_indicators": self.risk_indicators.to_dict(),
            "top_gap_areas": self.top_gap_areas[:10],  # Max 10 items
        }


# ── KB Validation Models ──

@dataclass
class ConflictAlert:
    """A knowledge base conflict detected by the KB Validator."""
    conflict_id: str
    department: str
    document_a: str  # e.g., "DTP v1.0"
    document_b: str  # e.g., "DTP v1.1"
    field_name: str  # e.g., "capital_of_myanmar"
    value_a: str  # e.g., "Yangon"
    value_b: str  # e.g., "Naypyidaw"
    severity: str = "high"  # "low" | "medium" | "high"
    status: str = "pending"  # "pending" | "resolved" | "dismissed"
    flagged_at: str = ""
    resolved_by: str = ""

    def __post_init__(self):
        if not self.flagged_at:
            self.flagged_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ConflictAlert":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
