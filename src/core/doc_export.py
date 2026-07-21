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
