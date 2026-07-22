"""
TEAP Department-Scoped Persistence Layer (Tier A: Namespace Isolation)
======================================================================
Every read/write operation is scoped to a department_id via path prefixes.
Cross-department access raises IsolationViolationError.

Storage backend:
  - Domain logic (path/key construction, ordering, filtering, KPI/version rules)
    lives here and is backend-agnostic. Actual leaf I/O goes through a pluggable
    `StorageBackend` (src/core/storage_backend.py), chosen by the STORAGE env var:
        STORAGE=local  -> filesystem under data/ (default; offline on any machine)
        STORAGE=cloud  -> Firestore (JSON/text) + GCS (binary blobs)
  - Relative POSIX path strings ("<domain>_rel") are the universal keys handed to
    the backend. The absolute `*_path` Path attributes are retained for local mode
    only (a couple of tests still assert on them); product code goes through the
    store's methods so it works under either backend.

Migrated from WAI_agent/shared/persistence.py → src/core/database.py (ADK 2.0)
"""

import json
import os
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from src.core.config import SCHEMA_VERSION
from src.core.storage_backend import get_backend

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
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise SchemaValidationError(
            f"Schema version mismatch: expected '{SCHEMA_VERSION}', "
            f"got '{payload.get('schema_version')}'"
        )

    missing = _KPI_REQUIRED_FIELDS - set(payload.keys())
    if missing:
        raise SchemaValidationError(f"Missing required fields: {missing}")

    extra = set(payload.keys()) - _KPI_REQUIRED_FIELDS
    if extra:
        raise SchemaValidationError(
            f"Additional fields not permitted (PII risk): {extra}"
        )

    _validate_sub_object(payload, "workforce_metrics", _WORKFORCE_REQUIRED)
    _validate_sub_object(payload, "learning_metrics", _LEARNING_REQUIRED)
    _validate_sub_object(payload, "assessment_metrics", _ASSESSMENT_REQUIRED)
    _validate_sub_object(payload, "knowledge_base_metrics", _KB_REQUIRED)
    _validate_sub_object(payload, "risk_indicators", _RISK_REQUIRED)

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


def _default_base_path() -> str:
    # Precedence: WAI_DATA_DIR env var > default data/ at project root.
    # WAI_DATA_DIR lets tests redirect all storage to an isolated temp dir.
    return os.getenv("WAI_DATA_DIR") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data"
    )


def _stem(name: str) -> str:
    """Filename without its final extension (mirrors pathlib's .stem)."""
    return name.rsplit(".", 1)[0] if "." in name else name


class DepartmentScopedStore:
    """
    Namespace-isolated persistence store.

    Every operation is scoped to the department_id passed at construction. The
    store physically cannot construct keys to another department's data.

    Logical layout (relpaths handed to the backend):
        user_progress/{department_id}/{user_id}.json
        knowledge_base/{department_id}/...
        kpi_store/{department_id}_daily_{date}.json
        conflicts/{department_id}/{conflict_id}.json
    """

    def __init__(self, department_id: str, base_path: str | None = None):
        """
        Args:
            department_id: The department this store is scoped to.
            base_path: Root data directory (local mode). Defaults to WAI_DATA_DIR
                or data/ at project root.
        """
        self.department_id = department_id
        if base_path is None:
            base_path = _default_base_path()
        self.base_path = Path(base_path)
        self._io = get_backend(self.base_path)

        # ── Relative path prefixes (universal keys for the backend) ──
        dept = department_id
        self.user_progress_rel = f"user_progress/{dept}"
        self.knowledge_base_rel = f"knowledge_base/{dept}"
        self.raw_documents_rel = f"knowledge_base/{dept}/raw"
        self.gap_cache_rel = f"knowledge_base/{dept}/gap_cache/tokens"
        self.conflicts_rel = f"conflicts/{dept}"
        self.kpi_store_rel = "kpi_store"
        self.learning_paths_rel = f"learning_paths/{dept}"
        self.quizzes_rel = f"quizzes/{dept}"
        self.kb_jobs_rel = f"kb_jobs/{dept}"
        self.tickets_rel = f"support_tickets/{dept}"
        self.uat_runs_rel = f"uat_runs/{dept}"
        self.team_docs_rel = f"team_docs/{dept}"
        self.version_history_rel = f"knowledge_base/{dept}/version_history"
        self.catalog_rel = f"knowledge_base/{dept}/catalog"
        self.catalog_inputs_rel = f"{self.catalog_rel}/inputs"
        self.catalog_standard_paths_rel = f"{self.catalog_rel}/standard_paths"
        self.catalog_unofficial_paths_rel = f"{self.catalog_rel}/unofficial_paths"
        self.catalog_gap_paths_rel = f"{self.catalog_rel}/gap_paths"

        # ── Absolute Path attributes (LOCAL MODE ONLY — retained for tests /
        #    backward compatibility; product code uses the methods below) ──
        self.user_progress_path = self.base_path / self.user_progress_rel
        self.knowledge_base_path = self.base_path / self.knowledge_base_rel
        self.raw_documents_path = self.base_path / self.raw_documents_rel
        self.gap_cache_path = self.base_path / self.gap_cache_rel
        self.conflicts_path = self.base_path / self.conflicts_rel
        self.kpi_store_path = self.base_path / self.kpi_store_rel
        self.learning_paths_path = self.base_path / self.learning_paths_rel
        self.quizzes_path = self.base_path / self.quizzes_rel
        self.kb_jobs_path = self.base_path / self.kb_jobs_rel
        self.tickets_path = self.base_path / self.tickets_rel
        self.uat_runs_path = self.base_path / self.uat_runs_rel
        self.team_docs_path = self.base_path / self.team_docs_rel
        self.version_history_path = self.base_path / self.version_history_rel
        self.catalog_path = self.base_path / self.catalog_rel
        self.catalog_inputs_path = self.base_path / self.catalog_inputs_rel
        self.catalog_standard_paths_path = self.base_path / self.catalog_standard_paths_rel
        self.catalog_unofficial_paths_path = self.base_path / self.catalog_unofficial_paths_rel
        self.catalog_gap_paths_path = self.base_path / self.catalog_gap_paths_rel

        # Pre-create directories (local backend mkdir; cloud is a no-op).
        self._io.ensure_dirs([
            self.user_progress_rel, self.knowledge_base_rel, self.raw_documents_rel,
            self.gap_cache_rel, self.conflicts_rel, self.kpi_store_rel,
            self.learning_paths_rel, self.quizzes_rel, self.kb_jobs_rel,
            self.tickets_rel, self.uat_runs_rel, self.team_docs_rel,
            self.version_history_rel, self.catalog_inputs_rel,
            self.catalog_standard_paths_rel, self.catalog_unofficial_paths_rel,
            self.catalog_gap_paths_rel,
        ])

    # ── User Progress ──

    def read_user_progress(self, user_id: str) -> dict | None:
        """Read a user's progress from the department-scoped directory."""
        raw = self._io.read_text(f"{self.user_progress_rel}/{user_id}.json")
        return json.loads(raw) if raw is not None else None

    def write_user_progress(self, user_id: str, data: dict) -> None:
        """Write a user's progress to the department-scoped directory."""
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        self._io.write_text(f"{self.user_progress_rel}/{user_id}.json", json.dumps(data, indent=2))

    def list_users(self) -> list[str]:
        """List all user IDs in this department's progress directory."""
        return [
            _stem(name) for name in self._io.list_files(self.user_progress_rel, ".json")
            if _stem(name) != ".gitkeep"
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
        for name in self._io.list_files(self.knowledge_base_rel, ".json"):
            if _stem(name) == ".gitkeep":
                continue
            raw = self._io.read_text(f"{self.knowledge_base_rel}/{name}")
            if raw is not None:
                documents.append(json.loads(raw))
        return documents

    def list_knowledge_document_ids(self) -> list[str]:
        """List the doc_ids (filename stems) of every KB document in this department."""
        return [
            _stem(name) for name in self._io.list_files(self.knowledge_base_rel, ".json")
            if _stem(name) != ".gitkeep"
        ]

    def read_knowledge_document(self, doc_id: str) -> Optional[dict]:
        """Read a single knowledge base document by id. Returns None if missing."""
        raw = self._io.read_text(f"{self.knowledge_base_rel}/{doc_id}.json")
        return json.loads(raw) if raw is not None else None

    def write_knowledge_document(self, doc_id: str, data: dict) -> None:
        """Write a knowledge base document to the department-scoped directory."""
        self._io.write_text(f"{self.knowledge_base_rel}/{doc_id}.json", json.dumps(data, indent=2))

    def delete_knowledge_document(self, doc_id: str) -> bool:
        """Delete a knowledge base document (e.g. a document's parsed chunks)."""
        return self._io.delete(f"{self.knowledge_base_rel}/{doc_id}.json")

    # ── Raw Document Storage ──

    def write_raw_document(self, filename: str, content: str) -> str:
        """Save an uploaded raw document (.txt or .md) to the raw/ subdirectory."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        rel = f"{self.raw_documents_rel}/{safe_name}"
        self._io.write_text(rel, content)
        return str(self.base_path / rel)

    def read_raw_document(self, filename: str) -> Optional[str]:
        """Read a raw document from the raw/ subdirectory."""
        return self._io.read_text(f"{self.raw_documents_rel}/{filename}")

    def write_raw_document_bytes(self, filename: str, data: bytes) -> str:
        """Save an uploaded binary document (PDF/image/audio/video) to raw/."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        rel = f"{self.raw_documents_rel}/{safe_name}"
        self._io.write_bytes(rel, data)
        return str(self.base_path / rel)

    def read_raw_document_bytes(self, filename: str) -> Optional[bytes]:
        """Read a binary raw document from the raw/ subdirectory."""
        return self._io.read_bytes(f"{self.raw_documents_rel}/{filename}")

    def list_raw_documents(self) -> list[str]:
        """List all raw document filenames in this department's raw/ directory."""
        return [
            name for name in self._io.list_files(self.raw_documents_rel)
            if name not in (".gitkeep",)
        ]

    def delete_raw_document(self, filename: str) -> bool:
        """Delete an uploaded raw document (.txt or .md) from the raw/ subdirectory."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        return self._io.delete(f"{self.raw_documents_rel}/{safe_name}")

    # ── Gap Cache (Phase 7 — Atomic Snippet Cache, Tier A scoped) ──

    def read_gap_cache(self, token_id: str) -> Optional[dict]:
        """Read a cached atomic remediation snippet for a specific ConceptToken."""
        raw = self._io.read_text(f"{self.gap_cache_rel}/{token_id}.json")
        return json.loads(raw) if raw is not None else None

    def write_gap_cache(self, token_id: str, data: dict) -> None:
        """Persist an atomic remediation snippet for a ConceptToken."""
        data["cached_at"] = datetime.now(timezone.utc).isoformat()
        self._io.write_text(f"{self.gap_cache_rel}/{token_id}.json", json.dumps(data, indent=2))

    # ── Quiz Session Persistence ──
    # Active quiz sessions are stored on disk (not in an in-process dict) so
    # they survive server restarts and are shared across multiple workers.
    # The FULL quiz — including correct answers — lives here server-side;
    # API responses are sanitized separately before reaching the client.

    def write_quiz(self, quiz_id: str, data: dict) -> None:
        """Persist a generated quiz (with answer keys) for later evaluation."""
        data["cached_at"] = datetime.now(timezone.utc).isoformat()
        self._io.write_text(f"{self.quizzes_rel}/{quiz_id}.json", json.dumps(data, indent=2))

    def read_quiz(self, quiz_id: str) -> Optional[dict]:
        """Read a persisted quiz session by its ID. Returns None if unknown."""
        raw = self._io.read_text(f"{self.quizzes_rel}/{quiz_id}.json")
        return json.loads(raw) if raw is not None else None

    # ── KB Upload Jobs (Async Processing) ──
    # Upload processing runs in a FastAPI BackgroundTask. Progress/status is
    # written here (not to an in-process dict) so a polling client can read it
    # across restarts and multiple workers, mirroring the quiz-session pattern.

    def write_kb_job(self, job_id: str, data: dict) -> None:
        """Persist the status/result of an async KB upload job."""
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._io.write_text(f"{self.kb_jobs_rel}/{job_id}.json", json.dumps(data, indent=2))

    def read_kb_job(self, job_id: str) -> Optional[dict]:
        """Read an async KB upload job's status by its ID. Returns None if unknown."""
        raw = self._io.read_text(f"{self.kb_jobs_rel}/{job_id}.json")
        return json.loads(raw) if raw is not None else None

    # ── Support Tickets ──
    # One JSON file per ticket, department-scoped like everything else. The
    # developer support console reads across a department via list_tickets().

    def write_ticket(self, ticket_id: str, data: dict) -> None:
        """Persist a support ticket (creation and every triage update)."""
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._io.write_text(f"{self.tickets_rel}/{ticket_id}.json", json.dumps(data, indent=2))

    def read_ticket(self, ticket_id: str) -> Optional[dict]:
        """Read a support ticket by its ID. Returns None if unknown."""
        raw = self._io.read_text(f"{self.tickets_rel}/{ticket_id}.json")
        return json.loads(raw) if raw is not None else None

    def list_tickets(self) -> list[dict]:
        """All tickets in this department, newest first."""
        tickets = []
        for name in self._io.list_files(self.tickets_rel, ".json"):
            if _stem(name) == ".gitkeep":
                continue
            raw = self._io.read_text(f"{self.tickets_rel}/{name}")
            if raw is not None:
                tickets.append(json.loads(raw))
        tickets.sort(key=lambda t: t.get("created_at", ""), reverse=True)
        return tickets

    def next_ticket_id(self) -> str:
        """Next TKT-#### id, derived from existing ticket files."""
        return self._next_seq_id(self.tickets_rel, "TKT")

    # ── UAT Runs ──
    # One JSON file per UAT run (checklist results + generated report), so
    # past acceptance-test runs stay reviewable and comparable over time.

    def write_uat_run(self, run_id: str, data: dict) -> None:
        """Persist a UAT run (creation, every item result, and the report)."""
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._io.write_text(f"{self.uat_runs_rel}/{run_id}.json", json.dumps(data, indent=2))

    def read_uat_run(self, run_id: str) -> Optional[dict]:
        """Read a UAT run by its ID. Returns None if unknown."""
        raw = self._io.read_text(f"{self.uat_runs_rel}/{run_id}.json")
        return json.loads(raw) if raw is not None else None

    def list_uat_runs(self) -> list[dict]:
        """All UAT runs in this department, newest first."""
        runs = []
        for name in self._io.list_files(self.uat_runs_rel, ".json"):
            if _stem(name) == ".gitkeep":
                continue
            raw = self._io.read_text(f"{self.uat_runs_rel}/{name}")
            if raw is not None:
                runs.append(json.loads(raw))
        runs.sort(key=lambda r: r.get("started_at", ""), reverse=True)
        return runs

    def next_uat_run_id(self) -> str:
        """Next UAT-#### id, derived from existing run files."""
        return self._next_seq_id(self.uat_runs_rel, "UAT")

    # ── Team Documentation Projects ──
    # One JSON file per project (metadata + all of its markdown pages), so a
    # team's project documentation stays a single reviewable document.

    def write_team_project(self, project_id: str, data: dict) -> None:
        """Persist a team documentation project (creation and every page edit)."""
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._io.write_text(f"{self.team_docs_rel}/{project_id}.json", json.dumps(data, indent=2))

    def read_team_project(self, project_id: str) -> Optional[dict]:
        """Read a team documentation project by its ID. Returns None if unknown."""
        raw = self._io.read_text(f"{self.team_docs_rel}/{project_id}.json")
        return json.loads(raw) if raw is not None else None

    def list_team_projects(self) -> list[dict]:
        """All team documentation projects in this department, latest-updated first."""
        projects = []
        for name in self._io.list_files(self.team_docs_rel, ".json"):
            if _stem(name) == ".gitkeep":
                continue
            raw = self._io.read_text(f"{self.team_docs_rel}/{name}")
            if raw is not None:
                projects.append(json.loads(raw))
        projects.sort(key=lambda p: p.get("updated_at", ""), reverse=True)
        return projects

    def next_team_project_id(self) -> str:
        """Next PROJ-#### id, derived from existing project files."""
        return self._next_seq_id(self.team_docs_rel, "PROJ")

    def delete_team_project(self, project_id: str) -> bool:
        """Delete a team documentation project. Returns True if it existed."""
        return self._io.delete(f"{self.team_docs_rel}/{project_id}.json")

    # ── Sequential-ID helper ──

    def _next_seq_id(self, reldir: str, prefix: str) -> str:
        """Compute the next '{prefix}-####' id by scanning existing '{prefix}-*.json'."""
        max_seq = 0
        for name in self._io.list_files(reldir, ".json"):
            stem = _stem(name)
            if stem.startswith(f"{prefix}-"):
                try:
                    max_seq = max(max_seq, int(stem.split("-", 1)[1]))
                except (ValueError, IndexError):
                    continue
        return f"{prefix}-{max_seq + 1:04d}"

    # ── Duplicate Detection ──

    def raw_document_exists(self, filename: str) -> bool:
        """Return True if a raw document with this filename already exists."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        return self._io.exists(f"{self.raw_documents_rel}/{safe_name}")

    def next_version_filename(self, filename: str) -> str:
        """Return a non-colliding versioned filename, e.g. 'doc.txt' → 'doc_v2.txt'.

        Increments the version suffix until a filename that does not already
        exist in the raw documents directory is found.
        """
        safe_name = filename.replace("/", "_").replace("\\", "_")
        if "." in safe_name:
            stem, ext = safe_name.rsplit(".", 1)
            ext = "." + ext
        else:
            stem, ext = safe_name, ""

        version = 2
        while True:
            candidate = f"{stem}_v{version}{ext}"
            if not self.raw_document_exists(candidate):
                return candidate
            version += 1

    # ── Version History ──
    # A JSON log per original filename recording every point-in-time state it's
    # been in. "live" entries point at a normal, still-existing catalog file
    # (today's current content, or a `new_version` sibling); "archived" entries
    # are full snapshots of content that got superseded by an Overwrite/Restore,
    # stored under version_history/{filename}/v{N}/ so it's never truly lost.

    def read_version_history(self, filename: str) -> list[dict]:
        """Read the version history log for a filename. Returns [] if none yet."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        raw = self._io.read_text(f"{self.version_history_rel}/{safe_name}.json")
        return json.loads(raw) if raw is not None else []

    def write_version_history(self, filename: str, entries: list[dict]) -> None:
        """Persist the version history log for a filename."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        self._io.write_text(f"{self.version_history_rel}/{safe_name}.json", json.dumps(entries, indent=2))

    def archive_document_snapshot(
        self,
        filename: str,
        version: int,
        content: str | bytes,
        mime_type: str,
        content_category: str,
        chunks_doc: Optional[dict] = None,
    ) -> str:
        """Save a full point-in-time snapshot of a document about to be
        superseded (raw content + meta + its parsed chunks doc, if any)."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        bundle_rel = f"{self.version_history_rel}/{safe_name}/v{version}"

        if isinstance(content, str):
            self._io.write_bytes(f"{bundle_rel}/raw.bin", content.encode("utf-8"))
        else:
            self._io.write_bytes(f"{bundle_rel}/raw.bin", content)
        self._io.write_text(
            f"{bundle_rel}/meta.json",
            json.dumps({"mime_type": mime_type, "content_category": content_category}, indent=2),
        )
        if chunks_doc is not None:
            self._io.write_text(f"{bundle_rel}/chunks.json", json.dumps(chunks_doc, indent=2))
        return str(self.base_path / bundle_rel)

    def read_archived_snapshot(self, filename: str, version: int) -> Optional[dict]:
        """Read back an archived snapshot for restore. Returns None if missing/pruned."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        bundle_rel = f"{self.version_history_rel}/{safe_name}/v{version}"
        raw_bytes = self._io.read_bytes(f"{bundle_rel}/raw.bin")
        meta_raw = self._io.read_text(f"{bundle_rel}/meta.json")
        if raw_bytes is None or meta_raw is None:
            return None
        meta = json.loads(meta_raw)
        content: str | bytes = raw_bytes.decode("utf-8") if meta["content_category"] == "text" else raw_bytes
        chunks_raw = self._io.read_text(f"{bundle_rel}/chunks.json")
        chunks_doc = json.loads(chunks_raw) if chunks_raw is not None else None
        return {
            "content": content,
            "mime_type": meta["mime_type"],
            "content_category": meta["content_category"],
            "chunks_doc": chunks_doc,
        }

    def prune_old_versions(self, filename: str, keep: int = 15) -> None:
        """Delete the oldest archived bundles beyond `keep`. The log entries stay
        (marked `pruned: true`) so the audit trail still shows they existed."""
        entries = self.read_version_history(filename)
        archived = [e for e in entries if e.get("kind") == "archived" and not e.get("pruned")]
        if len(archived) <= keep:
            return
        safe_name = filename.replace("/", "_").replace("\\", "_")
        for entry in archived[: len(archived) - keep]:
            self._io.delete_dir(f"{self.version_history_rel}/{safe_name}/v{entry['version']}")
            entry["pruned"] = True
        self.write_version_history(filename, entries)

    def delete_version_history(self, filename: str) -> None:
        """Remove a filename's entire version history log and archived bundles
        (called when the document itself is deleted, to avoid orphaned history)."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        self._io.delete(f"{self.version_history_rel}/{safe_name}.json")
        self._io.delete_dir(f"{self.version_history_rel}/{safe_name}")

    # ── Learning Path Persistence ──

    def write_learning_path(self, path_id: str, data: dict) -> None:
        """Persist a generated learning path to the department-scoped directory."""
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        self._io.write_text(f"{self.learning_paths_rel}/{path_id}.json", json.dumps(data, indent=2))

    def read_learning_path(self, path_id: str) -> Optional[dict]:
        """Read a persisted learning path."""
        raw = self._io.read_text(f"{self.learning_paths_rel}/{path_id}.json")
        return json.loads(raw) if raw is not None else None

    def delete_learning_path(self, path_id: str) -> bool:
        """Delete a persisted learning path (the activated/enrolled copy)."""
        return self._io.delete(f"{self.learning_paths_rel}/{path_id}.json")

    def list_learning_paths(self) -> list[dict]:
        """Read every persisted learning path for this department (unordered)."""
        paths = []
        for name in self._io.list_files(self.learning_paths_rel, ".json"):
            if _stem(name) == ".gitkeep":
                continue
            raw = self._io.read_text(f"{self.learning_paths_rel}/{name}")
            if raw is not None:
                paths.append(json.loads(raw))
        return paths

    def read_latest_learning_path(self) -> Optional[dict]:
        """Read the most recently updated learning path for this department."""
        metas = self._io.list_files_meta(self.learning_paths_rel, ".json")
        metas = [m for m in metas if _stem(m["name"]) != ".gitkeep"]
        if not metas:
            return None
        latest = max(metas, key=lambda m: m["mtime"])
        raw = self._io.read_text(f"{self.learning_paths_rel}/{latest['name']}")
        return json.loads(raw) if raw is not None else None

    # ── Catalog: Input Files ──

    def write_catalog_input(self, filename: str, content: str) -> str:
        """Save an uploaded raw document to catalog/inputs/."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        rel = f"{self.catalog_inputs_rel}/{safe_name}"
        self._io.write_text(rel, content)
        return str(self.base_path / rel)

    def write_catalog_input_bytes(self, filename: str, data: bytes) -> str:
        """Save an uploaded binary document (PDF/image/audio/video) to catalog/inputs/."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        rel = f"{self.catalog_inputs_rel}/{safe_name}"
        self._io.write_bytes(rel, data)
        return str(self.base_path / rel)

    def write_catalog_input_meta(self, filename: str, mime_type: str, content_category: str) -> None:
        """Record the mime type / content category for a catalog input file.

        Stored as a sidecar `.meta.json` next to the file — the raw/catalog input
        files themselves stay in their native format (text or binary), so this is
        the only place that remembers what kind of content a filename holds.
        """
        safe_name = filename.replace("/", "_").replace("\\", "_")
        self._io.write_text(
            f"{self.catalog_inputs_rel}/{safe_name}.meta.json",
            json.dumps({"mime_type": mime_type, "content_category": content_category}, indent=2),
        )

    def read_catalog_input_meta(self, filename: str) -> dict:
        """Read the mime type / content category for a catalog input file.

        Defaults to plain-text document metadata when no sidecar exists — covers
        files uploaded before multimodal support was added.
        """
        safe_name = filename.replace("/", "_").replace("\\", "_")
        raw = self._io.read_text(f"{self.catalog_inputs_rel}/{safe_name}.meta.json")
        if raw is None:
            return {"mime_type": "text/plain", "content_category": "text"}
        return json.loads(raw)

    def delete_catalog_input(self, filename: str) -> bool:
        """Delete an uploaded document's catalog/inputs/ copy."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        self._io.delete(f"{self.catalog_inputs_rel}/{safe_name}.meta.json")
        return self._io.delete(f"{self.catalog_inputs_rel}/{safe_name}")

    def list_catalog_inputs(self) -> list[dict]:
        """List all input files in catalog/inputs/ with metadata."""
        results = []
        for meta in self._io.list_files_meta(self.catalog_inputs_rel):
            name = meta["name"]
            if name in (".gitkeep",) or name.endswith(".meta.json"):
                continue
            file_meta = self.read_catalog_input_meta(name)
            results.append({
                "filename": name,
                "size_bytes": meta["size"],
                "date_added": datetime.fromtimestamp(meta["mtime"]).isoformat(),
                "mime_type": file_meta["mime_type"],
                "content_category": file_meta["content_category"],
            })
        return results

    # ── Catalog: Standard Learning Paths ──

    def write_standard_path(self, path_id: str, data: dict) -> None:
        """Persist a generated standard learning path to catalog/standard_paths/."""
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        data["path_type"] = "official"
        self._io.write_text(f"{self.catalog_standard_paths_rel}/{path_id}.json", json.dumps(data, indent=2))

    def read_standard_path(self, path_id: str) -> Optional[dict]:
        """Read a standard learning path from the catalog."""
        raw = self._io.read_text(f"{self.catalog_standard_paths_rel}/{path_id}.json")
        return json.loads(raw) if raw is not None else None

    def delete_standard_path(self, path_id: str) -> bool:
        """Delete a standard (official) learning path from the catalog."""
        return self._io.delete(f"{self.catalog_standard_paths_rel}/{path_id}.json")

    def list_standard_paths(self) -> list[dict]:
        """List all standard learning paths with summary metadata."""
        results = []
        for name in self._io.list_files(self.catalog_standard_paths_rel, ".json"):
            if name == ".gitkeep":
                continue
            try:
                data = json.loads(self._io.read_text(f"{self.catalog_standard_paths_rel}/{name}"))
                results.append({
                    "path_id": data.get("path_id", _stem(name)),
                    "title": self._extract_path_title(data),
                    "total_courses": data.get("total_courses", len(data.get("courses", []))),
                    "total_estimated_hours": data.get("total_estimated_hours", 0),
                    "source_document": data.get("source_document", ""),
                    "source_input_files": data.get("source_input_files", []),
                    "created_at": data.get("created_at", ""),
                    "path_type": "official",
                })
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return results

    # ── Catalog: Unofficial Learning Paths (User-Scoped) ──

    def write_unofficial_path(self, user_id: str, path_id: str, data: dict) -> None:
        """Persist an unofficial user-created learning path."""
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        data["path_type"] = "unofficial"
        data["created_by"] = user_id
        self._io.write_text(f"{self.catalog_unofficial_paths_rel}/{user_id}/{path_id}.json", json.dumps(data, indent=2))

    def read_unofficial_path(self, user_id: str, path_id: str) -> Optional[dict]:
        """Read an unofficial (user-created) learning path."""
        raw = self._io.read_text(f"{self.catalog_unofficial_paths_rel}/{user_id}/{path_id}.json")
        return json.loads(raw) if raw is not None else None

    def delete_unofficial_path(self, user_id: str, path_id: str) -> bool:
        """Delete an unofficial (user-created) learning path."""
        return self._io.delete(f"{self.catalog_unofficial_paths_rel}/{user_id}/{path_id}.json")

    def list_unofficial_paths(self, user_id: str | None = None) -> list[dict]:
        """List unofficial learning paths."""
        results = []
        user_ids = [user_id] if user_id else self._io.list_dirs(self.catalog_unofficial_paths_rel)
        for uid in user_ids:
            user_rel = f"{self.catalog_unofficial_paths_rel}/{uid}"
            for name in self._io.list_files(user_rel, ".json"):
                try:
                    data = json.loads(self._io.read_text(f"{user_rel}/{name}"))
                    results.append({
                        "path_id": data.get("path_id", _stem(name)),
                        "title": self._extract_path_title(data),
                        "total_courses": data.get("total_courses", len(data.get("courses", []))),
                        "total_estimated_hours": data.get("total_estimated_hours", 0),
                        "created_by": uid,
                        "created_at": data.get("created_at", ""),
                        "path_type": "unofficial",
                    })
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
        return results

    # ── Catalog: Gap Learning Paths (User-Scoped) ──

    def write_gap_path(self, user_id: str, path_id: str, data: dict) -> None:
        """Persist a knowledge gap learning path for a specific user."""
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        data["path_type"] = "gap"
        data["assigned_to"] = user_id
        self._io.write_text(f"{self.catalog_gap_paths_rel}/{user_id}/{path_id}.json", json.dumps(data, indent=2))

    def list_gap_paths(self, user_id: str | None = None) -> list[dict]:
        """List gap learning paths."""
        results = []
        user_ids = [user_id] if user_id else self._io.list_dirs(self.catalog_gap_paths_rel)
        for uid in user_ids:
            user_rel = f"{self.catalog_gap_paths_rel}/{uid}"
            for name in self._io.list_files(user_rel, ".json"):
                try:
                    data = json.loads(self._io.read_text(f"{user_rel}/{name}"))
                    results.append({
                        "path_id": data.get("path_id", _stem(name)),
                        "title": self._extract_path_title(data),
                        "total_courses": data.get("total_courses", len(data.get("courses", []))),
                        "assigned_to": uid,
                        "created_at": data.get("created_at", ""),
                        "path_type": "gap",
                    })
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
        return results

    # ── Catalog Helpers ──

    @staticmethod
    def _extract_path_title(data: dict) -> str:
        """Extract a human-readable title from a learning path JSON."""
        if data.get("title"):
            return data["title"]
        courses = data.get("courses", [])
        if courses and courses[0].get("title"):
            return courses[0]["title"]
        if data.get("source_document"):
            name = data["source_document"]
            return name.replace("_", " ").replace(".md", "").replace(".txt", "").title()
        return data.get("path_id", "Untitled Path")

    # ── Conflicts ──

    def read_conflicts(self, status: str | None = None) -> list[dict]:
        """Read conflict alerts for this department, optionally filtered by status."""
        conflicts = []
        for name in self._io.list_files(self.conflicts_rel, ".json"):
            if _stem(name) == ".gitkeep":
                continue
            raw = self._io.read_text(f"{self.conflicts_rel}/{name}")
            if raw is None:
                continue
            conflict = json.loads(raw)
            if status is None or conflict.get("status") == status:
                conflicts.append(conflict)
        return conflicts

    def write_conflict(self, conflict_id: str, data: dict) -> None:
        """Write a conflict alert to the department-scoped directory."""
        self._io.write_text(f"{self.conflicts_rel}/{conflict_id}.json", json.dumps(data, indent=2))

    # ── KPI Store (Tier 2 Boundary) ──

    def write_kpi_payload(self, report_date: str, payload: dict) -> str:
        """
        Validate and write a KPI payload to the central store.

        This is the ONE-WAY PUSH across the department boundary.
        The payload is validated against schema v1.0 before writing.

        Returns the path of the written file.
        """
        validate_kpi_schema(payload)

        if payload.get("department_id") != self.department_id:
            raise IsolationViolationError(
                f"KPI payload department_id '{payload.get('department_id')}' "
                f"does not match store scope '{self.department_id}'"
            )

        filename = f"{self.department_id}_daily_{report_date}.json"
        self._io.write_text(f"{self.kpi_store_rel}/{filename}", json.dumps(payload, indent=2))
        return str(self.kpi_store_path / filename)


class KPIStoreReader:
    """
    Read-only access to the central KPI store (Tier 3).

    This is the ONLY data access class the corporate_report_agent uses.
    It has NO methods to access user_progress, knowledge_base, or conflicts.
    It CANNOT write to the KPI store.
    """

    def __init__(self, base_path: str | None = None):
        if base_path is None:
            base_path = _default_base_path()
        self.base_path = Path(base_path)
        self._io = get_backend(self.base_path)
        self.kpi_store_rel = "kpi_store"
        self.kpi_store_path = self.base_path / self.kpi_store_rel

    def read_payloads(
        self,
        report_date: str,
        departments: list[str] | None = None
    ) -> list[dict]:
        """Read KPI payloads from the central store for a given date."""
        payloads = []
        suffix = f"_daily_{report_date}.json"
        for name in self._io.list_files(self.kpi_store_rel, ".json"):
            if not name.endswith(suffix):
                continue
            raw = self._io.read_text(f"{self.kpi_store_rel}/{name}")
            if raw is None:
                continue
            payload = json.loads(raw)

            if departments and payload.get("department_id") not in departments:
                continue

            try:
                validate_kpi_schema(payload)
                payloads.append(payload)
            except SchemaValidationError as e:
                print(f"WARNING: Skipping malformed KPI payload {name}: {e}")

        return payloads

    def list_available_dates(self) -> list[str]:
        """List all dates that have KPI payloads available."""
        dates = set()
        for name in self._io.list_files(self.kpi_store_rel, ".json"):
            parts = _stem(name).split("_daily_")
            if len(parts) == 2:
                dates.add(parts[1])
        return sorted(dates)

    def list_departments_for_date(self, report_date: str) -> list[str]:
        """List all departments that have KPI payloads for a given date."""
        departments = []
        suffix = f"_daily_{report_date}.json"
        for name in self._io.list_files(self.kpi_store_rel, ".json"):
            if not name.endswith(suffix):
                continue
            parts = _stem(name).split("_daily_")
            if len(parts) == 2:
                departments.append(parts[0])
        return sorted(departments)
