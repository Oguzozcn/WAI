"""
Shared documentation export (TXT / PDF)
=======================================
Renders a list of markdown pages into a downloadable plain-text bundle or a
PDF. Used by both the developer documentation (/api/docs/export) and the
team documentation projects (/api/team-docs/.../export).

Entries are dicts of {"section_title", "page_title", "content"} in the order
they should appear; a single-entry list produces a bare page (no cover/TOC).
"""

import re
from datetime import datetime, timezone
from typing import Optional


def export_txt(title: str, entries: list[dict]) -> bytes:
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
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text


def _parse_table_block(block: list[str]) -> tuple[Optional[list[str]], list[list[str]]]:
    """Split a contiguous run of '|...|' markdown lines into a header row
    (if the second line is a '---|---' separator) and the remaining body rows."""

    def split_row(raw: str) -> list[str]:
        s = raw.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        return [c.strip() for c in s.split("|")]

    rows = [split_row(r) for r in block if r.strip()]
    if len(rows) >= 2 and all(re.fullmatch(r":?-{1,}:?", c) for c in rows[1]):
        return rows[0], rows[2:]
    return None, rows


def export_pdf(title: str, entries: list[dict]) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(16, 16, 16)
    body_w = pdf.w - pdf.l_margin - pdf.r_margin

    def text_line(line: str, family="Helvetica", style="", size=10.0, indent=0.0, fill=False):
        # fpdf2 accepts str styles and float sizes at runtime; its stubs disagree.
        pdf.set_font(family, style, size)  # pyright: ignore[reportArgumentType]
        pdf.set_x(pdf.l_margin + indent)
        # align="L": multi_cell defaults to justify, which stretches word
        # spacing on every wrapped line except the last -- reads as broken
        # formatting for ordinary prose.
        pdf.multi_cell(body_w - indent, size * 0.52, _latin1_safe(line), fill=fill, align="L")

    def cover_line(line: str, style="", size=10.0, indent=0.0, color=(0, 0, 0)):
        # multi_cell leaves the cursor at the cell's right edge, so every
        # line must reposition X explicitly or it drifts to the margin.
        pdf.set_font("Helvetica", style, size)  # pyright: ignore[reportArgumentType]
        pdf.set_text_color(*color)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(body_w - indent, size * 0.58, _latin1_safe(line), align="L")
        pdf.set_text_color(0, 0, 0)

    def render_table(block: list[str]):
        header, rows = _parse_table_block(block)
        ncols = len(header) if header else max((len(r) for r in rows), default=0)
        if ncols == 0:
            return
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "", 8.5)  # pyright: ignore[reportArgumentType]
        with pdf.table(  # pyright: ignore[reportArgumentType]
            col_widths=[body_w / ncols] * ncols,
            text_align="LEFT",
            first_row_as_headings=bool(header),
            line_height=5.2,
            borders_layout="ALL",
            padding=1.5,
        ) as table:
            if header:
                row = table.row()
                for c in header:
                    row.cell(_latin1_safe(_strip_inline_markup(c)))
            for r in rows:
                cells = (r + [""] * ncols)[:ncols]
                row = table.row()
                for c in cells:
                    row.cell(_latin1_safe(_strip_inline_markup(c)))
        pdf.ln(2)

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
        lines = entry["content"].splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].rstrip()
            if line.strip().startswith("```"):
                in_code = not in_code
                if in_code:
                    pdf.ln(1)
                    pdf.set_fill_color(243, 244, 246)
                else:
                    pdf.ln(1)
                i += 1
                continue
            if in_code:
                text_line(line if line else " ", family="Courier", size=8.0, indent=2, fill=True)
                i += 1
                continue
            if not line:
                pdf.ln(2.5)
                i += 1
                continue
            if line.lstrip().startswith("|"):
                # A markdown table is a contiguous run of '|...|' lines --
                # collect the whole block and render it as one real table
                # rather than one raw pipe-delimited line at a time.
                block = []
                while i < len(lines) and lines[i].rstrip().lstrip().startswith("|"):
                    block.append(lines[i].rstrip())
                    i += 1
                render_table(block)
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
            i += 1

    return bytes(pdf.output())
