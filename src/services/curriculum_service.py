"""
TEAP Curriculum Tools
======================
ADK function tools for the Training Curriculum Builder agent.
Generates learning paths, daily agendas, and content gap analysis.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from google.genai import types

from src.core.database import DepartmentScopedStore
from src.core.config import DEFAULT_DEPARTMENT, DEFAULT_TIMEFRAME_WEEKS
from src.core.dev_config import get_config, get_param, get_logic_param
from src.services.llm_client import get_gemini_client, call_gemini_json


def generate_learning_path(
    role: str,
    department: str = DEFAULT_DEPARTMENT,
    timeframe_weeks: int = DEFAULT_TIMEFRAME_WEEKS,
) -> dict:
    """Generate a structured learning path based on the knowledge base content for a department.

    This tool reads the department's knowledge base (DTPs, documentation) and
    creates a sequenced 10-course learning path with time allocation.

    Args:
        role: The role of the learner (e.g., "new_joiner", "team_lead")
        department: The department to scope the learning path to
        timeframe_weeks: Number of weeks for the transition (default: 4)

    Returns:
        A structured learning path with courses, sequencing, and time estimates.
    """
    store = DepartmentScopedStore(department)
    knowledge_base = store.read_knowledge_base()

    # Build the learning path from knowledge base content
    path_id = f"lp_{uuid.uuid4().hex[:8]}"
    courses = []

    if knowledge_base:
        # Extract topics from the knowledge base documents
        for i, doc in enumerate(knowledge_base[:get_param("MAX_COURSES")]):
            course_topics = doc.get("topics", [])
            courses.append({
                "course_id": f"course_{i + 1:02d}",
                "title": doc.get("title", f"Course {i + 1}"),
                "description": doc.get("description", ""),
                "topics": course_topics,
                "estimated_hours": doc.get("estimated_hours", 1.5),
                "order": i + 1,
            })
    else:
        # No knowledge base found — return empty path with guidance
        return {
            "status": "no_content",
            "path_id": path_id,
            "message": (
                f"No knowledge base documents found for department '{department}'. "
                f"Please upload DTPs or training documents first."
            ),
        }

    # Calculate time distribution across the timeframe
    total_hours = sum(c["estimated_hours"] for c in courses)
    hours_per_week = total_hours / timeframe_weeks if timeframe_weeks > 0 else total_hours
    days_per_course = (timeframe_weeks * 5) / len(courses) if courses else 0  # business days

    learning_path = {
        "path_id": path_id,
        "department": department,
        "role": role,
        "timeframe_weeks": timeframe_weeks,
        "total_courses": len(courses),
        "total_estimated_hours": round(total_hours, 1),
        "hours_per_week": round(hours_per_week, 1),
        "days_per_course": round(days_per_course, 1),
        "courses": courses,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return learning_path


def generate_daily_agenda(
    learning_path_id: str,
    day_number: int,
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Generate a day-specific training agenda from a learning path.

    Creates a detailed daily schedule with activities like shadowing,
    simulations, study sessions, and short quizzes.

    Args:
        learning_path_id: The ID of the learning path to generate an agenda for
        day_number: The day number (1-based) within the training program
        department: The department scope

    Returns:
        A daily agenda with timed activities and objectives.
    """
    # Calculate which course this day falls into
    # Assuming 20 business days over 4 weeks, 2 days per course for 10 courses
    course_index = min((day_number - 1) // 2, get_param("MAX_COURSES") - 1)
    is_first_day_of_course = (day_number - 1) % 2 == 0

    if is_first_day_of_course:
        # Day 1 of a course: Introduction + Shadowing
        activities = [
            {
                "time_slot": "09:00 - 10:00",
                "type": "study",
                "title": f"Course {course_index + 1}: Introduction & Overview",
                "description": "Review the course material and key concepts",
                "duration_hours": 1.0,
            },
            {
                "time_slot": "10:00 - 12:00",
                "type": "shadowing",
                "title": "Guided Shadowing Session",
                "description": "Observe and follow along with experienced team member",
                "duration_hours": 2.0,
            },
            {
                "time_slot": "13:00 - 14:30",
                "type": "simulation",
                "title": "Hands-on Practice Simulation",
                "description": "Practice key procedures in a safe environment",
                "duration_hours": 1.5,
            },
            {
                "time_slot": "14:30 - 15:00",
                "type": "review",
                "title": "Daily Reflection & Notes",
                "description": "Document key learnings and questions",
                "duration_hours": 0.5,
            },
        ]
    else:
        # Day 2 of a course: Practice + Short Quiz
        activities = [
            {
                "time_slot": "09:00 - 10:30",
                "type": "study",
                "title": f"Course {course_index + 1}: Deep Dive",
                "description": "Review detailed procedures and edge cases",
                "duration_hours": 1.5,
            },
            {
                "time_slot": "10:30 - 12:00",
                "type": "simulation",
                "title": "Independent Practice Session",
                "description": "Work through scenarios independently",
                "duration_hours": 1.5,
            },
            {
                "time_slot": "13:00 - 13:30",
                "type": "quiz",
                "title": f"Short Quiz: Course {course_index + 1}",
                "description": "Quick knowledge check on today's material",
                "duration_hours": 0.5,
            },
            {
                "time_slot": "13:30 - 14:00",
                "type": "review",
                "title": "Quiz Review & Gap Analysis",
                "description": "Review any incorrect answers and clarify concepts",
                "duration_hours": 0.5,
            },
        ]

    agenda = {
        "day_number": day_number,
        "learning_path_id": learning_path_id,
        "course_module": course_index + 1,
        "total_hours": sum(float(a["duration_hours"]) for a in activities),
        "activities": activities,
        "objectives": [
            f"Complete all Day {day_number} activities",
            f"Demonstrate understanding of Course {course_index + 1} concepts",
        ],
    }

    return agenda


def identify_content_gaps(
    document_content: str,
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Analyze document content for gaps, inconsistencies, or unclear areas.

    Compares the provided document content against the existing knowledge base
    to identify missing information, contradictions, or areas needing clarification.

    Args:
        document_content: The text content of the document to analyze
        department: The department scope for comparison

    Returns:
        A report of identified gaps, inconsistencies, and recommendations.
    """
    store = DepartmentScopedStore(department)
    existing_docs = store.read_knowledge_base()

    # Analyze the document
    analysis = {
        "status": "analyzed",
        "document_length": len(document_content),
        "existing_documents_compared": len(existing_docs),
        "findings": [],
        "recommendations": [],
    }

    # Check if document is too short
    if len(document_content) < 100:
        analysis["findings"].append({
            "type": "gap",
            "severity": "high",
            "description": "Document appears to be too brief to serve as a comprehensive DTP.",
        })
        analysis["recommendations"].append(
            "Expand the document with detailed step-by-step procedures."
        )

    # Check for potential conflicts with existing documents via concept overlap.
    if existing_docs:
        analysis["findings"].append({
            "type": "info",
            "severity": "low",
            "description": (
                f"Found {len(existing_docs)} existing document(s) in the "
                f"'{department}' knowledge base for cross-reference."
            ),
        })

        new_concepts = {c.lower() for c in _extract_key_concepts(document_content)}
        if new_concepts:
            for doc in existing_docs:
                # Prefer the pre-extracted `topics` list; fall back to running the
                # concept extractor on the stored document content.
                topics = doc.get("topics", []) or []
                if topics:
                    existing_concepts = {str(t).lower() for t in topics}
                else:
                    existing_concepts = {
                        c.lower() for c in _extract_key_concepts(doc.get("content", ""))
                    }
                if not existing_concepts:
                    continue

                overlap = new_concepts & existing_concepts
                overlap_ratio = len(overlap) / len(new_concepts)

                min_ratio = get_logic_param("curriculum_generation", "conflict_overlap_ratio")
                min_count = get_logic_param("curriculum_generation", "conflict_min_overlap_count")
                if overlap_ratio >= min_ratio and len(overlap) >= min_count:
                    doc_title = doc.get("title", doc.get("course_id", "unknown"))
                    analysis["findings"].append({
                        "type": "conflict",
                        "severity": "medium",
                        "description": (
                            f"Significant concept overlap ({len(overlap)} shared concepts: "
                            f"{', '.join(list(overlap)[:5])}) with existing document "
                            f"'{doc_title}'."
                        ),
                        "existing_doc_title": doc_title,
                        "overlapping_concepts": list(overlap)[:10],
                    })
                    analysis["recommendations"].append(
                        f"Review '{doc_title}' for potential duplication or contradiction "
                        "before publishing this document."
                    )

    return analysis


def _analyze_media_upload(data: bytes, mime_type: str, filename: str) -> dict:
    """Use Gemini's native multimodal understanding to summarize an uploaded
    PDF/image/audio/video file for the knowledge base — no Python-side parsing
    library needed, Gemini reads the media directly (same client/JSON-parsing
    convention as `regenerate_lesson_content`).

    Returns ``{"summary": str, "topics": list[str]}``. On any LLM failure, falls
    back to a minimal filename-derived summary so the upload still completes.
    """
    prompt = (
        "You are cataloguing a piece of corporate training material for a knowledge base. "
        "Examine the attached file and summarize what it teaches so managers can find and "
        "reuse it later.\n\n"
        'Respond with ONLY a JSON object of the shape {"summary": "...", "topics": ["...", ...]}, '
        "no markdown code fences, no other text. The summary should be a few sentences; "
        "topics should be 3-10 short key terms/concepts covered in the material."
    )
    try:
        client = get_gemini_client()
        response = client.models.generate_content(
            model=get_param("GEMINI_MODEL"),
            contents=[
                types.Part.from_bytes(data=data, mime_type=mime_type),
                types.Part.from_text(text=prompt),
            ],
        )
        raw = (response.text or "").strip()
        if not raw:
            raise ValueError("LLM returned an empty response.")
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0].strip()

        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or not parsed.get("summary"):
            raise ValueError("LLM response missing a non-empty 'summary' field.")
        topics = parsed.get("topics", [])
        return {
            "summary": parsed["summary"],
            "topics": [str(t) for t in topics] if isinstance(topics, list) else [],
        }
    except Exception as e:
        print(f"[_analyze_media_upload] LLM call failed ({e}), using filename fallback.")
        return {"summary": f"Uploaded media file: {filename}", "topics": []}


def _archive_current(store: DepartmentScopedStore, filename: str, timestamp: str) -> None:
    """Snapshot whatever content currently exists at `filename` before it's
    replaced (by an Overwrite or Restore), so it's never permanently lost.

    Converts the existing live entry for THIS physical filename into an
    "archived" one in place (it now describes a superseded past state rather
    than the present), rather than fabricating new provenance for it. Only
    ever touches the entry for `filename` itself — a `new_version` sibling
    (a different physical file living under its own name, e.g. `doc_v2.pdf`)
    is a separate, still-live document and must never be archived here.
    """
    if not store.raw_document_exists(filename):
        return

    old_meta = store.read_catalog_input_meta(filename)
    old_category = old_meta["content_category"]
    old_content = (
        store.read_raw_document(filename) if old_category == "text"
        else store.read_raw_document_bytes(filename)
    )
    if old_content is None:
        return
    old_chunks_doc = store.read_knowledge_document(f"{Path(filename).stem}_chunks")

    entries = store.read_version_history(filename)
    current = next(
        (e for e in entries if e.get("kind") == "live" and e.get("filename") == filename), None
    )
    version = current["version"] if current else len(entries) + 1

    store.archive_document_snapshot(
        filename, version, old_content, old_meta["mime_type"], old_category, old_chunks_doc
    )
    if current:
        current["kind"] = "archived"
        current["is_current"] = False
    else:
        size_bytes = len(old_content) if isinstance(old_content, bytes) else len(old_content.encode("utf-8"))
        entries.append({
            "version": version,
            "kind": "archived",
            "action": "initial",
            "filename": filename,
            "timestamp": timestamp,
            "uploaded_by": "",
            "size_bytes": size_bytes,
            "mime_type": old_meta["mime_type"],
            "content_category": old_category,
            "is_current": False,
        })
    store.write_version_history(filename, entries)


def _append_live_version(
    store: DepartmentScopedStore,
    filename: str,
    actual_filename: str,
    mime_type: str,
    content_category: str,
    uploaded_by: str,
    timestamp: str,
    size_bytes: int,
    action: str,
) -> None:
    """Append the new current state to `filename`'s version history log.

    For an Overwrite/Restore, `_archive_current` has already demoted the
    prior entry for this same physical filename before this runs. For a
    `new_version` sibling (`actual_filename != filename`), nothing else needs
    demoting — the original file's content on disk hasn't changed, so its
    entry stays exactly as live/current as it was.
    """
    entries = store.read_version_history(filename)
    entries.append({
        "version": len(entries) + 1,
        "kind": "live",
        "action": action,
        "filename": actual_filename,
        "timestamp": timestamp,
        "uploaded_by": uploaded_by,
        "size_bytes": size_bytes,
        "mime_type": mime_type,
        "content_category": content_category,
        "is_current": True,
    })
    store.write_version_history(filename, entries)
    store.prune_old_versions(filename)


def restore_document_version(
    filename: str, version: int, department: str, uploaded_by: str = ""
) -> dict:
    """Restore an archived version's content back to current.

    Implemented as an Overwrite: the current content is itself archived first
    (so restoring is non-destructive too), then the target snapshot's raw
    bytes/meta/parsed-chunks are copied back into the live raw/catalog/
    knowledge-base locations that curriculum generation and gap analysis read.
    """
    store = DepartmentScopedStore(department)
    snapshot = store.read_archived_snapshot(filename, version)
    if snapshot is None:
        raise ValueError(f"Version {version} of '{filename}' was not found or has been pruned.")

    timestamp = datetime.now(timezone.utc).isoformat()
    _archive_current(store, filename, timestamp)

    content = snapshot["content"]
    mime_type = snapshot["mime_type"]
    content_category = snapshot["content_category"]
    chunks_doc = snapshot["chunks_doc"]

    if content_category == "text":
        store.write_raw_document(filename, content)
        store.write_catalog_input(filename, content)
        size_bytes = len(content.encode("utf-8"))
    else:
        store.write_raw_document_bytes(filename, content)
        store.write_catalog_input_bytes(filename, content)
        size_bytes = len(content)
    store.write_catalog_input_meta(filename, mime_type, content_category)

    if chunks_doc is not None:
        store.write_knowledge_document(f"{Path(filename).stem}_chunks", chunks_doc)

    _append_live_version(
        store, filename, filename, mime_type, content_category, uploaded_by, timestamp, size_bytes, "restore"
    )
    return {"filename": filename, "restored_from_version": version, "status": "restored"}


def process_kb_upload_job(
    job_id: str,
    filename: str,
    content: str | bytes,
    department: str,
    version_action: str = "",
    mime_type: str = "text/plain",
    content_category: str = "text",
    uploaded_by: str = "",
) -> None:
    """Background task: validate → chunk → save an uploaded KB document.

    Fire-and-forget: this function returns nothing. All progress and results are
    written to the KB job doc via `store.write_kb_job` so a polling client can
    observe stage-by-stage progress. Any exception is caught and persisted as an
    ``error`` status (FastAPI BackgroundTasks swallow unhandled exceptions, so we
    must record the failure ourselves for the poller to see it).

    Text-family documents (``content_category == "text"``) keep the original
    validate → chunk → save pipeline. PDF/image/audio/video are opaque binary
    media: Gemini is asked once for a summary + topic list (stage "analyzing"),
    which is stored as a single chunk so gap-analysis/KB search still work
    uniformly across every content type — no separate code path downstream.
    """
    store = DepartmentScopedStore(department)
    try:
        store.write_kb_job(job_id, {
            "job_id": job_id,
            "status": "processing",
            "stage": "validating",
            "filename": filename,
        })

        # Resolve the actual filename to use (new version vs. overwrite/as-is).
        if version_action == "new_version":
            actual_filename = store.next_version_filename(filename)
        else:
            actual_filename = filename

        upload_timestamp = datetime.now(timezone.utc).isoformat()
        chunks_doc_id = f"{Path(actual_filename).stem}_chunks"
        version_action_label = version_action if version_action in ("overwrite", "new_version") else "initial"

        if version_action == "overwrite":
            _archive_current(store, filename, upload_timestamp)

        if content_category != "text":
            # ── Binary media branch: image / audio / video / PDF ──
            store.write_kb_job(job_id, {
                "job_id": job_id,
                "status": "processing",
                "stage": "analyzing",
                "filename": actual_filename,
            })
            media_bytes = content if isinstance(content, bytes) else content.encode("utf-8")
            analysis = _analyze_media_upload(media_bytes, mime_type, actual_filename)

            store.write_kb_job(job_id, {
                "job_id": job_id,
                "status": "processing",
                "stage": "saving",
                "filename": actual_filename,
            })
            store.write_raw_document_bytes(actual_filename, media_bytes)
            store.write_catalog_input_bytes(actual_filename, media_bytes)
            store.write_catalog_input_meta(actual_filename, mime_type, content_category)
            store.write_knowledge_document(
                chunks_doc_id,
                {
                    "source_filename": actual_filename,
                    "department": department,
                    "chunk_count": 1,
                    "uploaded_at": upload_timestamp,
                    "topics": analysis["topics"],
                    "chunks": [{
                        "text": analysis["summary"],
                        "char_start": 0,
                        "char_end": len(analysis["summary"]),
                        "chunk_index": 0,
                        "source_filename": actual_filename,
                        "department": department,
                        "uploaded_at": upload_timestamp,
                    }],
                },
            )
            _append_live_version(
                store, filename, actual_filename, mime_type, content_category,
                uploaded_by, upload_timestamp, len(media_bytes), version_action_label,
            )
            store.write_kb_job(job_id, {
                "job_id": job_id,
                "status": "completed",
                "stage": "completed",
                "filename": actual_filename,
                "chunk_count": 1,
                "content_category": content_category,
                "validation": {"status": "APPROVED", "findings_count": 0},
            })
            return

        # ── Text-family branch (unchanged pipeline) ──
        text_content: str = content if isinstance(content, str) else content.decode("utf-8")

        # Stage: Validate
        gap_analysis = identify_content_gaps(
            document_content=text_content,
            department=department,
        )

        # Stage: Chunk
        store.write_kb_job(job_id, {
            "job_id": job_id,
            "status": "processing",
            "stage": "chunking",
            "filename": actual_filename,
        })
        chunks = recursive_character_splitter(text_content, max_tokens=1024, overlap=200)
        enriched_chunks = [
            {
                **chunk,
                "source_filename": actual_filename,
                "department": department,
                "uploaded_at": upload_timestamp,
            }
            for chunk in chunks
        ]

        # Stage: Save
        store.write_kb_job(job_id, {
            "job_id": job_id,
            "status": "processing",
            "stage": "saving",
            "filename": actual_filename,
        })
        store.write_raw_document(actual_filename, text_content)
        store.write_catalog_input(actual_filename, text_content)
        store.write_catalog_input_meta(actual_filename, mime_type, content_category)
        store.write_knowledge_document(
            chunks_doc_id,
            {
                "source_filename": actual_filename,
                "department": department,
                "chunk_count": len(enriched_chunks),
                "uploaded_at": upload_timestamp,
                "chunks": enriched_chunks,
            },
        )
        _append_live_version(
            store, filename, actual_filename, mime_type, content_category,
            uploaded_by, upload_timestamp, len(text_content.encode("utf-8")), version_action_label,
        )

        # Determine conflict findings (high/medium severity) → soft-flag for review.
        conflict_findings = [
            f for f in gap_analysis.get("findings", [])
            if f.get("severity") in ("high", "medium")
        ]

        if conflict_findings:
            flagged_at = datetime.now(timezone.utc).isoformat()
            conflicts_written = []
            for finding in conflict_findings:
                overlapping = finding.get("overlapping_concepts", [])
                conflict = {
                    "conflict_id": f"conflict_{uuid.uuid4().hex[:8]}",
                    "department": department,
                    "document_a": actual_filename,
                    "document_b": finding.get("existing_doc_title", "existing knowledge base"),
                    "field_name": finding.get("type", "content"),
                    "value_a": finding.get("description", ""),
                    "value_b": ", ".join(overlapping) if overlapping else "N/A",
                    "severity": finding.get("severity", "medium"),
                    "status": "pending",
                    "flagged_at": flagged_at,
                    "resolved_by": "",
                    "resolved_at": "",
                    "resolution_notes": "",
                    # Retraction handles for the resolve endpoint.
                    "raw_filename": actual_filename,
                    "chunks_doc_id": chunks_doc_id,
                }
                store.write_conflict(conflict["conflict_id"], conflict)
                conflicts_written.append(conflict)

            store.write_kb_job(job_id, {
                "job_id": job_id,
                "status": "flagged",
                "stage": "completed",
                "filename": actual_filename,
                "chunk_count": len(chunks),
                "conflicts": [c["conflict_id"] for c in conflicts_written],
                "validation": {
                    "status": "FLAGGED",
                    "findings_count": len(gap_analysis.get("findings", [])),
                },
            })
        else:
            store.write_kb_job(job_id, {
                "job_id": job_id,
                "status": "completed",
                "stage": "completed",
                "filename": actual_filename,
                "chunk_count": len(chunks),
                "validation": {
                    "status": "APPROVED",
                    "findings_count": len(gap_analysis.get("findings", [])),
                },
            })

    except Exception as e:
        store.write_kb_job(job_id, {
            "job_id": job_id,
            "status": "error",
            "stage": "failed",
            "message": str(e),
        })


def process_generate_job(
    job_id: str,
    filename: str,
    department: str,
    append_to_latest: bool,
    manager_id: str,
    filenames: Optional[list[str]] = None,
) -> None:
    """Background task: generate a course (lessons + short quizzes + final
    assessment) from one or more uploaded documents and save it as the
    manager's private draft.

    Fire-and-forget, mirroring process_kb_upload_job — progress is written to
    the KB job doc via store.write_kb_job so a polling client can observe
    stage-by-stage progress, including after the user dismisses the modal via
    "Continue in Background" and navigates away.

    Args:
        filename: Single-file case (kept for backward compatibility).
        filenames: Multi-file case — when given, combined into one course.
            Takes precedence over `filename`.
    """
    store = DepartmentScopedStore(department)
    files = filenames if filenames else [filename]
    files_label = ", ".join(files)

    def _progress(stage: str) -> None:
        store.write_kb_job(job_id, {
            "job_id": job_id,
            "status": "processing",
            "stage": stage,
            "filename": files_label,
        })

    try:
        _progress("parsing_document")
        result = trigger_curriculum_generation(
            filenames=files,
            department=department,
            append_to_latest=append_to_latest,
            progress_cb=_progress,
        )

        if result.get("status") != "success":
            store.write_kb_job(job_id, {
                "job_id": job_id,
                "status": "error",
                "stage": "failed",
                "filename": files_label,
                "message": result.get("message", "Curriculum generation failed."),
            })
            return

        if result.get("path_id"):
            path_data = store.read_learning_path(result["path_id"])
            if path_data:
                path_data["source_input_files"] = files
                # write_unofficial_path stamps path_type="unofficial" on this dict
                # in place — sync that into the activated copy too, so "Preview
                # Draft" (which reads the activated copy directly, without ever
                # calling /enroll) already knows it's a draft, not an active path.
                store.write_unofficial_path(manager_id, result["path_id"], path_data)
                store.write_learning_path(result["path_id"], path_data)

        store.write_kb_job(job_id, {
            "job_id": job_id,
            "status": "done",
            "stage": "complete",
            "filename": files_label,
            "result": result,
        })
    except Exception as e:
        store.write_kb_job(job_id, {
            "job_id": job_id,
            "status": "error",
            "stage": "failed",
            "filename": files_label,
            "message": str(e),
        })


# ── Chunking Utilities ──

def recursive_character_splitter(
    text: str,
    max_tokens: int = 1024,
    overlap: int = 200,
) -> list[dict]:
    """Split text into overlapping chunks using recursive character splitting.

    Attempts to split on semantic boundaries in priority order:
      1. Double newlines (paragraph breaks)
      2. Single newlines (line breaks)
      3. Sentence-ending punctuation (. ! ?)
      4. Spaces (word boundaries)
      5. Raw character slicing (last resort)

    Args:
        text: The raw text to split.
        max_tokens: Maximum characters per chunk (approximate token proxy).
        overlap: Number of characters to carry over between consecutive chunks
                 to preserve context across boundaries.

    Returns:
        A list of chunk dicts, each with:
          - ``text``: The chunk content.
          - ``char_start``: Starting character offset in the original text.
          - ``char_end``: Ending character offset in the original text.
          - ``chunk_index``: 0-based sequential index.
    """
    if not text or not text.strip():
        return []

    # Priority order of split separators (most preferred → least preferred)
    _SEPARATORS = ["\n\n", "\n", ". ", "! ", "? ", " ", ""]

    def _split_on_separator(s: str, sep: str) -> list[str]:
        """Split string on separator, re-attaching the separator to each segment."""
        if not sep:
            # Last resort: raw character slices
            return [s[i:i + max_tokens] for i in range(0, len(s), max_tokens - overlap)]
        parts = s.split(sep)
        # Re-attach separator to all but the last segment
        return [p + sep if i < len(parts) - 1 else p for i, p in enumerate(parts) if p]

    def _merge_splits(splits: list[str]) -> list[str]:
        """Greedily merge small splits up to max_tokens, then start a new chunk."""
        merged: list[str] = []
        current = ""
        for split in splits:
            if len(current) + len(split) <= max_tokens:
                current += split
            else:
                if current:
                    merged.append(current)
                # If a single split exceeds max_tokens, recurse with the next separator
                current = split
        if current:
            merged.append(current)
        return merged

    def _recursive_split(s: str, sep_index: int = 0) -> list[str]:
        """Recursively split using separators in priority order."""
        if len(s) <= max_tokens:
            return [s] if s.strip() else []

        sep = _SEPARATORS[sep_index] if sep_index < len(_SEPARATORS) else ""
        splits = _split_on_separator(s, sep)
        result: list[str] = []
        for part in splits:
            if len(part) <= max_tokens:
                if part.strip():
                    result.append(part)
            else:
                # Recurse with the next separator
                next_idx = sep_index + 1 if sep_index < len(_SEPARATORS) - 1 else sep_index
                result.extend(_recursive_split(part, next_idx))
        return result

    raw_chunks = _merge_splits(_recursive_split(text))

    # Apply overlap: each chunk (after the first) starts `overlap` chars before
    # where the previous chunk ended, preserving retrieval context.
    chunks: list[dict] = []
    char_cursor = 0
    for i, chunk_text in enumerate(raw_chunks):
        # Find the start position of this chunk in the original text
        search_from = max(0, char_cursor - overlap) if i > 0 else 0
        pos = text.find(chunk_text[:50].strip(), search_from)
        char_start = pos if pos != -1 else char_cursor
        char_end = char_start + len(chunk_text)
        chunks.append({
            "text": chunk_text.strip(),
            "char_start": char_start,
            "char_end": char_end,
            "chunk_index": i,
        })
        char_cursor = char_end

    return chunks


# ── Document-to-Curriculum Pipeline ──

def _split_text_into_sections(text: str) -> list[dict]:
    """Split document text into logical sections based on headings or paragraphs.

    Detects markdown-style headers (## or ###) as section delimiters.
    Falls back to paragraph-based chunking if no headers found.
    """
    import re
    sections = []

    # Try markdown heading-based splitting first
    heading_pattern = re.compile(r'^(#{1,3})\s+(.+)$', re.MULTILINE)
    headings = list(heading_pattern.finditer(text))

    if headings:
        for i, match in enumerate(headings):
            title = match.group(2).strip()
            start = match.end()
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            content = text[start:end].strip()
            if content:
                sections.append({"title": title, "content": content})
    else:
        # Paragraph-based chunking: split on double newlines
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        # Group paragraphs into chunks of roughly equal size (max MAX_COURSES chunks)
        max_sections = min(get_param("MAX_COURSES"), max(1, len(paragraphs)))
        chunk_size = max(1, len(paragraphs) // max_sections)

        for i in range(0, len(paragraphs), chunk_size):
            chunk = paragraphs[i:i + chunk_size]
            combined = "\n\n".join(chunk)
            # Generate title from first ~50 chars of first paragraph
            first_line = chunk[0][:60].strip()
            if len(chunk[0]) > 60:
                first_line += "..."
            sections.append({"title": first_line, "content": combined})

    return sections[:get_param("MAX_COURSES")]


def _extract_key_concepts(text: str) -> list[str]:
    """Extract key concepts/terms from a text block.

    Looks for bold terms (**term**), capitalized phrases, and terms after colons.
    """
    import re
    concepts = set()

    # Extract bold terms
    for match in re.finditer(r'\*\*(.*?)\*\*', text):
        term = match.group(1).strip()
        if 2 < len(term) < 60:
            concepts.add(term)

    # Extract terms after colons (definition-style)
    for match in re.finditer(r'(\w[\w\s]{2,30}):\s', text):
        term = match.group(1).strip()
        if len(term) > 3:
            concepts.add(term)

    # Extract capitalized multi-word terms (likely proper nouns / concepts)
    for match in re.finditer(r'\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\b', text):
        concepts.add(match.group(1))

    return list(concepts)[:10]


def _generate_sections_from_media(media_parts: list, document_title: str) -> tuple[list[dict], dict[int, dict]]:
    """Media-only curriculum source (no text file in the selection): ask Gemini
    to invent the section breakdown directly from the attached image/audio/video/
    PDF parts, since there's no heading/paragraph structure to regex-split.

    Returns (sections, llm_sections) in the exact shape `process_document_to_curriculum`'s
    lesson-building loop already expects, so that loop needs no changes to consume
    either a text-derived or a media-derived breakdown.
    """
    max_sections = get_param("MAX_COURSES")
    prompt = (
        "You are designing a corporate training course from the attached media file(s) "
        f"(source: '{document_title}'). Break the material into up to {max_sections} "
        "logical lesson sections covering it end to end.\n\n"
        'Respond with ONLY a JSON object of the shape {"sections": [{"index": 0, "title": "...", '
        '"content_summary": "...", "key_points": ["...", ...]}, ...]}, no markdown code fences, '
        "no other text. content_summary should be a thorough teaching summary of that section "
        "(a few paragraphs); key_points should be 3-8 short key terms/concepts for that section."
    )
    client = get_gemini_client()
    response = client.models.generate_content(
        model=get_param("GEMINI_MODEL"),
        contents=list(media_parts) + [types.Part.from_text(text=prompt)],
    )
    raw = (response.text or "").strip()
    if not raw:
        raise ValueError("LLM returned an empty response.")
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()

    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"LLM returned unexpected type: {type(parsed).__name__}")

    entries = [e for e in parsed.get("sections", []) if isinstance(e, dict)]
    entries.sort(key=lambda e: e.get("index", 0))
    if not entries:
        raise ValueError("LLM returned no sections.")

    sections = [
        {"title": e.get("title") or document_title, "content": e.get("content_summary") or ""}
        for e in entries
    ]
    llm_sections = {i: e for i, e in enumerate(entries)}
    return sections, llm_sections


def process_document_to_curriculum(
    document_text: str,
    document_title: str = "Uploaded Document",
    department: str = DEFAULT_DEPARTMENT,
    media_parts: Optional[list] = None,
) -> dict:
    """Split a document into a structured curriculum: Course → Lessons.

    The Course Splitter logic. Analyzes document_text and generates a
    structured curriculum with up to 10 lessons per module, each with
    a short quiz, plus a final assessment for the module.

    Args:
        document_text: The raw text content of the uploaded document(s). May be
            empty when the selection is media-only (image/audio/video/PDF).
        document_title: The title/filename of the document.
        department: The department scope.
        media_parts: Optional list of `google.genai.types.Part` built from
            binary media files (PDF/image/audio/video) selected alongside or
            instead of text documents — Gemini reads these natively rather
            than requiring Python-side text extraction.

    Returns:
        A structured curriculum dict with courses and lessons.
    """
    has_text = bool(document_text and document_text.strip())
    sections = _split_text_into_sections(document_text) if has_text else []

    if not sections and not media_parts:
        return {
            "status": "error",
            "message": "Could not extract any content from the document.",
        }

    # Ask Gemini — in ONE batched call for the whole document — to turn each
    # structural section into a teaching summary + key concepts. On any failure
    # we fall back per-section to the deterministic heuristic below. When the
    # selection is media-only (no text sections at all), skip straight to a
    # dedicated media-to-sections call instead.
    llm_sections: dict[int, dict] = {}
    try:
        if sections:
            section_blocks = []
            for i, section in enumerate(sections):
                # Cap per-section content so the batched prompt stays bounded.
                section_content = section["content"][:2500]
                section_blocks.append(
                    f"--- SECTION {i} ---\n"
                    f"Title: {section['title']}\n"
                    f"Content:\n{section_content}"
                )
            sections_text = "\n\n".join(section_blocks)

            tool_config = get_config()["tools"]["process_document_to_curriculum"]
            prompt = tool_config["prompt_template"].format(
                section_count=len(sections),
                sections_text=sections_text,
            )

            # Media parts (if any) ride along in the same call so Gemini can
            # ground each section's summary in the attached media too.
            contents = list(media_parts) + [types.Part.from_text(text=prompt)] if media_parts else prompt
            parsed = call_gemini_json(contents, model=tool_config.get("model"))

            # Index by the section index so per-section fallback stays simple/defensive.
            for entry in parsed.get("sections", []):
                if not isinstance(entry, dict):
                    continue
                idx = entry.get("index")
                if isinstance(idx, int) and 0 <= idx < len(sections):
                    llm_sections[idx] = entry
        else:
            # Media-only selection: no text structure to split, so let Gemini
            # invent the section breakdown directly from the attached media.
            # (media_parts is guaranteed non-empty here — the guard above
            # already returned early when both sections and media_parts were falsy.)
            assert media_parts
            sections, llm_sections = _generate_sections_from_media(media_parts, document_title)

    except Exception as e:
        print(f"[process_document_to_curriculum] LLM call failed ({e}), using fallback.")
        if not sections:
            # Media-only and the one call that could produce sections failed —
            # there's no deterministic text fallback for binary media.
            return {
                "status": "error",
                "message": "Could not generate a curriculum from the provided media.",
            }

    # Build lessons from sections. Use LLM output where available and valid,
    # otherwise fall back to the deterministic heuristic for that section.
    lessons = []
    for i, section in enumerate(sections):
        entry = llm_sections.get(i)
        content = None
        key_concepts = None
        if entry is not None:
            summary = entry.get("content_summary")
            points = entry.get("key_points")
            if isinstance(summary, str) and summary.strip():
                content = summary.strip()
            if isinstance(points, list) and points:
                key_concepts = [str(p) for p in points]

        if content is None:
            content = section["content"]
        if key_concepts is None:
            key_concepts = _extract_key_concepts(section["content"])

        lessons.append({
            "lesson_id": f"lesson_{i + 1:02d}",
            "title": section["title"],
            "content": content,
            "key_concepts": key_concepts,
            "estimated_minutes": max(10, min(30, len(section["content"]) // 200)),
            "order": i + 1,
            "has_quiz": True,
        })

    # Calculate total estimated hours
    total_minutes = sum(l["estimated_minutes"] for l in lessons)
    # Add 5 min per short quiz + 15 min for final assessment
    total_minutes += len(lessons) * 5 + 15
    estimated_hours = round(total_minutes / 60, 1)

    # Build the module/course
    # Extract a clean title from the document name
    clean_title = document_title.replace(".txt", "").replace(".md", "").replace("_", " ").title()

    course = {
        "course_id": f"course_{uuid.uuid4().hex[:8]}",
        "title": clean_title,
        "description": f"Auto-generated curriculum from '{document_title}'",
        "topics": list(set(
            concept
            for lesson in lessons
            for concept in lesson["key_concepts"][:3]
        ))[:10],
        "estimated_hours": estimated_hours,
        "order": 1,
        "lessons": lessons,
        "has_final_assessment": True,
    }

    return {
        "status": "success",
        "course": course,
        "total_lessons": len(lessons),
        "total_estimated_hours": estimated_hours,
    }


def _generate_course_quizzes(
    course: dict,
    department: str,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> None:
    """Pre-generate a short quiz per lesson and one final assessment for the
    course, persisting each via store.write_quiz and stamping the resulting
    quiz_id back onto the lesson/course dicts (short_quiz_id / final_assessment_id
    — the same field names generate_remedial_course already uses) so
    /api/quiz/by-lesson and /api/quiz/by-course can serve them instantly
    instead of calling Gemini live when the learner clicks "Start Quiz"."""
    from src.services.quiz_service import generate_quiz

    store = DepartmentScopedStore(department)
    lessons = course.get("lessons", [])

    for i, lesson in enumerate(lessons):
        if progress_cb:
            progress_cb(f"generating_quiz_{i + 1}_of_{len(lessons)}")
        quiz = generate_quiz(
            topic=lesson.get("title") or "Lesson",
            difficulty="medium",
            question_count=int(get_logic_param("curriculum_generation", "pregenerated_short_quiz_questions")),
            quiz_type="short_quiz",
            department=department,
        )
        store.write_quiz(quiz["quiz_id"], quiz)
        lesson["short_quiz_id"] = quiz["quiz_id"]

    if progress_cb:
        progress_cb("generating_final_assessment")
    final_quiz = generate_quiz(
        topic=course.get("title") or "Course",
        difficulty="medium",
        question_count=int(get_logic_param("curriculum_generation", "pregenerated_final_assessment_questions")),
        quiz_type="final_assessment",
        department=department,
    )
    store.write_quiz(final_quiz["quiz_id"], final_quiz)
    course["final_assessment_id"] = final_quiz["quiz_id"]


def trigger_curriculum_generation(
    filename: str = "",
    department: str = DEFAULT_DEPARTMENT,
    user_id: str = "manager",
    append_to_latest: bool = False,
    progress_cb: Optional[Callable[[str], None]] = None,
    filenames: Optional[list[str]] = None,
) -> dict:
    """Orchestrate the full upload-to-curriculum pipeline.

    1. Reads the saved raw document(s) from the knowledge base.
    2. Splits the (possibly combined) content into a structured curriculum (Course → Lessons).
    3. Pre-generates each lesson's short quiz and the course's final assessment.
    4. Saves the course JSON to the knowledge base.
    5. Generates and persists the learning path (either new or appended).

    Args:
        filename: The filename of a single raw document. Kept as the primary
            parameter for backward compatibility (agent tool-calling, single-file
            callers) — ignored if `filenames` is given.
        department: The department scope.
        user_id: The user who triggered the generation.
        append_to_latest: If True, merges this course into the latest existing path.
        progress_cb: Optional callback invoked with a stage name as generation
            progresses, so a background job can report granular status to a
            polling client.
        filenames: Multiple raw document filenames to combine into a single
            course. When given (non-empty), each document's content is
            concatenated (separated by a heading per source file, so the
            section-splitter treats each source as its own section) and the
            whole batch is generated as one course spanning all of them.
            Selections may freely mix text-family documents with binary media
            (PDF/image/audio/video) — media files are read as raw bytes and
            handed to Gemini natively rather than requiring text extraction.

    Returns:
        The generated learning path details.
    """
    store = DepartmentScopedStore(department)
    files = filenames if filenames else [filename]

    # Step 1: Read the raw document(s), branching per file by content category
    # (recorded at upload time via write_catalog_input_meta). Text-family files
    # stay strings for the section splitter; binary media becomes a
    # `Part.from_bytes` fed straight into the Gemini call.
    texts = []
    text_files = []
    media_parts: list = []
    for fn in files:
        meta = store.read_catalog_input_meta(fn)
        category = meta.get("content_category", "text")
        if category == "text":
            text = store.read_raw_document(fn)
            if not text:
                return {
                    "status": "error",
                    "message": f"Raw document '{fn}' not found.",
                }
            texts.append(text)
            text_files.append(fn)
        else:
            data = store.read_raw_document_bytes(fn)
            if not data:
                return {
                    "status": "error",
                    "message": f"Raw document '{fn}' not found.",
                }
            media_parts.append(types.Part.from_bytes(
                data=data,
                mime_type=meta.get("mime_type", "application/octet-stream"),
            ))

    if len(files) == 1:
        # Preserve exact prior behavior for the single-file path.
        document_title = files[0]
        document_text = texts[0] if text_files else ""
    else:
        document_title = " + ".join(Path(fn).stem for fn in files)
        document_text = "\n\n".join(
            f"## {Path(fn).stem}\n\n{text}" for fn, text in zip(text_files, texts)
        ) if text_files else ""
    source_label = ", ".join(files)

    # Step 2: Split into curriculum
    if progress_cb:
        progress_cb("generating_lessons")
    result = process_document_to_curriculum(
        document_text=document_text,
        document_title=document_title,
        department=department,
        media_parts=media_parts or None,
    )

    if result.get("status") != "success":
        return result

    course = result["course"]

    # Step 3: Pre-generate quizzes + final assessment for this course
    _generate_course_quizzes(course, department, progress_cb)

    # Step 4: Save the course to the knowledge base
    course_doc = {
        "title": course["title"],
        "description": course["description"],
        "topics": course["topics"],
        "content": document_text[:2000],
        "estimated_hours": course["estimated_hours"],
        "key_facts": [
            {"concept": c, "definition": ""}
            for c in course["topics"][:5]
        ],
        "source_dtp": f"raw/{files[0]}",
        "version": "1.0",
        "lessons": course["lessons"],
        "has_final_assessment": course["has_final_assessment"],
    }
    store.write_knowledge_document(course["course_id"], course_doc)

    # Step 5: Build or Append to learning path
    from src.core.database import _store_lock
    
    with _store_lock:
        existing_path = None
        if append_to_latest:
            existing_path = store.read_latest_learning_path()

        if existing_path:
            # Append to existing
            path_id = existing_path["path_id"]
            existing_path["courses"].append(course)
            existing_path["total_courses"] = len(existing_path["courses"])
            existing_path["total_estimated_hours"] = round(sum(c.get("estimated_hours", 0) for c in existing_path["courses"]), 1)
            existing_path["timeframe_weeks"] = max(1, int(existing_path["total_estimated_hours"] / 4) + 1)
            existing_path["hours_per_week"] = round(existing_path["total_estimated_hours"] / existing_path["timeframe_weeks"], 1)
            # Retain the earliest source_document or append
            if source_label not in existing_path.get("source_document", ""):
                existing_path["source_document"] = existing_path.get("source_document", "") + f", {source_label}"

            learning_path = existing_path
        else:
            # Create new
            path_id = f"lp_{uuid.uuid4().hex[:8]}"
            learning_path = {
                "path_id": path_id,
                "department": department,
                "role": "auto_generated",
                "timeframe_weeks": max(1, int(course["estimated_hours"] / 4) + 1),
                "total_courses": 1,
                "total_estimated_hours": course["estimated_hours"],
                "hours_per_week": round(course["estimated_hours"], 1),
                "days_per_course": 2,
                "source_document": source_label,
                "courses": [course],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

        store.write_learning_path(path_id, learning_path)

    return {
        "status": "success",
        "path_id": path_id,
        "course_id": course["course_id"],
        "total_lessons": result["total_lessons"],
        "total_estimated_hours": result["total_estimated_hours"],
        "learning_path": learning_path,
        "appended": bool(existing_path)
    }


def regenerate_lesson_content(
    lesson_title: str,
    lesson_content: str,
    instruction: str = "",
) -> dict:
    """Use Gemini to rewrite a single lesson's title + body content for a
    manager's manual edit ("Regenerate with AI" button), given an optional
    free-form instruction (e.g. "make it shorter", "add a concrete example").

    Returns a draft for the manager to review — never writes to disk itself.
    On any LLM failure, returns the original title/content unchanged so the
    editor always has something to show rather than an empty result.
    """
    instruction_text = instruction.strip() or "Improve clarity and structure while preserving all factual content."
    prompt = (
        "You are an expert corporate training content editor. Rewrite the following lesson "
        "for an employee learning platform. Keep it factually faithful to the original, and "
        "keep the same markdown-style conventions already used in it (## for a heading, "
        "**term** for bold emphasis, - **term**: description for bullet definitions).\n\n"
        f"Editing instruction: {instruction_text}\n\n"
        f"Current lesson title: {lesson_title}\n\n"
        f"Current lesson content:\n{lesson_content}\n\n"
        'Respond with ONLY a JSON object of the shape {"title": "...", "content": "..."}, '
        "no markdown code fences, no other text."
    )

    try:
        data = call_gemini_json(prompt)
        if not data.get("content"):
            raise ValueError("LLM response missing a non-empty 'content' field.")

        return {
            "status": "success",
            "title": data.get("title") or lesson_title,
            "content": data["content"],
        }
    except Exception as e:
        print(f"[regenerate_lesson_content] LLM call failed ({e}), returning original content.")
        return {
            "status": "error",
            "message": str(e),
            "title": lesson_title,
            "content": lesson_content,
        }


def get_pending_remedial_courses(progress: dict, source_course_id: str = "") -> list[dict]:
    """Remedial courses in `progress` that haven't been completed yet, optionally
    filtered to courses targeting a specific source_course_id. Shared by every
    code path that needs to know which remedial courses are still outstanding
    for a user (learning-path injection, accumulation-cap checks) so they can't
    silently disagree about what "pending" means."""
    completed = set(progress.get("completed_courses", []))
    pending = [c for c in progress.get("remedial_courses", []) if c.get("course_id") not in completed]
    if source_course_id:
        pending = [c for c in pending if c.get("source_course_id") == source_course_id]
    return pending


def generate_remedial_course(
    incorrect_answers: list[dict],
    user_id: str,
    source_course_id: str = "",
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Use Gemini LLM to perform gap analysis and generate a personalized remedial course.

    Analyzes the user's incorrect quiz answers, identifies the concept gaps,
    and generates a complete course structure (lesson + short quiz + final assessment)
    targeted at those exact weaknesses.

    If the user already has `remedial_course_cap` pending (not yet completed)
    remedial courses for this same source_course_id, this call merges into the
    most recently created one (same course_id, regenerated content covering
    the union of old + new gap topics) instead of piling on another course.

    Args:
        incorrect_answers: List of answer dicts with question_text, user_answer,
                           correct_answer, and concept_tags fields.
        user_id: The user who failed the assessment.
        department: The department scope.

    Returns:
        A complete course dict marked with is_remedial=True, ready to inject
        into the user's learning path.
    """
    store = DepartmentScopedStore(department)
    progress = store.read_user_progress(user_id) or {"user_id": user_id, "department": department}
    concept_diagnoses = progress.get("concept_diagnoses", {})

    cap = int(get_logic_param("curriculum_generation", "remedial_course_cap"))
    pending_for_source = (
        get_pending_remedial_courses(progress, source_course_id) if source_course_id else []
    )
    target_course = pending_for_source[-1] if len(pending_for_source) >= cap else None

    # Build a summary of mistakes for the LLM. When regenerating, prepend the
    # target course's still-unresolved gap topics (with their last-known
    # diagnosis, if any) so the merged course actually covers the union of
    # old + new gaps rather than dropping the earlier ones.
    gap_summary_lines = []
    all_concept_tags = []
    if target_course:
        for tag in target_course.get("gap_topics", []):
            all_concept_tags.append(tag)
            prior_diag = concept_diagnoses.get(tag, [])
            misconception = prior_diag[-1]["misconception"] if prior_diag else ""
            gap_summary_lines.append(
                f"(Previously flagged, still unresolved) Topic: {tag}"
                + (f" — misconception: {misconception}" if misconception else "")
            )

    for i, ans in enumerate(incorrect_answers, 1):
        tags = ans.get("concept_tags", [])
        all_concept_tags.extend(tags)
        gap_summary_lines.append(
            f"{i}. Question: {ans.get('question_text', ans.get('question_id', 'Unknown'))}\n"
            f"   User answered: {ans.get('user_answer', 'N/A')}\n"
            f"   Correct answer: {ans.get('correct_answer', 'N/A')}\n"
            f"   Topics: {', '.join(tags) if tags else 'general'}"
        )

    unique_tags = list(dict.fromkeys(all_concept_tags))  # preserve order, deduplicate
    gap_text = "\n".join(gap_summary_lines) if gap_summary_lines else "General knowledge gaps detected."

    tool_config = get_config()["tools"]["generate_remedial_course"]
    prompt = tool_config["prompt_template"].format(
        gap_text=gap_text,
        short_quiz_question_count=int(get_logic_param("curriculum_generation", "remedial_short_quiz_questions")),
        final_assessment_question_count=int(get_logic_param("curriculum_generation", "remedial_final_assessment_questions")),
    )

    # Call Gemini via Vertex AI using ADC (Application Default Credentials)
    # This matches how the rest of the project connects — no API key needed.

    def _build_fallback_question(topic_label: str, i: int) -> dict:
        """Deterministic fallback question, same shape as quiz_service's
        _build_template_question — used when the LLM call below fails, so the
        remedial course is still gradeable instead of shipping with 0 questions."""
        correct_idx = i % 4
        # All 4 options share identical neutral phrasing so none of them leaks
        # the answer through wording -- only correct_answer_index (never sent
        # to the client) marks which one is right.
        letters = "ABCD"
        options = [
            f"Statement {letters[j]}: a description related to {topic_label}, part {i+1}."
            for j in range(4)
        ]
        rationale = {}
        for j in range(4):
            if j == correct_idx:
                rationale[str(j)] = f"Correct! This option accurately defines the core concept of {topic_label} part {i+1}."
            else:
                rationale[str(j)] = f"This is incorrect. It focuses on the wrong aspect of {topic_label} and misses the main point."
        return {
            "text": f"Regarding '{topic_label}', which of the following represents the core concept for part {i+1}?",
            "options": options,
            "correct_answer_index": correct_idx,
            "rationale": rationale,
            "concept_tags": unique_tags[:2] or ["general"],
        }

    # Pre-declare llm_data as dict so the type checker always sees a dict,
    # regardless of whether the LLM call succeeds or falls back.
    topic_label = ", ".join(unique_tags[:3]) if unique_tags else "Key Concepts"
    _fallback_sq_count = int(get_logic_param("curriculum_generation", "remedial_short_quiz_questions"))
    _fallback_fa_count = int(get_logic_param("curriculum_generation", "remedial_final_assessment_questions"))
    llm_data: dict[str, Any] = {
        "course_title": f"Targeted Review: {topic_label}",
        "course_description": (
            f"This remedial course focuses on the topics where you had difficulty: "
            f"{topic_label}. Complete the lesson and quizzes to solidify your understanding."
        ),
        "gap_topics": unique_tags or ["general"],
        "lesson": {
            "lesson_title": f"Deep Dive: {topic_label}",
            "content_summary": (
                f"This lesson revisits the core concepts around {topic_label}. "
                "Review the original course materials and pay special attention to "
                "the areas highlighted in your gap analysis."
            ),
            "key_points": [f"Master {t}" for t in (unique_tags[:3] or ["key concept"])],
        },
        "short_quiz": {
            "title": f"Short Quiz: {topic_label}",
            "questions": [_build_fallback_question(topic_label, i) for i in range(_fallback_sq_count)],
        },
        "final_assessment": {
            "title": f"Final Assessment: {topic_label}",
            "questions": [_build_fallback_question(topic_label, i) for i in range(_fallback_fa_count)],
        },
    }

    diagnoses: list = []
    try:
        llm_data = call_gemini_json(prompt, model=tool_config.get("model"))
        raw_diagnoses = llm_data.get("diagnoses")
        if isinstance(raw_diagnoses, list):
            diagnoses = raw_diagnoses
    except Exception as e:
        # llm_data is already pre-initialised to the fallback dict above the try block.
        # Just log the failure — the fallback value is used automatically.
        print(f"[generate_remedial_course] LLM call failed ({e}), using fallback.")

    # Build course_id and lesson_id — reuse the target course's IDs when
    # regenerating (same quiz sessions, same links), mint fresh ones otherwise.
    if target_course:
        course_id = target_course["course_id"]
        lesson_id = (target_course.get("lessons") or [{}])[0].get("lesson_id") or "lesson_r01"
        sq_quiz_id = target_course.get("short_quiz_id") or f"quiz_{uuid.uuid4().hex[:8]}"
        fa_quiz_id = target_course.get("final_assessment_id") or f"quiz_{uuid.uuid4().hex[:8]}"
    else:
        course_id = f"remedial_{uuid.uuid4().hex[:8]}"
        lesson_id = "lesson_r01"
        sq_quiz_id = f"quiz_{uuid.uuid4().hex[:8]}"
        fa_quiz_id = f"quiz_{uuid.uuid4().hex[:8]}"

    # Enrich questions with IDs
    def _enrich_questions(raw_questions):
        result = []
        for q in raw_questions:
            q["question_id"] = f"q_{uuid.uuid4().hex[:6]}"
            result.append(q)
        return result

    sq_questions = _enrich_questions(llm_data.get("short_quiz", {}).get("questions", []))
    fa_questions = _enrich_questions(llm_data.get("final_assessment", {}).get("questions", []))

    short_quiz_doc = {
        "quiz_id": sq_quiz_id,
        "topic": llm_data.get("course_title", "Remedial Review"),
        "quiz_type": "short_quiz",
        "question_count": len(sq_questions),
        "questions": sq_questions,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    final_assessment_doc = {
        "quiz_id": fa_quiz_id,
        "topic": llm_data.get("course_title", "Remedial Review"),
        "quiz_type": "final_assessment",
        "question_count": len(fa_questions),
        "questions": fa_questions,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Build the full course structure
    remedial_course = {
        "course_id": course_id,
        "title": llm_data.get("course_title", "Targeted Review"),
        "description": llm_data.get("course_description", ""),
        "topics": llm_data.get("gap_topics", unique_tags),
        "estimated_hours": 1.0,
        "order": 0,
        "is_remedial": True,
        "remedial_for_user": user_id,
        "source_course_id": source_course_id,
        "gap_topics": llm_data.get("gap_topics", unique_tags),
        "has_final_assessment": True,
        "short_quiz_id": sq_quiz_id,
        "final_assessment_id": fa_quiz_id,
        "lessons": [
            {
                "lesson_id": lesson_id,
                "title": llm_data.get("lesson", {}).get("lesson_title", "Remedial Lesson"),
                "content_summary": llm_data.get("lesson", {}).get("content_summary", ""),
                "key_points": llm_data.get("lesson", {}).get("key_points", []),
                "estimated_minutes": 20,
                "has_quiz": True,
                "short_quiz_id": sq_quiz_id,
                "short_quiz": short_quiz_doc,
            }
        ],
        "final_assessment": final_assessment_doc,
        "created_at": target_course.get("created_at") if target_course else datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "regenerated_count": (target_course.get("regenerated_count", 0) + 1) if target_course else 0,
    }

    # Diagnosis persistence: zip the LLM's per-answer diagnoses against the
    # NEWLY-graded incorrect answers (in gap_text order) so gap-review and
    # reflection prompts can later cite WHY a concept keeps failing, not just
    # an integer failure count. Falls back to the raw concept_tags when the
    # LLM omitted "diagnoses" (e.g. on a fallback-path generation).
    now_iso = datetime.now(timezone.utc).isoformat()
    for diag, ans in zip(diagnoses, incorrect_answers):
        diag = diag if isinstance(diag, dict) else {}
        tags = diag.get("concept_tags") or ans.get("concept_tags") or ["general"]
        misconception = diag.get("misconception", "")
        for tag in tags:
            concept_diagnoses.setdefault(tag, []).append({
                "concept_tag": tag,
                "misconception": misconception,
                "question_text": ans.get("question_text", ""),
                "user_answer": ans.get("user_answer", ""),
                "correct_answer": ans.get("correct_answer", ""),
                "source": "remedial_course_generation",
                "quiz_id": fa_quiz_id,
                "course_id": course_id,
                "recorded_at": now_iso,
                "resolved": False,
            })
    progress["concept_diagnoses"] = concept_diagnoses

    # Persist remedial course to the user's progress record. When regenerating
    # (target_course set), replace that entry in place rather than appending —
    # it's the same course_id, just refreshed content covering the union of gaps.
    remedial_courses = progress.get("remedial_courses", [])
    if target_course:
        remedial_courses = [
            remedial_course if c.get("course_id") == course_id else c
            for c in remedial_courses
        ]
    else:
        remedial_courses.append(remedial_course)
    progress["remedial_courses"] = remedial_courses
    store.write_user_progress(user_id, progress)

    return remedial_course
