"""Story archive reader for the posting module.

Reads from the m_x/Archives/Complete_Stories/ directory structure to build
StoryUploadPackage objects for each platform. Handles:
  - split_manifest.json parsing (chapter structure)
  - tags_upload.txt parsing (per-platform tag lists)
  - Format file resolution (BBCode → IB, SoFurry HTML → SF, etc.)
  - Description/summary extraction
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import config
from posting.platforms.base import StoryUploadPackage

logger = logging.getLogger(__name__)

# Platform → preferred format file patterns.
# Each entry is (subdirectory, glob pattern, file_type label).
# Checked in order; first match wins.
PLATFORM_FORMAT_MAP: dict[str, list[tuple[str, str, str]]] = {
    "ib": [
        ("Chapters/BBCode", "*.txt", "bbcode"),
        ("BBCode", "*_bbcode.txt", "bbcode"),
    ],
    "fa": [
        ("PDF", "*.pdf", "pdf"),
        ("Chapters/PDF", "*.pdf", "pdf"),
    ],
    "ws": [
        ("Chapters/BBCode", "*.txt", "bbcode"),
        ("BBCode", "*_bbcode.txt", "bbcode"),
        ("Markdown", "MASTER.md", "markdown"),
    ],
    "sf": [
        ("Chapters/SoFurry_HTML", "*.html", "html"),
        ("HTML", "*_Clean.html", "html"),
        ("HTML", "*_sofurry.html", "html"),
    ],
    "sqw": [
        ("SquidgeWorld", "*.html", "html"),
        ("Chapters/SoFurry_HTML", "*.html", "html"),
    ],
    "ao3": [
        ("SquidgeWorld", "*.html", "html"),  # Same OTW format as SQW
        ("Chapters/SoFurry_HTML", "*.html", "html"),
    ],
    "ik": [],  # Itaku: images uploaded separately, text posts use description
    "bsky": [],  # Bluesky uses text from description, no file upload
}


@dataclass
class StoryInfo:
    """Parsed story metadata from the archive."""
    name: str
    path: Path
    total_chapters: int
    total_words: int
    author: str
    chapters: list[ChapterInfo]
    description: str                                  # short blurb (STORY DESCRIPTION)
    tags_by_platform: dict[str, list[str]]          # platform → tag list
    chapter_tags_by_platform: dict[int, dict[str, list[str]]]  # chapter_index → platform → tags
    chapter_descriptions: dict[int, str]             # chapter_index → description
    summary: str = ""                                 # detailed summary (SUMMARY section, for SQW/AO3)
    thumbnail_path: str | None = None                 # full-series thumbnail
    chapter_thumbnails: dict[int, str] = None         # chapter_index → thumbnail path

    def __post_init__(self):
        if self.chapter_thumbnails is None:
            self.chapter_thumbnails = {}


@dataclass
class ChapterInfo:
    """Single chapter from split_manifest.json."""
    index: int
    title: str
    filename: str
    word_count: int
    files: dict[str, str]   # format_key → relative path


def get_archive_path() -> Path:
    """Get the story archive root, configurable via settings.

    Resolution order:
      1. posting_story_archive_path setting (explicit override)
      2. /app/story-archive (Docker bind mount on GCP server)
      3. ../m_x/Archives/Complete_Stories/ (relative to PawPoller, for desktop)
    """
    settings = config.get_settings()
    custom = settings.get("posting_story_archive_path", "")
    if custom and os.path.isdir(custom):
        return Path(custom)
    # Docker: bind-mounted at /app/story-archive
    docker_mount = Path("/app/story-archive")
    if docker_mount.is_dir() and any(docker_mount.iterdir()):
        return docker_mount
    # Desktop: relative to PawPoller project
    default = Path(config.resource_path(".")).parent / "m_x" / "Archives" / "Complete_Stories"
    if default.is_dir():
        return default
    return Path(custom) if custom else default


def list_stories() -> list[dict]:
    """List all available stories in the archive.

    Returns a list of dicts with story metadata from story.json (if available),
    plus file inventory and format availability.
    """
    archive = get_archive_path()
    if not archive.is_dir():
        logger.warning("Story archive not found at %s", archive)
        return []
    stories = []
    for entry in sorted(archive.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name == "Reference_Guides":
            continue
        # Check if this is a direct story folder
        if (entry / "Markdown" / "MASTER.md").is_file() or (entry / "Tags").is_dir() or (entry / "story.json").is_file():
            stories.append(_story_entry(entry))
        else:
            # Check for sub-stories (e.g. The_Abstinent_Bet/Naughty_Version/)
            for sub in sorted(entry.iterdir()):
                if sub.is_dir() and (
                    (sub / "Markdown" / "MASTER.md").is_file() or (sub / "story.json").is_file()
                ):
                    stories.append(_story_entry(sub, parent_name=entry.name))
    return stories


def _story_entry(path: Path, parent_name: str = "") -> dict:
    """Build a story list entry from a folder path.

    If story.json exists, uses it for rich metadata. Otherwise falls back
    to basic folder inspection.
    """
    name = f"{parent_name}/{path.name}" if parent_name else path.name
    story_json = path / "story.json"

    entry = {
        "name": name,
        "path": str(path),
        "has_manifest": (path / "Chapters" / "split_manifest.json").is_file(),
        "has_tags": (path / "Tags" / "tags_upload.txt").is_file(),
        "has_master": (path / "Markdown" / "MASTER.md").is_file(),
        "has_story_json": story_json.is_file(),
    }

    if story_json.is_file():
        try:
            data = json.loads(story_json.read_text(encoding="utf-8"))
            entry["title"] = data.get("title", name.replace("_", " "))
            entry["author"] = data.get("author", "")
            entry["description"] = data.get("description", "")
            entry["word_count"] = data.get("word_count", 0)
            entry["chapters"] = data.get("chapters", 0)
            entry["rating"] = data.get("rating", "")
            entry["category"] = data.get("category", "")
            entry["formats"] = data.get("formats", {})
            entry["platforms"] = list(data.get("platforms", {}).keys())
            entry["images"] = data.get("images", {})
            entry["warnings"] = data.get("warnings", [])
        except Exception as e:
            logger.warning("Failed to read story.json for %s: %s", name, e)

    return entry


def load_story(story_name: str) -> StoryInfo:
    """Load full story metadata from the archive.

    Reads from story.json if available (preferred), falling back to
    tags_upload.txt + split_manifest.json parsing.
    """
    archive = get_archive_path()
    story_path = archive / story_name
    if not story_path.is_dir():
        raise FileNotFoundError(f"Story folder not found: {story_path}")

    story_json_path = story_path / "story.json"
    if story_json_path.is_file():
        return _load_from_story_json(story_name, story_path, story_json_path)
    return _load_from_legacy(story_name, story_path)


def _load_from_story_json(story_name: str, story_path: Path, json_path: Path) -> StoryInfo:
    """Load story metadata from story.json."""
    data = json.loads(json_path.read_text(encoding="utf-8"))

    # Build chapter list from story.json (merge with manifest for file paths)
    chapters = []
    manifest_chapters = {}
    manifest_path = story_path / "Chapters" / "split_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for ch in manifest.get("chapters", []):
            manifest_chapters[ch.get("index", 0)] = ch

    for ch_data in data.get("chapter_info", []):
        idx = ch_data.get("index", 0)
        manifest_ch = manifest_chapters.get(idx, {})
        chapters.append(ChapterInfo(
            index=idx,
            title=ch_data.get("title", ""),
            filename=manifest_ch.get("filename", ""),
            word_count=ch_data.get("words", manifest_ch.get("word_count", 0)),
            files=manifest_ch.get("files", {}),
        ))

    # Build tags_by_platform from story.json tags
    tags = data.get("tags", {})
    tags_by_platform = {}
    for plat_key, tag_list in tags.items():
        # Map platform names to IDs
        plat_map = {"inkbunny": "ib", "furaffinity": "fa", "weasyl": "ws",
                    "sofurry": "sf", "squidgeworld": "sqw", "wattpad": "wp"}
        plat_id = plat_map.get(plat_key, plat_key)
        tags_by_platform[plat_id] = tag_list

    # Chapter descriptions
    chapter_descriptions = {}
    for ch_data in data.get("chapter_info", []):
        if ch_data.get("description"):
            chapter_descriptions[ch_data["index"]] = ch_data["description"]

    # Images
    images = data.get("images", {})
    thumbnail_path = None
    chapter_thumbnails = {}
    if images.get("cover"):
        thumbnail_path = str(story_path / images["cover"])
    for ch_idx, ch_path in images.get("chapter_thumbnails", {}).items():
        chapter_thumbnails[int(ch_idx)] = str(story_path / ch_path)

    return StoryInfo(
        name=story_name,
        path=story_path,
        total_chapters=data.get("chapters", len(chapters)),
        total_words=data.get("word_count", 0),
        author=data.get("author", "KnaughtyKat"),
        chapters=chapters,
        description=data.get("description", ""),
        tags_by_platform=tags_by_platform,
        chapter_tags_by_platform={},  # Per-chapter tags not in story.json yet
        chapter_descriptions=chapter_descriptions,
        summary=data.get("summary", ""),
        thumbnail_path=thumbnail_path,
        chapter_thumbnails=chapter_thumbnails,
    )


def _load_from_legacy(story_name: str, story_path: Path) -> StoryInfo:
    """Load story metadata from tags_upload.txt + split_manifest.json (fallback)."""
    # Parse manifest
    chapters = []
    total_chapters = 0
    total_words = 0
    author = ""
    manifest_path = story_path / "Chapters" / "split_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        total_chapters = manifest.get("total_chapters", 0)
        total_words = manifest.get("total_words", 0)
        author = manifest.get("author", "")
        for ch in manifest.get("chapters", []):
            chapters.append(ChapterInfo(
                index=ch.get("index", 0),
                title=ch.get("title", ""),
                filename=ch.get("filename", ""),
                word_count=ch.get("word_count", 0),
                files=ch.get("files", {}),
            ))

    # Parse tags_upload.txt
    description = ""
    summary = ""
    tags_by_platform: dict[str, list[str]] = {}
    chapter_tags: dict[int, dict[str, list[str]]] = {}
    chapter_descriptions: dict[int, str] = {}
    tags_path = story_path / "Tags" / "tags_upload.txt"
    if tags_path.is_file():
        tags_text = tags_path.read_text(encoding="utf-8")
        description, summary, tags_by_platform, chapter_tags, chapter_descriptions = _parse_tags_upload(
            tags_text, total_chapters
        )

    # Discover thumbnails
    thumbnail_path = None
    chapter_thumbnails: dict[int, str] = {}
    for f in story_path.iterdir():
        if not f.is_file() or f.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif"):
            continue
        fname = f.name.lower()
        if "thumbnail" in fname and ("full" in fname or "series" in fname or "cover" in fname):
            thumbnail_path = str(f)
        elif "thumbnail" in fname:
            part_match = re.search(r'part[_\s]*(\d+)', fname)
            if part_match:
                chapter_thumbnails[int(part_match.group(1))] = str(f)

    return StoryInfo(
        name=story_name,
        path=story_path,
        total_chapters=total_chapters,
        total_words=total_words,
        author=author,
        chapters=chapters,
        description=description,
        summary=summary,
        tags_by_platform=tags_by_platform,
        chapter_tags_by_platform=chapter_tags,
        chapter_descriptions=chapter_descriptions,
        thumbnail_path=thumbnail_path,
        chapter_thumbnails=chapter_thumbnails,
    )


def build_package(
    story: StoryInfo,
    chapter_index: int,
    platform: str,
    title_override: str | None = None,
    description_override: str | None = None,
    tags_override: list[str] | None = None,
    rating_override: str | None = None,
    file_path_override: str | None = None,
) -> StoryUploadPackage:
    """Build a StoryUploadPackage for a specific chapter + platform combination.

    Args:
        story: Loaded story info.
        chapter_index: 0 = full story, 1+ = specific chapter.
        platform: Platform ID ('ib', 'fa', 'ws', 'sf', 'bsky').
        *_override: Override any auto-resolved field.
    """
    # Resolve chapter info
    chapter_title = ""
    word_count = story.total_words
    if chapter_index > 0 and chapter_index <= len(story.chapters):
        ch = story.chapters[chapter_index - 1]
        chapter_title = ch.title
        word_count = ch.word_count

    # Title
    if title_override:
        title = title_override
    elif chapter_index > 0 and chapter_title:
        title = f"{story.name.replace('_', ' ')} — {chapter_title}"
    else:
        title = story.name.replace("_", " ")

    # Description — platform-specific selection:
    #   SQW/AO3: use detailed summary (SUMMARY section) for work-level, chapter desc for chapters
    #   FA: use per-chapter description (DESCRIPTION under each PART section)
    #   IB/SF/WS/BSKY: use short blurb (STORY DESCRIPTION)
    if description_override:
        description = description_override
    elif chapter_index > 0 and chapter_index in story.chapter_descriptions:
        description = story.chapter_descriptions[chapter_index]
    elif platform in ("sqw", "ao3") and story.summary:
        description = story.summary
    else:
        description = story.description

    # Tags
    if tags_override:
        tags = tags_override
    elif chapter_index > 0 and chapter_index in story.chapter_tags_by_platform:
        ch_tags = story.chapter_tags_by_platform[chapter_index]
        tags = ch_tags.get(platform, ch_tags.get("default", []))
    else:
        tags = story.tags_by_platform.get(platform, [])

    # Rating — default to adult, overridable
    rating = rating_override or "adult"

    # File path
    file_path = file_path_override
    file_type = ""
    if not file_path:
        file_path, file_type = _resolve_format_file(story, chapter_index, platform)

    # Thumbnail: per-chapter thumbnail takes priority over full-series
    thumbnail = None
    if chapter_index > 0 and chapter_index in story.chapter_thumbnails:
        thumbnail = story.chapter_thumbnails[chapter_index]
    elif story.thumbnail_path:
        thumbnail = story.thumbnail_path

    return StoryUploadPackage(
        story_name=story.name,
        chapter_index=chapter_index,
        chapter_title=chapter_title,
        platform=platform,
        title=title,
        description=description,
        tags=tags,
        rating=rating,
        file_path=file_path,
        file_type=file_type,
        word_count=word_count,
        thumbnail_path=thumbnail,
    )


def _resolve_format_file(
    story: StoryInfo, chapter_index: int, platform: str
) -> tuple[str | None, str]:
    """Find the appropriate format file for a platform.

    Returns (absolute_path, file_type) or (None, '') if no file needed/found.
    """
    format_specs = PLATFORM_FORMAT_MAP.get(platform, [])
    if not format_specs:
        return None, ""

    story_path = story.path

    for subdir, pattern, file_type in format_specs:
        search_dir = story_path / subdir
        if not search_dir.is_dir():
            continue

        if chapter_index > 0 and chapter_index <= len(story.chapters):
            # Look for chapter-specific file
            ch = story.chapters[chapter_index - 1]
            ch_filename = ch.filename
            # Try matching by chapter filename prefix
            for f in sorted(search_dir.iterdir()):
                if f.is_file() and ch_filename in f.stem:
                    return str(f), file_type
            # Try matching by chapter index
            for f in sorted(search_dir.iterdir()):
                if f.is_file() and f"Chapter_{chapter_index}" in f.name:
                    return str(f), file_type
        else:
            # Full-story file
            import fnmatch
            for f in sorted(search_dir.iterdir()):
                if f.is_file() and fnmatch.fnmatch(f.name, pattern):
                    return str(f), file_type

    logger.warning(
        "No format file found for %s ch%d on %s", story.name, chapter_index, platform
    )
    return None, ""


def _parse_tags_upload(
    text: str, total_chapters: int
) -> tuple[str, str, dict[str, list[str]], dict[int, dict[str, list[str]]], dict[int, str]]:
    """Parse a tags_upload.txt file.

    Returns:
        (story_description, summary, tags_by_platform, chapter_tags, chapter_descriptions)
    """
    description = ""
    summary = ""
    tags_by_platform: dict[str, list[str]] = {}
    chapter_tags: dict[int, dict[str, list[str]]] = {}
    chapter_descriptions: dict[int, str] = {}

    # Extract detailed summary (SUMMARY section — used by SQW/AO3)
    summary_match = re.search(
        r"^SUMMARY[^:]*:\s*\n(.+?)(?:\nNOTES|\nASSOCIATIONS|\n=====)",
        text, re.MULTILINE | re.DOTALL
    )
    if summary_match:
        summary = summary_match.group(1).strip()

    # Extract short story description (STORY DESCRIPTION — used by IB/SF/etc.)
    desc_match = re.search(
        r"STORY DESCRIPTION:\s*\n(.+?)(?:\n=====|\nPART \d|\nTAGS|\n$)",
        text, re.DOTALL
    )
    if desc_match:
        description = desc_match.group(1).strip()

    # Extract story-level tags sections
    # SoFurry / default tags (the first TAGS section)
    tags_match = re.search(r"^TAGS \(\d+\):\s*\n(.+?)(?:\n\n|\nINKBUNNY)", text, re.MULTILINE | re.DOTALL)
    if tags_match:
        raw = tags_match.group(1).strip()
        tags_by_platform["sf"] = [t.strip() for t in raw.split(",") if t.strip()]
        tags_by_platform["default"] = tags_by_platform["sf"]

    # Inkbunny tags (flatten all categories)
    ib_match = re.search(
        r"INKBUNNY TAGS \(Categorized\):\s*\n(.+?)(?:\n\nWATTPAD|\n\n=====|\nOther Keywords:.*?\n\n)",
        text, re.DOTALL
    )
    if ib_match:
        ib_section = ib_match.group(0)
        ib_tags = []
        for line in ib_section.split("\n"):
            line = line.strip()
            if not line or line.endswith(":") or "INKBUNNY" in line:
                continue
            ib_tags.extend(t.strip() for t in line.split(",") if t.strip())
        if ib_tags:
            tags_by_platform["ib"] = ib_tags

    # Wattpad tags
    wp_match = re.search(r"WATTPAD TAGS.*?:\s*\n(.+?)(?:\n\n|\n=====)", text, re.DOTALL)
    if wp_match:
        raw = wp_match.group(1).strip()
        tags_by_platform["wp"] = raw.split()

    # Weasyl uses same tags as Inkbunny (both accept keyword lists)
    if "ib" in tags_by_platform:
        tags_by_platform["ws"] = tags_by_platform["ib"]

    # FA uses same as default/SF but space-separated
    if "default" in tags_by_platform:
        tags_by_platform["fa"] = tags_by_platform["default"]

    # Bluesky doesn't use tags from the file

    # Extract per-chapter sections
    part_pattern = re.compile(
        r"PART (\d+) OF \d+:.*?\n(.*?)(?=PART \d+ OF \d+:|$)",
        re.DOTALL
    )
    for match in part_pattern.finditer(text):
        ch_idx = int(match.group(1))
        ch_section = match.group(2)

        # Chapter description
        ch_desc_match = re.search(r"DESCRIPTION:\s*\n(.+?)(?:\n\nTAGS|\n\n)", ch_section, re.DOTALL)
        if ch_desc_match:
            chapter_descriptions[ch_idx] = ch_desc_match.group(1).strip()

        # Chapter tags (same format as story-level)
        ch_tags: dict[str, list[str]] = {}
        ch_tags_match = re.search(r"^TAGS \(\d+\):\s*\n(.+?)(?:\n\nINKBUNNY|\n\n)", ch_section, re.MULTILINE | re.DOTALL)
        if ch_tags_match:
            raw = ch_tags_match.group(1).strip()
            ch_tags["sf"] = [t.strip() for t in raw.split(",") if t.strip()]
            ch_tags["default"] = ch_tags["sf"]
            ch_tags["fa"] = ch_tags["sf"]

        # Chapter Inkbunny tags
        ch_ib_match = re.search(r"INKBUNNY TAGS.*?:\s*\n(.+?)(?:\nWATTPAD|\n\n=====|\n\n)", ch_section, re.DOTALL)
        if ch_ib_match:
            ib_tags = []
            for line in ch_ib_match.group(0).split("\n"):
                line = line.strip()
                if not line or line.endswith(":") or "INKBUNNY" in line:
                    continue
                ib_tags.extend(t.strip() for t in line.split(",") if t.strip())
            if ib_tags:
                ch_tags["ib"] = ib_tags
                ch_tags["ws"] = ib_tags

        if ch_tags:
            chapter_tags[ch_idx] = ch_tags

    return description, summary, tags_by_platform, chapter_tags, chapter_descriptions
