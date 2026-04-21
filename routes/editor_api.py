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

import config
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
    skip_pdf: bool = False  # WeasyPrint is fast enough to be on by default
    formats: list[str] | None = None  # None = all, or subset of: html, bbcode, styled, sqw, pdf, chapters


class CreateStoryRequest(BaseModel):
    name: str            # Folder name (e.g. "My_New_Story")
    title: str           # Display title (e.g. "My New Story")
    author: str = ""
    chapters: int = 1    # Initial chapter count
    rating: str = "explicit"  # general, mature, explicit
    genre: str = ""      # Optional genre template preset
    file_content: str = ""   # Optional uploaded file content
    file_format: str = ""    # File extension: md, txt, html, bbcode, rtf


# ---------------------------------------------------------------------------
# Simple format converters for file upload in Create Story
# ---------------------------------------------------------------------------

def _convert_html_to_md(html: str) -> str:
    """Basic HTML to Markdown: strip tags, preserve structure."""
    text = re.sub(r'<br\s*/?\s*>', '\n', html)
    text = re.sub(r'<p[^>]*>', '\n\n', text)
    text = re.sub(r'</p>', '', text)
    text = re.sub(r'<h([1-6])[^>]*>(.*?)</h\1>', lambda m: '#' * int(m.group(1)) + ' ' + m.group(2), text)
    text = re.sub(r'<strong>(.*?)</strong>', r'**\1**', text)
    text = re.sub(r'<b>(.*?)</b>', r'**\1**', text)
    text = re.sub(r'<em>(.*?)</em>', r'*\1*', text)
    text = re.sub(r'<i>(.*?)</i>', r'*\1*', text)
    text = re.sub(r'<hr\s*/?\s*>', '\n---\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    from html import unescape
    text = unescape(text)
    return text.strip()


def _convert_bbcode_to_md(bbcode: str) -> str:
    """Basic BBCode to Markdown."""
    text = re.sub(r'\[b\](.*?)\[/b\]', r'**\1**', bbcode, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\[i\](.*?)\[/i\]', r'*\1*', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\[u\](.*?)\[/u\]', r'\1', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\[url=([^\]]+)\](.*?)\[/url\]', r'[\2](\1)', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\[url\](.*?)\[/url\]', r'\1', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\[hr\]', '\n---\n', text, flags=re.IGNORECASE)
    text = re.sub(r'\[(?:size|color|font|quote|center|right|left)[^\]]*\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[/(?:size|color|font|quote|center|right|left)\]', '', text, flags=re.IGNORECASE)
    return text.strip()


def _strip_rtf(rtf: str) -> str:
    """Strip RTF control codes to extract plain text."""
    text = re.sub(r'\{\\[^}]+\}', '', rtf)
    text = re.sub(r'\\[a-z]+\d*\s?', '', text)
    text = re.sub(r'[{}]', '', text)
    return text.strip()


# ---------------------------------------------------------------------------
# Genre template presets — pre-fill tags, rating, warnings, category
# ---------------------------------------------------------------------------

GENRE_TEMPLATES = {
    "romance": {
        "tags": ["romance", "love", "relationship", "emotional", "passion", "first_kiss", "dating", "affection"],
        "rating": "mature",
        "warnings": [],
        "category": "F/M",
    },
    "erotica": {
        "tags": ["erotica", "explicit", "sexual_content", "nsfw", "adult", "passion", "desire", "intimacy"],
        "rating": "explicit",
        "warnings": [],
        "category": "F/M",
    },
    "adventure": {
        "tags": ["adventure", "action", "quest", "journey", "exploration", "danger", "heroism", "travel"],
        "rating": "general",
        "warnings": [],
        "category": "Gen",
    },
    "comedy": {
        "tags": ["comedy", "humor", "funny", "lighthearted", "jokes", "slapstick", "witty_dialogue"],
        "rating": "general",
        "warnings": [],
        "category": "Gen",
    },
    "drama": {
        "tags": ["drama", "emotional", "conflict", "tension", "character_development", "angst", "relationships"],
        "rating": "mature",
        "warnings": [],
        "category": "Gen",
    },
    "fantasy": {
        "tags": ["fantasy", "magic", "mythical", "supernatural", "worldbuilding", "quest", "enchantment"],
        "rating": "general",
        "warnings": [],
        "category": "Gen",
    },
    "sci_fi": {
        "tags": ["science_fiction", "technology", "futuristic", "space", "cyberpunk", "artificial_intelligence"],
        "rating": "general",
        "warnings": [],
        "category": "Gen",
    },
    "slice_of_life": {
        "tags": ["slice_of_life", "everyday", "mundane", "character_study", "friendship", "daily_life", "cozy"],
        "rating": "general",
        "warnings": [],
        "category": "Gen",
    },
    "horror": {
        "tags": ["horror", "dark", "suspense", "fear", "thriller", "gore", "psychological_horror"],
        "rating": "mature",
        "warnings": ["Graphic Depictions Of Violence"],
        "category": "Gen",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SKIP_DIRS = {"Reference_Guides"}


def _resolve_story_dir(story_name: str) -> Path:
    """Resolve a story name to its directory. Handles versioned stories
    like 'The_Abstinent_Bet/Nice_Version' via the :path converter."""
    archive = get_archive_path()
    candidate = (archive / story_name).resolve()
    try:
        candidate.relative_to(archive.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid story path")
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


@editor_router.get("/genre-templates")
async def genre_templates():
    """Return available genre template presets for the create-story wizard."""
    return {"templates": GENRE_TEMPLATES}


@editor_router.post("/stories/create")
async def create_story(req: CreateStoryRequest):
    """Create a new story with folder structure and template files."""
    # Validate name: only alphanumeric + underscore, no leading/trailing spaces
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Story name cannot be empty")
    if not re.match(r'^[A-Za-z0-9_]+$', name):
        raise HTTPException(
            status_code=400,
            detail="Story name may only contain letters, digits, and underscores",
        )
    if len(name) > 200:
        raise HTTPException(status_code=400, detail="Story name too long (max 200 chars)")

    title = req.title.strip() or name.replace("_", " ")
    author = req.author.strip()
    chapters = max(1, min(req.chapters, 20))

    # Resolve genre template (if any) before rating so template can supply default
    genre = req.genre.strip().lower()
    genre_tmpl = GENRE_TEMPLATES.get(genre, {})

    # User-supplied rating takes priority; fall back to genre template default
    rating = req.rating.strip().lower()
    if rating not in ("general", "mature", "explicit"):
        rating = genre_tmpl.get("rating", "explicit")

    archive = get_archive_path()
    story_dir = archive / name

    if story_dir.exists():
        raise HTTPException(status_code=409, detail=f"Story '{name}' already exists")

    # Create directory structure
    dirs = [
        story_dir / "Markdown",
        story_dir / "BBCode",
        story_dir / "HTML",
        story_dir / "PDF",
        story_dir / "SquidgeWorld",
        story_dir / "Chapters" / "Markdown",
        story_dir / "Chapters" / "BBCode",
        story_dir / "Chapters" / "SoFurry_HTML",
        story_dir / "Chapters" / "Styled_HTML",
        story_dir / "Chapters" / "PDF",
        story_dir / "Images",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # Generate template MASTER.md
    chapter_blocks = ""
    if chapters > 1:
        for i in range(2, chapters + 1):
            chapter_blocks += f"""
---

# Chapter {i}: Untitled

Continue your story here...
"""

    master_content = f"""<!-- @title -->
# {title}

<!-- @subtitle -->
*A story subtitle goes here*

<!-- @byline -->
by {author or 'Author Name'}

<!-- @warning -->
Content warnings go here.

<!-- @disclaimer -->
This is a work of fiction. All characters are fictional.

<!-- @body -->

Your story begins here. Everything above the @body anchor is front
matter — it appears in styled formats but not in plain BBCode.

## Using Section Breaks

Use `---` on its own line to create a section break (renders as * * *).

---

## Text Messages

<!-- @text-sent -->
This appears as an outgoing text message bubble.
<!-- @text-end -->

<!-- @text-received -->
This appears as an incoming text message bubble.
<!-- @text-end -->

## Phone Screens

<!-- @phone -->
Content inside a phone screen frame.
<!-- @phone-end -->

## Chapter Breaks

Use `---` followed by `# Chapter N: Title` to start a new chapter.
{chapter_blocks}
<!-- @story-end -->
"""

    # If user uploaded a file, use its content instead of the template
    if req.file_content:
        imported = req.file_content
        fmt = req.file_format.lower()
        if fmt in ("html", "htm"):
            imported = _convert_html_to_md(imported)
        elif fmt == "bbcode":
            imported = _convert_bbcode_to_md(imported)
        elif fmt == "rtf":
            imported = _strip_rtf(imported)
        # md and txt are used as-is

        master_content = f"""<!-- @title -->
# {title}

<!-- @byline -->
by {author or 'Author Name'}

<!-- @body -->

{imported}

<!-- @story-end -->
"""

    (story_dir / "Markdown" / "MASTER.md").write_text(master_content, encoding="utf-8")

    # Generate story.json — merge genre template if one was selected
    story_json = {
        "title": title,
        "author": author,
        "description": "",
        "summary": "",
        "rating": rating,
        "category": genre_tmpl.get("category", ""),
        "fandom": "Original Work",
        "genre": genre if genre_tmpl else "",
        "warnings": list(genre_tmpl.get("warnings", [])),
        "characters": [],
        "relationships": [],
        "word_count": 0,
        "chapters": chapters,
        "tags": {"default": list(genre_tmpl.get("tags", []))},
        "chapter_info": [],
        "formats": {"bbcode": True, "html": True, "markdown": True, "squidgeworld": True},
        "images": {"cover": ""},
    }
    (story_dir / "story.json").write_text(
        json.dumps(story_json, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Copy CHAPTER_STYLING.md from Reference_Guides if available
    styling_src = archive / "Reference_Guides" / "Styling" / "HTML_CSS" / "STYLING_REFERENCE.md"
    styling_dest = story_dir / "CHAPTER_STYLING.md"
    if styling_src.is_file():
        try:
            styling_dest.write_text(styling_src.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            # Fallback: write a minimal placeholder
            styling_dest.write_text(
                "# Chapter Styling\n\nCopy STYLING_REFERENCE.md here or configure theme variables.\n",
                encoding="utf-8",
            )
    else:
        styling_dest.write_text(
            "# Chapter Styling\n\nCopy STYLING_REFERENCE.md here or configure theme variables.\n",
            encoding="utf-8",
        )

    logger.info("Created new story: %s at %s", name, story_dir)
    return {"ok": True, "story_name": name}


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

    # Format selector: None = generate everything, or a subset list
    should_gen = lambda fmt: req.formats is None or fmt in req.formats

    stem = story_dir.name
    html_dir = story_dir / "HTML"
    bb_dir = story_dir / "BBCode"
    html_dir.mkdir(exist_ok=True)
    bb_dir.mkdir(exist_ok=True)

    # --- Full-story Clean HTML ---
    if should_gen("html"):
        try:
            html_result = convert(content, "clean_html")
            (html_dir / f"{stem}_Clean.html").write_text(html_result.output, encoding="utf-8")
            results.append(f"HTML/{stem}_Clean.html ({len(html_result.output):,} bytes)")
        except Exception as e:
            errors.append(f"Clean HTML: {e}")

    # --- Full-story SoFurry HTML ---
    if should_gen("html"):
        try:
            sf_result = convert(content, "sofurry_html")
            (html_dir / f"{stem}_SoFurry.html").write_text(sf_result.output, encoding="utf-8")
            results.append(f"HTML/{stem}_SoFurry.html ({len(sf_result.output):,} bytes)")
        except Exception as e:
            errors.append(f"SoFurry HTML: {e}")

    # --- Full-story BBCode ---
    if should_gen("bbcode"):
        try:
            bb_result = convert(content, "bbcode")
            (bb_dir / f"{stem}_bbcode.txt").write_text(bb_result.output, encoding="utf-8")
            results.append(f"BBCode/{stem}_bbcode.txt ({len(bb_result.output):,} bytes)")
        except Exception as e:
            errors.append(f"BBCode: {e}")

    # --- SquidgeWorld chapters (from anchored source) ---
    if should_gen("sqw"):
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
    if should_gen("styled"):
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

    # --- PDF (full + per-chapter) ---
    if should_gen("pdf") and not req.skip_pdf:
        try:
            from editor.pdf_generator import html_to_pdf, get_backend
            backend = get_backend()
            if backend == "none":
                errors.append("PDF: no backend available (WeasyPrint not installed and Edge not found)")
            else:
                pdf_dir = story_dir / "PDF"
                pdf_dir.mkdir(exist_ok=True)
                pdf_count = 0

                full_styled = html_dir / f"{stem}_Styled.html"
                if full_styled.is_file():
                    full_pdf = pdf_dir / f"{stem}.pdf"
                    ok, _ = html_to_pdf(full_styled, full_pdf)
                    if ok:
                        pdf_count += 1
                    else:
                        errors.append(f"PDF: full-story render failed ({backend})")

                ch_styled_dir = story_dir / "Chapters" / "Styled_HTML"
                ch_pdf_dir = story_dir / "Chapters" / "PDF"
                if ch_styled_dir.is_dir():
                    ch_pdf_dir.mkdir(parents=True, exist_ok=True)
                    for ch_html in sorted(ch_styled_dir.glob("Chapter_*.html")):
                        ch_pdf = ch_pdf_dir / (ch_html.stem + ".pdf")
                        ok, _ = html_to_pdf(ch_html, ch_pdf)
                        if ok:
                            pdf_count += 1
                        else:
                            errors.append(f"PDF: {ch_html.name} render failed ({backend})")

                if pdf_count:
                    results.append(f"PDF: {pdf_count} file(s) generated via {backend}")
        except Exception as e:
            errors.append(f"PDF: {e}")

    # --- Chapter splits (Markdown, SoFurry HTML, BBCode) ---
    if should_gen("chapters"):
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

                # Chapter SoFurry HTML — use the body converter directly so
                # semantic anchors (text-sent, text-received, phone, etc.)
                # get processed. The top-level convert() falls through to the
                # heuristic parser for fragments without <!-- @body -->, which
                # escapes anchors as literal HTML.
                try:
                    from editor.converter import _convert_body_clean_html, ConversionResult
                    ch_lines = ch_content.split("\n")
                    ch_parts, ch_stats = _convert_body_clean_html(ch_lines, 0)
                    ch_html_output = "\n".join(ch_parts)
                    (sf_dir / f"{ch_filename}.html").write_text(ch_html_output, encoding="utf-8")
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


# ---------------------------------------------------------------------------
# Publishability check (Phase 6a — read-only validation matrix)
# ---------------------------------------------------------------------------

# Platform display order + labels for the matrix
PUBLISH_PLATFORMS = [
    ("ib", "Inkbunny"),
    ("fa", "FurAffinity"),
    ("ws", "Weasyl"),
    ("sf", "SoFurry"),
    ("sqw", "SquidgeWorld"),
    ("ao3", "AO3"),
    ("da", "DeviantArt"),
    ("ik", "Itaku"),
    ("bsky", "Bluesky"),
]


@editor_router.get("/stories/{story_name:path}/publish-check")
async def publish_check(story_name: str):
    """Validate every (chapter × platform) combination against its poster.

    Returns a matrix of cells, each describing whether that combination is
    ready to post, blocked by validation errors, or already published.
    No HTTP requests are made to external platforms — this is pure local
    validation + a read of the publications registry.
    """
    from posting import story_reader, manager
    from posting.sync import hash_file
    from database.db import get_connection
    from database import posting_queries

    # Resolve the canonical story name (the editor passes the URL-safe form,
    # but story_reader works off the archive folder name).
    story_dir = _resolve_story_dir(story_name)
    canonical = str(story_dir.relative_to(get_archive_path()))

    try:
        story = story_reader.load_story(canonical)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Story not found: {e}")

    # Build row list. Always include the "Full story" row (index 0).
    # For chaptered stories, follow it with per-chapter rows so the user
    # can choose to post the whole work as one submission OR split into
    # chapters (some platforms prefer one mode over the other).
    chapters = [{"index": 0, "title": story.title or canonical, "kind": "full"}]
    if story.total_chapters > 0:
        for i in range(1, story.total_chapters + 1):
            chapters.append({
                "index": i,
                "title": story.chapters[i - 1].title,
                "kind": "chapter",
            })

    # Pre-load existing publications keyed by (chapter, platform)
    conn = get_connection()
    try:
        pubs = posting_queries.get_publications(conn, story_name=canonical)
    finally:
        conn.close()
    pub_map = {(p["chapter_index"], p["platform"]): p for p in pubs}

    # OTW-Archive-family platforms post the whole work as one submission
    # containing N chapters. Posting a single lone chapter to one of these
    # platforms isn't a concept — you post the work. Per-chapter rows for
    # these get marked not_supported; the full-story row is the actionable
    # one (and internally handles multi-chapter creation).
    WORK_ORIENTED = {"ao3", "sqw", "sf"}

    # Required credentials per platform — if any key is empty/missing,
    # the platform is shown as "no_credentials" instead of "blocked".
    PLATFORM_CREDS = {
        "ib":   ("username", "password"),
        "fa":   ("fa_cookie_a", "fa_cookie_b"),
        "ws":   ("ws_api_key",),
        "sf":   ("sf_username", "sf_password"),
        "sqw":  ("sqw_author_username", "sqw_author_password"),
        "ao3":  ("ao3_username", "ao3_password"),
        "da":   ("da_cookie",),
        "ik":   (),
        "bsky": ("bsky_identifier", "bsky_app_password"),
    }
    settings = config.get_settings()
    platform_has_creds = {}
    for plat_id, _ in PUBLISH_PLATFORMS:
        required = PLATFORM_CREDS.get(plat_id, ())
        platform_has_creds[plat_id] = all(
            settings.get(k) for k in required
        ) if required else True

    # Build the matrix
    matrix = []
    for ch in chapters:
        row = {
            "chapter_index": ch["index"],
            "chapter_title": ch["title"],
            "kind": ch.get("kind", "chapter"),
            "cells": {},
        }
        for plat_id, _ in PUBLISH_PLATFORMS:
            # No credentials configured — show as unavailable
            if not platform_has_creds[plat_id]:
                row["cells"][plat_id] = {
                    "status": "no_credentials",
                    "errors": ["No credentials configured — set up in Settings"],
                }
                continue

            # Work-oriented platforms: per-chapter rows aren't valid; use
            # the full-story row instead. Only applies to chaptered stories
            # (single-chapter stories only have the full-story row anyway).
            if (
                ch["index"] > 0
                and plat_id in WORK_ORIENTED
                and story.total_chapters > 0
            ):
                row["cells"][plat_id] = {
                    "status": "not_supported",
                    "errors": ["Platform posts a whole work at once — use the Full story row"],
                }
                continue

            try:
                poster = manager._get_poster(plat_id)
            except Exception as e:
                row["cells"][plat_id] = {
                    "status": "error",
                    "errors": [f"Poster init failed: {e}"],
                }
                continue

            try:
                package = story_reader.build_package(story, ch["index"], plat_id)
            except Exception as e:
                row["cells"][plat_id] = {
                    "status": "error",
                    "errors": [f"Package build failed: {e}"],
                }
                continue

            errors = poster.validate(package)
            existing = pub_map.get((ch["index"], plat_id))

            cell = {
                "errors": errors,
                "title": package.title,
                "tag_count": len(package.tags),
                "file_path": package.file_path or "",
                "file_size": (
                    os.path.getsize(package.file_path)
                    if package.file_path and os.path.isfile(package.file_path)
                    else 0
                ),
                "requires_mode": poster.requires_mode,
                "max_file_size": poster.max_file_size,
                "supports_edit": poster.supports_edit,
            }

            if existing:
                # Detect content drift — has the local file changed since
                # the last successful post? If so, the user should hit
                # Update to push the fresh content. We only check this for
                # rows that have a file; tag-only platforms (Bsky, Itaku)
                # store an empty file_hash and we skip the check.
                drift = False
                if (
                    existing["status"] == "posted"
                    and package.file_path
                    and os.path.isfile(package.file_path)
                    and existing.get("file_hash")
                ):
                    current_hash = hash_file(package.file_path)
                    if current_hash and current_hash != existing["file_hash"]:
                        drift = True

                cell["existing"] = {
                    "status": existing["status"],
                    "external_id": existing["external_id"],
                    "external_url": existing["external_url"],
                    "posted_at": existing.get("created_at"),
                    "updated_at": existing.get("updated_at"),
                    "file_hash": existing.get("file_hash", ""),
                    "drifted": drift,
                }
                if existing["status"] == "deleted":
                    # Submission no longer exists on the platform — treat
                    # the cell as re-postable but keep the history visible.
                    cell["status"] = "deleted_upstream" if not errors else "blocked"
                elif existing["status"] == "posted":
                    if errors:
                        cell["status"] = "posted_stale"
                    elif drift:
                        cell["status"] = "posted_drifted"
                    else:
                        cell["status"] = "posted"
                else:
                    cell["status"] = "failed_prev" if errors else "ready_retry"
            else:
                cell["status"] = "ready" if not errors else "blocked"

            row["cells"][plat_id] = cell

        matrix.append(row)

    # ---- Regeneration staleness check ----
    # Compare MASTER.md mtime against the newest generated format file.
    # If MASTER.md is newer, the user may be about to publish stale content.
    regen_stale = False
    master_mtime: float | None = None
    newest_gen_mtime: float | None = None
    master_path = _get_master_path(story_dir)
    if master_path.is_file():
        master_mtime = master_path.stat().st_mtime
        gen_dirs = ["HTML", "BBCode", "SquidgeWorld", "PDF", "Styled_HTML"]
        for dname in gen_dirs:
            d = story_dir / dname
            if not d.is_dir():
                continue
            for f in d.iterdir():
                if f.is_file():
                    fmt = f.stat().st_mtime
                    if newest_gen_mtime is None or fmt > newest_gen_mtime:
                        newest_gen_mtime = fmt
        if newest_gen_mtime is not None and master_mtime > newest_gen_mtime:
            regen_stale = True

    resp: dict = {
        "ok": True,
        "story_name": canonical,
        "story_title": story.title or canonical,
        "total_chapters": story.total_chapters,
        "platforms": [{"id": pid, "name": pname} for pid, pname in PUBLISH_PLATFORMS],
        "chapters": chapters,
        "matrix": matrix,
    }
    if regen_stale:
        resp["regen_stale"] = True
        resp["master_mtime"] = master_mtime
        resp["newest_gen_mtime"] = newest_gen_mtime
    return resp


@editor_router.post("/stories/{story_name:path}/verify")
async def verify_publications(story_name: str):
    """Probe every posted publication for this story to detect upstream deletions.

    Calls each poster's ``probe_exists()`` — platforms that haven't
    implemented probing return None and are left alone. Publications
    confirmed missing are flipped to ``status='deleted'`` in the registry
    so the matrix shows them as re-postable.
    """
    import asyncio
    from posting import story_reader, manager
    from database.db import get_connection
    from database import posting_queries

    story_dir = _resolve_story_dir(story_name)
    canonical = str(story_dir.relative_to(get_archive_path()))

    conn = get_connection()
    try:
        posted = posting_queries.get_publications(conn, story_name=canonical, status="posted")
    finally:
        conn.close()

    results = []
    for pub_idx, pub in enumerate(posted):
        # Light rate limit between probes — each is an authenticated HTTP
        # round-trip and we don't want to hammer a platform on a 20-chapter
        # story. First probe fires immediately.
        if pub_idx > 0:
            await asyncio.sleep(0.4)
        plat = pub["platform"]
        ext_id = pub["external_id"]
        ch_idx = pub["chapter_index"]
        if not ext_id:
            continue
        try:
            poster = manager._get_poster(plat)
        except Exception:
            continue

        try:
            exists = await poster.probe_exists(ext_id)
        except Exception as e:
            # Belt-and-braces — probe_exists() is supposed to swallow its own
            # errors and return None, but if a poster raises anyway we don't
            # want one bad platform to crash the whole verify loop.
            logger.warning(
                "Verify: %s ch%d on %s probe raised: %s — treating as not_probed",
                canonical, ch_idx, plat, e,
            )
            results.append({
                "platform": plat, "chapter_index": ch_idx,
                "external_id": ext_id, "status": "not_probed",
            })
            continue
        if exists is None:
            results.append({
                "platform": plat, "chapter_index": ch_idx,
                "external_id": ext_id, "status": "not_probed",
            })
            continue
        if exists:
            results.append({
                "platform": plat, "chapter_index": ch_idx,
                "external_id": ext_id, "status": "still_live",
            })
            continue

        # Confirmed deleted — flip registry
        conn = get_connection()
        try:
            posting_queries.upsert_publication(
                conn, canonical, ch_idx, plat,
                external_id=ext_id,
                external_url=pub["external_url"],
                title_used=pub.get("title_used") or "",
                description_used=pub.get("description_used") or "",
                tags_used=(pub.get("tags_used") or "").split(",") if pub.get("tags_used") else [],
                rating_used=pub.get("rating_used") or "",
                format_file=pub.get("format_file") or "",
                file_hash=pub.get("file_hash") or "",
                word_count=pub.get("word_count") or 0,
                status="deleted",
            )
        finally:
            conn.close()
        results.append({
            "platform": plat, "chapter_index": ch_idx,
            "external_id": ext_id, "status": "deleted",
        })
        logger.info("Verify: %s ch%d on %s deleted upstream (id=%s)",
                    canonical, ch_idx, plat, ext_id)

    summary = {
        "ok": True,
        "probed": len(results),
        "deleted": sum(1 for r in results if r["status"] == "deleted"),
        "still_live": sum(1 for r in results if r["status"] == "still_live"),
        "not_probed": sum(1 for r in results if r["status"] == "not_probed"),
        "results": results,
    }
    return summary


class PublishRequest(BaseModel):
    platform: str                 # 'sf', 'ib', 'fa', etc.
    chapter: int                  # 0 = full story; 1+ = specific chapter
    action: str = "post"          # 'post' | 'update' | 'update_metadata' | 'dry_run'
    draft: bool = True            # SF/SQW/AO3 etc. — post as draft if supported
    confirm_live: bool = False    # Must be True for non-dry-run actions


@editor_router.post("/stories/{story_name:path}/publish")
async def publish(story_name: str, req: PublishRequest):
    """Post or update a single (chapter × platform) combination.

    Phase 6b — single-platform action endpoint. The matrix UI calls this
    when the user clicks Post/Update on a specific cell. Front-end MUST
    set ``confirm_live=True`` for non-dry-run actions; this is a
    server-side guard in case the UI bypass is forgotten.

    For ``action='dry_run'`` we build the package and validate without
    making any external HTTP calls — useful for inspecting the exact
    payload that would be posted.
    """
    from posting import story_reader, manager
    from database.db import get_connection
    from database import posting_queries

    story_dir = _resolve_story_dir(story_name)
    canonical = str(story_dir.relative_to(get_archive_path()))

    if req.action not in ("post", "update", "update_metadata", "dry_run"):
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")

    if req.action in ("post", "update", "update_metadata") and not req.confirm_live:
        raise HTTPException(
            status_code=400,
            detail=f"action='{req.action}' requires confirm_live=true (safety guard)",
        )

    extras: dict = {}
    if req.draft:
        extras["draft"] = True
    if req.action == "update_metadata":
        extras["skip_content_refresh"] = True

    # --- Dry run: just rebuild the package and validate, return as JSON ---
    if req.action == "dry_run":
        story = story_reader.load_story(canonical)
        try:
            poster = manager._get_poster(req.platform)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Unknown platform: {e}")
        package = story_reader.build_package(story, req.chapter, req.platform)
        package.extra.update(extras)
        errors = poster.validate(package)
        return {
            "ok": not errors,
            "action": "dry_run",
            "platform": req.platform,
            "chapter": req.chapter,
            "errors": errors,
            "package": {
                "title": package.title,
                "description": package.description,
                "tags": package.tags,
                "rating": package.rating,
                "file_path": package.file_path,
                "file_size": (
                    os.path.getsize(package.file_path)
                    if package.file_path and os.path.isfile(package.file_path)
                    else 0
                ),
                "word_count": package.word_count,
                "extra": package.extra,
            },
        }

    # --- Real action ---
    if req.action == "post":
        results = await manager.post_story(
            canonical,
            platforms=[req.platform],
            chapters=[req.chapter],
            extras=extras,
        )
    else:  # update / update_metadata — both route through update_story
        results = await manager.update_story(
            canonical,
            platforms=[req.platform],
            chapters=[req.chapter],
            extras=extras,
        )

    return {
        "ok": all(r.get("success") for r in results),
        "action": req.action,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Scheduling (Phase 6f — deferred publish via posting_queue)
# ---------------------------------------------------------------------------

class ScheduleRequest(BaseModel):
    platform: str                 # 'sf', 'ib', 'fa', etc.
    chapter: int                  # 0 = full story; 1+ = specific chapter
    action: str = "post"          # 'post' | 'update'
    scheduled_at: str             # ISO 8601 datetime string
    draft: bool = True


@editor_router.post("/stories/{story_name:path}/schedule")
async def schedule_publish(story_name: str, req: ScheduleRequest):
    """Schedule a post/update for a future date/time.

    Validates the story exists and the platform/chapter is valid, then
    inserts a row into the posting_queue with a scheduled_at timestamp.
    The posting scheduler daemon picks it up when the time arrives.
    """
    from datetime import datetime, timezone
    from posting import story_reader, manager
    from database.db import get_connection
    from database import posting_queries

    story_dir = _resolve_story_dir(story_name)
    canonical = str(story_dir.relative_to(get_archive_path()))

    if req.action not in ("post", "update"):
        raise HTTPException(status_code=400, detail=f"Schedulable actions: post, update (got '{req.action}')")

    # Validate the scheduled time
    try:
        scheduled_dt = datetime.fromisoformat(req.scheduled_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format — use ISO 8601")

    # Ensure the time is in the future (with 30s grace for clock skew)
    now = datetime.now(timezone.utc)
    if scheduled_dt.tzinfo is None:
        # Treat naive datetimes as UTC
        scheduled_dt = scheduled_dt.replace(tzinfo=timezone.utc)
    if (scheduled_dt - now).total_seconds() < -30:
        raise HTTPException(status_code=400, detail="Scheduled time must be in the future")

    # Validate story + platform + chapter
    try:
        story = story_reader.load_story(canonical)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Story not found: {e}")

    try:
        poster = manager._get_poster(req.platform)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {e}")

    try:
        package = story_reader.build_package(story, req.chapter, req.platform)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Package build failed: {e}")

    errors = poster.validate(package)
    if errors:
        raise HTTPException(status_code=400, detail=f"Validation errors: {'; '.join(errors)}")

    # Format scheduled_at as UTC string for SQLite
    scheduled_str = scheduled_dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Determine runtime requirement from the poster
    requires = getattr(poster, "requires_mode", "any")

    conn = get_connection()
    try:
        queue_id = posting_queries.add_to_queue(
            conn,
            canonical,
            req.chapter,
            req.platform,
            action=req.action,
            scheduled_at=scheduled_str,
            requires=requires,
        )
    finally:
        conn.close()

    logger.info(
        "Scheduled queue item #%d: %s %s ch%d on %s at %s",
        queue_id, req.action, canonical, req.chapter, req.platform, scheduled_str,
    )

    return {
        "ok": True,
        "queue_id": queue_id,
        "scheduled_at": scheduled_str,
        "action": req.action,
        "platform": req.platform,
        "chapter": req.chapter,
    }


@editor_router.get("/stories/{story_name:path}/scheduled")
async def get_scheduled(story_name: str):
    """Return pending/scheduled queue items for this story."""
    from database.db import get_connection
    from database import posting_queries

    story_dir = _resolve_story_dir(story_name)
    canonical = str(story_dir.relative_to(get_archive_path()))

    conn = get_connection()
    try:
        items = posting_queries.get_queue(conn, include_completed=False, story_name=canonical)
    finally:
        conn.close()

    return {
        "ok": True,
        "items": items,
    }


@editor_router.delete("/stories/{story_name:path}/scheduled/{queue_id:int}")
async def cancel_scheduled(story_name: str, queue_id: int):
    """Cancel a pending scheduled queue item."""
    from database.db import get_connection
    from database import posting_queries

    # Validate story exists (prevents arbitrary queue_id cancellation)
    story_dir = _resolve_story_dir(story_name)
    canonical = str(story_dir.relative_to(get_archive_path()))

    conn = get_connection()
    try:
        # Verify the queue item belongs to this story
        items = posting_queries.get_queue(conn, include_completed=False, story_name=canonical)
        matching = [i for i in items if i["queue_id"] == queue_id]
        if not matching:
            raise HTTPException(
                status_code=404,
                detail=f"Queue item #{queue_id} not found for story '{canonical}'",
            )
        ok = posting_queries.cancel_queue_item(conn, queue_id)
    finally:
        conn.close()

    if not ok:
        raise HTTPException(status_code=409, detail="Item is no longer pending (may have already been processed)")

    logger.info("Cancelled scheduled queue item #%d for %s", queue_id, canonical)

    return {"ok": True, "queue_id": queue_id}


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

        # Replace any existing variables table (between markers) while
        # preserving whatever content sits before the start marker AND
        # after the end marker (user-authored notes, credits, extra sections
        # appended below the variables block).
        marker_start = "<!-- THEME_VARIABLES_START -->"
        marker_end = "<!-- THEME_VARIABLES_END -->"
        if marker_start in existing:
            before = existing[:existing.index(marker_start)]
            if marker_end in existing:
                after = existing[existing.index(marker_end) + len(marker_end):]
            else:
                after = ""
            existing = before.rstrip() + "\n"
        else:
            after = ""
            existing = existing.rstrip() + "\n\n"

        # Build variables table
        var_lines = [marker_start, "", "## Theme Variables", "", "| Variable | Value |", "| --- | --- |"]
        for key in STYLED_HTML_THEME_KEYS:
            if key in req.variables:
                var_lines.append(f"| `{key}` | `{req.variables[key]}` |")
        var_lines.extend(["", marker_end, ""])
        existing += "\n".join(var_lines)
        # Re-attach any content that lived after the end marker. lstrip the
        # after-chunk so we don't carry double blank lines.
        if after.strip():
            existing += after.lstrip("\n")
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


@editor_router.post("/stories/{story_name:path}/chapter-thumbnail")
async def upload_chapter_thumbnail(
    story_name: str,
    file: UploadFile = File(...),
    chapter_index: int = 0,
):
    """Upload a per-chapter thumbnail image."""
    story_dir = _resolve_story_dir(story_name)

    orig_name = file.filename or ""
    ext = Path(orig_name).suffix.lower()
    if ext not in _COVER_ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {ext}")

    data = await file.read()
    if len(data) > _COVER_MAX_BYTES:
        raise HTTPException(status_code=400, detail=f"Image too large ({len(data):,} bytes)")
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    images_dir = story_dir / "Images"
    images_dir.mkdir(exist_ok=True)
    filename = f"ch{chapter_index}_thumbnail{ext}"
    dest = images_dir / filename
    dest.write_bytes(data)

    rel_path = f"Images/{filename}"

    sj = story_dir / "story.json"
    if sj.is_file():
        try:
            raw = json.loads(sj.read_text(encoding="utf-8"))
            if "images" not in raw:
                raw["images"] = {}
            if "chapter_thumbnails" not in raw["images"]:
                raw["images"]["chapter_thumbnails"] = {}
            raw["images"]["chapter_thumbnails"][str(chapter_index)] = rel_path
            sj.write_text(json.dumps(raw, indent=4, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    return {"ok": True, "filename": rel_path, "size": len(data)}


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
    # Phase 3b: user-added tags via "+ Library" from the e621 lookup panel.
    # Shown as category "user" in the autocomplete.  The file is created on
    # first use; existence is optional so checkout-fresh repos still work.
    ("tag_database_user.txt", "user"),
]

_TAG_ALIASES_FILE = "tag_aliases.json"

# Phase 3b: compact e621 lookup TSV generated by
# m_x/Scripts_Utils/generate_e621_lookup.py.  Loaded lazily on first
# /tags/lookup request.  Rows: name<TAB>category<TAB>post_count.
_E621_LOOKUP_PATH = _TAG_DB_DIR / "e621_lookup.tsv"
_E621_LOOKUP: dict[str, dict] = {}       # name -> {"cat": int, "count": int}
_E621_LOOKUP_LOADED: bool = False        # flip True after first load attempt
_E621_NAME_RE = re.compile(r"^[a-z0-9_/-]+$")
_VALID_ADD_TARGETS = {"physical", "acts", "kink", "meta", "image", "user"}

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


# ---------------------------------------------------------------------------
# Phase 3b: e621 lookup fallback + "+ Add to library" workflow.
# ---------------------------------------------------------------------------

def _load_e621_lookup() -> dict[str, dict]:
    """Parse the bundled e621_lookup.tsv into an in-memory dict.

    Lazy — called on first lookup request.  Missing file is silently tolerated
    so the editor degrades to local-only autocomplete instead of crashing.

    Row format: name<TAB>cat<TAB>count (no header).  cat is the raw e621
    category integer; count is post_count.
    """
    global _E621_LOOKUP, _E621_LOOKUP_LOADED
    if _E621_LOOKUP_LOADED:
        return _E621_LOOKUP
    _E621_LOOKUP_LOADED = True  # set even on failure so we don't retry every call
    if not _E621_LOOKUP_PATH.is_file():
        logger.warning("e621 lookup TSV missing at %s — lookup disabled", _E621_LOOKUP_PATH)
        return _E621_LOOKUP
    try:
        text = _E621_LOOKUP_PATH.read_text(encoding="utf-8")
    except Exception as e:
        logger.error("e621 lookup: failed reading TSV: %s", e)
        return _E621_LOOKUP

    n = 0
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        name, cat_s, count_s = parts[0], parts[1], parts[2]
        try:
            cat = int(cat_s)
            count = int(count_s)
        except ValueError:
            continue
        _E621_LOOKUP[name] = {"cat": cat, "count": count}
        n += 1
    logger.info("e621 lookup: loaded %d tags from %s", n, _E621_LOOKUP_PATH.name)
    return _E621_LOOKUP


@editor_router.get("/tags/lookup")
async def lookup_tags(q: str, limit: int = 10):
    """Substring search the bundled e621 lookup for tags NOT in the local DB.

    Query params:
      q     — search string (required, min length 2).
      limit — max rows (default 10, clamped to [1, 50]).

    Returns: {"matches": [{"name": "...", "category": 0, "post_count": N}, ...]}

    Ranking: exact match > prefix match > substring match, then by post_count
    descending.  Tags already present in the local DB (any category, including
    user) are filtered out so the user only sees genuinely new suggestions.
    """
    q = (q or "").strip().lower()
    # Normalise spaces to underscores (e621 convention) so "racoon tail"
    # matches the same as "racoon_tail"
    q = q.replace(" ", "_")
    if len(q) < 2:
        return {"matches": []}
    limit = max(1, min(50, int(limit or 10)))

    lookup = _load_e621_lookup()
    if not lookup:
        return {"matches": []}

    # Pull known names from the local DB so we can filter them out.
    local_names: set[str] = set()
    try:
        db = _load_tag_db()
        for t in db.get("tags", []):
            nm = t.get("name")
            if nm:
                local_names.add(nm.lower())
    except Exception as e:
        logger.warning("e621 lookup: failed reading local DB for dedupe: %s", e)

    exact: list[tuple[str, dict]] = []
    prefix: list[tuple[str, dict]] = []
    substring: list[tuple[str, dict]] = []

    # Cap scan at a reasonable volume — we only need to surface the best
    # `limit` matches and the TSV is already sorted by post_count desc, so
    # early-exit once we have plenty.
    max_scan = limit * 200
    scanned = 0
    for name, meta in lookup.items():
        if scanned >= max_scan and (len(exact) + len(prefix) + len(substring)) >= limit * 3:
            break
        scanned += 1
        lname = name.lower()
        if lname in local_names:
            continue
        if lname == q:
            exact.append((name, meta))
        elif lname.startswith(q):
            prefix.append((name, meta))
        elif q in lname:
            substring.append((name, meta))

    # Within each bucket, sort by post_count desc (TSV order isn't guaranteed
    # after filtering, and python sort is stable so ties fall back to scan order).
    for bucket in (exact, prefix, substring):
        bucket.sort(key=lambda item: -item[1]["count"])

    merged = exact + prefix + substring
    out = [
        {"name": name, "category": meta["cat"], "post_count": meta["count"]}
        for name, meta in merged[:limit]
    ]
    return {"matches": out}


class AddTagRequest(BaseModel):
    name: str
    target: str = "user"
    description: str = ""


# Header template used when creating tag_database_user.txt from scratch, or
# when appending a new USER ADDITIONS section to an existing curated DB file.
_USER_SECTION_HEADER = (
    "================================================================================\n"
    "USER ADDITIONS\n"
    "================================================================================\n"
)


def _tag_exists_in_local_db(name: str) -> bool:
    """Case-insensitive existence check across the cached local DB."""
    lname = name.lower()
    try:
        db = _load_tag_db()
    except HTTPException:
        return False
    for t in db.get("tags", []):
        if (t.get("name") or "").lower() == lname:
            return True
    return False


def _invalidate_tag_db_cache() -> None:
    """Force the next /tags request to re-parse files from disk."""
    global _TAG_DB_CACHE
    _TAG_DB_CACHE = None


@editor_router.post("/tags/add")
async def add_tag(req: AddTagRequest):
    """Append a new tag to one of the local DB files.

    Body:
      {
        "name": "raccoon_tail",
        "target": "physical" | "acts" | "kink" | "meta" | "image" | "user",
        "description": ""   // optional
      }

    Policy:
      - `target=user` appends to tag_database_user.txt (created with a header
        if missing).
      - Any other target appends under a "USER ADDITIONS" section at the end
        of the target curated DB file. Section is created if missing.
      - Fails 409 if `name` already exists in any local DB (case-insensitive).

    Side effects:
      - Invalidates the in-memory _TAG_DB_CACHE so the next /tags call
        reflects the addition.
      - Does NOT touch the e621 lookup TSV — future lookup requests will
        simply dedupe against the now-populated local DB.
    """
    name = (req.name or "").strip()
    target = (req.target or "user").strip().lower()
    description = (req.description or "").strip()

    if not _E621_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="Invalid tag name. Must match ^[a-z0-9_/-]+$",
        )
    if target not in _VALID_ADD_TARGETS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid target '{target}'. Must be one of: {sorted(_VALID_ADD_TARGETS)}",
        )
    if _tag_exists_in_local_db(name):
        raise HTTPException(
            status_code=409,
            detail=f"Tag '{name}' already exists in the local database.",
        )

    if not _TAG_DB_DIR.is_dir():
        raise HTTPException(status_code=500, detail=f"Tag DB dir missing: {_TAG_DB_DIR}")

    if not description:
        description = "User-added from e621 lookup"

    target_file = _TAG_DB_DIR / f"tag_database_{target}.txt"

    # Build the line we'll append.  Matches the existing format: "name | desc".
    new_line = f"{name} | {description}\n"

    if target == "user":
        # Fresh or append. Header only written when file is new.
        if not target_file.is_file():
            header = (
                "TAG DATABASE: USER ADDITIONS\n"
                "========================================\n"
                'Tags added via the editor\'s "+ Library" button.\n'
                "\n"
                + _USER_SECTION_HEADER
            )
            with target_file.open("w", encoding="utf-8") as f:
                f.write(header)
                f.write(new_line)
        else:
            with target_file.open("a", encoding="utf-8") as f:
                f.write(new_line)
    else:
        # Curated DB: append under a USER ADDITIONS section (create section
        # if it doesn't yet exist). We read the file, check for the section
        # header, and either inject the line beneath it or append a new
        # section block at EOF.
        if not target_file.is_file():
            raise HTTPException(
                status_code=500,
                detail=f"Target DB file missing: {target_file.name}",
            )
        existing = target_file.read_text(encoding="utf-8")

        section_marker = "\nUSER ADDITIONS\n"
        if section_marker in existing:
            # Append at EOF within the existing USER ADDITIONS block.
            if not existing.endswith("\n"):
                existing += "\n"
            existing += new_line
            target_file.write_text(existing, encoding="utf-8")
        else:
            # Append a new section block at EOF.
            if not existing.endswith("\n"):
                existing += "\n"
            if not existing.endswith("\n\n"):
                existing += "\n"
            existing += _USER_SECTION_HEADER
            existing += new_line
            target_file.write_text(existing, encoding="utf-8")

    _invalidate_tag_db_cache()
    logger.info("Tag added to library: %s -> %s", name, target_file.name)

    return {
        "ok": True,
        "added_to": target_file.name,
        "category": target,
    }


# ---------------------------------------------------------------------------
# Import from platforms
# ---------------------------------------------------------------------------

# Platforms that support story import (code, label, content_type_filter)
IMPORT_PLATFORMS = {
    "ib": {"label": "Inkbunny", "filter_field": "type_name", "filter_value": "Writing"},
    "sf": {"label": "SoFurry", "filter_field": "content_type", "filter_value": "story"},
    "fa": {"label": "FurAffinity", "filter_field": "category", "filter_value": "Story"},
}

IMPORT_COMING_SOON = ["sqw", "ao3"]


@editor_router.get("/import/available")
async def list_importable():
    """List submissions from all platforms that could be imported.

    Cross-references polled submissions against existing story folders to
    find submissions not yet in the local archive. Only includes writing/story
    submissions (filters out artwork, music, etc.).
    """
    from database.db import get_connection
    from database import queries as ib_queries
    from database import sf_queries
    from database import fa_queries

    archive = get_archive_path()

    imported: dict[str, set[str]] = {"ib": set(), "sf": set(), "fa": set()}
    if archive.is_dir():
        for entry in archive.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            sj = entry / "story.json"
            if sj.is_file():
                try:
                    data = json.loads(sj.read_text(encoding="utf-8"))
                    src = data.get("import_source", {})
                    plat = src.get("platform", "")
                    sid = src.get("submission_id", "")
                    if plat and sid and plat in imported:
                        imported[plat].add(str(sid))
                except Exception:
                    pass

    conn = get_connection()
    result: list[dict] = []

    try:
        # --- Inkbunny ---
        ib_subs = ib_queries.get_all_submissions(conn, sort_by="title", order="asc")
        for sub in ib_subs:
            # Only include writing submissions
            type_name = (sub.get("type_name") or "").lower()
            if "writing" not in type_name:
                continue
            sid = str(sub.get("submission_id", ""))
            if sid in imported["ib"]:
                continue
            result.append({
                "platform": "ib",
                "platform_label": "Inkbunny",
                "submission_id": sid,
                "title": sub.get("title", ""),
                "author": sub.get("username", ""),
                "url": sub.get("url", f"https://inkbunny.net/s/{sid}"),
                "word_count": 0,  # IB doesn't store word count in the DB
                "rating": sub.get("rating_name", ""),
                "thumbnail_url": sub.get("thumb_url", ""),
            })

        # --- SoFurry ---
        sf_subs = sf_queries.get_all_sf_submissions(conn, sort_by="title", order="asc")
        for sub in sf_subs:
            content_type = (sub.get("content_type") or "").lower()
            if content_type != "story":
                continue
            sid = str(sub.get("submission_id", ""))
            if sid in imported["sf"]:
                continue
            result.append({
                "platform": "sf",
                "platform_label": "SoFurry",
                "submission_id": sid,
                "title": sub.get("title", ""),
                "author": sub.get("username", ""),
                "url": sub.get("link", f"https://sofurry.com/s/{sid}"),
                "word_count": 0,
                "rating": sub.get("rating", ""),
                "thumbnail_url": sub.get("thumbnail_url", ""),
            })

        # --- FurAffinity ---
        fa_subs = fa_queries.get_all_fa_submissions(conn, sort_by="title", order="asc")
        for sub in fa_subs:
            category = (sub.get("category") or "").lower()
            if "story" not in category:
                continue
            sid = str(sub.get("submission_id", ""))
            if sid in imported["fa"]:
                continue
            result.append({
                "platform": "fa",
                "platform_label": "FurAffinity",
                "submission_id": sid,
                "title": sub.get("title", ""),
                "author": sub.get("username", ""),
                "url": f"https://www.furaffinity.net/view/{sid}/",
                "word_count": 0,
                "rating": sub.get("rating", ""),
                "thumbnail_url": sub.get("thumbnail_url", ""),
            })
    finally:
        conn.close()

    # Add coming-soon placeholders
    coming_soon = [
        {"platform": p, "label": p.upper()} for p in IMPORT_COMING_SOON
    ]

    return {
        "ok": True,
        "submissions": result,
        "total": len(result),
        "coming_soon": coming_soon,
    }


@editor_router.post("/import/{platform}/{submission_id}")
async def import_submission(platform: str, submission_id: str):
    """Import a single submission from a platform into the local archive.

    Downloads the content, creates the folder structure, and generates
    story.json from the submission metadata.
    """
    from posting.importer import import_from_inkbunny, import_from_sofurry, import_from_furaffinity

    if platform not in IMPORT_PLATFORMS:
        raise HTTPException(
            status_code=400,
            detail=f"Import not supported for platform: {platform}",
        )

    try:
        if platform == "ib":
            result = await import_from_inkbunny(submission_id)
        elif platform == "sf":
            result = await import_from_sofurry(submission_id)
        elif platform == "fa":
            result = await import_from_furaffinity(submission_id)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform}")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("Import failed for %s/%s", platform, submission_id)
        raise HTTPException(status_code=500, detail=f"Import failed: {e}")

    return {
        "ok": True,
        "story_name": result["story_name"],
        "title": result["title"],
    }
