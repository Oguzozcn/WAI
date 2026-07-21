"""
Developer Documentation routes
================================
Serves, edits, and exports the markdown documentation under docs/.

Structure is defined by docs/manifest.json (sections -> pages); content is one
markdown file per page. Section/page ids arriving over the API are only ever
*looked up* in the manifest — file paths always come from the manifest itself,
so the ids cannot be used for path traversal.

Role gating mirrors the dev-console pattern: reads are open, the save endpoint
requires a client-supplied role == "developer" (client-trusted, matching the
app's trust model everywhere else).
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.core.doc_export import export_pdf, export_txt

router = APIRouter(prefix="/api/docs", tags=["docs"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _docs_dir() -> Path:
    """Resolved per-call (not at import) so tests can redirect docs I/O into a
    temp directory via WAI_DOCS_DIR — same contract as WAI_DATA_DIR for data/."""
    override = os.environ.get("WAI_DOCS_DIR")
    return Path(override) if override else PROJECT_ROOT / "docs"


class DocSaveRequest(BaseModel):
    content: str
    role: str = ""


def _require_developer(role: str) -> None:
    if role != "developer":
        raise HTTPException(status_code=403, detail="Only a developer can edit documentation.")


def _load_manifest() -> dict:
    manifest_path = _docs_dir() / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=500, detail="docs/manifest.json is missing.")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _find_page(manifest: dict, section_id: str, page_id: str) -> tuple[dict, dict]:
    for section in manifest.get("sections", []):
        if section.get("id") != section_id:
            continue
        for page in section.get("pages", []):
            if page.get("id") == page_id:
                return section, page
    raise HTTPException(status_code=404, detail=f"Unknown documentation page '{section_id}/{page_id}'.")


def _page_file(page: dict) -> Path:
    return _docs_dir() / page["file"]


def _updated_at(filepath: Path) -> str:
    if not filepath.exists():
        return ""
    return datetime.fromtimestamp(filepath.stat().st_mtime, tz=timezone.utc).isoformat()


@router.get("/tree")
async def api_docs_tree():
    manifest = _load_manifest()
    for section in manifest.get("sections", []):
        for page in section.get("pages", []):
            page["updated_at"] = _updated_at(_page_file(page))
    return manifest


@router.get("/page/{section_id}/{page_id}")
async def api_docs_page(section_id: str, page_id: str):
    manifest = _load_manifest()
    section, page = _find_page(manifest, section_id, page_id)
    filepath = _page_file(page)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Documentation file '{page['file']}' not found on disk.")
    return {
        "section_id": section["id"],
        "section_title": section["title"],
        "page_id": page["id"],
        "title": page["title"],
        "content": filepath.read_text(encoding="utf-8"),
        "updated_at": _updated_at(filepath),
    }


@router.put("/page/{section_id}/{page_id}")
async def api_docs_save_page(section_id: str, page_id: str, body: DocSaveRequest):
    _require_developer(body.role)
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Documentation content cannot be empty.")
    manifest = _load_manifest()
    _, page = _find_page(manifest, section_id, page_id)
    filepath = _page_file(page)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(body.content, encoding="utf-8")
    return {"status": "saved", "page_id": page_id, "updated_at": _updated_at(filepath)}


# ── Export (TXT / PDF) ──────────────────────────────────────────────────────

def _collect_export_pages(manifest: dict, scope: str) -> tuple[str, list[dict]]:
    """Resolve an export scope to a slug (for the filename) and a list of
    {section_title, page_title, content} entries in manifest order."""
    if scope == "all":
        entries = []
        for section in manifest.get("sections", []):
            for page in section.get("pages", []):
                filepath = _page_file(page)
                if not filepath.exists():
                    continue
                entries.append({
                    "section_title": section["title"],
                    "page_title": page["title"],
                    "content": filepath.read_text(encoding="utf-8"),
                })
        if not entries:
            raise HTTPException(status_code=404, detail="No documentation pages found to export.")
        return "all", entries

    if "/" not in scope:
        raise HTTPException(status_code=400, detail="scope must be 'all' or '<section>/<page>'.")
    section_id, page_id = scope.split("/", 1)
    section, page = _find_page(manifest, section_id, page_id)
    filepath = _page_file(page)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Documentation file '{page['file']}' not found on disk.")
    entry = {
        "section_title": section["title"],
        "page_title": page["title"],
        "content": filepath.read_text(encoding="utf-8"),
    }
    return f"{section_id}-{page_id}", [entry]


@router.get("/export")
async def api_docs_export(format: str = "txt", scope: str = "all"):
    if format not in ("txt", "pdf"):
        raise HTTPException(status_code=400, detail="format must be 'txt' or 'pdf'.")
    manifest = _load_manifest()
    doc_title = manifest.get("title", "WisdomAI Documentation")
    slug, entries = _collect_export_pages(manifest, scope)
    filename = f"wisdomai-docs-{slug}.{format}"

    if format == "txt":
        payload = export_txt(doc_title, entries)
        media_type = "text/plain; charset=utf-8"
    else:
        payload = export_pdf(doc_title, entries)
        media_type = "application/pdf"

    return StreamingResponse(
        iter([payload]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
