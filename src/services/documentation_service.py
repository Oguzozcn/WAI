"""
Documentation Master — full-project documentation synthesis
=============================================================
Turns everything linked to a Team Documentation project (PDFs, spreadsheets,
video/audio transcripts, text glossaries, business-logic docs, DTPs — any
mix) into a coherent, onboarding-quality documentation set: what the project
is, how it works, its requirements, and — only where the sources actually
contain it — implementation detail with code snippets. Domain-agnostic: a
finance project, an e-commerce project, and a software project all go
through the same synthesis.

This is both a plain function called directly by the Team Docs route
(button-triggered) and an ADK tool attached to the root orchestrator's
SkillToolset (chat-triggered), per this codebase's "one function, two
callers" convention (see trigger_curriculum_generation).
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from google.genai import types

from src.core.config import DEFAULT_DEPARTMENT, SUPPORTED_MIME_TYPES
from src.core.database import DepartmentScopedStore
from src.core.dev_config import get_config
from src.services.llm_client import call_gemini_json

MAX_SOURCE_CHARS_PER_FILE = 30_000


def _clean_title(value: Any, max_len: int = 100) -> str:
    if not isinstance(value, str):
        return ""
    title = " ".join(value.split())
    if not title:
        return ""
    return title if len(title) <= max_len else title[:max_len].rstrip() + "…"


def _resolve_source(store: DepartmentScopedStore, doc_id: str) -> Optional[dict]:
    """Read a linked source's chunks doc and load its actual content —
    raw text for text-family uploads, a genai Part for binary media. Returns
    None (never raises) if the source or its underlying file is missing, so
    the caller can skip it and keep going rather than fail the whole run."""
    doc = store.read_knowledge_document(doc_id)
    if doc is None or "source_filename" not in doc:
        return None
    filename = doc["source_filename"]
    ext = Path(filename).suffix.lower()
    _, category = SUPPORTED_MIME_TYPES.get(ext, ("application/octet-stream", "text"))

    if category == "text":
        text = store.read_raw_document(filename)
        if not text or not text.strip():
            return None
        return {"filename": filename, "kind": "text", "text": text[:MAX_SOURCE_CHARS_PER_FILE]}

    data = store.read_raw_document_bytes(filename)
    if not data:
        return None
    mime_type, _ = SUPPORTED_MIME_TYPES.get(ext, ("application/octet-stream", category))
    return {"filename": filename, "kind": "media",
            "part": types.Part.from_bytes(data=data, mime_type=mime_type)}


def generate_project_documentation(
    project_id: str,
    department: str = DEFAULT_DEPARTMENT,
) -> dict:
    """Synthesize a full documentation set for a Team Documentation project
    from every Knowledge Vault source linked to it.

    Reads the project's linked_sources (set via PUT /api/team-docs/projects/
    {id}/sources), gathers each source's actual content — raw text for text/
    spreadsheet uploads, native binary media (PDF/image/audio/video) for
    everything else — and asks Gemini for a structured, onboarding-quality
    documentation set in one multimodal call. Writes the result as pages in
    the project, replacing any pages from a previous synthesis run so
    regenerating doesn't pile up duplicates, while leaving manually-written
    or single-source AI-drafted pages untouched.

    Args:
        project_id: The Team Documentation project to document.
        department: The department scope.

    Returns:
        {"status": "success", "project_id", "pages_written": [titles],
         "project": <updated project dict>} on success, or a {"status": ...,
        "message": ...} sentinel — "not_found" (unknown project), "no_sources"
        (nothing linked yet), or "error" (LLM call failed or returned an
        unusable shape) — since there's no sound deterministic fallback for
        synthesizing an entire document from scratch.
    """
    store = DepartmentScopedStore(department)
    project = store.read_team_project(project_id)
    if project is None:
        return {"status": "not_found",
                "message": f"Team Documentation project '{project_id}' not found."}

    linked = project.get("linked_sources", [])
    if not linked:
        return {"status": "no_sources",
                "message": "This project has no linked Knowledge Vault sources yet. "
                           "Link some sources in Team Docs, then generate documentation."}

    text_blocks = []
    media_parts: list = []
    used_filenames = []
    for doc_id in linked:
        source = _resolve_source(store, doc_id)
        if source is None:
            continue
        used_filenames.append(source["filename"])
        if source["kind"] == "text":
            text_blocks.append(f"## {source['filename']}\n\n{source['text']}")
        else:
            media_parts.append(source["part"])

    if not text_blocks and not media_parts:
        return {"status": "no_sources",
                "message": "None of this project's linked sources have readable content."}

    tool_config = get_config()["tools"]["generate_project_documentation"]
    prompt = tool_config["prompt_template"].format(
        project_name=project["name"],
        sources_text="\n\n---\n\n".join(text_blocks) if text_blocks else "(no text-family sources — see attached media)",
    )
    contents = [*media_parts, prompt] if media_parts else prompt

    try:
        llm_data = call_gemini_json(contents, model=tool_config.get("model"))
        raw_pages = llm_data.get("pages")
        if not isinstance(raw_pages, list) or not raw_pages:
            raise ValueError("LLM response missing a non-empty 'pages' list.")
        drafted = []
        for entry in raw_pages:
            title = _clean_title(entry.get("title"), max_len=80)
            content = str(entry.get("content_markdown", "")).strip()
            if not title or not content:
                continue
            drafted.append({"title": title, "content": content})
        if not drafted:
            raise ValueError("LLM response had no usable title/content_markdown pairs.")
    except Exception as e:
        print(f"[generate_project_documentation] LLM call failed ({e}), no fallback available.")
        return {"status": "error",
                "message": f"Documentation generation failed: {e}"}

    now = datetime.now(timezone.utc).isoformat()
    project["pages"] = [p for p in project["pages"] if p.get("drafted_by") != "ai_synthesis"]
    for page in drafted:
        seq = project.get("next_page_seq", len(project["pages"]) + 1)
        project["pages"].append({
            "id": f"page-{seq:04d}",
            "title": page["title"],
            "content": page["content"],
            "source": {"type": "vault_synthesis", "doc_ids": list(linked),
                      "filenames": used_filenames},
            "drafted_by": "ai_synthesis",
            "created_by": "documentation-master",
            "created_at": now,
            "updated_at": now,
        })
        project["next_page_seq"] = seq + 1

    store.write_team_project(project_id, project)
    return {
        "status": "success",
        "project_id": project_id,
        "pages_written": [p["title"] for p in drafted],
        "project": project,
    }
