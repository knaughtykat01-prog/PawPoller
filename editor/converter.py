"""Core markdown-to-format conversion library for the story editor.

This is the SINGLE implementation of the markdown italic/bold parser,
shared by the editor live-preview, the regeneration pipeline, and
(eventually) the standalone CLI converter scripts.

Supports:
  - `*italic*`  → toggles italic state
  - `**bold**`  → toggles bold state
  - `***both***`→ toggles both states
  - Mixed: `*narration* "dialogue" *narration*` → alternating italic/roman
  - Nested: `*outer *inner* outer*` → italic, roman, italic, roman
  - Text messages: `**SENDER: msg**` → bold header
  - POV markers: `**⟨ Name ⟩**` → bold
  - Chapter headings: `# Chapter N: Title`
  - Section breaks: `---`
  - End marker: `*End of ...*` → `~ End ~`
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Core parser — handles *, **, *** correctly
# ---------------------------------------------------------------------------

def parse_markdown_formatting(line: str) -> list[tuple[str, bool, bool]]:
    """Parse a markdown line for `*` (italic) and `**` (bold) markers.

    Scans left-to-right, toggling italic/bold state at each marker.
    Returns list of (text, is_italic, is_bold) tuples.
    """
    segments: list[tuple[str, bool, bool]] = []
    current: list[str] = []
    in_italic = False
    in_bold = False
    i = 0
    while i < len(line):
        if line[i] == "*":
            j = i
            while j < len(line) and line[j] == "*":
                j += 1
            n_stars = j - i
            if current:
                segments.append(("".join(current), in_italic, in_bold))
                current = []
            if n_stars >= 3:
                in_italic = not in_italic
                in_bold = not in_bold
            elif n_stars == 2:
                in_bold = not in_bold
            else:
                in_italic = not in_italic
            i = j
        else:
            current.append(line[i])
            i += 1
    if current:
        segments.append(("".join(current), in_italic, in_bold))
    return segments


# ---------------------------------------------------------------------------
# HTML rendering (SoFurry / AO3 / SquidgeWorld body)
# ---------------------------------------------------------------------------

def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_html(segments: list[tuple[str, bool, bool]]) -> str:
    """Render parsed segments as HTML with <em> and <strong> tags."""
    parts: list[str] = []
    for text, italic, bold in segments:
        if not text:
            continue
        escaped = _escape_html(text)
        if italic and bold:
            parts.append(f"<em><strong>{escaped}</strong></em>")
        elif italic:
            parts.append(f"<em>{escaped}</em>")
        elif bold:
            parts.append(f"<strong>{escaped}</strong>")
        else:
            parts.append(escaped)
    return "".join(parts)


def format_paragraph_html(line: str) -> str:
    """Convert a markdown paragraph to HTML."""
    return render_html(parse_markdown_formatting(line))


# ---------------------------------------------------------------------------
# BBCode rendering (Inkbunny)
# ---------------------------------------------------------------------------

def render_bbcode(segments: list[tuple[str, bool, bool]]) -> str:
    """Render parsed segments as BBCode with [i] and [b] tags."""
    parts: list[str] = []
    for text, italic, bold in segments:
        if not text:
            continue
        if italic and bold:
            parts.append(f"[i][b]{text}[/b][/i]")
        elif italic:
            parts.append(f"[i]{text}[/i]")
        elif bold:
            parts.append(f"[b]{text}[/b]")
        else:
            parts.append(text)
    return "".join(parts)


def format_paragraph_bbcode(line: str) -> str:
    """Convert a markdown paragraph to BBCode."""
    return render_bbcode(parse_markdown_formatting(line))


# ---------------------------------------------------------------------------
# Structural detection helpers
# ---------------------------------------------------------------------------

def is_pov_marker(stripped: str) -> bool:
    """Detect POV markers: **⟨ Name ⟩** on own line."""
    if stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 4:
        inner = stripped[2:-2]
        if "⟨" in inner and "⟩" in inner:
            return True
    return False


def is_text_message(stripped: str) -> re.Match | None:
    """Detect text messages: **SENDER: message text** on own line."""
    return re.match(r"^\*\*([A-Z][A-Z\s❤♥]*?):\s*(.+?)\*\*$", stripped)


def is_phone_display(stripped: str) -> re.Match | None:
    """Detect phone call display: **NAME ❤** on own line."""
    return re.match(r"^\*\*([A-Z][A-Z\s]*[❤♥])\*\*$", stripped)


def detect_chapters(text: str) -> list[dict]:
    """Parse chapter headings from markdown text.

    Returns list of {index, title, line_start, line_end} dicts.
    """
    lines = text.split("\n")
    chapters: list[dict] = []
    for i, line in enumerate(lines):
        m = re.match(r"^#\s+(.+)$", line.strip())
        if m:
            title = m.group(1)
            # Close previous chapter
            if chapters:
                chapters[-1]["line_end"] = i - 1
            chapters.append({
                "index": len(chapters),
                "title": title,
                "line_start": i,
                "line_end": len(lines) - 1,
            })
    return chapters


# ---------------------------------------------------------------------------
# Full document conversion — markdown text → output format
# ---------------------------------------------------------------------------

@dataclass
class ConversionResult:
    """Result of a full markdown-to-format conversion."""
    output: str
    format: str
    stats: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class FrontMatter:
    """Structured front matter extracted from anchored MASTER.md.

    Anchors are HTML comments that mark structural sections:
      <!-- @title -->      → title heading
      <!-- @subtitle -->   → subtitle/tagline (optional)
      <!-- @byline -->     → author attribution (optional)
      <!-- @warning -->    → content warning block
      <!-- @disclaimer --> → disclaimer block
      <!-- @body -->       → boundary where story content begins
    """
    title: str = ""
    subtitle: str | None = None
    byline: str | None = None
    warning: str = ""
    disclaimer: str = ""
    body_start_line: int = 0  # line index where @body begins


def parse_front_matter(text: str) -> FrontMatter | None:
    """Parse anchored front matter from MASTER.md.

    Looks for `<!-- @body -->` as the primary indicator that the file
    uses the anchor system. If absent, returns None (caller should
    fall back to heuristic parsing).

    Extracts text between each anchor pair. Content after each anchor
    runs until the next anchor or end of front matter.
    """
    lines = text.split("\n")

    # Quick check: does this file use anchors?
    body_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "<!-- @body -->":
            body_idx = i
            break
    if body_idx is None:
        return None  # no anchors, use heuristic fallback

    fm = FrontMatter(body_start_line=body_idx)

    # Parse front matter (everything before @body)
    current_section: str | None = None
    section_lines: dict[str, list[str]] = {}

    for i in range(body_idx):
        stripped = lines[i].strip()

        # Check for anchor markers
        anchor_m = re.match(r"^<!--\s*@(\w+)\s*-->$", stripped)
        if anchor_m:
            current_section = anchor_m.group(1)
            section_lines.setdefault(current_section, [])
            continue

        # Accumulate non-blank lines into the current section
        if current_section and stripped:
            section_lines[current_section].append(stripped)

    # Extract structured fields from raw section lines
    if "title" in section_lines:
        raw = " ".join(section_lines["title"])
        # Strip the leading # from the heading
        fm.title = re.sub(r"^#+\s*", "", raw).strip()

    if "subtitle" in section_lines:
        raw = " ".join(section_lines["subtitle"])
        # Strip italic markers
        fm.subtitle = raw.strip("* ").strip()

    if "byline" in section_lines:
        raw = " ".join(section_lines["byline"])
        fm.byline = raw.strip("* ").strip()

    if "warning" in section_lines:
        raw = "\n".join(section_lines["warning"])
        # Strip the **Content Warning**: prefix to get just the warning text
        raw = re.sub(r"^\*\*Content Warning\*?\*?:?\s*", "", raw, flags=re.IGNORECASE).strip()
        fm.warning = raw

    if "disclaimer" in section_lines:
        raw_lines = section_lines["disclaimer"]
        # Filter out the **DISCLAIMER** heading itself
        body_lines = [l for l in raw_lines if l.strip() != "**DISCLAIMER**"]
        fm.disclaimer = "\n".join(body_lines).strip()

    return fm


def render_front_matter_clean_html(fm: FrontMatter) -> list[str]:
    """Render FrontMatter as centred Clean HTML (AO3) paragraphs."""
    parts: list[str] = []
    c = lambda inner: f'<p style="text-align:center">{inner}</p>'

    parts.append(c(f"<strong>{_escape_html(fm.title)}</strong>"))
    if fm.subtitle:
        parts.append(c(f"<em>{_escape_html(fm.subtitle)}</em>"))
    if fm.byline:
        parts.append(c(f"<em>{_escape_html(fm.byline)}</em>"))
    parts.append(c(f"<strong>Content Warning</strong>: {_escape_html(fm.warning)}"))
    parts.append(c("<strong>DISCLAIMER</strong>"))
    parts.append(c(_escape_html(fm.disclaimer)))
    return parts


def render_front_matter_sofurry(fm: FrontMatter) -> list[str]:
    """Render FrontMatter as SoFurry HTML using SF's tag system."""
    parts: list[str] = []
    tc = lambda inner: f'<p class="text-center">{inner}</p>'

    parts.append(f'<h2 class="text-center">{_escape_html(fm.title)}</h2>')
    if fm.subtitle:
        parts.append(tc(f"<em>{_escape_html(fm.subtitle)}</em>"))
    if fm.byline:
        parts.append(tc(f"<em>{_escape_html(fm.byline)}</em>"))
    parts.append(tc(f"<strong>Content Warning</strong>: {_escape_html(fm.warning)}"))
    parts.append(tc("<strong>DISCLAIMER</strong>"))
    parts.append(tc(_escape_html(fm.disclaimer)))
    return parts


def render_front_matter_bbcode(fm: FrontMatter) -> list[str]:
    """Render FrontMatter as BBCode."""
    parts: list[str] = []

    parts.append(f"[center][t]{fm.title}[/t][/center]")
    if fm.subtitle:
        parts.extend(["", f"[center][i]{fm.subtitle}[/i][/center]"])
    if fm.byline:
        parts.extend(["", f"[center][i]{fm.byline}[/i][/center]"])
    parts.extend(["", f"[center][b]Content Warning[/b]: {fm.warning}[/center]"])
    parts.extend(["", f"[center][b]DISCLAIMER[/b][/center]"])
    parts.extend(["", f"[center]{fm.disclaimer}[/center]"])
    return parts


def render_front_matter_sqw(fm: FrontMatter, chapter_title: str,
                            warning_icon: str = "&#9888;") -> list[str]:
    """Render FrontMatter as SquidgeWorld warning-page div."""
    parts: list[str] = []
    parts.append('<div class="warning-page">')
    parts.append(f'    <h1 class="story-title">{_escape_html(fm.title)}</h1>')
    parts.append(f'    <p class="byline">by {_escape_html(fm.byline or "KnaughtyKat")}</p>')
    parts.append('    <hr class="title-rule">')
    parts.append(f'    <h2 class="chapter-subtitle">{_escape_html(chapter_title)}</h2>')
    parts.append("")
    parts.append(f'    <p class="warning-heading">{warning_icon} CONTENT WARNING {warning_icon}</p>')
    parts.append("")
    parts.append(f'    <p class="warning-body">{_escape_html(fm.warning)}</p>')
    parts.append("")
    parts.append('    <hr class="warning-divider">')
    parts.append("")
    parts.append('    <p class="disclaimer-heading">DISCLAIMER</p>')
    parts.append("")
    parts.append(f'    <p class="disclaimer-body">{_escape_html(fm.disclaimer)}</p>')
    parts.append('</div>')
    return parts


def _is_warning_line(stripped: str) -> bool:
    """Detect content-warning/disclaimer lines from MASTER.md front matter."""
    return (
        stripped.startswith("**Content Warning**")
        or stripped.startswith("**Content Warning:**")
        or stripped.startswith("**Content Warning:")
        or stripped == "**DISCLAIMER**"
        or stripped.startswith("**DISCLAIMER**")
    )


def _center_html(inner: str) -> str:
    """Wrap HTML content in a centred paragraph."""
    return f'<p style="text-align:center">{inner}</p>'


def _convert_body_clean_html(lines: list[str], start: int = 0) -> tuple[list[str], dict]:
    """Convert body content (after front matter) to Clean HTML.

    Handles chapter headings, section breaks, POV markers, text messages,
    paragraphs — everything INSIDE the story. Front matter is handled
    separately by render_front_matter_clean_html().
    """
    body_parts: list[str] = []
    stats: dict = {
        "chapters": [], "section_breaks": 0, "paragraphs": 0,
        "pov_markers": [], "text_messages": 0, "end_marker": False,
    }
    i = start
    current_paragraph: list[str] = []

    def flush():
        if current_paragraph:
            text = " ".join(current_paragraph)
            converted = format_paragraph_html(text)
            body_parts.append(f"<p>{converted}</p>")
            stats["paragraphs"] += 1
            current_paragraph.clear()

    while i < len(lines):
        stripped = lines[i].strip()

        # Skip anchor comments in body
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            i += 1
            continue

        if stripped == "---":
            flush()
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and lines[j].strip().startswith("# "):
                body_parts.append("<hr />")
            else:
                body_parts.append('<p style="text-align:center" class="section-break">* * *</p>')
                stats["section_breaks"] += 1
            i += 1
            continue

        if stripped.startswith("# "):
            flush()
            heading = _escape_html(stripped[2:].strip())
            body_parts.append(_center_html(f"<strong>{heading}</strong>"))
            stats["chapters"].append(heading)
            i += 1
            continue

        if re.match(r"^\*End of .+\*$", stripped):
            flush()
            body_parts.append(_center_html("<strong>~ End ~</strong>"))
            stats["end_marker"] = True
            i += 1
            continue

        if is_pov_marker(stripped):
            flush()
            inner = stripped[2:-2]
            body_parts.append(_center_html(f"<strong>{_escape_html(inner)}</strong>"))
            stats["pov_markers"].append(inner)
            i += 1
            continue

        phone_m = is_phone_display(stripped)
        if phone_m:
            flush()
            caller = phone_m.group(1).strip()
            body_parts.append(_center_html(f"<strong>{_escape_html(caller)}</strong>"))
            stats["text_messages"] += 1
            i += 1
            continue

        msg_m = is_text_message(stripped)
        if msg_m:
            flush()
            sender = msg_m.group(1).strip()
            message = msg_m.group(2).strip()
            body_parts.append(
                f"<p><strong>{_escape_html(sender)}:</strong> {_escape_html(message)}</p>"
            )
            stats["text_messages"] += 1
            i += 1
            continue

        if stripped == "":
            flush()
            i += 1
            continue

        current_paragraph.append(stripped)
        i += 1

    flush()
    return body_parts, stats


def convert_to_clean_html(markdown_text: str) -> ConversionResult:
    """Convert full MASTER.md text to body-only Clean HTML (AO3/SQW).

    If the file has anchors (<!-- @body -->), uses structured front matter
    parsing. Otherwise falls back to heuristic parsing.
    """
    lines = markdown_text.split("\n")

    # Try anchor-based parsing first
    fm = parse_front_matter(markdown_text)
    if fm is not None:
        # Render front matter
        front_parts = render_front_matter_clean_html(fm)
        # Render body (everything after @body)
        body_parts, body_stats = _convert_body_clean_html(lines, fm.body_start_line + 1)
        # Combine
        all_parts = front_parts + body_parts
        stats = {
            "title": fm.title, "subtitle": fm.subtitle,
            **body_stats,
        }
        output = "\n".join(all_parts)
        return ConversionResult(output=output, format="clean_html", stats=stats)

    # --- HEURISTIC FALLBACK (for non-anchored files) ---
    body_parts: list[str] = []
    stats = {
        "title": None, "subtitle": None, "chapters": [],
        "section_breaks": 0, "paragraphs": 0,
        "pov_markers": [], "text_messages": 0, "end_marker": False,
    }
    warnings: list[str] = []

    title_seen = False
    subtitle_done = False
    in_warning_block = False
    i = 0
    current_paragraph: list[str] = []

    def flush():
        if current_paragraph:
            text = " ".join(current_paragraph)
            converted = format_paragraph_html(text)
            if in_warning_block:
                body_parts.append(_center_html(converted))
            else:
                body_parts.append(f"<p>{converted}</p>")
            stats["paragraphs"] += 1
            current_paragraph.clear()

    while i < len(lines):
        stripped = lines[i].strip()

        if stripped == "---":
            flush()
            in_warning_block = False
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and lines[j].strip().startswith("# "):
                body_parts.append("<hr />")
            else:
                body_parts.append('<p style="text-align:center" class="section-break">* * *</p>')
                stats["section_breaks"] += 1
            i += 1
            continue

        if stripped.startswith("# "):
            flush()
            in_warning_block = False
            heading = _escape_html(stripped[2:].strip())
            body_parts.append(_center_html(f"<strong>{heading}</strong>"))
            if not title_seen:
                title_seen = True
                stats["title"] = heading
            else:
                stats["chapters"].append(heading)
                subtitle_done = True
            i += 1
            continue

        if title_seen and not subtitle_done:
            if stripped == "":
                flush()
                i += 1
                continue
            if re.match(r"^\*[^*]+\*$", stripped):
                inner = stripped[1:-1]
                if not inner.startswith("End of "):
                    if True:
                        flush()
                        body_parts.append(_center_html(f"<em>{_escape_html(inner)}</em>"))
                        subtitle_done = True
                        stats["subtitle"] = inner
                        i += 1
                        continue
                    else:
                        subtitle_done = True
            else:
                subtitle_done = True

        if _is_warning_line(stripped):
            flush()
            in_warning_block = True
            converted = format_paragraph_html(stripped)
            body_parts.append(_center_html(converted))
            stats["paragraphs"] += 1
            i += 1
            continue

        if re.match(r"^\*End of .+\*$", stripped):
            flush()
            body_parts.append(_center_html("<strong>~ End ~</strong>"))
            stats["end_marker"] = True
            i += 1
            continue

        if is_pov_marker(stripped):
            flush()
            inner = stripped[2:-2]
            body_parts.append(_center_html(f"<strong>{_escape_html(inner)}</strong>"))
            stats["pov_markers"].append(inner)
            i += 1
            continue

        phone_m = is_phone_display(stripped)
        if phone_m:
            flush()
            caller = phone_m.group(1).strip()
            body_parts.append(_center_html(f"<strong>{_escape_html(caller)}</strong>"))
            stats["text_messages"] += 1
            i += 1
            continue

        msg_m = is_text_message(stripped)
        if msg_m:
            flush()
            sender = msg_m.group(1).strip()
            message = msg_m.group(2).strip()
            body_parts.append(
                f"<p><strong>{_escape_html(sender)}:</strong> {_escape_html(message)}</p>"
            )
            stats["text_messages"] += 1
            i += 1
            continue

        if stripped == "":
            flush()
            i += 1
            continue

        current_paragraph.append(stripped)
        i += 1

    flush()

    output = "\n".join(body_parts)
    return ConversionResult(output=output, format="clean_html", stats=stats, warnings=warnings)


def _convert_body_sofurry(lines: list[str], start: int = 0) -> tuple[list[str], dict]:
    """Convert body content to SoFurry HTML (after front matter)."""
    body_parts: list[str] = []
    stats: dict = {
        "chapters": [], "section_breaks": 0, "paragraphs": 0,
        "pov_markers": [], "text_messages": 0, "end_marker": False,
    }
    tc = lambda inner: f'<p class="text-center">{inner}</p>'
    i = start
    current_paragraph: list[str] = []

    def flush():
        if current_paragraph:
            text = " ".join(current_paragraph)
            body_parts.append(f"<p>{format_paragraph_html(text)}</p>")
            stats["paragraphs"] += 1
            current_paragraph.clear()

    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            i += 1
            continue
        if stripped == "---":
            flush()
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and lines[j].strip().startswith("# "):
                body_parts.append("<hr />")
            else:
                body_parts.append(tc("* * *"))
                stats["section_breaks"] += 1
            i += 1
            continue
        if stripped.startswith("# "):
            flush()
            heading = _escape_html(stripped[2:].strip())
            body_parts.append(f'<h3 class="text-center">{heading}</h3>')
            stats["chapters"].append(heading)
            i += 1
            continue
        if re.match(r"^\*End of .+\*$", stripped):
            flush()
            body_parts.append(tc("<strong>~ End ~</strong>"))
            stats["end_marker"] = True
            i += 1
            continue
        if is_pov_marker(stripped):
            flush()
            inner = stripped[2:-2]
            body_parts.append(tc(f"<strong>{_escape_html(inner)}</strong>"))
            stats["pov_markers"].append(inner)
            i += 1
            continue
        phone_m = is_phone_display(stripped)
        if phone_m:
            flush()
            body_parts.append(tc(f"<strong>{_escape_html(phone_m.group(1).strip())}</strong>"))
            stats["text_messages"] += 1
            i += 1
            continue
        msg_m = is_text_message(stripped)
        if msg_m:
            flush()
            sender, message = msg_m.group(1).strip(), msg_m.group(2).strip()
            is_sent = "MAYA" in sender.upper()
            align = "text-right" if is_sent else "text-left"
            body_parts.append(f'<p class="{align}"><strong>{_escape_html(sender)}:</strong> {_escape_html(message)}</p>')
            stats["text_messages"] += 1
            i += 1
            continue
        if stripped == "":
            flush()
            i += 1
            continue
        current_paragraph.append(stripped)
        i += 1
    flush()
    return body_parts, stats


def _convert_body_bbcode(lines: list[str], start: int = 0) -> tuple[list[str], dict]:
    """Convert body content to BBCode (after front matter)."""
    output_lines: list[str] = []
    stats: dict = {
        "chapters": [], "section_breaks": 0, "paragraphs": 0,
        "pov_markers": [], "text_messages": 0, "end_marker": False,
    }
    i = start

    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            i += 1
            continue
        if stripped == "---":
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and lines[j].strip().startswith("# "):
                output_lines.extend(["", "[center]───────────────────[/center]", ""])
            elif j < len(lines) and re.match(r"^\*End of .+\*$", lines[j].strip()):
                output_lines.extend(["", "[center]───────────────────[/center]", ""])
            else:
                output_lines.extend(["", "[center]* * *[/center]", ""])
                stats["section_breaks"] += 1
            i += 1
            continue
        if stripped.startswith("# "):
            heading = stripped[2:].strip()
            output_lines.extend(["", f"[center][b]{heading}[/b][/center]"])
            stats["chapters"].append(heading)
            i += 1
            continue
        if re.match(r"^\*End of .+\*$", stripped):
            output_lines.extend(["", "[center][b]~ End ~[/b][/center]"])
            stats["end_marker"] = True
            i += 1
            continue
        if is_pov_marker(stripped):
            inner = stripped[2:-2]
            output_lines.extend(["", f"[center][b]{inner}[/b][/center]", ""])
            stats["pov_markers"].append(inner)
            i += 1
            continue
        phone_m = is_phone_display(stripped)
        if phone_m:
            output_lines.extend(["", f"[center]───── [color=#4a9eff]📱 {phone_m.group(1).strip()}[/color] ─────[/center]", ""])
            stats["text_messages"] += 1
            i += 1
            continue
        msg_m = is_text_message(stripped)
        if msg_m:
            sender, message = msg_m.group(1).strip(), msg_m.group(2).strip()
            is_sent = "MAYA" in sender.upper()
            color = "#4a9eff" if is_sent else "#aab0bc"
            align = "right" if is_sent else "left"
            output_lines.append(f"[{align}][color={color}][b]{sender}[/b]: {message}[/color][/{align}]")
            stats["text_messages"] += 1
            i += 1
            continue
        if stripped == "":
            output_lines.append("")
            i += 1
            continue
        output_lines.append(format_paragraph_bbcode(stripped))
        stats["paragraphs"] += 1
        i += 1
    return output_lines, stats


def convert_to_sofurry_html(markdown_text: str) -> ConversionResult:
    """Convert full MASTER.md text to SoFurry-specific HTML.

    If the file has anchors, uses structured parsing.
    Otherwise falls back to heuristic parsing.
    """
    lines = markdown_text.split("\n")

    fm = parse_front_matter(markdown_text)
    if fm is not None:
        front_parts = render_front_matter_sofurry(fm)
        body_parts, body_stats = _convert_body_sofurry(lines, fm.body_start_line + 1)
        all_parts = front_parts + body_parts
        stats = {"title": fm.title, "subtitle": fm.subtitle, **body_stats}
        return ConversionResult(output="\n".join(all_parts), format="sofurry_html", stats=stats)

    # --- HEURISTIC FALLBACK ---
    body_parts: list[str] = []
    stats = {
        "title": None, "subtitle": None, "chapters": [],
        "section_breaks": 0, "paragraphs": 0,
        "pov_markers": [], "text_messages": 0, "end_marker": False,
    }
    title_seen = False
    subtitle_done = False
    in_warning_block = False
    i = 0
    current_paragraph: list[str] = []
    tc = lambda inner: f'<p class="text-center">{inner}</p>'

    def flush():
        if current_paragraph:
            text = " ".join(current_paragraph)
            converted = format_paragraph_html(text)
            body_parts.append(tc(converted) if in_warning_block else f"<p>{converted}</p>")
            stats["paragraphs"] += 1
            current_paragraph.clear()

    while i < len(lines):
        stripped = lines[i].strip()
        if stripped == "---":
            flush(); in_warning_block = False
            j = i + 1
            while j < len(lines) and lines[j].strip() == "": j += 1
            body_parts.append("<hr />" if j < len(lines) and lines[j].strip().startswith("# ") else tc("* * *"))
            if not (j < len(lines) and lines[j].strip().startswith("# ")): stats["section_breaks"] += 1
            i += 1; continue
        if stripped.startswith("# "):
            flush(); in_warning_block = False; heading = _escape_html(stripped[2:].strip())
            if not title_seen:
                body_parts.append(f'<h2 class="text-center">{heading}</h2>'); title_seen = True; stats["title"] = heading
            else:
                body_parts.append(f'<h3 class="text-center">{heading}</h3>'); stats["chapters"].append(heading); subtitle_done = True
            i += 1; continue
        if title_seen and not subtitle_done:
            if stripped == "": flush(); i += 1; continue
            if re.match(r"^\*[^*]+\*$", stripped):
                inner = stripped[1:-1]
                if not inner.startswith("End of "):
                    flush(); body_parts.append(tc(f"<em>{_escape_html(inner)}</em>")); subtitle_done = True; stats["subtitle"] = inner; i += 1; continue
            subtitle_done = True
        if _is_warning_line(stripped):
            flush(); in_warning_block = True; body_parts.append(tc(format_paragraph_html(stripped))); stats["paragraphs"] += 1; i += 1; continue
        if re.match(r"^\*End of .+\*$", stripped):
            flush(); body_parts.append(tc("<strong>~ End ~</strong>")); stats["end_marker"] = True; i += 1; continue
        if is_pov_marker(stripped):
            flush(); body_parts.append(tc(f"<strong>{_escape_html(stripped[2:-2])}</strong>")); stats["pov_markers"].append(stripped[2:-2]); i += 1; continue
        phone_m = is_phone_display(stripped)
        if phone_m:
            flush(); body_parts.append(tc(f"<strong>{_escape_html(phone_m.group(1).strip())}</strong>")); stats["text_messages"] += 1; i += 1; continue
        msg_m = is_text_message(stripped)
        if msg_m:
            flush(); s, m = msg_m.group(1).strip(), msg_m.group(2).strip()
            align = "text-right" if "MAYA" in s.upper() else "text-left"
            body_parts.append(f'<p class="{align}"><strong>{_escape_html(s)}:</strong> {_escape_html(m)}</p>'); stats["text_messages"] += 1; i += 1; continue
        if stripped == "": flush(); i += 1; continue
        current_paragraph.append(stripped); i += 1
    flush()
    return ConversionResult(output="\n".join(body_parts), format="sofurry_html", stats=stats)


def convert_to_bbcode(markdown_text: str) -> ConversionResult:
    """Convert full MASTER.md text to BBCode (Inkbunny).

    If the file has anchors, uses structured parsing.
    Otherwise falls back to heuristic parsing.
    """
    lines = markdown_text.split("\n")

    fm = parse_front_matter(markdown_text)
    if fm is not None:
        front_parts = render_front_matter_bbcode(fm)
        body_parts, body_stats = _convert_body_bbcode(lines, fm.body_start_line + 1)
        all_parts = front_parts + body_parts
        stats = {"title": fm.title, "subtitle": fm.subtitle, **body_stats}
        return ConversionResult(output="\n".join(all_parts), format="bbcode", stats=stats)

    # --- HEURISTIC FALLBACK ---
    output_lines: list[str] = []
    stats = {
        "title": None, "subtitle": None, "chapters": [],
        "section_breaks": 0, "paragraphs": 0,
        "pov_markers": [], "text_messages": 0, "end_marker": False,
    }
    title_seen = False
    subtitle_done = False
    in_warning_block = False
    i = 0

    while i < len(lines):
        stripped = lines[i].strip()
        if stripped == "---":
            in_warning_block = False
            j = i + 1
            while j < len(lines) and lines[j].strip() == "": j += 1
            if j < len(lines) and lines[j].strip().startswith("# "):
                output_lines.extend(["", "[center]───────────────────[/center]", ""])
            elif j < len(lines) and re.match(r"^\*End of .+\*$", lines[j].strip()):
                output_lines.extend(["", "[center]───────────────────[/center]", ""])
            else:
                output_lines.extend(["", "[center]* * *[/center]", ""]); stats["section_breaks"] += 1
            i += 1; continue
        if stripped.startswith("# "):
            in_warning_block = False; heading = stripped[2:].strip()
            if not title_seen:
                output_lines.append(f"[center][t]{heading}[/t][/center]"); title_seen = True; stats["title"] = heading
            else:
                output_lines.extend(["", f"[center][b]{heading}[/b][/center]"]); stats["chapters"].append(heading); subtitle_done = True
            i += 1; continue
        if _is_warning_line(stripped):
            in_warning_block = True; output_lines.append(f"[center]{format_paragraph_bbcode(stripped)}[/center]"); stats["paragraphs"] += 1; i += 1; continue
        if title_seen and not subtitle_done:
            if stripped == "": output_lines.append(""); i += 1; continue
            if re.match(r"^\*[^*]+\*$", stripped):
                inner = stripped[1:-1]
                if not inner.startswith("End of "):
                    output_lines.extend(["", f"[center][i]{inner}[/i][/center]", ""]); subtitle_done = True; stats["subtitle"] = inner; i += 1; continue
            subtitle_done = True
        if re.match(r"^\*End of .+\*$", stripped):
            output_lines.extend(["", "[center][b]~ End ~[/b][/center]"]); stats["end_marker"] = True; i += 1; continue
        if is_pov_marker(stripped):
            output_lines.extend(["", f"[center][b]{stripped[2:-2]}[/b][/center]", ""]); stats["pov_markers"].append(stripped[2:-2]); i += 1; continue
        phone_m = is_phone_display(stripped)
        if phone_m:
            output_lines.extend(["", f"[center]───── [color=#4a9eff]📱 {phone_m.group(1).strip()}[/color] ─────[/center]", ""]); stats["text_messages"] += 1; i += 1; continue
        msg_m = is_text_message(stripped)
        if msg_m:
            s, m = msg_m.group(1).strip(), msg_m.group(2).strip()
            color = "#4a9eff" if "MAYA" in s.upper() else "#aab0bc"
            align = "right" if "MAYA" in s.upper() else "left"
            output_lines.append(f"[{align}][color={color}][b]{s}[/b]: {m}[/color][/{align}]"); stats["text_messages"] += 1; i += 1; continue
        if stripped == "": output_lines.append(""); i += 1; continue
        converted = format_paragraph_bbcode(stripped)
        output_lines.append(f"[center]{converted}[/center]" if in_warning_block else converted); stats["paragraphs"] += 1; i += 1

    return ConversionResult(output="\n".join(output_lines), format="bbcode", stats=stats)


def convert_to_sqw_chapters(markdown_text: str, warning_icon: str = "&#9888;") -> list[ConversionResult]:
    """Convert anchored MASTER.md to per-chapter SquidgeWorld body HTML.

    Returns a list of ConversionResult, one per chapter. Chapter 1 gets
    the full warning-page div; subsequent chapters get a bare title block.

    Requires anchored MASTER.md (returns empty list if no anchors).
    """
    fm = parse_front_matter(markdown_text)
    if fm is None:
        return []

    lines = markdown_text.split("\n")
    body_lines = lines[fm.body_start_line + 1:]

    # Detect chapters in the body section
    body_text = "\n".join(body_lines)
    chapters = detect_chapters(body_text)

    if not chapters:
        return []

    results: list[ConversionResult] = []

    for ch_idx, ch in enumerate(chapters):
        ch_lines = body_text.split("\n")[ch["line_start"]:ch["line_end"] + 1]
        # Convert body content (skip the chapter heading line itself)
        body_start = 1  # skip the # heading line
        while body_start < len(ch_lines) and ch_lines[body_start].strip() == "":
            body_start += 1

        body_parts, stats = _convert_body_clean_html(ch_lines, body_start)

        # Build the chapter HTML
        parts: list[str] = []

        if ch_idx == 0:
            # Chapter 1: full warning-page div
            parts.extend(render_front_matter_sqw(fm, ch["title"], warning_icon))
        else:
            # Chapter 2+: bare title block (no warning page)
            parts.append(f'<h1 class="story-title">{_escape_html(fm.title)}</h1>')
            if fm.byline:
                parts.append(f'<p class="byline">{_escape_html(fm.byline)}</p>')
            else:
                parts.append('<p class="byline">by KnaughtyKat</p>')
            parts.append('<hr class="title-rule">')
            parts.append(f'<h2 class="chapter-subtitle">{_escape_html(ch["title"])}</h2>')

        parts.extend(body_parts)

        output = "\n".join(parts)
        results.append(ConversionResult(
            output=output,
            format="sqw",
            stats={"chapter_index": ch_idx, "chapter_title": ch["title"], **stats},
        ))

    return results


def convert(markdown_text: str, target_format: str) -> ConversionResult:
    """Convert markdown to the specified format.

    Supported formats: 'clean_html', 'sofurry_html', 'bbcode'
    For SQW per-chapter output, use convert_to_sqw_chapters() directly.
    """
    if target_format == "clean_html":
        return convert_to_clean_html(markdown_text)
    elif target_format == "sofurry_html":
        return convert_to_sofurry_html(markdown_text)
    elif target_format == "bbcode":
        return convert_to_bbcode(markdown_text)
    else:
        raise ValueError(f"Unsupported format: {target_format}")
