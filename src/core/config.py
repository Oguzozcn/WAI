"""
TEAP Platform Constants
========================
Central configuration for thresholds, limits, and platform-wide settings.

Migrated from WAI_agent/shared/constants.py → src/core/config.py (ADK 2.0)
"""

# ── Assessment Thresholds ──
PASS_THRESHOLD = 0.80  # 80% required to pass validation assessments
LUCK_FAILURE_THRESHOLD = 2  # ≥2 failures on same concept tag → mandatory path

# ── Learning Path Limits ──
MAX_COURSES = 10  # Standard learning path length
MAX_QUIZ_QUESTIONS = 10  # Max questions per short quiz
MAX_ASSESSMENT_QUESTIONS = 20  # Max questions per validation assessment
MAX_QUIZ_ATTEMPTS = 3  # Maximum quiz attempts before state-locking
DEFAULT_TIMEFRAME_WEEKS = 4  # Default transition timeframe

# ── Departments (MVP: single department) ──
DEPARTMENTS = ["operations"]
DEFAULT_DEPARTMENT = "operations"

# ── KPI Schema ──
SCHEMA_VERSION = "1.0"

# ── Reporting ──
REPORTING_PERIODS = ["daily", "weekly", "monthly"]
DEFAULT_REPORTING_PERIOD = "daily"

# ── Risk Thresholds ──
AT_RISK_READINESS_THRESHOLD = 0.60  # Below this → HIGH PRIORITY flag
AT_RISK_PERCENTAGE_THRESHOLD = 25.0  # % of team below threshold → alert

# ── Entry Path Options ──
ENTRY_PATH_VETERAN = "veteran"
ENTRY_PATH_INTERMEDIATE = "intermediate"
ENTRY_PATH_STANDARD = "standard"

# ── State Machine States ──
STATE_ENROLLED = "enrolled"
STATE_FAST_TRACK = "fast_track"
STATE_INTERMEDIATE_CHOICE = "intermediate_choice"
STATE_STANDARD_PATH = "standard_path"
STATE_COURSE_IN_PROGRESS = "course_in_progress"
STATE_SHORT_QUIZ = "short_quiz"
STATE_VALIDATION_ASSESSMENT = "validation_assessment"
STATE_PASSED = "passed"
STATE_FAILED = "failed"
STATE_BYPASS_LOCKED = "bypass_locked"
STATE_MANDATORY_PATH = "mandatory_path"
STATE_GAP_REVIEW = "gap_review"
STATE_METACOGNITIVE_REFLECTION = "metacognitive_reflection"
STATE_SPACED_REPETITION = "spaced_repetition"
STATE_COMPLETED = "completed"
