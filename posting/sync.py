"""Retroactive sync — claim existing platform submissions into the publications registry.

Scans each platform's submissions table in PawPoller's database, matches them
to stories in the local archive by title, and populates the publications table
so that future /update commands can push revisions to already-live submissions.

Matching strategy:
  1. Normalize both story folder names and submission titles (lowercase, strip
     punctuation, collapse whitespace)
  2. Full-story match: "Extra Credit" ↔ Extra_Credit
  3. Chapter match: "Hypnotic Claim - Chapter 1: The Seduction" ↔ Hypnotic_Claim ch1
  4. Multi-part match: "Velvet and Vice (Part One)" ↔ Velvet_And_Vice ch1-4
  5. Skip test submissions (titles starting with [TEST])
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from database.db import get_connection
from database import posting_queries
from posting import story_reader

logger = logging.getLogger(__name__)

# Platform submission table configs: (table, id_col, title_col, url_template)
PLATFORM_TABLES = {
    "ib": {
        "table": "submissions",
        "id_col": "submission_id",
        "title_col": "title",
        "url_template": "https://inkbunny.net/s/{id}",
    },
    "fa": {
        "table": "fa_submissions",
        "id_col": "submission_id",
        "title_col": "title",
        "url_template": "https://www.furaffinity.net/view/{id}/",
    },
    "ws": {
        "table": "ws_submissions",
        "id_col": "submission_id",
        "title_col": "title",
        "url_template": "https://www.weasyl.com/submission/{id}",
    },
    "sf": {
        "table": "sf_submissions",
        "id_col": "submission_id",
        "title_col": "title",
        "url_template": "https://sofurry.com/s/{id}",
    },
    "sqw": {
        "table": "sqw_submissions",
        "id_col": "submission_id",
        "title_col": "title",
        "url_template": "https://squidgeworld.org/works/{id}",
    },
    "ao3": {
        "table": "ao3_submissions",
        "id_col": "submission_id",
        "title_col": "title",
        "url_template": "https://archiveofourown.org/works/{id}",
    },
    "wp": {
        "table": "wp_submissions",
        "id_col": "submission_id",
        "title_col": "title",
        "url_template": "https://www.wattpad.com/story/{id}",
    },
    "bsky": {
        "table": "bsky_submissions",
        "id_col": "submission_id",
        "title_col": "title",
        "url_template": "https://bsky.app/profile/_/post/{id}",
    },
}

# Word-to-number mapping for "Part One", "Part Two" etc.
_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _normalize(text: str) -> str:
    """Normalize a title for fuzzy matching."""
    text = text.lower().strip()
    text = re.sub(r'\[test\]', '', text)
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _story_name_to_title(name: str) -> str:
    """Convert folder name to normalized title.

    Handles compound names: The_Abstinent_Bet/Naughty_Version → the abstinent bet naughty version
    """
    return _normalize(name.replace("_", " ").replace("/", " "))


def claim_existing_submissions(
    platforms: list[str] | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """Scan platform tables and match submissions to archive stories.

    Args:
        platforms: Which platforms to scan (None = all with data).
        dry_run: If True, return matches without writing to publications.

    Returns:
        List of match dicts: {platform, story_name, chapter_index, external_id, title, url, status}
    """
    # Load all stories from archive
    stories = {}
    try:
        for s in story_reader.list_stories():
            try:
                info = story_reader.load_story(s["name"])
                stories[s["name"]] = info
            except Exception as e:
                logger.warning("Could not load story %s: %s", s["name"], e)
    except Exception as e:
        logger.error("Could not list stories: %s", e)
        return [{"error": f"Could not list stories: {e}"}]

    # Build lookup: normalized title → (story_name, chapter_index, chapter_title)
    title_map: list[tuple[str, str, int, str]] = []
    for name, info in stories.items():
        # Full story match
        norm = _story_name_to_title(name)
        title_map.append((norm, name, 0, ""))

        # Chapter matches
        for ch in info.chapters:
            # "Chapter 1: The Arrangement" → multiple match patterns
            ch_title_norm = _normalize(ch.title)
            # Pattern: "story - chapter title"
            title_map.append((f"{norm} {ch_title_norm}", name, ch.index, ch.title))
            # Pattern: "story chapter N"
            title_map.append((f"{norm} chapter {ch.index}", name, ch.index, ch.title))
            # Pattern: "story part N"
            title_map.append((f"{norm} part {ch.index}", name, ch.index, ch.title))

    conn = get_connection()
    results = []

    try:
        scan_platforms = platforms or list(PLATFORM_TABLES.keys())

        for platform in scan_platforms:
            cfg = PLATFORM_TABLES.get(platform)
            if not cfg:
                continue

            try:
                rows = conn.execute(
                    f"SELECT {cfg['id_col']}, {cfg['title_col']} FROM {cfg['table']}"
                ).fetchall()
            except Exception:
                continue  # Table doesn't exist or is empty

            if not rows:
                continue

            for row in rows:
                ext_id = str(row[0])
                title = row[1] or ""
                norm_title = _normalize(title)

                # Skip test submissions
                if "[test]" in title.lower():
                    continue

                # Try to match
                match = _find_match(norm_title, title_map, stories)
                if not match:
                    results.append({
                        "platform": platform,
                        "external_id": ext_id,
                        "title": title,
                        "status": "unmatched",
                        "story_name": None,
                        "chapter_index": None,
                    })
                    continue

                story_name, chapter_index, chapter_title = match
                url = cfg["url_template"].format(id=ext_id)

                # Check if already claimed
                existing = posting_queries.get_publication_by_story(
                    conn, story_name, chapter_index, platform
                )
                if existing:
                    results.append({
                        "platform": platform,
                        "external_id": ext_id,
                        "title": title,
                        "status": "already_claimed",
                        "story_name": story_name,
                        "chapter_index": chapter_index,
                    })
                    continue

                if not dry_run:
                    posting_queries.upsert_publication(
                        conn, story_name, chapter_index, platform,
                        external_id=ext_id,
                        external_url=url,
                        title_used=title,
                        status="posted",
                    )

                results.append({
                    "platform": platform,
                    "external_id": ext_id,
                    "title": title,
                    "url": url,
                    "status": "claimed",
                    "story_name": story_name,
                    "chapter_index": chapter_index,
                    "chapter_title": chapter_title,
                })

    finally:
        conn.close()

    claimed = sum(1 for r in results if r["status"] == "claimed")
    already = sum(1 for r in results if r["status"] == "already_claimed")
    unmatched = sum(1 for r in results if r["status"] == "unmatched")
    logger.info(
        "Claim sync: %d claimed, %d already claimed, %d unmatched",
        claimed, already, unmatched,
    )
    return results


def _find_match(
    norm_title: str,
    title_map: list[tuple[str, str, int, str]],
    stories: dict,
) -> tuple[str, int, str] | None:
    """Find the best story/chapter match for a normalized submission title.

    Returns (story_name, chapter_index, chapter_title) or None.
    """
    # Direct exact match
    for pattern, story_name, ch_idx, ch_title in title_map:
        if norm_title == pattern:
            return (story_name, ch_idx, ch_title)

    # Contains match — submission title contains the story name
    # Sort by longest pattern first (prefer more specific matches)
    sorted_patterns = sorted(title_map, key=lambda t: len(t[0]), reverse=True)
    for pattern, story_name, ch_idx, ch_title in sorted_patterns:
        if pattern in norm_title and len(pattern) > 5:
            # Check if there's chapter info in the title we can extract
            if ch_idx == 0:
                # Full story pattern matched — check for chapter number in title
                ch_num = _extract_chapter_number(norm_title, story_name)
                if ch_num and story_name in stories:
                    info = stories[story_name]
                    for ch in info.chapters:
                        if ch.index == ch_num:
                            return (story_name, ch_num, ch.title)
                # No chapter found — treat as full story
                return (story_name, 0, "")
            else:
                return (story_name, ch_idx, ch_title)

    # "Part One/Two" matching for split uploads
    for story_name_norm, story_name, _, _ in title_map:
        if story_name_norm in norm_title:
            part_match = re.search(r'part\s+(\w+)', norm_title)
            if part_match:
                part_word = part_match.group(1)
                part_num = _WORD_NUMBERS.get(part_word)
                if part_num is None:
                    try:
                        part_num = int(part_word)
                    except ValueError:
                        pass
                if part_num:
                    return (story_name, part_num, f"Part {part_num}")

    return None


def _extract_chapter_number(norm_title: str, story_name: str) -> int | None:
    """Try to extract a chapter number from a submission title."""
    # "story chapter 3" or "story ch 3" or "story - chapter 3: title"
    patterns = [
        r'chapter\s*(\d+)',
        r'ch\s*(\d+)',
        r'part\s*(\d+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, norm_title)
        if m:
            return int(m.group(1))
    return None
