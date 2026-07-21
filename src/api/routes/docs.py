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


def _export_txt(title: str, entries: list[dict]) -> bytes:
    parts = []
    if len(entries) > 1:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        parts.append(f"{title}\nExported {stamp}\n{'=' * 72}\n")
    current_section = None
    for entry in entries:
        if len(entries) > 1 and entry["section_title"] != current_section:
            current_section = entry["section_title"]
            parts.append(f"\n{'=' * 72}\n  {current_section.upper()}\n{'=' * 72}\n")
        parts.append(entry["content"].rstrip() + "\n")
        if len(entries) > 1:
            parts.append("\n" + "-" * 72 + "\n")
    return "\n".join(parts).encode("utf-8")


# fpdf2's built-in core fonts are latin-1 only; the docs use a handful of
# wider-unicode characters (arrows, box drawing, math). Map them to ASCII
# rather than shipping/embedding a TTF just for an export convenience.
_LATIN1_REPLACEMENTS = {
    "—": "--", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
    "→": "->", "←": "<-", "▼": "v", "▲": "^", "•": "-",
    "≥": ">=", "≤": "<=", "×": "x", "Δ": "delta", "θ": "theta", "≈": "~",
    "─": "-", "━": "-", "│": "|", "┃": "|", "┌": "+", "┐": "+", "└": "+",
    "┘": "+", "├": "+", "┤": "+", "┬": "+", "┴": "+", "┼": "+",
    "…": "...", "✅": "[done]", "🚧": "[wip]", "📋": "[plan]", "💡": "[idea]", "🗑": "[old]",
}


def _latin1_safe(text: str) -> str:
    for src, dst in _LATIN1_REPLACEMENTS.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", "replace").decode("latin-1")


def _strip_inline_markup(text: str) -> str:
    """Drop markdown inline markers for PDF body text (rendered unstyled)."""
    import re
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text


def _export_pdf(title: str, entries: list[dict]) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(16, 16, 16)
    body_w = pdf.w - pdf.l_margin - pdf.r_margin

    def text_line(line: str, family="Helvetica", style="", size=10.0, indent=0.0, fill=False):
        # fpdf2 accepts str styles and float sizes at runtime; its stubs disagree.
        pdf.set_font(family, style, size)  # pyright: ignore[reportArgumentType]
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(body_w - indent, size * 0.52, _latin1_safe(line), fill=fill)

    def cover_line(line: str, style="", size=10.0, indent=0.0, color=(0, 0, 0)):
        # multi_cell leaves the cursor at the cell's right edge, so every
        # line must reposition X explicitly or it drifts to the margin.
        pdf.set_font("Helvetica", style, size)  # pyright: ignore[reportArgumentType]
        pdf.set_text_color(*color)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(body_w - indent, size * 0.58, _latin1_safe(line))
        pdf.set_text_color(0, 0, 0)

    if len(entries) > 1:
        # Cover page with a table of contents
        pdf.add_page()
        pdf.ln(30)
        cover_line(title, style="B", size=22)
        cover_line(datetime.now(timezone.utc).strftime("Exported %Y-%m-%d %H:%M UTC"), color=(110, 110, 110))
        pdf.ln(8)
        cover_line("Contents", style="B", size=12)
        pdf.ln(1)
        current_section = None
        for entry in entries:
            if entry["section_title"] != current_section:
                current_section = entry["section_title"]
                pdf.ln(1.5)
                cover_line(current_section, style="B", size=10)
            cover_line(entry["page_title"], indent=6, size=10)

    for entry in entries:
        pdf.add_page()
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(110, 110, 110)
        pdf.multi_cell(body_w, 5, _latin1_safe(f"{title}  /  {entry['section_title']}"))
        pdf.set_text_color(0, 0, 0)
        pdf.ln(2)

        in_code = False
        for raw_line in entry["content"].splitlines():
            line = raw_line.rstrip()
            if line.strip().startswith("```"):
                in_code = not in_code
                if in_code:
                    pdf.ln(1)
                    pdf.set_fill_color(243, 244, 246)
                else:
                    pdf.ln(1)
                continue
            if in_code:
                text_line(line if line else " ", family="Courier", size=8.0, indent=2, fill=True)
                continue
            if not line:
                pdf.ln(2.5)
                continue
            if line.startswith("# "):
                pdf.ln(1)
                text_line(line[2:], style="B", size=19)
                pdf.ln(1.5)
            elif line.startswith("## "):
                pdf.ln(2)
                text_line(line[3:], style="B", size=14)
                pdf.ln(0.5)
            elif line.startswith("### "):
                pdf.ln(1.5)
                text_line(line[4:], style="B", size=11.5)
            elif line.startswith("#### "):
                pdf.ln(1)
                text_line(line[5:], style="B", size=10.5)
            elif line.strip() in ("---", "***", "___"):
                pdf.ln(2)
                y = pdf.get_y()
                pdf.set_draw_color(200, 200, 200)
                pdf.line(pdf.l_margin, y, pdf.l_margin + body_w, y)
                pdf.ln(2)
            elif line.lstrip().startswith("|"):
                # Table row: keep monospace so columns roughly align.
                text_line(_strip_inline_markup(line.strip()), family="Courier", size=7.5)
            elif line.lstrip().startswith(("- ", "* ")):
                stripped = line.lstrip()
                indent = (len(line) - len(stripped)) * 1.2 + 2
                text_line("-  " + _strip_inline_markup(stripped[2:]), indent=indent)
            elif line.lstrip().startswith("> "):
                pdf.set_text_color(90, 90, 90)
                text_line(_strip_inline_markup(line.lstrip()[2:]), style="I", indent=4)
                pdf.set_text_color(0, 0, 0)
            else:
                text_line(_strip_inline_markup(line))

    return bytes(pdf.output())


@router.get("/export")
async def api_docs_export(format: str = "txt", scope: str = "all"):
    if format not in ("txt", "pdf"):
        raise HTTPException(status_code=400, detail="format must be 'txt' or 'pdf'.")
    manifest = _load_manifest()
    doc_title = manifest.get("title", "WisdomAI Documentation")
    slug, entries = _collect_export_pages(manifest, scope)
    filename = f"wisdomai-docs-{slug}.{format}"

    if format == "txt":
        payload = _export_txt(doc_title, entries)
        media_type = "text/plain; charset=utf-8"
    else:
        payload = _export_pdf(doc_title, entries)
        media_type = "application/pdf"

    return StreamingResponse(
        iter([payload]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
