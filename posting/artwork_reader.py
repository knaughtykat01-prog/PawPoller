"""Artwork archive reader for the posting module.

The Artwork hub (PostyBirb-style image posting) stores one folder per artwork
under the artwork archive, each containing the primary image + an artwork.json
metadata file (+ an optional separate thumbnail). This module mirrors
``story_reader.py`` but for single-image submissions: it lists/loads artworks
and builds a ``StoryUploadPackage`` (reused as the universal upload package)
that the existing per-platform posters can send.

Unlike stories, artworks have no chapters and no generated format files — the
uploaded image IS the file. So ``build_artwork_package`` always uses
chapter_index 0 and points ``file_path`` at the image.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import config
from posting.platforms.base import StoryUploadPackage

logger = logging.getLogger(__name__)

# Image extensions accepted as a primary artwork file (and as a thumbnail).
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")

# Every poster ID the Artwork hub targets — used to cascade default tags to any
# platform without an explicit list. These are exactly the image-capable
# platforms wired into manager._get_poster; the fiction-only sites (ao3/sqw/wp)
# don't take image submissions. e621 is a full art poster (2.118.0, ≥4 tags) and
# a valid Masterpiece target (Masterpieces Phase 4). Instagram (2.139.0) is a
# full artwork target via posting.platforms.instagram.InstagramPoster (reuses the
# Posts module's public-image-hosting path); it's post-only (no edit/replace API)
# and needs a public host (IG_PUBLIC_BASE_URL) or a paired server.
_ALL_POSTER_IDS = ["ib", "fa", "ws", "sf", "da", "ik", "bsky", "e621", "ig"]

# Metadata filename. The Masterpiece era (Phase 0) writes `masterpiece.json`;
# legacy folders have `artwork.json`. `masterpiece.json` is a back-compatible
# SUPERSET of `artwork.json`, so a folder with only the legacy file is a valid
# Masterpiece with no members yet. Readers accept BOTH (prefer the new file);
# writers emit the new file and retire the legacy one on first edit.
_META_FILE = "masterpiece.json"
_LEGACY_META_FILE = "artwork.json"


def _meta_path(folder: Path) -> Path | None:
    """Metadata file for an artwork/Masterpiece folder — prefers
    ``masterpiece.json``, falls back to legacy ``artwork.json``; ``None`` if
    neither exists."""
    new = folder / _META_FILE
    if new.is_file():
        return new
    legacy = folder / _LEGACY_META_FILE
    if legacy.is_file():
        return legacy
    return None


def get_artwork_archive_path() -> Path:
    """Get the artwork archive root, configurable via settings.

    Resolution order:
      1. artwork_archive_path setting (explicit override)
      2. /app/data/artwork (Docker server — on the existing persistent volume
         that already holds settings.json, so no docker-compose change needed)
      3. ../m_x/Archives/Artwork/ (maintainer's dev checkout — ONLY if it exists
         beside the source; never present in a shipped install)
      4. <user data>/artwork — the generic per-user default, created on first use
         (mirrors the Docker /app/data/artwork layout).
    """
    settings = config.get_settings()
    custom = settings.get("artwork_archive_path", "")
    if custom and os.path.isdir(custom):
        return Path(custom)
    # Docker server: /app/data is the mounted persistent volume.
    data_dir = Path("/app/data")
    if data_dir.is_dir():
        return data_dir / "artwork"
    # Maintainer's dev checkout only — skipped on every real install.
    dev = Path(config.resource_path(".")).parent / "m_x" / "Archives" / "Artwork"
    if dev.is_dir():
        return dev
    # Generic per-user default (mirrors the Docker /app/data/artwork convention).
    default = config.DATA_DIR / "artwork"
    default.mkdir(parents=True, exist_ok=True)
    return default


@dataclass
class ArtworkInfo:
    """Parsed artwork metadata from the archive."""
    name: str                                    # folder name (the artwork key)
    path: Path
    title: str
    description: str
    author: str
    rating: str                                  # general / mature / adult
    image: str                                   # primary image filename (relative)
    thumbnail: str | None = None                 # optional separate thumbnail (relative)
    tags_by_platform: dict[str, list[str]] = field(default_factory=dict)
    titles_by_platform: dict[str, str] = field(default_factory=dict)
    descriptions_by_platform: dict[str, str] = field(default_factory=dict)
    categories_by_platform: dict[str, dict] = field(default_factory=dict)
    platforms: list[str] = field(default_factory=list)   # target platforms
    characters: list[str] = field(default_factory=list)  # canonical characters (parity with story.json)
    created_at: str = ""

    @property
    def image_path(self) -> str | None:
        return str(self.path / self.image) if self.image else None

    @property
    def thumbnail_path(self) -> str | None:
        return str(self.path / self.thumbnail) if self.thumbnail else None


def list_artworks() -> list[dict]:
    """List all artworks in the archive (folders containing artwork.json)."""
    archive = get_artwork_archive_path()
    if not archive.is_dir():
        return []
    items = []
    for entry in sorted(archive.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        meta_path = _meta_path(entry)
        if meta_path is None:
            continue
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to read %s for %s: %s", meta_path.name, entry.name, e)
            continue
        items.append({
            "name": entry.name,
            "path": str(entry),
            "title": data.get("title", entry.name.replace("_", " ")),
            "description": data.get("description", ""),
            "rating": data.get("rating", ""),
            "image": data.get("image", ""),
            "thumbnail": data.get("thumbnail", ""),
            "tags": data.get("tags", {}),
            "characters": data.get("characters", []),
            "platforms": data.get("platforms", []),
            "import_source": data.get("import_source", {}),
            "created_at": data.get("created_at", ""),
        })
    # Newest first (created_at is an ISO-ish string; empty sorts last).
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items


def load_artwork(name: str) -> ArtworkInfo:
    """Load full artwork metadata from the archive.

    Security: re-anchor against the archive root so a crafted name with ``../``
    segments can't escape into the host filesystem (mirrors
    ``story_reader.load_story``).
    """
    archive = get_artwork_archive_path().resolve()
    candidate = (archive / name).resolve()
    try:
        candidate.relative_to(archive)
    except ValueError:
        raise FileNotFoundError(f"Artwork folder not found: {name}") from None
    if not candidate.is_dir():
        raise FileNotFoundError(f"Artwork folder not found: {candidate}")
    meta_path = _meta_path(candidate)
    if meta_path is None:
        raise FileNotFoundError(f"masterpiece.json / artwork.json not found for: {name}")

    data = json.loads(meta_path.read_text(encoding="utf-8"))

    # Tags: cascade default → any platform without an explicit list (mirrors the
    # story_reader cascade + the editor's "Default tab cascades to all").
    tags = {k: list(v) for k, v in data.get("tags", {}).items()}
    if "default" in tags:
        for pid in _ALL_POSTER_IDS:
            tags.setdefault(pid, list(tags["default"]))

    return ArtworkInfo(
        name=name,
        path=candidate,
        title=data.get("title", name.replace("_", " ")),
        description=data.get("description", ""),
        author=data.get("author", config.get_settings().get("default_author", "")),
        rating=data.get("rating", ""),
        image=data.get("image", ""),
        thumbnail=data.get("thumbnail") or None,
        tags_by_platform=tags,
        titles_by_platform=data.get("titles", {}),
        descriptions_by_platform=data.get("descriptions", {}),
        categories_by_platform=data.get("categories", {}),
        platforms=data.get("platforms", []),
        characters=list(data.get("characters", []) or []),
        created_at=data.get("created_at", ""),
    )


def build_artwork_package(
    artwork: ArtworkInfo,
    platform: str,
    title_override: str | None = None,
    description_override: str | None = None,
    tags_override: list[str] | None = None,
    rating_override: str | None = None,
) -> StoryUploadPackage:
    """Build a StoryUploadPackage for one artwork + platform.

    Reuses StoryUploadPackage (the universal upload package): file_path is the
    image, file_type its extension, chapter_index fixed at 0. Per-platform
    title/description/tag overrides cascade just like ``build_package``.
    ``extra`` carries the platform's submission-category params (FA
    cat/species/gender, SF category/sub_type, …) for the poster to apply.
    """
    title = title_override or artwork.titles_by_platform.get(platform) or artwork.title

    if description_override:
        description = description_override
    elif platform in artwork.descriptions_by_platform:
        description = artwork.descriptions_by_platform[platform]
    elif platform == "bsky" and artwork.descriptions_by_platform.get("announcement"):
        description = artwork.descriptions_by_platform["announcement"]
    else:
        description = artwork.descriptions_by_platform.get("default", artwork.description)

    if tags_override is not None:
        tags = tags_override
    else:
        tags = artwork.tags_by_platform.get(
            platform, artwork.tags_by_platform.get("default", []))

    settings = config.get_settings()
    rating = (rating_override or artwork.rating
              or settings.get("artwork_default_rating",
                              settings.get("posting_default_rating", "adult")))

    image_path = artwork.image_path
    file_type = Path(image_path).suffix.lstrip(".").lower() if image_path else ""

    return StoryUploadPackage(
        story_name=artwork.name,
        chapter_index=0,
        chapter_title="",
        platform=platform,
        title=title,
        description=description,
        tags=tags,
        rating=rating,
        file_path=image_path,
        file_type=file_type,
        word_count=0,
        thumbnail_path=artwork.thumbnail_path,
        extra=dict(artwork.categories_by_platform.get(platform, {})),
    )


# ── Creation (used by the upload + create-from-local-path endpoints) ──────

def slugify(title: str) -> str:
    """Turn a title into a safe folder name (word chars + underscores)."""
    slug = re.sub(r"[^\w\s-]", "", (title or "").strip())
    slug = re.sub(r"[\s-]+", "_", slug).strip("_")
    return slug or "artwork"


def _unique_dir(archive: Path, slug: str) -> Path:
    """Return a non-colliding folder path under archive for slug."""
    candidate = archive / slug
    n = 2
    while candidate.exists():
        candidate = archive / f"{slug}_{n}"
        n += 1
    return candidate


def _safe_filename(filename: str, default: str) -> str:
    """Sanitise an uploaded filename to a bare, safe image basename.

    Preserves a valid image extension; falls back to ``default`` when the
    extension isn't an accepted image type (the endpoint validates too).
    """
    base = os.path.basename(filename or "").strip()
    base = re.sub(r"[^\w.\-]", "_", base)
    ext = Path(base).suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        return default
    if not base or base.startswith("."):
        return f"image{ext}"
    return base


def create_artwork(
    *,
    title: str,
    image_filename: str,
    image_bytes: bytes,
    description: str = "",
    author: str = "",
    rating: str = "",
    tags: dict | None = None,
    titles: dict | None = None,
    descriptions: dict | None = None,
    categories: dict | None = None,
    platforms: list[str] | None = None,
    characters: list[str] | None = None,
    thumbnail_filename: str | None = None,
    thumbnail_bytes: bytes | None = None,
    source: dict | None = None,
) -> str:
    """Create a new artwork folder (image + masterpiece.json). Returns its name.

    Used by both the browser-upload endpoint (bytes from an UploadFile) and the
    desktop create-from-local-path endpoint (bytes read from the chosen file),
    so a single code path handles both runtimes.
    """
    archive = get_artwork_archive_path()
    archive.mkdir(parents=True, exist_ok=True)
    folder = _unique_dir(archive, slugify(title))
    folder.mkdir(parents=True)

    image_name = _safe_filename(image_filename, default="image.png")
    (folder / image_name).write_bytes(image_bytes)

    thumb_name = ""
    if thumbnail_bytes and thumbnail_filename:
        thumb_name = _safe_filename(thumbnail_filename, default="thumbnail.png")
        (folder / thumb_name).write_bytes(thumbnail_bytes)

    meta = {
        "title": title or folder.name.replace("_", " "),
        "description": description,
        "author": author or config.get_settings().get("default_author", ""),
        "rating": rating,
        "image": image_name,
        "thumbnail": thumb_name,
        "tags": tags or {},
        "titles": titles or {},
        "descriptions": descriptions or {},
        "categories": categories or {},
        "characters": characters or [],
        "platforms": platforms or [],
        "import_source": source or {},
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }
    (folder / _META_FILE).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Created masterpiece %s (%s)", folder.name, image_name)
    return folder.name


def read_raw_metadata(name: str) -> dict:
    """The raw parsed ``masterpiece.json`` for a folder — no tag cascade applied.

    ``load_artwork`` cascades ``tags.default`` onto every poster id (for package
    building); callers that need to EDIT the canonical record (e.g. change the
    default tags without freezing the cascade or clobbering real per-platform
    overrides) must read the raw file instead. Traversal-guarded via
    ``load_artwork``.
    """
    art = load_artwork(name)                 # re-anchors + validates the name
    src = _meta_path(art.path)
    if src is None:
        return {}
    return json.loads(src.read_text(encoding="utf-8"))


def save_artwork_metadata(name: str, updates: dict) -> ArtworkInfo:
    """Merge updates into an existing folder's metadata (the edit flow).

    Reads whichever metadata file exists, merges, and writes forward as
    ``masterpiece.json`` — retiring a legacy ``artwork.json`` so the folder keeps
    a single source of truth (migrate-on-edit; Phase 0). ``masterpiece.json`` is
    a strict superset, so nothing is lost.
    """
    artwork = load_artwork(name)
    src_path = _meta_path(artwork.path)
    data = json.loads(src_path.read_text(encoding="utf-8")) if src_path else {}
    data.update(updates)
    new_path = artwork.path / _META_FILE
    new_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    legacy = artwork.path / _LEGACY_META_FILE
    if legacy.is_file() and legacy != new_path:
        try:
            legacy.unlink()
        except OSError:
            logger.warning("Could not remove legacy artwork.json for %s", name)
    return load_artwork(name)
