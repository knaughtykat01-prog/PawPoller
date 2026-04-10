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


def convert_to_clean_html(markdown_text: str) -> ConversionResult:
    """Convert full MASTER.md text to body-only Clean HTML (AO3/SQW).

    Centering rules:
      - Title, subtitle, chapter headings: centred
      - Content Warning + DISCLAIMER block: centred
      - Section breaks, POV markers, end marker: centred
      - Spacing before chapter headings
    """
    lines = markdown_text.split("\n")
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

        # --- Section/chapter break ---
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

        # --- Headings ---
        if stripped.startswith("# "):
            flush()
            in_warning_block = False
            heading = _escape_html(stripped[2:].strip())
            if not title_seen:
                body_parts.append(_center_html(f"<strong>{heading}</strong>"))
                title_seen = True
                stats["title"] = heading
            else:
                body_parts.append(_center_html(f"<strong>{heading}</strong>"))
                stats["chapters"].append(heading)
                subtitle_done = True
            i += 1
            continue

        # --- Subtitle ---
        if title_seen and not subtitle_done:
            if stripped == "":
                flush()
                i += 1
                continue
            if re.match(r"^\*[^*]+\*$", stripped):
                inner = stripped[1:-1]
                if not inner.startswith("End of "):
                    # Any italic-only line in subtitle position is a subtitle
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

        # --- Warning/disclaimer block detection ---
        if _is_warning_line(stripped):
            flush()
            in_warning_block = True
            converted = format_paragraph_html(stripped)
            body_parts.append(_center_html(converted))
            stats["paragraphs"] += 1
            i += 1
            continue

        # --- End marker ---
        if re.match(r"^\*End of .+\*$", stripped):
            flush()
            body_parts.append(_center_html("<strong>~ End ~</strong>"))
            stats["end_marker"] = True
            i += 1
            continue

        # --- POV marker ---
        if is_pov_marker(stripped):
            flush()
            inner = stripped[2:-2]
            body_parts.append(_center_html(f"<strong>{_escape_html(inner)}</strong>"))
            stats["pov_markers"].append(inner)
            i += 1
            continue

        # --- Phone display ---
        phone_m = is_phone_display(stripped)
        if phone_m:
            flush()
            caller = phone_m.group(1).strip()
            body_parts.append(_center_html(f"<strong>{_escape_html(caller)}</strong>"))
            stats["text_messages"] += 1
            i += 1
            continue

        # --- Text message ---
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

        # --- Blank line ---
        if stripped == "":
            flush()
            i += 1
            continue

        # --- Regular text ---
        current_paragraph.append(stripped)
        i += 1

    flush()

    output = "\n".join(body_parts)
    return ConversionResult(output=output, format="clean_html", stats=stats, warnings=warnings)


def convert_to_sofurry_html(markdown_text: str) -> ConversionResult:
    """Convert full MASTER.md text to SoFurry-specific HTML.

    Uses SF's supported tags:
      - <h2> for story title (centred via class)
      - <h3> for chapter headings (centred)
      - <p class="text-center"> for centred text (subtitles, POV markers,
        section breaks, end marker)
      - <p class="text-right"> for sent text messages
      - <blockquote> for content warnings (optional)
      - <em>, <strong>, <s> for inline formatting
    """
    lines = markdown_text.split("\n")
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

    def _sf_center(inner: str) -> str:
        return f'<p class="text-center">{inner}</p>'

    def flush():
        if current_paragraph:
            text = " ".join(current_paragraph)
            converted = format_paragraph_html(text)
            if in_warning_block:
                body_parts.append(_sf_center(converted))
            else:
                body_parts.append(f"<p>{converted}</p>")
            stats["paragraphs"] += 1
            current_paragraph.clear()

    while i < len(lines):
        stripped = lines[i].strip()

        # --- Section/chapter break ---
        if stripped == "---":
            flush()
            in_warning_block = False
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and lines[j].strip().startswith("# "):
                body_parts.append("<hr />")
            else:
                body_parts.append('<p class="text-center">* * *</p>')
                stats["section_breaks"] += 1
            i += 1
            continue

        # --- Headings ---
        if stripped.startswith("# "):
            flush()
            in_warning_block = False
            heading = _escape_html(stripped[2:].strip())
            if not title_seen:
                body_parts.append(f'<h2 class="text-center">{heading}</h2>')
                title_seen = True
                stats["title"] = heading
            else:
                body_parts.append(f'<h3 class="text-center">{heading}</h3>')
                stats["chapters"].append(heading)
                subtitle_done = True
            i += 1
            continue

        # --- Subtitle ---
        if title_seen and not subtitle_done:
            if stripped == "":
                flush()
                i += 1
                continue
            if re.match(r"^\*[^*]+\*$", stripped):
                inner = stripped[1:-1]
                if not inner.startswith("End of "):
                    # Any italic-only line in subtitle position is a subtitle
                    if True:
                        flush()
                        body_parts.append(_sf_center(f"<em>{_escape_html(inner)}</em>"))
                        subtitle_done = True
                        stats["subtitle"] = inner
                        i += 1
                        continue
                    else:
                        subtitle_done = True
            else:
                subtitle_done = True

        # --- Warning/disclaimer block detection ---
        if _is_warning_line(stripped):
            flush()
            in_warning_block = True
            converted = format_paragraph_html(stripped)
            body_parts.append(_sf_center(converted))
            stats["paragraphs"] += 1
            i += 1
            continue

        # --- End marker ---
        if re.match(r"^\*End of .+\*$", stripped):
            flush()
            body_parts.append(_sf_center("<strong>~ End ~</strong>"))
            stats["end_marker"] = True
            i += 1
            continue

        # --- POV marker ---
        if is_pov_marker(stripped):
            flush()
            inner = stripped[2:-2]
            body_parts.append(_sf_center(f"<strong>{_escape_html(inner)}</strong>"))
            stats["pov_markers"].append(inner)
            i += 1
            continue

        # --- Phone display ---
        phone_m = is_phone_display(stripped)
        if phone_m:
            flush()
            caller = phone_m.group(1).strip()
            body_parts.append(_sf_center(f"<strong>{_escape_html(caller)}</strong>"))
            stats["text_messages"] += 1
            i += 1
            continue

        # --- Text message ---
        msg_m = is_text_message(stripped)
        if msg_m:
            flush()
            sender = msg_m.group(1).strip()
            message = msg_m.group(2).strip()
            is_sent = "MAYA" in sender.upper()
            align = "text-right" if is_sent else "text-left"
            body_parts.append(
                f'<p class="{align}"><strong>{_escape_html(sender)}:</strong> {_escape_html(message)}</p>'
            )
            stats["text_messages"] += 1
            i += 1
            continue

        # --- Blank line ---
        if stripped == "":
            flush()
            i += 1
            continue

        # --- Regular text ---
        current_paragraph.append(stripped)
        i += 1

    flush()

    output = "\n".join(body_parts)
    return ConversionResult(output=output, format="sofurry_html", stats=stats, warnings=warnings)


def convert_to_bbcode(markdown_text: str) -> ConversionResult:
    """Convert full MASTER.md text to BBCode (Inkbunny).

    Centering rules:
      - Title, subtitle, chapter headings: centred
      - Content Warning + DISCLAIMER block: centred
      - Section breaks, POV markers, end marker: centred
    """
    lines = markdown_text.split("\n")
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

        # --- Section/chapter break ---
        if stripped == "---":
            in_warning_block = False
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and lines[j].strip().startswith("# "):
                output_lines.append("")
                output_lines.append("[center]───────────────────[/center]")
                output_lines.append("")
            elif j < len(lines) and re.match(r"^\*End of .+\*$", lines[j].strip()):
                output_lines.append("")
                output_lines.append("[center]───────────────────[/center]")
                output_lines.append("")
            else:
                output_lines.append("")
                output_lines.append("[center]* * *[/center]")
                output_lines.append("")
                stats["section_breaks"] += 1
            i += 1
            continue

        # --- Headings ---
        if stripped.startswith("# "):
            in_warning_block = False
            heading = stripped[2:].strip()
            if not title_seen:
                output_lines.append(f"[center][t]{heading}[/t][/center]")
                title_seen = True
                stats["title"] = heading
            else:
                output_lines.append("")
                output_lines.append(f"[center][b]{heading}[/b][/center]")
                stats["chapters"].append(heading)
                subtitle_done = True
            i += 1
            continue

        # --- Warning/disclaimer block detection ---
        if _is_warning_line(stripped):
            in_warning_block = True
            converted = format_paragraph_bbcode(stripped)
            output_lines.append(f"[center]{converted}[/center]")
            stats["paragraphs"] += 1
            i += 1
            continue

        # --- Subtitle ---
        if title_seen and not subtitle_done:
            if stripped == "":
                output_lines.append("")
                i += 1
                continue
            if re.match(r"^\*[^*]+\*$", stripped):
                inner = stripped[1:-1]
                if not inner.startswith("End of "):
                    # Any italic-only line in subtitle position is a subtitle
                    if True:
                        output_lines.extend(["", f"[center][i]{inner}[/i][/center]", ""])
                        subtitle_done = True
                        stats["subtitle"] = inner
                        i += 1
                        continue
                    else:
                        subtitle_done = True
            else:
                subtitle_done = True

        # --- End marker ---
        if re.match(r"^\*End of .+\*$", stripped):
            output_lines.extend(["", "[center][b]~ End ~[/b][/center]"])
            stats["end_marker"] = True
            i += 1
            continue

        # --- POV marker ---
        if is_pov_marker(stripped):
            inner = stripped[2:-2]
            output_lines.extend(["", f"[center][b]{inner}[/b][/center]", ""])
            stats["pov_markers"].append(inner)
            i += 1
            continue

        # --- Phone display ---
        phone_m = is_phone_display(stripped)
        if phone_m:
            caller = phone_m.group(1).strip()
            output_lines.extend(["", f"[center]───── [color=#4a9eff]📱 {caller}[/color] ─────[/center]", ""])
            stats["text_messages"] += 1
            i += 1
            continue

        # --- Text message ---
        msg_m = is_text_message(stripped)
        if msg_m:
            sender = msg_m.group(1).strip()
            message = msg_m.group(2).strip()
            is_sent = "MAYA" in sender.upper()
            color = "#4a9eff" if is_sent else "#aab0bc"
            align = "right" if is_sent else "left"
            output_lines.append(f"[{align}][color={color}][b]{sender}[/b]: {message}[/color][/{align}]")
            stats["text_messages"] += 1
            i += 1
            continue

        # --- Blank line ---
        if stripped == "":
            output_lines.append("")
            i += 1
            continue

        # --- Regular paragraph ---
        converted = format_paragraph_bbcode(stripped)
        if in_warning_block:
            output_lines.append(f"[center]{converted}[/center]")
        else:
            output_lines.append(converted)
        stats["paragraphs"] += 1
        i += 1

    output = "\n".join(output_lines)
    return ConversionResult(output=output, format="bbcode", stats=stats)


def convert(markdown_text: str, target_format: str) -> ConversionResult:
    """Convert markdown to the specified format.

    Supported formats: 'clean_html', 'sofurry_html', 'bbcode'
    Future: 'sqw', 'styled_html'
    """
    if target_format == "clean_html":
        return convert_to_clean_html(markdown_text)
    elif target_format == "sofurry_html":
        return convert_to_sofurry_html(markdown_text)
    elif target_format == "bbcode":
        return convert_to_bbcode(markdown_text)
    else:
        raise ValueError(f"Unsupported format: {target_format}")
