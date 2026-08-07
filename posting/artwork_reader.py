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
_ALL_POSTER_IDS = ["ib", "fa", "ws", "sf", "da", "ik", "bsky", "e621", "ig", "fn"]

# Metadata filename. The Masterpiece era (Phase 0) writes `masterpiece.json`;
# legacy folders have `artwork.json`. `masterpiece.json` is a back-compatible
# SUPERSET of `artwork.json`, so a folder with only the legacy file is a valid
# Masterpiece with no members yet. Readers accept BOTH (prefer the new file);
# writers emit the new file and retire the legacy one on first edit.
_META_FILE = "masterpiece.json"
_LEGACY_META_FILE = "artwork.json"

# Keys inside a work's `tags` dict that are NOT platform codes. Everything else
# in that dict is a per-platform override and wins over the canonical list.
_TAG_KEY_CORE = "core"
_TAG_KEY_AUX = "auxiliary"
_TAG_KEY_LEGACY = "default"
_RESERVED_TAG_KEYS = frozenset({_TAG_KEY_CORE, _TAG_KEY_AUX, _TAG_KEY_LEGACY})

# Per-platform tag budgets. `chars` is the maximum length of the joined tag
# string, `count` the maximum number of tags. None = no known limit, send
# everything.
#
# FurAffinity's 500 is enforced by posting/platforms/furaffinity.py::validate,
# which REJECTS the upload rather than truncating — so trimming here is what
# keeps a heavily-tagged work postable to FA at all. AO3/SquidgeWorld cap the
# total tag count at 75 (OTW); that trim already happens in ao3.py, and the
# budget is repeated here so the resolver agrees with it.
_TAG_BUDGET: dict[str, dict] = {
    "fa": {"chars": 500, "count": None},
    "ao3": {"chars": None, "count": 75},
    "sqw": {"chars": None, "count": 75},
}


def _canonical_tag_list(tags: dict) -> list[str]:
    """core + auxiliary, de-duplicated, order preserved.

    Falls back to the legacy flat `default` list for folders written before the
    core/auxiliary split, so nothing has to be migrated up front — a folder is
    converted the next time it is saved.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for key in (_TAG_KEY_CORE, _TAG_KEY_LEGACY, _TAG_KEY_AUX):
        for tag in tags.get(key) or []:
            low = tag.lower()
            if low not in seen:
                seen.add(low)
                ordered.append(tag)
    return ordered


def variant_tags(artwork_tags: dict, variant: dict) -> dict:
    """The effective tag dict for one variant.

    A variant may carry its own ``tags`` ({"core": [...], "auxiliary": [...]});
    when it doesn't, it inherits the parent work's. This matters because a
    variant is genuinely different content, not just a different file — the
    catalogue already has **SFW**, **Nude**, **Cum**, **Clean** and **Sketch**
    variants, and three of them carry a different rating from their parent.
    Posting an SFW render with the parent's explicit tag set would mis-tag it
    on every booru that reads tags literally.
    """
    own = variant.get("tags")
    if isinstance(own, dict) and any(own.get(k) for k in _RESERVED_TAG_KEYS):
        return {k: list(v) for k, v in own.items()}
    return {k: list(v) for k, v in (artwork_tags or {}).items()}


def variant_description(artwork_description: str, variant: dict) -> str:
    """The effective description for one variant.

    A variant may carry its own ``description``; without one it inherits the
    work's. Unlike the per-platform description map, a variant's description
    beats everything except an explicit ``description_override`` — because a
    variant is different CONTENT, not a different audience. Letting a
    per-platform description win here would caption an SFW render with the
    parent's explicit blurb, which is the exact failure the variant tag split
    was built to stop.
    """
    own = (variant or {}).get("description")
    return own if isinstance(own, str) and own.strip() else artwork_description


def fit_tags_to_platform(tags: list[str], platform: str,
                         core_count: int | None = None) -> list[str]:
    """Trim a tag list to what `platform` will actually accept.

    Tags are assumed to arrive core-first. Trimming therefore drops from the
    TAIL, which is why the core/auxiliary split matters: whatever survives is
    guaranteed to be the tags that were declared to matter most.

    `core_count` (when known) marks the boundary, and is used only to warn when
    a platform's budget is so tight that even the core set does not fit — that
    is a tagging problem the user needs to know about, not something to paper
    over silently.
    """
    budget = _TAG_BUDGET.get(platform)
    if not budget:
        return list(tags)

    out = list(tags)
    max_count = budget.get("count")
    if max_count and len(out) > max_count:
        out = out[:max_count]
    max_chars = budget.get("chars")
    if max_chars:
        while out and len(" ".join(out)) > max_chars:
            out.pop()

    if core_count and len(out) < core_count:
        logger.warning(
            "%s tag budget cut into the core set: %d of %d core tags fit "
            "(limit chars=%s count=%s)",
            platform, len(out), core_count, budget.get("chars"), budget.get("count"))
    return out


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
    # Image description for screen readers (gap G6). Used by platforms that
    # support per-image alt (Bluesky today); falls back to the title at post
    # time so alt is never regressed to empty.
    alt_text: str = ""

    # Declared variants (2.190.0): one entry per alternate render, each with
    # key/label/image/rating and — since 3.2.0 — optionally its own `tags`.
    # Carried on the dataclass so build_artwork_package can post a specific
    # render; list_artworks() has always exposed them in its dict output.
    variants: list = field(default_factory=list)

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
            # Declared variants (2.190.0) so the gallery can show a tile per render,
            # not just the master. Empty for a plain single-image piece.
            "variants": data.get("variants", []),
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

    # Tags: cascade the canonical list → any platform without an explicit list
    # (mirrors the story_reader cascade + the editor's "cascades to all").
    #
    # The tags dict is keyed by PLATFORM, with three RESERVED keys that are not
    # platforms (see _RESERVED_TAG_KEYS):
    #   core       the 20-25 tags that matter most, already in priority order
    #              (artist → species → character → mainstream kink → act →
    #              explicit anatomy → niche → misc)
    #   auxiliary  the long tail; everything else worth carrying
    #   default    legacy name for the whole flat list, read as `core`
    #
    # The split exists because the tag budget is per platform: FurAffinity
    # rejects a submission whose whole tag string exceeds 500 characters, so a
    # 90-tag work cannot go there intact. Keeping core separate means the
    # platforms that truncate still receive the tags that matter, and the ones
    # with no limit receive everything. Ordering alone could not guarantee that
    # — a cut could land mid-way through the core set.
    tags = {k: list(v) for k, v in data.get("tags", {}).items()}
    canonical = _canonical_tag_list(tags)
    if canonical:
        for pid in _ALL_POSTER_IDS:
            tags.setdefault(pid, list(canonical))

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
        alt_text=data.get("alt_text", ""),
        variants=list(data.get("variants", []) or []),
    )


def build_artwork_package(
    artwork: ArtworkInfo,
    platform: str,
    title_override: str | None = None,
    description_override: str | None = None,
    tags_override: list[str] | None = None,
    rating_override: str | None = None,
    variant_key: str | None = None,
) -> StoryUploadPackage:
    """Build a StoryUploadPackage for one artwork + platform.

    Reuses StoryUploadPackage (the universal upload package): file_path is the
    image, file_type its extension, chapter_index fixed at 0. Per-platform
    title/description/tag overrides cascade just like ``build_package``.
    ``extra`` carries the platform's submission-category params (FA
    cat/species/gender, SF category/sub_type, …) for the poster to apply.

    ``variant_key`` selects a declared variant instead of the primary render —
    its image, its rating, and its own tags where it has them (3.2.0). A
    variant is genuinely different content: the catalogue holds SFW, Censored,
    Nude and Cum renders, three of which already carry a rating different from
    their parent, so posting one under the parent's explicit tags would
    mis-tag it. No UI passes a variant_key yet; this is the mechanism that a
    "post this render" action will use.
    """
    variant = None
    if variant_key:
        variant = next((v for v in (artwork.variants or [])
                        if v.get("key") == variant_key), None)
        if variant is None:
            raise ValueError(
                f"{artwork.name}: no variant with key {variant_key!r}")
    title = title_override or artwork.titles_by_platform.get(platform) or artwork.title

    if description_override:
        description = description_override
    elif variant is not None and variant_description("", variant):
        # A variant's own description describes different CONTENT, so it beats
        # the per-platform map (see variant_description). Only an explicit
        # override outranks it.
        description = variant_description("", variant)
    elif platform in artwork.descriptions_by_platform:
        description = artwork.descriptions_by_platform[platform]
    elif platform == "bsky" and artwork.descriptions_by_platform.get("announcement"):
        description = artwork.descriptions_by_platform["announcement"]
    else:
        description = artwork.descriptions_by_platform.get("default", artwork.description)

    # "Posted via PawPoller" credit line (gap-wave-2 §1) — appended here, the
    # choke point every artwork posting path flows through. Self-gates on the
    # pawpoller_attribution setting, skips bsky, never double-appends.
    from posting import attribution
    description = attribution.maybe_append(description, platform)

    if tags_override is not None:
        tags = tags_override
    else:
        # An explicit per-platform list wins outright; otherwise take the
        # canonical core+auxiliary list and trim it to what this platform
        # accepts. Trimming drops from the tail, so the core survives.
        # A variant's own tags replace the parent's outright; without them it
        # inherits, which is the pre-3.2.0 behaviour.
        source = (variant_tags(artwork.tags_by_platform, variant)
                  if variant is not None else artwork.tags_by_platform)
        explicit = source.get(platform)
        if explicit is not None and platform not in _RESERVED_TAG_KEYS:
            tags = list(explicit)
        else:
            canonical = _canonical_tag_list(source)
            core_len = len(source.get(_TAG_KEY_CORE) or []) or None
            tags = fit_tags_to_platform(canonical, platform, core_len)

    settings = config.get_settings()
    rating = (rating_override
              or (variant.get("rating") if variant else "")
              or artwork.rating
              or settings.get("artwork_default_rating",
                              settings.get("posting_default_rating", "adult")))

    image_path = artwork.image_path
    if variant and variant.get("image"):
        candidate = artwork.path / variant["image"]
        if candidate.is_file():
            image_path = str(candidate)
        else:
            logger.warning("%s: variant %r image %s missing, using the primary render",
                           artwork.name, variant_key, variant["image"])
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
        # Categories are the platform's submission params; alt_text rides along
        # for posters that support per-image alt (bluesky.py reads it, G6).
        extra={**dict(artwork.categories_by_platform.get(platform, {})),
               **({"alt_text": artwork.alt_text} if artwork.alt_text else {})},
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
    alt_text: str = "",
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
        "alt_text": alt_text,
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
