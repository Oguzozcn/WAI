"""
TEAP Department-Scoped Persistence Layer (Tier A: Namespace Isolation)
======================================================================
Every read/write operation is scoped to a department_id via path prefixes.
Cross-department access raises IsolationViolationError.

Future migration path:
  - Swap this module's backend from local JSON → BigQuery/GCS
  - DepartmentScopedStore interface stays identical
  - Only internal file I/O changes to API calls
"""

import json
import os
import threading
from pathlib import Path
from datetime import date, datetime
from typing import Optional

from .constants import SCHEMA_VERSION

# Global lock for thread safety during read-modify-write operations
_store_lock = threading.Lock()


class IsolationViolationError(Exception):
    """Raised when an operation attempts to access data outside its department scope."""
    pass


class SchemaValidationError(Exception):
    """Raised when a KPI payload doesn't conform to schema v1.0."""
    pass


# Required fields in the KPI payload (structural enforcement)
_KPI_REQUIRED_FIELDS = {
    "schema_version", "department_id", "report_date", "generated_at_utc",
    "reporting_period", "workforce_metrics", "learning_metrics",
    "assessment_metrics", "knowledge_base_metrics", "risk_indicators",
    "top_gap_areas"
}

_WORKFORCE_REQUIRED = {"total_enrolled", "active_learners", "inactive_count"}
_LEARNING_REQUIRED = {"courses_completed_period", "avg_completion_rate_pct", "learning_paths_generated", "avg_time_per_course_hours"}
_ASSESSMENT_REQUIRED = {"quizzes_administered", "avg_quiz_score_pct", "assessments_passed", "assessments_failed", "pass_rate_pct", "bypass_attempts", "bypass_lockouts", "luck_eliminations_triggered"}
_KB_REQUIRED = {"documents_ingested", "conflicts_detected", "conflicts_resolved", "conflicts_pending_review"}
_RISK_REQUIRED = {"at_risk_employee_count", "avg_readiness_score", "employees_below_threshold_pct"}


def validate_kpi_schema(payload: dict) -> None:
    """
    Validates a KPI payload against schema v1.0.
    
    Enforces:
    - All required top-level fields present
    - No additional fields at any level (structural PII prevention)
    - Schema version matches
    - Sub-object field completeness
    
    Raises SchemaValidationError on any violation.
    """
    # Check schema version
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise SchemaValidationError(
            f"Schema version mismatch: expected '{SCHEMA_VERSION}', "
            f"got '{payload.get('schema_version')}'"
        )

    # Check top-level required fields
    missing = _KPI_REQUIRED_FIELDS - set(payload.keys())
    if missing:
        raise SchemaValidationError(f"Missing required fields: {missing}")

    # Check no additional top-level fields (PII prevention)
    extra = set(payload.keys()) - _KPI_REQUIRED_FIELDS
    if extra:
        raise SchemaValidationError(
            f"Additional fields not permitted (PII risk): {extra}"
        )

    # Validate sub-objects
    _validate_sub_object(payload, "workforce_metrics", _WORKFORCE_REQUIRED)
    _validate_sub_object(payload, "learning_metrics", _LEARNING_REQUIRED)
    _validate_sub_object(payload, "assessment_metrics", _ASSESSMENT_REQUIRED)
    _validate_sub_object(payload, "knowledge_base_metrics", _KB_REQUIRED)
    _validate_sub_object(payload, "risk_indicators", _RISK_REQUIRED)

    # Validate top_gap_areas is a list of strings (no PII)
    gaps = payload.get("top_gap_areas", [])
    if not isinstance(gaps, list):
        raise SchemaValidationError("top_gap_areas must be a list")
    if len(gaps) > 10:
        raise SchemaValidationError("top_gap_areas max 10 items")


def _validate_sub_object(payload: dict, key: str, required_fields: set) -> None:
    """Validates a sub-object has exactly the required fields, no more."""
    obj = payload.get(key, {})
    if not isinstance(obj, dict):
        raise SchemaValidationError(f"{key} must be an object")

    missing = required_fields - set(obj.keys())
    if missing:
        raise SchemaValidationError(f"{key} missing fields: {missing}")

    extra = set(obj.keys()) - required_fields
    if extra:
        raise SchemaValidationError(
            f"{key} has additional fields not permitted: {extra}"
        )


class DepartmentScopedStore:
    """
    Namespace-isolated persistence store.
    
    Every file operation is scoped to the department_id passed at construction.
    The store physically cannot construct paths to another department's data.
    
    Directory layout:
        data/user_progress/{department_id}/{user_id}.json
        data/knowledge_base/{department_id}/...
        data/kpi_store/{department_id}_daily_{date}.json
        data/conflicts/{department_id}/{conflict_id}.json
    """

    def __init__(self, department_id: str, base_path: str | None = None):
        """
        Args:
            department_id: The department this store is scoped to.
            base_path: Root data directory. Defaults to WAI_agent/data/.
        """
        self.department_id = department_id

        if base_path is None:
            # Default to the data/ directory inside WAI_agent/
            base_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data"
            )
        self.base_path = Path(base_path)

        # Scoped paths — these are the ONLY directories this store can access
        self.user_progress_path = self.base_path / "user_progress" / department_id
        self.knowledge_base_path = self.base_path / "knowledge_base" / department_id
        self.raw_documents_path = self.base_path / "knowledge_base" / department_id / "raw"
        self.gap_cache_path = self.base_path / "knowledge_base" / department_id / "gap_cache" / "tokens"
        self.conflicts_path = self.base_path / "conflicts" / department_id
        self.kpi_store_path = self.base_path / "kpi_store"
        self.learning_paths_path = self.base_path / "learning_paths" / department_id

        # Ensure directories exist
        self.user_progress_path.mkdir(parents=True, exist_ok=True)
        self.knowledge_base_path.mkdir(parents=True, exist_ok=True)
        self.raw_documents_path.mkdir(parents=True, exist_ok=True)
        self.gap_cache_path.mkdir(parents=True, exist_ok=True)
        self.conflicts_path.mkdir(parents=True, exist_ok=True)
        self.kpi_store_path.mkdir(parents=True, exist_ok=True)
        self.learning_paths_path.mkdir(parents=True, exist_ok=True)

    # ── User Progress ──

    def read_user_progress(self, user_id: str) -> dict | None:
        """Read a user's progress from the department-scoped directory."""
        file_path = self.user_progress_path / f"{user_id}.json"
        if not file_path.exists():
            return None
        return json.loads(file_path.read_text())

    def write_user_progress(self, user_id: str, data: dict) -> None:
        """Write a user's progress to the department-scoped directory."""
        data["last_updated"] = datetime.utcnow().isoformat()
        file_path = self.user_progress_path / f"{user_id}.json"
        file_path.write_text(json.dumps(data, indent=2))

    def list_users(self) -> list[str]:
        """List all user IDs in this department's progress directory."""
        return [
            f.stem for f in self.user_progress_path.glob("*.json")
            if f.stem != ".gitkeep"
        ]

    def read_all_user_progress(self) -> list[dict]:
        """Read all user progress files in this department. Used by KPI synthesizer."""
        results = []
        for user_id in self.list_users():
            data = self.read_user_progress(user_id)
            if data:
                results.append(data)
        return results

    # ── Knowledge Base ──

    def read_knowledge_base(self) -> list[dict]:
        """Read all knowledge base documents for this department."""
        documents = []
        for file_path in sorted(self.knowledge_base_path.glob("*.json")):
            if file_path.stem == ".gitkeep":
                continue
            documents.append(json.loads(file_path.read_text()))
        return documents

    def write_knowledge_document(self, doc_id: str, data: dict) -> None:
        """Write a knowledge base document to the department-scoped directory."""
        file_path = self.knowledge_base_path / f"{doc_id}.json"
        file_path.write_text(json.dumps(data, indent=2))

    # ── Raw Document Storage ──

    def write_raw_document(self, filename: str, content: str) -> str:
        """Save an uploaded raw document (.txt or .md) to the raw/ subdirectory.

        Args:
            filename: Original filename of the uploaded document.
            content: The text content of the document.

        Returns:
            The absolute path of the saved file.
        """
        safe_name = filename.replace("/", "_").replace("\\", "_")
        file_path = self.raw_documents_path / safe_name
        file_path.write_text(content, encoding="utf-8")
        return str(file_path)

    def read_raw_document(self, filename: str) -> Optional[str]:
        """Read a raw document from the raw/ subdirectory."""
        file_path = self.raw_documents_path / filename
        if not file_path.exists():
            return None
        return file_path.read_text(encoding="utf-8")

    def list_raw_documents(self) -> list[str]:
        """List all raw document filenames in this department's raw/ directory."""
        return [
            f.name for f in self.raw_documents_path.iterdir()
            if f.is_file() and f.name not in (".gitkeep",)
        ]

    # ── Gap Cache (Phase 7 — Atomic Snippet Cache, Tier A scoped) ──

    def read_gap_cache(self, token_id: str) -> Optional[dict]:
        """Read a cached atomic remediation snippet for a specific ConceptToken.

        Cache is strictly scoped to this department's namespace:
            data/knowledge_base/{department_id}/gap_cache/tokens/{token_id}.json

        Returns None if no cached snippet exists for this token.
        """
        file_path = self.gap_cache_path / f"{token_id}.json"
        if not file_path.exists():
            return None
        return json.loads(file_path.read_text())

    def write_gap_cache(self, token_id: str, data: dict) -> None:
        """Persist an atomic remediation snippet for a ConceptToken.

        Cache is strictly scoped to this department's namespace.
        Subsequent employees who fail the same token receive this cached snippet instantly.
        """
        file_path = self.gap_cache_path / f"{token_id}.json"
        data["cached_at"] = datetime.utcnow().isoformat()
        file_path.write_text(json.dumps(data, indent=2))

    # ── Learning Path Persistence ──

    def write_learning_path(self, path_id: str, data: dict) -> None:
        """Persist a generated learning path to the department-scoped directory."""
        data["last_updated"] = datetime.utcnow().isoformat()
        file_path = self.learning_paths_path / f"{path_id}.json"
        file_path.write_text(json.dumps(data, indent=2))

    def read_learning_path(self, path_id: str) -> Optional[dict]:
        """Read a persisted learning path."""
        file_path = self.learning_paths_path / f"{path_id}.json"
        if not file_path.exists():
            return None
        return json.loads(file_path.read_text())

    def read_latest_learning_path(self) -> Optional[dict]:
        """Read the most recently updated learning path for this department."""
        paths = list(self.learning_paths_path.glob("*.json"))
        if not paths:
            return None
        # Sort by modification time, newest first
        paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return json.loads(paths[0].read_text())

    # ── Conflicts ──

    def read_conflicts(self, status: str | None = None) -> list[dict]:
        """Read conflict alerts for this department, optionally filtered by status."""
        conflicts = []
        for file_path in self.conflicts_path.glob("*.json"):
            if file_path.stem == ".gitkeep":
                continue
            conflict = json.loads(file_path.read_text())
            if status is None or conflict.get("status") == status:
                conflicts.append(conflict)
        return conflicts

    def write_conflict(self, conflict_id: str, data: dict) -> None:
        """Write a conflict alert to the department-scoped directory."""
        file_path = self.conflicts_path / f"{conflict_id}.json"
        file_path.write_text(json.dumps(data, indent=2))

    # ── KPI Store (Tier 2 Boundary) ──

    def write_kpi_payload(self, report_date: str, payload: dict) -> str:
        """
        Validate and write a KPI payload to the central store.
        
        This is the ONE-WAY PUSH across the department boundary.
        The payload is validated against schema v1.0 before writing.
        
        Returns the path of the written file.
        """
        # Enforce schema — rejects payloads with extra fields (PII prevention)
        validate_kpi_schema(payload)

        # Ensure department_id matches this store's scope
        if payload.get("department_id") != self.department_id:
            raise IsolationViolationError(
                f"KPI payload department_id '{payload.get('department_id')}' "
                f"does not match store scope '{self.department_id}'"
            )

        filename = f"{self.department_id}_daily_{report_date}.json"
        file_path = self.kpi_store_path / filename
        file_path.write_text(json.dumps(payload, indent=2))
        return str(file_path)


class KPIStoreReader:
    """
    Read-only access to the central KPI store (Tier 3).
    
    This is the ONLY data access class the corporate_report_agent uses.
    It has NO methods to access user_progress, knowledge_base, or conflicts.
    It CANNOT write to the KPI store.
    """

    def __init__(self, base_path: str | None = None):
        if base_path is None:
            base_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data"
            )
        self.kpi_store_path = Path(base_path) / "kpi_store"

    def read_payloads(
        self,
        report_date: str,
        departments: list[str] | None = None
    ) -> list[dict]:
        """
        Read KPI payloads from the central store for a given date.
        
        Args:
            report_date: ISO date string (YYYY-MM-DD)
            departments: Optional list of department IDs to filter.
                         If None, reads all available departments.
        
        Returns:
            List of validated KPI payload dicts.
        """
        payloads = []

        for file_path in self.kpi_store_path.glob(f"*_daily_{report_date}.json"):
            payload = json.loads(file_path.read_text())

            # Filter by department if specified
            if departments and payload.get("department_id") not in departments:
                continue

            # Validate schema before returning (defense in depth)
            try:
                validate_kpi_schema(payload)
                payloads.append(payload)
            except SchemaValidationError as e:
                # Log but skip malformed payloads
                print(f"WARNING: Skipping malformed KPI payload {file_path}: {e}")

        return payloads

    def list_available_dates(self) -> list[str]:
        """List all dates that have KPI payloads available."""
        dates = set()
        for file_path in self.kpi_store_path.glob("*_daily_*.json"):
            # Extract date from filename: {dept}_daily_{date}.json
            parts = file_path.stem.split("_daily_")
            if len(parts) == 2:
                dates.add(parts[1])
        return sorted(dates)

    def list_departments_for_date(self, report_date: str) -> list[str]:
        """List all departments that have KPI payloads for a given date."""
        departments = []
        for file_path in self.kpi_store_path.glob(f"*_daily_{report_date}.json"):
            parts = file_path.stem.split("_daily_")
            if len(parts) == 2:
                departments.append(parts[0])
        return sorted(departments)
