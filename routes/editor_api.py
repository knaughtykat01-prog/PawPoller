"""Story editor API routes.

Provides endpoints for reading/writing MASTER.md, live preview in
multiple formats, and triggering format regeneration.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
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


class RegenerateRequest(BaseModel):
    skip_pdf: bool = True  # PDFs are slow; opt-in


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SKIP_DIRS = {"Reference_Guides"}


def _resolve_story_dir(story_name: str) -> Path:
    """Resolve a story name to its directory. Handles versioned stories."""
    archive = get_archive_path()
    # Direct match
    direct = archive / story_name
    if direct.is_dir():
        return direct
    # Try as a sub-path (e.g., "The_Abstinent_Bet/Nice_Version")
    sub = archive / story_name
    if sub.is_dir():
        return sub
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

    Writes BBCode, Clean HTML, and per-chapter splits to the story's
    folder structure. Styled HTML and PDF generation are future phases.
    """
    from editor.converter import convert
    story_dir = _resolve_story_dir(story_name)
    master = _get_master_path(story_dir)

    if not master.is_file():
        raise HTTPException(status_code=404, detail="MASTER.md not found")

    content = master.read_text(encoding="utf-8")
    results: list[str] = []
    errors: list[str] = []

    # --- Full-story Clean HTML ---
    try:
        html_result = convert(content, "clean_html")
        html_dir = story_dir / "HTML"
        html_dir.mkdir(exist_ok=True)
        stem = story_dir.name
        html_path = html_dir / f"{stem}_Clean.html"
        html_path.write_text(html_result.output, encoding="utf-8")
        results.append(f"HTML/{stem}_Clean.html ({len(html_result.output):,} bytes)")
    except Exception as e:
        errors.append(f"Clean HTML: {e}")

    # --- Full-story BBCode ---
    try:
        bb_result = convert(content, "bbcode")
        bb_dir = story_dir / "BBCode"
        bb_dir.mkdir(exist_ok=True)
        stem = story_dir.name
        bb_path = bb_dir / f"{stem}_bbcode.txt"
        bb_path.write_text(bb_result.output, encoding="utf-8")
        results.append(f"BBCode/{stem}_bbcode.txt ({len(bb_result.output):,} bytes)")
    except Exception as e:
        errors.append(f"BBCode: {e}")

    # --- Chapter splits ---
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
