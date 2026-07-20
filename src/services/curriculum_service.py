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

from src.core.database import DepartmentScopedStore
from src.core.config import DEFAULT_DEPARTMENT, DEFAULT_TIMEFRAME_WEEKS
from src.core.dev_config import get_config, get_param, get_logic_param
from src.services.llm_client import get_gemini_client


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


def process_kb_upload_job(
    job_id: str,
    filename: str,
    content: str,
    department: str,
    version_action: str = "",
) -> None:
    """Background task: validate → chunk → save an uploaded KB document.

    Fire-and-forget: this function returns nothing. All progress and results are
    written to the KB job doc via `store.write_kb_job` so a polling client can
    observe stage-by-stage progress. Any exception is caught and persisted as an
    ``error`` status (FastAPI BackgroundTasks swallow unhandled exceptions, so we
    must record the failure ourselves for the poller to see it).
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

        # Stage: Validate
        gap_analysis = identify_content_gaps(
            document_content=content,
            department=department,
        )

        # Stage: Chunk
        store.write_kb_job(job_id, {
            "job_id": job_id,
            "status": "processing",
            "stage": "chunking",
            "filename": actual_filename,
        })
        chunks = recursive_character_splitter(content, max_tokens=1024, overlap=200)
        upload_timestamp = datetime.now(timezone.utc).isoformat()
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
        chunks_doc_id = f"{Path(actual_filename).stem}_chunks"
        store.write_raw_document(actual_filename, content)
        store.write_catalog_input(actual_filename, content)
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
) -> None:
    """Background task: generate a course (lessons + short quizzes + final
    assessment) from an uploaded document and save it as the manager's
    private draft.

    Fire-and-forget, mirroring process_kb_upload_job — progress is written to
    the KB job doc via store.write_kb_job so a polling client can observe
    stage-by-stage progress, including after the user dismisses the modal via
    "Continue in Background" and navigates away.
    """
    store = DepartmentScopedStore(department)

    def _progress(stage: str) -> None:
        store.write_kb_job(job_id, {
            "job_id": job_id,
            "status": "processing",
            "stage": stage,
            "filename": filename,
        })

    try:
        _progress("parsing_document")
        result = trigger_curriculum_generation(
            filename=filename,
            department=department,
            append_to_latest=append_to_latest,
            progress_cb=_progress,
        )

        if result.get("status") != "success":
            store.write_kb_job(job_id, {
                "job_id": job_id,
                "status": "error",
                "stage": "failed",
                "filename": filename,
                "message": result.get("message", "Curriculum generation failed."),
            })
            return

        if result.get("path_id"):
            path_data = store.read_learning_path(result["path_id"])
            if path_data:
                path_data["source_input_files"] = [filename]
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
            "filename": filename,
            "result": result,
        })
    except Exception as e:
        store.write_kb_job(job_id, {
            "job_id": job_id,
            "status": "error",
            "stage": "failed",
            "filename": filename,
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


def process_document_to_curriculum(
    document_text: str,
    document_title: str = "Uploaded Document",
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Split a document into a structured curriculum: Course → Lessons.

    The Course Splitter logic. Analyzes document_text and generates a
    structured curriculum with up to 10 lessons per module, each with
    a short quiz, plus a final assessment for the module.

    Args:
        document_text: The raw text content of the uploaded document.
        document_title: The title/filename of the document.
        department: The department scope.

    Returns:
        A structured curriculum dict with courses and lessons.
    """
    sections = _split_text_into_sections(document_text)

    if not sections:
        return {
            "status": "error",
            "message": "Could not extract any content from the document.",
        }

    # Ask Gemini — in ONE batched call for the whole document — to turn each
    # structural section into a teaching summary + key concepts. On any failure
    # we fall back per-section to the deterministic heuristic below.
    llm_sections: dict[int, dict] = {}
    try:
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

        client = get_gemini_client()
        response = client.models.generate_content(
            model=tool_config.get("model") or get_param("GEMINI_MODEL"),
            contents=prompt,
        )
        raw = (response.text or "").strip()
        if not raw:
            raise ValueError("LLM returned an empty response.")

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0].strip()

        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"LLM returned unexpected type: {type(parsed).__name__}")

        # Index by the section index so per-section fallback stays simple/defensive.
        for entry in parsed.get("sections", []):
            if not isinstance(entry, dict):
                continue
            idx = entry.get("index")
            if isinstance(idx, int) and 0 <= idx < len(sections):
                llm_sections[idx] = entry

    except Exception as e:
        print(f"[process_document_to_curriculum] LLM call failed ({e}), using fallback.")

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
    filename: str,
    department: str = DEFAULT_DEPARTMENT,
    user_id: str = "manager",
    append_to_latest: bool = False,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    """Orchestrate the full upload-to-curriculum pipeline.

    1. Reads the saved raw document from the knowledge base.
    2. Splits it into a structured curriculum (Course → Lessons).
    3. Pre-generates each lesson's short quiz and the course's final assessment.
    4. Saves the course JSON to the knowledge base.
    5. Generates and persists the learning path (either new or appended).

    Args:
        filename: The filename of the raw document.
        department: The department scope.
        user_id: The user who triggered the generation.
        append_to_latest: If True, merges this course into the latest existing path.
        progress_cb: Optional callback invoked with a stage name as generation
            progresses, so a background job can report granular status to a
            polling client.

    Returns:
        The generated learning path details.
    """
    store = DepartmentScopedStore(department)

    # Step 1: Read the raw document
    document_text = store.read_raw_document(filename)
    if not document_text:
        return {
            "status": "error",
            "message": f"Raw document '{filename}' not found.",
        }

    # Step 2: Split into curriculum
    if progress_cb:
        progress_cb("generating_lessons")
    result = process_document_to_curriculum(
        document_text=document_text,
        document_title=filename,
        department=department,
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
        "source_dtp": f"raw/{filename}",
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
            if filename not in existing_path.get("source_document", ""):
                existing_path["source_document"] = existing_path.get("source_document", "") + f", {filename}"
            
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
                "source_document": filename,
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

    Args:
        incorrect_answers: List of answer dicts with question_text, user_answer,
                           correct_answer, and concept_tags fields.
        user_id: The user who failed the assessment.
        department: The department scope.

    Returns:
        A complete course dict marked with is_remedial=True, ready to inject
        into the user's learning path.
    """
    # Build a summary of mistakes for the LLM
    gap_summary_lines = []
    all_concept_tags = []
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

    # Pre-declare llm_data as dict so the type checker always sees a dict,
    # regardless of whether the LLM call succeeds or falls back.
    topic_label = ", ".join(unique_tags[:3]) if unique_tags else "Key Concepts"
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
            "questions": [],
        },
        "final_assessment": {
            "title": f"Final Assessment: {topic_label}",
            "questions": [],
        },
    }

    try:
        client = get_gemini_client()

        response = client.models.generate_content(
            model=tool_config.get("model") or get_param("GEMINI_MODEL"),
            contents=prompt,
        )
        raw = (response.text or "").strip()
        if not raw:
            raise ValueError("LLM returned an empty response.")

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0].strip()

        llm_data = json.loads(raw)
        # Ensure the LLM returned a dict, not a list or scalar
        if not isinstance(llm_data, dict):
            raise ValueError(f"LLM returned unexpected type: {type(llm_data).__name__}")

    except Exception as e:
        # llm_data is already pre-initialised to the fallback dict above the try block.
        # Just log the failure — the fallback value is used automatically.
        print(f"[generate_remedial_course] LLM call failed ({e}), using fallback.")


    # Build course_id and lesson_id
    course_id = f"remedial_{uuid.uuid4().hex[:8]}"
    lesson_id = f"lesson_r01"
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

    # Persist quizzes to the store so they can be evaluated server-side
    store = DepartmentScopedStore(department)

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
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Persist remedial course to the user's progress record
    progress = store.read_user_progress(user_id) or {"user_id": user_id, "department": department}
    remedial_courses = progress.get("remedial_courses", [])
    remedial_courses.append(remedial_course)
    progress["remedial_courses"] = remedial_courses
    store.write_user_progress(user_id, progress)

    return remedial_course
