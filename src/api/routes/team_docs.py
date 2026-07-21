"""
Team Documentation routes
=========================
A shared documentation workspace for managers and employees: a team keeps any
number of PROJECTS (data/team_docs/<dept>/PROJ-<n>.json), and each project
holds markdown documentation PAGES. Pages start blank or are built from a
Knowledge Vault upload — either imported verbatim or drafted into a clean
structured page by the LLM (with the standard deterministic fallback to a
plain import when the LLM is unavailable).

Role gating follows the app's client-trusted pattern (see dev_console.py):
every endpoint requires role == "manager" or "individual_contributor" —
developers have their own Documentation section. Deleting a whole project
additionally requires the manager role.
"""

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.core.config import DEFAULT_DEPARTMENT
from src.core.database import DepartmentScopedStore
from src.core.dev_config import get_config
from src.core.doc_export import export_pdf, export_txt
from src.services.documentation_service import generate_project_documentation
from src.services.llm_client import call_gemini_json

router = APIRouter(prefix="/api/team-docs", tags=["team-docs"])

TEAM_ROLES = ("manager", "individual_contributor")
PAGE_MODES = ("blank", "import", "ai_draft")

# Cap what we hand the LLM so a huge upload can't blow up the prompt.
MAX_SOURCE_CHARS = 30_000


# ── Request bodies ───────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    role: str = ""
    user_id: str = ""
    display_name: str = ""
    department: str = DEFAULT_DEPARTMENT


class ProjectUpdate(BaseModel):
    role: str = ""
    name: Optional[str] = None
    description: Optional[str] = None


class PageCreate(BaseModel):
    role: str = ""
    user_id: str = ""
    display_name: str = ""
    mode: str = "blank"
    title: str = ""
    content: str = ""
    source_doc_id: str = ""


class PageSave(BaseModel):
    role: str = ""
    content: str
    title: str = ""


class SourcesUpdate(BaseModel):
    role: str = ""
    source_doc_ids: list[str] = []


# ── Guards & helpers ─────────────────────────────────────────────────────────

def _require_team_member(role: str) -> None:
    if role not in TEAM_ROLES:
        raise HTTPException(status_code=403,
                            detail="Team Documentation is for managers and employees.")


def _require_manager(role: str) -> None:
    if role != "manager":
        raise HTTPException(status_code=403,
                            detail="Only a manager can create or delete a project.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_project_id(store: DepartmentScopedStore) -> str:
    """Sequential, human-readable project ids (PROJ-0001), like ticket ids."""
    highest = 0
    for existing in store.team_docs_path.glob("PROJ-*.json"):
        try:
            highest = max(highest, int(existing.stem.split("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"PROJ-{highest + 1:04d}"


def _get_project(store: DepartmentScopedStore, project_id: str) -> dict:
    project = store.read_team_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")
    return project


def _get_page(project: dict, page_id: str) -> dict:
    page = next((p for p in project["pages"] if p["id"] == page_id), None)
    if page is None:
        raise HTTPException(status_code=404,
                            detail=f"Page '{page_id}' not found in this project.")
    return page


def _project_overview(project: dict) -> dict:
    """The list-view projection: everything except the page contents."""
    return {
        "project_id": project["project_id"],
        "name": project["name"],
        "description": project.get("description", ""),
        "page_count": len(project.get("pages", [])),
        "created_by": project.get("created_by", {}),
        "created_at": project.get("created_at", ""),
        "updated_at": project.get("updated_at", ""),
    }


# ── Knowledge Vault sources ──────────────────────────────────────────────────

def _vault_sources(store: DepartmentScopedStore) -> list[dict]:
    """Uploads usable as page material: the *_chunks docs written at upload
    time (course docs and other KB shapes are skipped — they aren't uploads)."""
    sources = []
    for path in store.knowledge_base_path.glob("*.json"):
        if path.stem == ".gitkeep":
            continue
        doc = json.loads(path.read_text())
        if "chunks" not in doc or "source_filename" not in doc:
            continue
        sources.append({
            "doc_id": path.stem,
            "filename": doc["source_filename"],
            "uploaded_at": doc.get("uploaded_at", ""),
            "chunk_count": doc.get("chunk_count", len(doc.get("chunks", []))),
            "topics": doc.get("topics", []),
        })
    sources.sort(key=lambda s: s.get("uploaded_at", ""), reverse=True)
    return sources


def _source_text(store: DepartmentScopedStore, doc_id: str) -> tuple[str, str]:
    """Resolve a vault source to (filename, text). Prefers the original raw
    file (text uploads); media uploads fall back to their chunk text, which
    holds the Gemini summary produced at upload time."""
    doc = store.read_knowledge_document(doc_id)
    if doc is None or "chunks" not in doc:
        raise HTTPException(status_code=404,
                            detail=f"Knowledge Vault source '{doc_id}' not found.")
    filename = doc.get("source_filename", "")
    raw = None
    if filename:
        try:
            raw = store.read_raw_document(filename)
        except (UnicodeDecodeError, OSError):
            raw = None  # binary upload (pdf/media) — use the chunk text instead
    if raw and raw.strip():
        return filename, raw.strip()
    chunk_text = "\n\n".join(
        c.get("text", "") for c in doc.get("chunks", []) if c.get("text", "").strip()
    ).strip()
    if not chunk_text:
        raise HTTPException(status_code=400,
                            detail=f"'{filename or doc_id}' has no text content to build a page from.")
    return filename, chunk_text


def _title_from_filename(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return stem.replace("_", " ").replace("-", " ").strip().title() or "Imported Document"


def _ai_draft_page(project_name: str, filename: str, source_text: str) -> tuple[str, str]:
    """LLM-drafted page from a vault source. Raises on any failure — the
    caller falls back to a plain import (quiz_service pattern)."""
    tool_config = get_config()["tools"]["draft_team_doc_page"]
    prompt = tool_config["prompt_template"].format(
        project_name=project_name,
        source_filename=filename or "(untitled upload)",
        source_content=source_text[:MAX_SOURCE_CHARS],
    )
    llm_data = call_gemini_json(prompt, model=tool_config.get("model"))
    title = str(llm_data.get("title", "")).strip()
    content = str(llm_data.get("content_markdown", "")).strip()
    if not title or not content:
        raise ValueError("LLM response missing title/content_markdown.")
    return title, content


# ── Projects ─────────────────────────────────────────────────────────────────

@router.get("/projects")
async def api_list_projects(role: str = "", department: str = DEFAULT_DEPARTMENT):
    _require_team_member(role)
    store = DepartmentScopedStore(department)
    projects = [_project_overview(p) for p in store.list_team_projects()]
    return {"projects": projects, "count": len(projects)}


@router.post("/projects")
async def api_create_project(body: ProjectCreate):
    _require_manager(body.role)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Project name is required.")

    store = DepartmentScopedStore(body.department)
    project_id = _next_project_id(store)
    project = {
        "project_id": project_id,
        "department": body.department,
        "name": body.name.strip(),
        "description": body.description.strip(),
        "created_by": {
            "user_id": body.user_id,
            "display_name": body.display_name or body.user_id,
            "role": body.role,
        },
        "created_at": _now(),
        "next_page_seq": 1,
        "pages": [],
        "linked_sources": [],
    }
    store.write_team_project(project_id, project)
    return project


@router.get("/projects/{project_id}")
async def api_get_project(project_id: str, role: str = "",
                          department: str = DEFAULT_DEPARTMENT):
    _require_team_member(role)
    return _get_project(DepartmentScopedStore(department), project_id)


@router.patch("/projects/{project_id}")
async def api_update_project(project_id: str, body: ProjectUpdate,
                             department: str = DEFAULT_DEPARTMENT):
    _require_team_member(body.role)
    store = DepartmentScopedStore(department)
    project = _get_project(store, project_id)
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=400, detail="Project name cannot be empty.")
        project["name"] = body.name.strip()
    if body.description is not None:
        project["description"] = body.description.strip()
    store.write_team_project(project_id, project)
    return project


@router.delete("/projects/{project_id}")
async def api_delete_project(project_id: str, role: str = "",
                             department: str = DEFAULT_DEPARTMENT):
    _require_manager(role)
    store = DepartmentScopedStore(department)
    if not store.delete_team_project(project_id):
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")
    return {"status": "deleted", "project_id": project_id}


# ── Knowledge Vault sources ──────────────────────────────────────────────────

@router.get("/sources")
async def api_list_sources(role: str = "", department: str = DEFAULT_DEPARTMENT):
    _require_team_member(role)
    sources = _vault_sources(DepartmentScopedStore(department))
    return {"sources": sources, "count": len(sources)}


@router.put("/projects/{project_id}/sources")
async def api_set_project_sources(project_id: str, body: SourcesUpdate,
                                  department: str = DEFAULT_DEPARTMENT):
    """Replace a project's linked-sources list wholesale — the set of
    Knowledge Vault uploads its documentation should be synthesized from,
    independent of which (if any) already have their own page."""
    _require_team_member(body.role)
    store = DepartmentScopedStore(department)
    project = _get_project(store, project_id)
    known_ids = {s["doc_id"] for s in _vault_sources(store)}
    unknown = [d for d in body.source_doc_ids if d not in known_ids]
    if unknown:
        raise HTTPException(status_code=404,
                            detail=f"Unknown Knowledge Vault source(s): {', '.join(unknown)}")
    project["linked_sources"] = list(dict.fromkeys(body.source_doc_ids))  # de-dupe, keep order
    store.write_team_project(project_id, project)
    return project


# ── Pages ────────────────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/pages")
async def api_add_page(project_id: str, body: PageCreate,
                       department: str = DEFAULT_DEPARTMENT):
    _require_team_member(body.role)
    if body.mode not in PAGE_MODES:
        raise HTTPException(status_code=400,
                            detail=f"mode must be one of: {', '.join(PAGE_MODES)}")

    store = DepartmentScopedStore(department)
    project = _get_project(store, project_id)

    if body.mode == "blank":
        title = body.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="A blank page needs a title.")
        content = body.content.strip() or f"# {title}\n\n_Start writing this page..._"
        source = {"type": "blank"}
        drafted_by = "manual"
    else:
        if not body.source_doc_id.strip():
            raise HTTPException(status_code=400,
                                detail="Pick a Knowledge Vault document to build the page from.")
        filename, text = _source_text(store, body.source_doc_id.strip())
        title = body.title.strip() or _title_from_filename(filename)
        content = text
        drafted_by = "import"
        if body.mode == "ai_draft":
            try:
                title, content = _ai_draft_page(project["name"], filename, text)
                if body.title.strip():
                    title = body.title.strip()  # an explicit title always wins
                drafted_by = "ai"
            except Exception as e:
                print(f"[add_team_doc_page] LLM call failed ({e}), using import fallback.")
        source = {"type": "vault", "doc_id": body.source_doc_id.strip(),
                  "filename": filename}

    seq = project.get("next_page_seq", len(project["pages"]) + 1)
    page = {
        "id": f"page-{seq:04d}",
        "title": title,
        "content": content,
        "source": source,
        "drafted_by": drafted_by,
        "created_by": body.display_name or body.user_id,
        "created_at": _now(),
        "updated_at": _now(),
    }
    project["next_page_seq"] = seq + 1
    project["pages"].append(page)
    store.write_team_project(project_id, project)
    return {"status": "created", "page_id": page["id"], "project": project}


@router.put("/projects/{project_id}/pages/{page_id}")
async def api_save_page(project_id: str, page_id: str, body: PageSave,
                        department: str = DEFAULT_DEPARTMENT):
    _require_team_member(body.role)
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Page content cannot be empty.")
    store = DepartmentScopedStore(department)
    project = _get_project(store, project_id)
    page = _get_page(project, page_id)
    page["content"] = body.content
    if body.title.strip():
        page["title"] = body.title.strip()
    page["updated_at"] = _now()
    store.write_team_project(project_id, project)
    return {"status": "saved", "page_id": page_id, "updated_at": page["updated_at"]}


@router.delete("/projects/{project_id}/pages/{page_id}")
async def api_delete_page(project_id: str, page_id: str, role: str = "",
                          department: str = DEFAULT_DEPARTMENT):
    _require_team_member(role)
    store = DepartmentScopedStore(department)
    project = _get_project(store, project_id)
    _get_page(project, page_id)  # 404 if unknown
    project["pages"] = [p for p in project["pages"] if p["id"] != page_id]
    store.write_team_project(project_id, project)
    return {"status": "deleted", "page_id": page_id, "project": project}


# ── Documentation Master (full-project synthesis from linked sources) ───────

class GenerateDocsRequest(BaseModel):
    role: str = ""


@router.post("/projects/{project_id}/generate-documentation")
async def api_generate_project_documentation(project_id: str, body: GenerateDocsRequest,
                                              department: str = DEFAULT_DEPARTMENT):
    """Synthesize the project's full documentation set from its linked
    Knowledge Vault sources. Same underlying function the Documentation
    Master ADK agent calls from chat — this is the direct, non-chat trigger."""
    _require_team_member(body.role)
    _get_project(DepartmentScopedStore(department), project_id)  # 404 if unknown
    result = generate_project_documentation(project_id, department=department)
    if result["status"] == "no_sources":
        raise HTTPException(status_code=400, detail=result["message"])
    if result["status"] == "error":
        raise HTTPException(status_code=502, detail=result["message"])
    return result


# ── Export (TXT / PDF via the shared doc_export module) ──────────────────────

@router.get("/projects/{project_id}/export")
async def api_export_project(project_id: str, format: str = "txt", scope: str = "all",
                             role: str = "", department: str = DEFAULT_DEPARTMENT):
    _require_team_member(role)
    if format not in ("txt", "pdf"):
        raise HTTPException(status_code=400, detail="format must be 'txt' or 'pdf'.")
    project = _get_project(DepartmentScopedStore(department), project_id)

    if scope == "all":
        pages = project["pages"]
        if not pages:
            raise HTTPException(status_code=404, detail="This project has no pages to export.")
        slug = "all"
    else:
        pages = [_get_page(project, scope)]
        slug = scope

    entries = [{"section_title": project["name"], "page_title": p["title"],
                "content": p["content"]} for p in pages]
    filename = f"team-docs-{project_id.lower()}-{slug}.{format}"

    if format == "txt":
        payload = export_txt(project["name"], entries)
        media_type = "text/plain; charset=utf-8"
    else:
        payload = export_pdf(project["name"], entries)
        media_type = "application/pdf"

    return StreamingResponse(
        iter([payload]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
