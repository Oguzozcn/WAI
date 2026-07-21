"""
TEAP Department-Scoped Persistence Layer (Tier A: Namespace Isolation)
======================================================================
Every read/write operation is scoped to a department_id via path prefixes.
Cross-department access raises IsolationViolationError.

Future migration path:
  - Swap this module's backend from local JSON → BigQuery/GCS
  - DepartmentScopedStore interface stays identical
  - Only internal file I/O changes to API calls

Migrated from WAI_agent/shared/persistence.py → src/core/database.py (ADK 2.0)
"""

import json
import os
import shutil
import threading
from pathlib import Path
from datetime import date, datetime, timezone
from typing import Optional

from src.core.config import SCHEMA_VERSION

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
            base_path: Root data directory. Defaults to data/ at project root.
        """
        self.department_id = department_id

        if base_path is None:
            # Precedence: explicit base_path arg > WAI_DATA_DIR env var > default.
            # WAI_DATA_DIR lets tests redirect all storage to an isolated temp dir
            # without touching the real project data/ directory. When unset, the
            # behavior is identical to before (defaults to data/ at project root).
            base_path = os.getenv("WAI_DATA_DIR") or os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
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
        self.quizzes_path = self.base_path / "quizzes" / department_id
        self.kb_jobs_path = self.base_path / "kb_jobs" / department_id
        self.version_history_path = self.base_path / "knowledge_base" / department_id / "version_history"

        # ── Catalog Paths (Knowledge Vault catalog structure) ──
        self.catalog_path = self.base_path / "knowledge_base" / department_id / "catalog"
        self.catalog_inputs_path = self.catalog_path / "inputs"
        self.catalog_standard_paths_path = self.catalog_path / "standard_paths"
        self.catalog_unofficial_paths_path = self.catalog_path / "unofficial_paths"
        self.catalog_gap_paths_path = self.catalog_path / "gap_paths"

        # Ensure directories exist
        self.user_progress_path.mkdir(parents=True, exist_ok=True)
        self.knowledge_base_path.mkdir(parents=True, exist_ok=True)
        self.raw_documents_path.mkdir(parents=True, exist_ok=True)
        self.gap_cache_path.mkdir(parents=True, exist_ok=True)
        self.conflicts_path.mkdir(parents=True, exist_ok=True)
        self.kpi_store_path.mkdir(parents=True, exist_ok=True)
        self.learning_paths_path.mkdir(parents=True, exist_ok=True)
        self.quizzes_path.mkdir(parents=True, exist_ok=True)
        self.kb_jobs_path.mkdir(parents=True, exist_ok=True)
        self.version_history_path.mkdir(parents=True, exist_ok=True)
        self.catalog_inputs_path.mkdir(parents=True, exist_ok=True)
        self.catalog_standard_paths_path.mkdir(parents=True, exist_ok=True)
        self.catalog_unofficial_paths_path.mkdir(parents=True, exist_ok=True)
        self.catalog_gap_paths_path.mkdir(parents=True, exist_ok=True)

    # ── User Progress ──

    def read_user_progress(self, user_id: str) -> dict | None:
        """Read a user's progress from the department-scoped directory."""
        file_path = self.user_progress_path / f"{user_id}.json"
        if not file_path.exists():
            return None
        return json.loads(file_path.read_text())

    def write_user_progress(self, user_id: str, data: dict) -> None:
        """Write a user's progress to the department-scoped directory."""
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
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

    def read_knowledge_document(self, doc_id: str) -> Optional[dict]:
        """Read a single knowledge base document by id. Returns None if missing."""
        file_path = self.knowledge_base_path / f"{doc_id}.json"
        if not file_path.exists():
            return None
        return json.loads(file_path.read_text())

    def write_knowledge_document(self, doc_id: str, data: dict) -> None:
        """Write a knowledge base document to the department-scoped directory."""
        file_path = self.knowledge_base_path / f"{doc_id}.json"
        file_path.write_text(json.dumps(data, indent=2))

    def delete_knowledge_document(self, doc_id: str) -> bool:
        """Delete a knowledge base document (e.g. a document's parsed chunks)."""
        file_path = self.knowledge_base_path / f"{doc_id}.json"
        if not file_path.exists():
            return False
        file_path.unlink()
        return True

    # ── Raw Document Storage ──

    def write_raw_document(self, filename: str, content: str) -> str:
        """Save an uploaded raw document (.txt or .md) to the raw/ subdirectory."""
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

    def write_raw_document_bytes(self, filename: str, data: bytes) -> str:
        """Save an uploaded binary document (PDF/image/audio/video) to raw/."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        file_path = self.raw_documents_path / safe_name
        file_path.write_bytes(data)
        return str(file_path)

    def read_raw_document_bytes(self, filename: str) -> Optional[bytes]:
        """Read a binary raw document from the raw/ subdirectory."""
        file_path = self.raw_documents_path / filename
        if not file_path.exists():
            return None
        return file_path.read_bytes()

    def list_raw_documents(self) -> list[str]:
        """List all raw document filenames in this department's raw/ directory."""
        return [
            f.name for f in self.raw_documents_path.iterdir()
            if f.is_file() and f.name not in (".gitkeep",)
        ]

    def delete_raw_document(self, filename: str) -> bool:
        """Delete an uploaded raw document (.txt or .md) from the raw/ subdirectory."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        file_path = self.raw_documents_path / safe_name
        if not file_path.exists():
            return False
        file_path.unlink()
        return True

    # ── Gap Cache (Phase 7 — Atomic Snippet Cache, Tier A scoped) ──

    def read_gap_cache(self, token_id: str) -> Optional[dict]:
        """Read a cached atomic remediation snippet for a specific ConceptToken."""
        file_path = self.gap_cache_path / f"{token_id}.json"
        if not file_path.exists():
            return None
        return json.loads(file_path.read_text())

    def write_gap_cache(self, token_id: str, data: dict) -> None:
        """Persist an atomic remediation snippet for a ConceptToken."""
        file_path = self.gap_cache_path / f"{token_id}.json"
        data["cached_at"] = datetime.now(timezone.utc).isoformat()
        file_path.write_text(json.dumps(data, indent=2))

    # ── Quiz Session Persistence ──
    # Active quiz sessions are stored on disk (not in an in-process dict) so
    # they survive server restarts and are shared across multiple workers.
    # The FULL quiz — including correct answers — lives here server-side;
    # API responses are sanitized separately before reaching the client.

    def write_quiz(self, quiz_id: str, data: dict) -> None:
        """Persist a generated quiz (with answer keys) for later evaluation."""
        data["cached_at"] = datetime.now(timezone.utc).isoformat()
        file_path = self.quizzes_path / f"{quiz_id}.json"
        file_path.write_text(json.dumps(data, indent=2))

    def read_quiz(self, quiz_id: str) -> Optional[dict]:
        """Read a persisted quiz session by its ID. Returns None if unknown."""
        file_path = self.quizzes_path / f"{quiz_id}.json"
        if not file_path.exists():
            return None
        return json.loads(file_path.read_text())

    # ── KB Upload Jobs (Async Processing) ──
    # Upload processing runs in a FastAPI BackgroundTask. Progress/status is
    # written here (not to an in-process dict) so a polling client can read it
    # across restarts and multiple workers, mirroring the quiz-session pattern.

    def write_kb_job(self, job_id: str, data: dict) -> None:
        """Persist the status/result of an async KB upload job."""
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        file_path = self.kb_jobs_path / f"{job_id}.json"
        file_path.write_text(json.dumps(data, indent=2))

    def read_kb_job(self, job_id: str) -> Optional[dict]:
        """Read an async KB upload job's status by its ID. Returns None if unknown."""
        file_path = self.kb_jobs_path / f"{job_id}.json"
        if not file_path.exists():
            return None
        return json.loads(file_path.read_text())

    # ── Duplicate Detection ──

    def raw_document_exists(self, filename: str) -> bool:
        """Return True if a raw document with this filename already exists."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        return (self.raw_documents_path / safe_name).exists()

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
        log_path = self.version_history_path / f"{safe_name}.json"
        if not log_path.exists():
            return []
        return json.loads(log_path.read_text())

    def write_version_history(self, filename: str, entries: list[dict]) -> None:
        """Persist the version history log for a filename."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        log_path = self.version_history_path / f"{safe_name}.json"
        log_path.write_text(json.dumps(entries, indent=2))

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
        bundle_dir = self.version_history_path / safe_name / f"v{version}"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        data = content.encode("utf-8") if isinstance(content, str) else content
        (bundle_dir / "raw.bin").write_bytes(data)
        (bundle_dir / "meta.json").write_text(
            json.dumps({"mime_type": mime_type, "content_category": content_category}, indent=2)
        )
        if chunks_doc is not None:
            (bundle_dir / "chunks.json").write_text(json.dumps(chunks_doc, indent=2))
        return str(bundle_dir)

    def read_archived_snapshot(self, filename: str, version: int) -> Optional[dict]:
        """Read back an archived snapshot for restore. Returns None if missing/pruned."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        bundle_dir = self.version_history_path / safe_name / f"v{version}"
        raw_path = bundle_dir / "raw.bin"
        meta_path = bundle_dir / "meta.json"
        if not raw_path.exists() or not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text())
        raw_bytes = raw_path.read_bytes()
        content: str | bytes = raw_bytes.decode("utf-8") if meta["content_category"] == "text" else raw_bytes
        chunks_path = bundle_dir / "chunks.json"
        chunks_doc = json.loads(chunks_path.read_text()) if chunks_path.exists() else None
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
            bundle_dir = self.version_history_path / safe_name / f"v{entry['version']}"
            if bundle_dir.exists():
                shutil.rmtree(bundle_dir)
            entry["pruned"] = True
        self.write_version_history(filename, entries)

    def delete_version_history(self, filename: str) -> None:
        """Remove a filename's entire version history log and archived bundles
        (called when the document itself is deleted, to avoid orphaned history)."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        log_path = self.version_history_path / f"{safe_name}.json"
        if log_path.exists():
            log_path.unlink()
        bundle_root = self.version_history_path / safe_name
        if bundle_root.exists():
            shutil.rmtree(bundle_root)

    # ── Learning Path Persistence ──

    def write_learning_path(self, path_id: str, data: dict) -> None:
        """Persist a generated learning path to the department-scoped directory."""
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        file_path = self.learning_paths_path / f"{path_id}.json"
        file_path.write_text(json.dumps(data, indent=2))

    def read_learning_path(self, path_id: str) -> Optional[dict]:
        """Read a persisted learning path."""
        file_path = self.learning_paths_path / f"{path_id}.json"
        if not file_path.exists():
            return None
        return json.loads(file_path.read_text())

    def delete_learning_path(self, path_id: str) -> bool:
        """Delete a persisted learning path (the activated/enrolled copy)."""
        file_path = self.learning_paths_path / f"{path_id}.json"
        if not file_path.exists():
            return False
        file_path.unlink()
        return True

    def read_latest_learning_path(self) -> Optional[dict]:
        """Read the most recently updated learning path for this department."""
        paths = list(self.learning_paths_path.glob("*.json"))
        if not paths:
            return None
        paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return json.loads(paths[0].read_text())

    # ── Catalog: Input Files ──

    def write_catalog_input(self, filename: str, content: str) -> str:
        """Save an uploaded raw document to catalog/inputs/."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        file_path = self.catalog_inputs_path / safe_name
        file_path.write_text(content, encoding="utf-8")
        return str(file_path)

    def write_catalog_input_bytes(self, filename: str, data: bytes) -> str:
        """Save an uploaded binary document (PDF/image/audio/video) to catalog/inputs/."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        file_path = self.catalog_inputs_path / safe_name
        file_path.write_bytes(data)
        return str(file_path)

    def write_catalog_input_meta(self, filename: str, mime_type: str, content_category: str) -> None:
        """Record the mime type / content category for a catalog input file.

        Stored as a sidecar `.meta.json` next to the file — the raw/catalog input
        files themselves stay in their native format (text or binary), so this is
        the only place that remembers what kind of content a filename holds.
        """
        safe_name = filename.replace("/", "_").replace("\\", "_")
        meta_path = self.catalog_inputs_path / f"{safe_name}.meta.json"
        meta_path.write_text(json.dumps({
            "mime_type": mime_type,
            "content_category": content_category,
        }, indent=2))

    def read_catalog_input_meta(self, filename: str) -> dict:
        """Read the mime type / content category for a catalog input file.

        Defaults to plain-text document metadata when no sidecar exists — covers
        files uploaded before multimodal support was added.
        """
        safe_name = filename.replace("/", "_").replace("\\", "_")
        meta_path = self.catalog_inputs_path / f"{safe_name}.meta.json"
        if not meta_path.exists():
            return {"mime_type": "text/plain", "content_category": "text"}
        return json.loads(meta_path.read_text())

    def delete_catalog_input(self, filename: str) -> bool:
        """Delete an uploaded document's catalog/inputs/ copy."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        file_path = self.catalog_inputs_path / safe_name
        meta_path = self.catalog_inputs_path / f"{safe_name}.meta.json"
        if meta_path.exists():
            meta_path.unlink()
        if not file_path.exists():
            return False
        file_path.unlink()
        return True

    def list_catalog_inputs(self) -> list[dict]:
        """List all input files in catalog/inputs/ with metadata."""
        results = []
        for f in sorted(self.catalog_inputs_path.iterdir()):
            if f.is_file() and f.name not in (".gitkeep",) and not f.name.endswith(".meta.json"):
                stat = f.stat()
                meta = self.read_catalog_input_meta(f.name)
                results.append({
                    "filename": f.name,
                    "size_bytes": stat.st_size,
                    "date_added": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "mime_type": meta["mime_type"],
                    "content_category": meta["content_category"],
                })
        return results

    # ── Catalog: Standard Learning Paths ──

    def write_standard_path(self, path_id: str, data: dict) -> None:
        """Persist a generated standard learning path to catalog/standard_paths/."""
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        data["path_type"] = "official"
        file_path = self.catalog_standard_paths_path / f"{path_id}.json"
        file_path.write_text(json.dumps(data, indent=2))

    def read_standard_path(self, path_id: str) -> Optional[dict]:
        """Read a standard learning path from the catalog."""
        file_path = self.catalog_standard_paths_path / f"{path_id}.json"
        if not file_path.exists():
            return None
        return json.loads(file_path.read_text())

    def delete_standard_path(self, path_id: str) -> bool:
        """Delete a standard (official) learning path from the catalog."""
        file_path = self.catalog_standard_paths_path / f"{path_id}.json"
        if not file_path.exists():
            return False
        file_path.unlink()
        return True

    def list_standard_paths(self) -> list[dict]:
        """List all standard learning paths with summary metadata."""
        results = []
        for f in sorted(self.catalog_standard_paths_path.glob("*.json")):
            if f.name == ".gitkeep":
                continue
            try:
                data = json.loads(f.read_text())
                results.append({
                    "path_id": data.get("path_id", f.stem),
                    "title": self._extract_path_title(data),
                    "total_courses": data.get("total_courses", len(data.get("courses", []))),
                    "total_estimated_hours": data.get("total_estimated_hours", 0),
                    "source_document": data.get("source_document", ""),
                    "source_input_files": data.get("source_input_files", []),
                    "created_at": data.get("created_at", ""),
                    "path_type": "official",
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return results

    # ── Catalog: Unofficial Learning Paths (User-Scoped) ──

    def write_unofficial_path(self, user_id: str, path_id: str, data: dict) -> None:
        """Persist an unofficial user-created learning path."""
        user_dir = self.catalog_unofficial_paths_path / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        data["path_type"] = "unofficial"
        data["created_by"] = user_id
        file_path = user_dir / f"{path_id}.json"
        file_path.write_text(json.dumps(data, indent=2))

    def read_unofficial_path(self, user_id: str, path_id: str) -> Optional[dict]:
        """Read an unofficial (user-created) learning path."""
        file_path = self.catalog_unofficial_paths_path / user_id / f"{path_id}.json"
        if not file_path.exists():
            return None
        return json.loads(file_path.read_text())

    def delete_unofficial_path(self, user_id: str, path_id: str) -> bool:
        """Delete an unofficial (user-created) learning path."""
        file_path = self.catalog_unofficial_paths_path / user_id / f"{path_id}.json"
        if not file_path.exists():
            return False
        file_path.unlink()
        return True

    def list_unofficial_paths(self, user_id: str | None = None) -> list[dict]:
        """List unofficial learning paths."""
        results = []
        if user_id:
            user_dir = self.catalog_unofficial_paths_path / user_id
            dirs = [user_dir] if user_dir.exists() else []
        else:
            dirs = [d for d in self.catalog_unofficial_paths_path.iterdir() if d.is_dir()]

        for user_dir in dirs:
            uid = user_dir.name
            for f in sorted(user_dir.glob("*.json")):
                try:
                    data = json.loads(f.read_text())
                    results.append({
                        "path_id": data.get("path_id", f.stem),
                        "title": self._extract_path_title(data),
                        "total_courses": data.get("total_courses", len(data.get("courses", []))),
                        "total_estimated_hours": data.get("total_estimated_hours", 0),
                        "created_by": uid,
                        "created_at": data.get("created_at", ""),
                        "path_type": "unofficial",
                    })
                except (json.JSONDecodeError, KeyError):
                    continue
        return results

    # ── Catalog: Gap Learning Paths (User-Scoped) ──

    def write_gap_path(self, user_id: str, path_id: str, data: dict) -> None:
        """Persist a knowledge gap learning path for a specific user."""
        user_dir = self.catalog_gap_paths_path / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        data["path_type"] = "gap"
        data["assigned_to"] = user_id
        file_path = user_dir / f"{path_id}.json"
        file_path.write_text(json.dumps(data, indent=2))

    def list_gap_paths(self, user_id: str | None = None) -> list[dict]:
        """List gap learning paths."""
        results = []
        if user_id:
            user_dir = self.catalog_gap_paths_path / user_id
            dirs = [user_dir] if user_dir.exists() else []
        else:
            dirs = [d for d in self.catalog_gap_paths_path.iterdir() if d.is_dir()]

        for user_dir in dirs:
            uid = user_dir.name
            for f in sorted(user_dir.glob("*.json")):
                try:
                    data = json.loads(f.read_text())
                    results.append({
                        "path_id": data.get("path_id", f.stem),
                        "title": self._extract_path_title(data),
                        "total_courses": data.get("total_courses", len(data.get("courses", []))),
                        "assigned_to": uid,
                        "created_at": data.get("created_at", ""),
                        "path_type": "gap",
                    })
                except (json.JSONDecodeError, KeyError):
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
        validate_kpi_schema(payload)

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
            # Precedence: explicit base_path arg > WAI_DATA_DIR env var > default.
            # (Mirrors DepartmentScopedStore — keeps test isolation consistent.)
            base_path = os.getenv("WAI_DATA_DIR") or os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "data"
            )
        self.kpi_store_path = Path(base_path) / "kpi_store"

    def read_payloads(
        self,
        report_date: str,
        departments: list[str] | None = None
    ) -> list[dict]:
        """Read KPI payloads from the central store for a given date."""
        payloads = []

        for file_path in self.kpi_store_path.glob(f"*_daily_{report_date}.json"):
            payload = json.loads(file_path.read_text())

            if departments and payload.get("department_id") not in departments:
                continue

            try:
                validate_kpi_schema(payload)
                payloads.append(payload)
            except SchemaValidationError as e:
                print(f"WARNING: Skipping malformed KPI payload {file_path}: {e}")

        return payloads

    def list_available_dates(self) -> list[str]:
        """List all dates that have KPI payloads available."""
        dates = set()
        for file_path in self.kpi_store_path.glob("*_daily_*.json"):
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
