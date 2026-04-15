"""Story editor API routes.

Provides endpoints for reading/writing MASTER.md, live preview in
multiple formats, and triggering format regeneration.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from posting.story_reader import get_archive_path

logger = logging.getLogger(__name__)

editor_router = APIRouter(prefix="/api/editor", tags=["editor"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class SaveRequest(BaseModel):
    content: str
    expected_mtime: float | None = None  # optimistic concurrency check


class PreviewRequest(BaseModel):
    content: str
    format: str = "clean_html"  # clean_html, bbcode, sqw
    chapter: int = 0  # 0 = full story
    theme: dict | None = None  # live theme overrides for styled_html


class RegenerateRequest(BaseModel):
    skip_pdf: bool = True  # PDFs are slow; opt-in


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SKIP_DIRS = {"Reference_Guides"}


def _resolve_story_dir(story_name: str) -> Path:
    """Resolve a story name to its directory. Handles versioned stories
    like 'The_Abstinent_Bet/Nice_Version' via the :path converter."""
    archive = get_archive_path()
    candidate = archive / story_name
    if candidate.is_dir():
        return candidate
    raise HTTPException(status_code=404, detail=f"Story not found: {story_name}")


def _get_master_path(story_dir: Path) -> Path:
    return story_dir / "Markdown" / "MASTER.md"


def _backup_master(master_path: Path) -> Path | None:
    """Create a timestamped backup of MASTER.md before saving."""
    if not master_path.is_file():
        return None
    ts = int(time.time())
    backup = master_path.with_suffix(f".md.bak.{ts}")
    backup.write_text(master_path.read_text(encoding="utf-8"), encoding="utf-8")
    # Cleanup: keep only the 10 most recent backups
    bak_dir = master_path.parent
    baks = sorted(bak_dir.glob("MASTER.md.bak.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in baks[10:]:
        old.unlink(missing_ok=True)
    return backup


def _word_count(text: str) -> int:
    return len(text.split())


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@editor_router.get("/stories")
async def list_stories():
    """List all stories available for editing."""
    archive = get_archive_path()
    if not archive.is_dir():
        return {"stories": []}

    stories = []
    for entry in sorted(archive.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name in SKIP_DIRS:
            continue
        # Direct story (has Markdown/MASTER.md or story.json)
        master = entry / "Markdown" / "MASTER.md"
        sj = entry / "story.json"
        if master.is_file() or sj.is_file():
            info = _story_info(entry)
            if info:
                stories.append(info)
        else:
            # Versioned story (subdirectories like Nice_Version)
            for sub in sorted(entry.iterdir()):
                if sub.is_dir() and ((sub / "Markdown" / "MASTER.md").is_file() or (sub / "story.json").is_file()):
                    info = _story_info(sub, prefix=entry.name)
                    if info:
                        stories.append(info)

    return {"stories": stories}


def _story_info(story_dir: Path, prefix: str = "") -> dict | None:
    """Build story info dict for the story list."""
    master = story_dir / "Markdown" / "MASTER.md"
    sj = story_dir / "story.json"

    name = f"{prefix}/{story_dir.name}" if prefix else story_dir.name
    title = story_dir.name.replace("_", " ")
    word_count = 0
    chapters = 0

    if sj.is_file():
        try:
            data = json.loads(sj.read_text(encoding="utf-8"))
            title = data.get("title", title)
            word_count = data.get("word_count", 0)
            chapters = data.get("chapters", 0)
        except Exception:
            pass

    has_master = master.is_file()
    last_modified = master.stat().st_mtime if has_master else 0

    return {
        "name": name,
        "title": title,
        "word_count": word_count,
        "chapters": chapters,
        "has_master": has_master,
        "last_modified": last_modified,
    }


@editor_router.get("/stories/{story_name:path}/content")
async def get_content(story_name: str):
    """Read MASTER.md content for editing."""
    story_dir = _resolve_story_dir(story_name)
    master = _get_master_path(story_dir)

    if not master.is_file():
        raise HTTPException(status_code=404, detail="MASTER.md not found")

    content = master.read_text(encoding="utf-8")
    mtime = master.stat().st_mtime

    # Detect chapters
    from editor.converter import detect_chapters
    chapters = detect_chapters(content)

    return {
        "content": content,
        "last_modified": mtime,
        "word_count": _word_count(content),
        "chapters": chapters,
    }


@editor_router.put("/stories/{story_name:path}/content")
async def save_content(story_name: str, req: SaveRequest):
    """Save MASTER.md content. Creates a backup first."""
    story_dir = _resolve_story_dir(story_name)
    master = _get_master_path(story_dir)

    # Ensure directory exists
    master.parent.mkdir(parents=True, exist_ok=True)

    # Optimistic concurrency check
    if req.expected_mtime is not None and master.is_file():
        actual_mtime = master.stat().st_mtime
        if abs(actual_mtime - req.expected_mtime) > 0.5:
            raise HTTPException(
                status_code=409,
                detail="File has been modified externally since you loaded it. Reload and merge your changes.",
            )

    # Backup
    _backup_master(master)

    # Atomic write via temp file
    tmp = master.with_suffix(".md.tmp")
    tmp.write_text(req.content, encoding="utf-8")
    os.replace(str(tmp), str(master))

    return {
        "ok": True,
        "word_count": _word_count(req.content),
        "last_modified": master.stat().st_mtime,
    }


@editor_router.post("/stories/{story_name:path}/preview")
async def preview(story_name: str, req: PreviewRequest):
    """Convert markdown content to the requested format (in-memory, no file I/O)."""
    from editor.converter import convert, detect_chapters

    content = req.content

    # Chapter-scoped preview
    if req.chapter > 0:
        chapters = detect_chapters(content)
        if req.chapter <= len(chapters):
            ch = chapters[req.chapter - 1]
            lines = content.split("\n")
            content = "\n".join(lines[ch["line_start"]:ch["line_end"] + 1])

    # Styled HTML needs theme + template from the story's files
    if req.format == "styled_html":
        from editor.converter import convert_to_styled_html_external_css, generate_styled_css, parse_chapter_styling
        story_dir = _resolve_story_dir(story_name)
        archive = get_archive_path()

        # Use live theme vars from GUI if provided, otherwise read from disk
        if req.theme:
            theme = req.theme
        else:
            theme = {}
            styling_path = story_dir / "CHAPTER_STYLING.md"
            if styling_path.is_file():
                theme = parse_chapter_styling(styling_path.read_text(encoding="utf-8"))

        template = ""
        template_path = archive / "Reference_Guides" / "Styling" / "HTML_CSS" / "STYLING_REFERENCE.md"
        if template_path.is_file():
            template = template_path.read_text(encoding="utf-8")
        if not template:
            return {"html": "(Styled HTML requires STYLING_REFERENCE.md template — not found)", "format": "styled_html", "stats": {}, "warnings": ["Template not found"]}
        if not theme:
            return {"html": "(Styled HTML requires CHAPTER_STYLING.md theme — not found or empty)", "format": "styled_html", "stats": {}, "warnings": ["Theme not found"]}
        try:
            result = convert_to_styled_html_external_css(content, theme, template, mode="full", css_href="style.css")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        # Source panel: the <link> version (what the file looks like)
        source_html = result.full_story.output if result.full_story else ""

        # Preview iframe: inject CSS inline so it renders in srcdoc
        preview_html = source_html.replace(
            '<link rel="stylesheet" href="style.css">',
            f"<style>\n{result.css}\n</style>",
        ) if source_html else ""

        # Also return generated CSS so the frontend can sync the source view
        css = result.css

        return {
            "html": source_html,
            "preview_html": preview_html,
            "css": css,
            "format": "styled_html",
            "stats": result.full_story.stats if result.full_story else {},
            "warnings": [],
        }

    try:
        result = convert(content, req.format)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "html": result.output,
        "format": result.format,
        "stats": result.stats,
        "warnings": result.warnings,
    }


@editor_router.post("/stories/{story_name:path}/regenerate")
async def regenerate(story_name: str, req: RegenerateRequest):
    """Regenerate all derived format files from MASTER.md.

    Writes all formats: Clean HTML, SoFurry HTML, BBCode, Styled HTML
    (full + chapters + style.css), SquidgeWorld, and per-chapter splits.
    """
    from editor.converter import convert
    story_dir = _resolve_story_dir(story_name)
    master = _get_master_path(story_dir)

    if not master.is_file():
        raise HTTPException(status_code=404, detail="MASTER.md not found")

    content = master.read_text(encoding="utf-8")
    results: list[str] = []
    errors: list[str] = []

    stem = story_dir.name
    html_dir = story_dir / "HTML"
    bb_dir = story_dir / "BBCode"
    html_dir.mkdir(exist_ok=True)
    bb_dir.mkdir(exist_ok=True)

    # --- Full-story Clean HTML ---
    try:
        html_result = convert(content, "clean_html")
        (html_dir / f"{stem}_Clean.html").write_text(html_result.output, encoding="utf-8")
        results.append(f"HTML/{stem}_Clean.html ({len(html_result.output):,} bytes)")
    except Exception as e:
        errors.append(f"Clean HTML: {e}")

    # --- Full-story SoFurry HTML ---
    try:
        sf_result = convert(content, "sofurry_html")
        (html_dir / f"{stem}_SoFurry.html").write_text(sf_result.output, encoding="utf-8")
        results.append(f"HTML/{stem}_SoFurry.html ({len(sf_result.output):,} bytes)")
    except Exception as e:
        errors.append(f"SoFurry HTML: {e}")

    # --- Full-story BBCode ---
    try:
        bb_result = convert(content, "bbcode")
        (bb_dir / f"{stem}_bbcode.txt").write_text(bb_result.output, encoding="utf-8")
        results.append(f"BBCode/{stem}_bbcode.txt ({len(bb_result.output):,} bytes)")
    except Exception as e:
        errors.append(f"BBCode: {e}")

    # --- SquidgeWorld chapters (from anchored source) ---
    try:
        from editor.converter import convert_to_sqw_chapters
        # Read warning icon from CHAPTER_STYLING.md if available
        warning_icon = "&#9888;"  # default
        styling_path = story_dir / "CHAPTER_STYLING.md"
        if styling_path.is_file():
            styling_text = styling_path.read_text(encoding="utf-8")
            icon_m = re.search(r"Warning icon.*?`(&#\d+;)`", styling_text, re.IGNORECASE)
            if icon_m:
                warning_icon = icon_m.group(1)

        sqw_chapters = convert_to_sqw_chapters(content, warning_icon=warning_icon)
        if sqw_chapters:
            sqw_dir = story_dir / "SquidgeWorld"
            sqw_dir.mkdir(exist_ok=True)
            for ch_result in sqw_chapters:
                ch_idx = ch_result.stats["chapter_index"]
                ch_title = ch_result.stats["chapter_title"]
                ch_title_safe = re.sub(r"^(Chapter|Part|Prelude|Epilogue)\s*\d*:?\s*", "", ch_title).strip()
                ch_title_safe = re.sub(r"[^\w\s()-]", "", ch_title_safe).replace(" ", "_")
                ch_filename = f"Chapter_{ch_idx + 1}_{ch_title_safe}.html"
                (sqw_dir / ch_filename).write_text(ch_result.output, encoding="utf-8")
            results.append(f"SquidgeWorld: {len(sqw_chapters)} chapters generated")
    except Exception as e:
        errors.append(f"SquidgeWorld: {e}")

    # --- Styled HTML (full + chapters + CSS) ---
    try:
        from editor.converter import (
            convert_to_styled_html_external_css, generate_styled_css,
            parse_chapter_styling,
        )
        archive = get_archive_path()
        template_path = archive / "Reference_Guides" / "Styling" / "HTML_CSS" / "STYLING_REFERENCE.md"
        styling_path = story_dir / "CHAPTER_STYLING.md"

        if template_path.is_file() and styling_path.is_file():
            theme = parse_chapter_styling(styling_path.read_text(encoding="utf-8"))
            template = template_path.read_text(encoding="utf-8")

            # CSS
            css = generate_styled_css(theme, template)
            (html_dir / "style.css").write_text(css, encoding="utf-8")

            ch_styled_dir = story_dir / "Chapters" / "Styled_HTML"
            if ch_styled_dir.is_dir():
                (ch_styled_dir / "style.css").write_text(css, encoding="utf-8")

            # Full story
            full_result = convert_to_styled_html_external_css(
                content, theme, template, mode="full", css_href="style.css"
            )
            if full_result.full_story:
                (html_dir / f"{stem}_Styled.html").write_text(
                    full_result.full_story.output, encoding="utf-8"
                )
                results.append(f"HTML/{stem}_Styled.html ({len(full_result.full_story.output):,} bytes)")

            # Per-chapter styled HTML
            ch_result = convert_to_styled_html_external_css(
                content, theme, template, mode="chapters", css_href="style.css"
            )
            if ch_result.chapters:
                ch_styled_dir.mkdir(parents=True, exist_ok=True)
                for ch_r in ch_result.chapters:
                    ch_title = ch_r.stats.get("chapter_title", "")
                    ch_title_safe = re.sub(
                        r"^(Chapter|Part|Prelude|Epilogue)\s*\d*:?\s*", "", ch_title
                    ).strip()
                    ch_title_safe = re.sub(r"[^\w\s()-]", "", ch_title_safe).replace(" ", "_")
                    ch_idx = ch_r.stats.get("chapter_index", 0)
                    ch_filename = f"Chapter_{ch_idx + 1}_{ch_title_safe}.html"
                    (ch_styled_dir / ch_filename).write_text(ch_r.output, encoding="utf-8")
                results.append(f"Styled HTML: {len(ch_result.chapters)} chapters + full story + style.css")
    except Exception as e:
        errors.append(f"Styled HTML: {e}")

    # --- Chapter splits (Markdown, SoFurry HTML, BBCode) ---
    from editor.converter import detect_chapters
    chapters = detect_chapters(content)
    lines = content.split("\n")

    if len(chapters) > 1:
        md_dir = story_dir / "Chapters" / "Markdown"
        sf_dir = story_dir / "Chapters" / "SoFurry_HTML"
        bb_ch_dir = story_dir / "Chapters" / "BBCode"
        for d in [md_dir, sf_dir, bb_ch_dir]:
            d.mkdir(parents=True, exist_ok=True)

        for ch in chapters[1:]:  # Skip the title "chapter" (index 0)
            ch_idx = ch["index"]
            ch_title = re.sub(r"^(Chapter|Part|Prelude|Epilogue)\s*\d*:?\s*", "", ch["title"]).strip()
            ch_title_safe = re.sub(r"[^\w\s()-]", "", ch_title).replace(" ", "_")
            ch_filename = f"Chapter_{ch_idx}_{ch_title_safe}"
            ch_content = "\n".join(lines[ch["line_start"]:ch["line_end"] + 1])

            # Chapter markdown
            ch_md_path = md_dir / f"{ch_filename}.md"
            ch_md_path.write_text(ch_content, encoding="utf-8")

            # Chapter Clean HTML
            try:
                ch_html = convert(ch_content, "clean_html")
                (sf_dir / f"{ch_filename}.html").write_text(ch_html.output, encoding="utf-8")
            except Exception:
                pass

            # Chapter BBCode
            try:
                ch_bb = convert(ch_content, "bbcode")
                (bb_ch_dir / f"{ch_filename}.txt").write_text(ch_bb.output, encoding="utf-8")
            except Exception:
                pass

        results.append(f"{len(chapters) - 1} chapters split + converted (Markdown, HTML, BBCode)")

    return {
        "ok": True,
        "results": results,
        "errors": errors,
        "word_count": _word_count(content),
    }


class ThemeSaveRequest(BaseModel):
    variables: dict


@editor_router.get("/stories/{story_name:path}/theme")
async def get_theme(story_name: str):
    """Get the story's theme variables as a dict."""
    from editor.converter import parse_chapter_styling, STYLED_HTML_THEME_KEYS
    story_dir = _resolve_story_dir(story_name)
    styling_path = story_dir / "CHAPTER_STYLING.md"
    if not styling_path.is_file():
        return {"variables": {}, "error": "No CHAPTER_STYLING.md found"}
    theme = parse_chapter_styling(styling_path.read_text(encoding="utf-8"))
    # Fill in defaults for any missing keys so the GUI always has values
    defaults = {
        "BACKGROUND": "#1a1118", "TEXT_COLOUR": "#e0d6cc",
        "TITLE_COLOUR": "#e8ddd0", "BYLINE_COLOUR": "#b89a80",
        "ACCENT_COLOUR": "#8b2030", "WARNING_HEADING_COLOUR": "#c4a040",
        "WARNING_BODY_COLOUR": "#c8b8a8", "DISCLAIMER_HEADING_COLOUR": "#e8ddd0",
        "STORY_END_COLOUR": "#e8ddd0", "SIGNATURE_COLOUR": "#c4a040",
        "TEXT_SENT_COLOUR": "#508c46", "TEXT_RECEIVED_COLOUR": "#8b2030",
        "TITLE_TEXT_SHADOW": "", "SECTION_BREAK_SYMBOL": "* &ensp; * &ensp; *",
        "WARNING_ICON": "&#9888;", "PRINT_APPROACH": "colour-preserve",
    }
    for key, default in defaults.items():
        if key not in theme:
            theme[key] = default
    # Default TEXT_RECEIVED_COLOUR to ACCENT_COLOUR if not set
    if theme.get("TEXT_RECEIVED_COLOUR") == "#8b2030" and theme.get("ACCENT_COLOUR") != "#8b2030":
        theme["TEXT_RECEIVED_COLOUR"] = theme["ACCENT_COLOUR"]
    return {"variables": theme, "keys": STYLED_HTML_THEME_KEYS}


@editor_router.put("/stories/{story_name:path}/theme")
async def save_theme(story_name: str, req: ThemeSaveRequest):
    """Save theme variables → regenerate style.css + update CHAPTER_STYLING.md."""
    from editor.converter import generate_styled_css, STYLED_HTML_THEME_KEYS
    story_dir = _resolve_story_dir(story_name)
    archive = get_archive_path()

    template_path = archive / "Reference_Guides" / "Styling" / "HTML_CSS" / "STYLING_REFERENCE.md"
    if not template_path.is_file():
        logger.error("Theme save: template not found at %s (archive=%s)", template_path, archive)
        raise HTTPException(status_code=500, detail=f"STYLING_REFERENCE.md not found (archive={archive})")
    template = template_path.read_text(encoding="utf-8")

    # Generate CSS from the new theme variables
    try:
        css = generate_styled_css(req.variables, template)
    except Exception as e:
        logger.error("Theme save: generate_styled_css failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"CSS generation failed: {e}")

    if not css:
        logger.warning("Theme save: generated CSS is empty (template may be malformed)")

    # Write style.css
    try:
        html_dir = story_dir / "HTML"
        html_dir.mkdir(exist_ok=True)
        (html_dir / "style.css").write_text(css, encoding="utf-8")

        ch_styled = story_dir / "Chapters" / "Styled_HTML"
        if ch_styled.is_dir():
            (ch_styled / "style.css").write_text(css, encoding="utf-8")
    except PermissionError as e:
        logger.error("Theme save: permission denied writing CSS: %s", e)
        raise HTTPException(status_code=500, detail=f"Permission denied writing style.css — check archive permissions")

    # Persist theme variables to CHAPTER_STYLING.md so Regenerate uses them
    try:
        styling_path = story_dir / "CHAPTER_STYLING.md"
        if styling_path.is_file():
            existing = styling_path.read_text(encoding="utf-8")
        else:
            existing = ""

        # Remove any existing variables table (between markers)
        marker_start = "<!-- THEME_VARIABLES_START -->"
        marker_end = "<!-- THEME_VARIABLES_END -->"
        if marker_start in existing:
            before = existing[:existing.index(marker_start)]
            after_idx = existing.index(marker_end) + len(marker_end) if marker_end in existing else len(existing)
            existing = before.rstrip() + "\n"
        else:
            existing = existing.rstrip() + "\n\n"

        # Build variables table
        var_lines = [marker_start, "", "## Theme Variables", "", "| Variable | Value |", "| --- | --- |"]
        for key in STYLED_HTML_THEME_KEYS:
            if key in req.variables:
                var_lines.append(f"| `{key}` | `{req.variables[key]}` |")
        var_lines.extend(["", marker_end, ""])
        existing += "\n".join(var_lines)
        styling_path.write_text(existing, encoding="utf-8")
    except Exception as e:
        logger.warning("Theme save: failed to update CHAPTER_STYLING.md: %s", e)

    return {"ok": True, "css_bytes": len(css)}


class CssSaveRequest(BaseModel):
    css: str


@editor_router.get("/stories/{story_name:path}/css")
async def get_css(story_name: str):
    """Get the story's style.css (or generate from CHAPTER_STYLING.md if absent)."""
    from editor.converter import generate_styled_css, parse_chapter_styling
    story_dir = _resolve_story_dir(story_name)
    archive = get_archive_path()

    # Check for existing style.css
    css_path = story_dir / "HTML" / "style.css"
    if css_path.is_file():
        return {"css": css_path.read_text(encoding="utf-8"), "source": "file"}

    # Generate from theme
    styling_path = story_dir / "CHAPTER_STYLING.md"
    if not styling_path.is_file():
        return {"css": "", "source": "none", "error": "No CHAPTER_STYLING.md found"}

    theme = parse_chapter_styling(styling_path.read_text(encoding="utf-8"))
    template_path = archive / "Reference_Guides" / "Styling" / "HTML_CSS" / "STYLING_REFERENCE.md"
    if not template_path.is_file():
        return {"css": "", "source": "none", "error": "No STYLING_REFERENCE.md template"}

    css = generate_styled_css(theme, template_path.read_text(encoding="utf-8"))
    return {"css": css, "source": "generated"}


@editor_router.put("/stories/{story_name:path}/css")
async def save_css(story_name: str, req: CssSaveRequest):
    """Save the story's style.css file."""
    story_dir = _resolve_story_dir(story_name)
    html_dir = story_dir / "HTML"
    html_dir.mkdir(exist_ok=True)

    css_path = html_dir / "style.css"
    css_path.write_text(req.css, encoding="utf-8")

    # Also copy to Chapters/Styled_HTML/ for per-chapter files
    ch_styled = story_dir / "Chapters" / "Styled_HTML"
    if ch_styled.is_dir():
        (ch_styled / "style.css").write_text(req.css, encoding="utf-8")

    return {"ok": True, "bytes": len(req.css)}


class MetadataSaveRequest(BaseModel):
    metadata: dict
    expected_mtime: float | None = None  # optimistic concurrency check


# Canonical AO3-style ratings (Phase 1 validation whitelist).
# Also accept common lowercase short forms seen in existing story.json files
# ("explicit", "mature", etc.) so historical data round-trips cleanly.
_VALID_RATINGS_CANONICAL = {
    "Not Rated",
    "General Audiences",
    "Teen And Up Audiences",
    "Mature",
    "Explicit",
}
_VALID_RATINGS_LOWER = {
    "not rated",
    "general audiences",
    "teen and up audiences",
    "mature",
    "explicit",
    # Historical short forms present in existing story.json files
    "general",
    "teen",
}


def _backup_story_json(sj_path: Path) -> Path | None:
    """Create a timestamped backup of story.json. Keeps the 10 most recent."""
    if not sj_path.is_file():
        return None
    ts = int(time.time())
    backup = sj_path.with_name(f"story.json.bak.{ts}")
    backup.write_text(sj_path.read_text(encoding="utf-8"), encoding="utf-8")
    baks = sorted(
        sj_path.parent.glob("story.json.bak.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in baks[10:]:
        old.unlink(missing_ok=True)
    return backup


@editor_router.get("/stories/{story_name:path}/metadata")
async def get_metadata(story_name: str):
    """Read the story's story.json metadata file."""
    story_dir = _resolve_story_dir(story_name)
    sj = story_dir / "story.json"
    if not sj.is_file():
        raise HTTPException(status_code=404, detail="story.json not found")
    try:
        data = json.loads(sj.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON in story.json: {e}")
    return {
        "metadata": data,
        "last_modified": sj.stat().st_mtime,
    }


@editor_router.put("/stories/{story_name:path}/metadata")
async def save_metadata(story_name: str, req: MetadataSaveRequest):
    """Save the story's story.json with backup + optimistic concurrency check."""
    story_dir = _resolve_story_dir(story_name)
    sj = story_dir / "story.json"

    # Tier 1 validation: title non-empty, rating in whitelist.
    md = req.metadata or {}
    title = (md.get("title") or "").strip() if isinstance(md.get("title"), str) else ""
    if not title:
        raise HTTPException(status_code=400, detail="title must be non-empty")
    rating = md.get("rating")
    if rating is not None and rating != "":
        if not isinstance(rating, str) or rating.strip().lower() not in _VALID_RATINGS_LOWER:
            canonical = ", ".join(sorted(_VALID_RATINGS_CANONICAL))
            raise HTTPException(
                status_code=400,
                detail=f"rating must be one of: {canonical}",
            )

    # Optimistic concurrency check (match save_content pattern).
    if req.expected_mtime is not None and sj.is_file():
        actual_mtime = sj.stat().st_mtime
        if abs(actual_mtime - req.expected_mtime) > 0.5:
            raise HTTPException(
                status_code=409,
                detail="story.json has been modified externally since you loaded it. Reload and merge your changes.",
            )

    # Ensure parent directory exists (story dir always does, but be safe).
    sj.parent.mkdir(parents=True, exist_ok=True)

    # Backup existing file.
    _backup_story_json(sj)

    # Atomic write via temp file.
    tmp = sj.with_name("story.json.tmp")
    tmp.write_text(json.dumps(md, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(sj))

    return {
        "ok": True,
        "last_modified": sj.stat().st_mtime,
    }


# ---------------------------------------------------------------------------
# Phase 4: Chapter detection + merge with stored chapter_info
# ---------------------------------------------------------------------------

@editor_router.get("/stories/{story_name:path}/chapters")
async def get_chapters(story_name: str):
    """Return a merged view of MASTER.md chapter detection + stored
    chapter_info from story.json, along with a drift report.

    The title "chapter" (index 0 — the story-level `# Title` heading) is
    skipped; we only return real story chapters. Returned chapter index
    numbers start at 1 (matching the convention used in story.json).
    """
    from editor.converter import detect_chapters

    story_dir = _resolve_story_dir(story_name)
    master = _get_master_path(story_dir)
    sj = story_dir / "story.json"

    if not master.is_file():
        raise HTTPException(status_code=404, detail="MASTER.md not found")

    md_text = master.read_text(encoding="utf-8")
    md_chapters_all = detect_chapters(md_text)
    # Skip the title heading at index 0 — it's the story title, not a chapter
    md_chapters = md_chapters_all[1:] if len(md_chapters_all) > 1 else []
    md_lines = md_text.split("\n")

    # Load stored chapter_info from story.json (may be missing entirely)
    stored_info: list[dict] = []
    if sj.is_file():
        try:
            raw = json.loads(sj.read_text(encoding="utf-8"))
            ci = raw.get("chapter_info", [])
            if isinstance(ci, list):
                stored_info = ci
        except Exception as e:
            logger.warning("chapters: failed reading chapter_info from %s: %s", sj, e)

    # Build lookup by chapter number. story.json uses 1-based index.
    stored_by_index: dict[int, dict] = {}
    for entry in stored_info:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        if isinstance(idx, int):
            stored_by_index[idx] = entry

    # Build merged chapter rows. MASTER.md is the source of truth for
    # existence; story.json provides description/tags overrides.
    chapters_out: list[dict] = []
    seen_indices: set[int] = set()
    added_in_md: list[dict] = []
    renamed: list[dict] = []

    for slice_i, ch in enumerate(md_chapters):
        # detect_chapters indexes from 0 including the title row. Re-number
        # against our skipped slice so index 1 is the first real chapter.
        chapter_number = slice_i + 1
        md_title = ch.get("title", "") or ""
        seen_indices.add(chapter_number)

        # Word count scoped to this chapter's line range
        line_start = ch.get("line_start", 0)
        line_end = ch.get("line_end", line_start)
        ch_body = "\n".join(md_lines[line_start:line_end + 1])
        words = _word_count(ch_body)

        stored = stored_by_index.get(chapter_number)
        in_metadata = stored is not None

        override_title = ""
        description = ""
        tags: dict = {"default": [], "sofurry": [], "wattpad": []}
        if stored:
            stored_title = stored.get("title")
            if isinstance(stored_title, str) and stored_title.strip():
                override_title = stored_title
            desc = stored.get("description")
            if isinstance(desc, str):
                description = desc
            stored_tags = stored.get("tags")
            if isinstance(stored_tags, dict):
                for k in ("default", "sofurry", "wattpad"):
                    v = stored_tags.get(k)
                    if isinstance(v, list):
                        tags[k] = [str(t) for t in v]

        if in_metadata and override_title and override_title != md_title:
            renamed.append({
                "index": chapter_number,
                "md_title": md_title,
                "stored_title": override_title,
            })

        chapters_out.append({
            "index": chapter_number,
            "title_from_md": md_title,
            "title": override_title or md_title,
            "words": words,
            "description": description,
            "tags": tags,
            "in_md": True,
            "in_metadata": in_metadata,
        })

        if not in_metadata:
            added_in_md.append({"index": chapter_number, "title": md_title})

    # Chapters in stored metadata but no longer in MD
    removed_in_md: list[dict] = []
    for idx, entry in stored_by_index.items():
        if idx in seen_indices:
            continue
        title = entry.get("title") or f"Chapter {idx}"
        tags_raw = entry.get("tags") if isinstance(entry.get("tags"), dict) else {}
        desc = entry.get("description") if isinstance(entry.get("description"), str) else ""
        tags: dict = {"default": [], "sofurry": [], "wattpad": []}
        for k in ("default", "sofurry", "wattpad"):
            v = tags_raw.get(k) if isinstance(tags_raw, dict) else None
            if isinstance(v, list):
                tags[k] = [str(t) for t in v]
        chapters_out.append({
            "index": idx,
            "title_from_md": "",
            "title": title,
            "words": entry.get("words", 0) if isinstance(entry.get("words"), int) else 0,
            "description": desc,
            "tags": tags,
            "in_md": False,
            "in_metadata": True,
        })
        removed_in_md.append({"index": idx, "title": title})

    # Sort output by chapter index for stable rendering
    chapters_out.sort(key=lambda c: c["index"])

    return {
        "chapters": chapters_out,
        "drift": {
            "added_in_md": added_in_md,
            "removed_in_md": removed_in_md,
            "renamed": renamed,
        },
    }


# ---------------------------------------------------------------------------
# Phase 5: Cover image upload + fetch
# ---------------------------------------------------------------------------

_COVER_ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_COVER_MAX_BYTES = 5 * 1024 * 1024  # 5 MB


def _find_existing_cover(story_dir: Path) -> Path | None:
    """Return the Path of an existing cover image referenced in story.json,
    or (fallback) a conventionally named `<stem>_cover.<ext>` in the dir."""
    sj = story_dir / "story.json"
    if sj.is_file():
        try:
            data = json.loads(sj.read_text(encoding="utf-8"))
            images = data.get("images") or {}
            cover = images.get("cover")
            if isinstance(cover, str) and cover.strip():
                candidate = story_dir / cover.strip()
                if candidate.is_file():
                    return candidate
        except Exception:
            pass
    # Fallback: search by conventional name
    stem_lower = story_dir.name.lower()
    for ext in _COVER_ALLOWED_EXTS:
        candidate = story_dir / f"{stem_lower}_cover{ext}"
        if candidate.is_file():
            return candidate
    return None


@editor_router.get("/stories/{story_name:path}/cover")
async def get_cover(story_name: str):
    """Serve the story's cover image file, or 404 if none is present."""
    story_dir = _resolve_story_dir(story_name)
    cover = _find_existing_cover(story_dir)
    if cover is None:
        raise HTTPException(status_code=404, detail="No cover image")
    # Guess media type from extension (FileResponse will also infer)
    ext = cover.suffix.lower()
    media = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(ext, "application/octet-stream")
    return FileResponse(str(cover), media_type=media)


@editor_router.post("/stories/{story_name:path}/cover")
async def upload_cover(story_name: str, file: UploadFile = File(...)):
    """Upload a cover image. Saves to the story directory using an existing
    filename if one is already configured, otherwise `<stem>_cover.<ext>`.

    Returns the filename (relative to the story dir) and byte size. Caller
    is responsible for updating story.json via PUT /metadata."""
    story_dir = _resolve_story_dir(story_name)

    # Validate extension
    orig_name = file.filename or ""
    ext = Path(orig_name).suffix.lower()
    if ext not in _COVER_ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type: {ext or '(none)'} — allowed: {', '.join(sorted(_COVER_ALLOWED_EXTS))}",
        )

    # Read + size-check (stream to memory since limit is small)
    data = await file.read()
    if len(data) > _COVER_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Image too large ({len(data):,} bytes) — max {_COVER_MAX_BYTES:,} bytes",
        )
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Determine destination filename. If story.json already references a
    # cover, reuse its filename (swap extension to match new upload).
    sj = story_dir / "story.json"
    existing_name: str | None = None
    if sj.is_file():
        try:
            raw = json.loads(sj.read_text(encoding="utf-8"))
            images = raw.get("images") or {}
            cover_ref = images.get("cover")
            if isinstance(cover_ref, str) and cover_ref.strip():
                existing_name = cover_ref.strip()
        except Exception:
            existing_name = None

    if existing_name:
        # Preserve stem, swap extension to match uploaded bytes
        dest = story_dir / (Path(existing_name).stem + ext)
    else:
        dest = story_dir / f"{story_dir.name.lower()}_cover{ext}"

    try:
        dest.write_bytes(data)
    except PermissionError:
        raise HTTPException(status_code=500, detail=f"Permission denied writing {dest.name}")

    return {
        "ok": True,
        "filename": dest.name,
        "size": len(data),
    }


class SaveFormatRequest(BaseModel):
    format: str  # clean_html, sofurry_html, bbcode, styled_html
    content: str


@editor_router.put("/stories/{story_name:path}/format-file")
async def save_format_file(story_name: str, req: SaveFormatRequest):
    """Save formatted content directly to the appropriate format file."""
    story_dir = _resolve_story_dir(story_name)
    stem = story_dir.name

    format_paths = {
        "clean_html": story_dir / "HTML" / f"{stem}_Clean.html",
        "sofurry_html": story_dir / "HTML" / f"{stem}_SoFurry.html",
        "bbcode": story_dir / "BBCode" / f"{stem}_bbcode.txt",
        "styled_html": story_dir / "HTML" / f"{stem}_Styled.html",
    }

    path = format_paths.get(req.format)
    if not path:
        raise HTTPException(status_code=400, detail=f"Unknown format: {req.format}")

    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        path.write_text(req.content, encoding="utf-8")
    except PermissionError:
        raise HTTPException(status_code=500, detail=f"Permission denied writing {path.name}")

    return {"ok": True, "file": str(path.relative_to(story_dir)), "bytes": len(req.content)}


class SlopRequest(BaseModel):
    content: str


@editor_router.post("/stories/{story_name:path}/slop")
async def slop_score(story_name: str, req: SlopRequest):
    """Run the slop scorer on the provided content."""
    from editor.slop import score_text
    result = score_text(req.content)
    return {
        "score": result.score,
        "rating": result.rating,
        "word_count": result.word_count,
        "word_hits": dict(sorted(result.word_hits.items(), key=lambda x: -x[1])[:20]),
        "trigram_hits": dict(sorted(result.trigram_hits.items(), key=lambda x: -x[1])[:10]),
        "contrast_count": result.contrast_count,
    }


# ---------------------------------------------------------------------------
# Tag database (Phase 3a — autocomplete)
# ---------------------------------------------------------------------------

# Bundled e621-derived tag database. Shipped with the repo under
# PawPoller/tag_database/ — NOT under data/ because /app/data is volume-mounted
# in Docker (would shadow bundled files).
_TAG_DB_DIR = Path(__file__).resolve().parent.parent / "tag_database"

# Files → category label exposed to the frontend.
_TAG_DB_FILES = [
    ("tag_database_physical.txt", "physical"),
    ("tag_database_acts.txt", "acts"),
    ("tag_database_kink.txt", "kink"),
    ("tag_database_meta.txt", "meta"),
    ("tag_database_image.txt", "image"),
]

_TAG_ALIASES_FILE = "tag_aliases.json"

# In-process cache of the parsed + flattened tag DB. Populated on first
# request, reused afterwards.  Keyed by version hash so if someone hot-swaps
# files on disk the cache self-invalidates.
_TAG_DB_CACHE: dict | None = None


def _parse_tag_db_file(text: str, category: str) -> list[dict]:
    """Parse a tag DB text file into a list of {name, category, section, desc}.

    Format (roughly):

        TAG DATABASE: ...
        ========================================
        ...header lines...

        ================================================================================
        SECTION NAME
        ================================================================================
        tag_name | description
        other_tag | other description
        ...

        ================================================================================
        NEXT SECTION
        ================================================================================
        ...

    We skip the file preamble (before the first `===...===` fence pair),
    track the active section via the text line sandwiched between `===`
    fences, and emit one entry per `name | desc` line.
    """
    lines = text.splitlines()
    entries: list[dict] = []
    section = ""
    i = 0
    n = len(lines)
    # Fence rows are runs of 40+ `=` characters.
    fence_re = re.compile(r"^={40,}\s*$")

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Detect a fenced section header: fence / text / fence
        if fence_re.match(stripped) and i + 2 < n and fence_re.match(lines[i + 2].strip()):
            section = lines[i + 1].strip()
            i += 3
            continue

        # Skip blank + comment lines
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # Skip standalone fence lines (shouldn't happen after pairing above,
        # but some files have a trailing `===` without a text row)
        if fence_re.match(stripped):
            i += 1
            continue

        # Skip the file-header preamble (lines without `|` encountered before
        # we've set a section — e.g., "Total tags: 4354").
        if "|" not in stripped:
            i += 1
            continue

        # Parse `name | desc` rows
        name, _, desc = stripped.partition("|")
        name = name.strip()
        desc = desc.strip()
        if not name:
            i += 1
            continue

        entries.append({
            "name": name,
            "category": category,
            "section": section,
            "desc": desc,
        })
        i += 1

    return entries


def _compute_tag_db_version() -> str | None:
    """SHA256 over all tag DB file bytes.  Returns None if the directory is
    missing (so the endpoint can surface a clean error)."""
    if not _TAG_DB_DIR.is_dir():
        return None
    h = hashlib.sha256()
    missing_any = True
    for fname, _cat in _TAG_DB_FILES:
        p = _TAG_DB_DIR / fname
        if p.is_file():
            missing_any = False
            # Include filename so reordering/renaming perturbs the hash
            h.update(fname.encode("utf-8"))
            h.update(p.read_bytes())
    aliases_path = _TAG_DB_DIR / _TAG_ALIASES_FILE
    if aliases_path.is_file():
        missing_any = False
        h.update(_TAG_ALIASES_FILE.encode("utf-8"))
        h.update(aliases_path.read_bytes())
    if missing_any:
        return None
    return h.hexdigest()


def _load_tag_db() -> dict:
    """Parse + cache the full tag DB. Returned dict is the exact payload
    shipped to the frontend."""
    global _TAG_DB_CACHE

    version = _compute_tag_db_version()
    if _TAG_DB_CACHE is not None and _TAG_DB_CACHE.get("version") == version:
        return _TAG_DB_CACHE

    if version is None or not _TAG_DB_DIR.is_dir():
        raise HTTPException(
            status_code=500,
            detail=f"Tag database not found at {_TAG_DB_DIR}",
        )

    tags: list[dict] = []
    for fname, category in _TAG_DB_FILES:
        p = _TAG_DB_DIR / fname
        if not p.is_file():
            logger.warning("Tag DB file missing: %s", p)
            continue
        try:
            txt = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            txt = p.read_text(encoding="utf-8", errors="replace")
        try:
            parsed = _parse_tag_db_file(txt, category)
            tags.extend(parsed)
            logger.info("Tag DB: loaded %d tags from %s", len(parsed), fname)
        except Exception as e:
            logger.error("Tag DB: failed parsing %s: %s", fname, e)

    aliases: dict = {}
    aliases_path = _TAG_DB_DIR / _TAG_ALIASES_FILE
    if aliases_path.is_file():
        try:
            aliases = json.loads(aliases_path.read_text(encoding="utf-8"))
            if not isinstance(aliases, dict):
                logger.warning("Tag DB: tag_aliases.json is not an object, ignoring")
                aliases = {}
        except Exception as e:
            logger.error("Tag DB: failed reading tag_aliases.json: %s", e)

    payload = {
        "tags": tags,
        "aliases": aliases,
        "version": version,
    }
    _TAG_DB_CACHE = payload
    logger.info(
        "Tag DB: cached %d tags, %d aliases (version=%s)",
        len(tags), len(aliases), version[:12] if version else "?",
    )
    return payload


@editor_router.get("/tags")
async def get_tag_database():
    """Return the full bundled tag database + alias map for the autocomplete
    frontend.

    Response shape:
        {
          "tags":    [{"name": "raccoon", "category": "physical",
                       "section": "SPECIES & BODY TYPE", "desc": "..."}, ...],
          "aliases": {"boobs": "breasts", ...},
          "version": "<sha256>"
        }

    Parsed once per process (keyed by version hash) and served from memory
    afterwards.  FastAPI auto-gzips so ~2MB raw lands as ~400KB on the wire.
    """
    return _load_tag_db()
