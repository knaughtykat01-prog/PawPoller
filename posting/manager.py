"""Posting manager — orchestrates multi-platform story uploads and updates.

This is the main entry point for all posting operations. It coordinates
between the story_reader (which resolves local files and tags) and the
platform posters (which handle the actual HTTP uploads).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from database.db import get_connection
from database import posting_queries
from posting import story_reader
from posting.platforms.base import PlatformPoster, PostResult, StoryUploadPackage

logger = logging.getLogger(__name__)

# Platform poster registry — lazy-loaded to avoid circular imports
_posters: dict[str, PlatformPoster] = {}


def _get_poster(platform: str) -> PlatformPoster:
    """Get or create a platform poster instance."""
    if platform not in _posters:
        if platform == "ib":
            from posting.platforms.inkbunny import InkbunnyPoster
            _posters["ib"] = InkbunnyPoster()
        elif platform == "bsky":
            from posting.platforms.bluesky import BlueskyPoster
            _posters["bsky"] = BlueskyPoster()
        elif platform == "ws":
            from posting.platforms.weasyl import WeasylPoster
            _posters["ws"] = WeasylPoster()
        elif platform == "sf":
            from posting.platforms.sofurry import SoFurryPoster
            _posters["sf"] = SoFurryPoster()
        elif platform == "fa":
            from posting.platforms.furaffinity import FurAffinityPoster
            _posters["fa"] = FurAffinityPoster()
        elif platform == "sqw":
            from posting.platforms.squidgeworld import SquidgeWorldPoster
            _posters["sqw"] = SquidgeWorldPoster()
        else:
            raise ValueError(f"Unknown platform: {platform}")
    return _posters[platform]


def get_platform_requires(platform: str) -> str:
    """Get the runtime mode requirement for a platform."""
    try:
        poster = _get_poster(platform)
        return poster.requires_mode
    except ValueError:
        return "any"


PLATFORM_EMOJIS = {
    "ib": "🐾",
    "fa": "🦊",
    "ws": "🦎",
    "sf": "🐺",
    "bsky": "🦋",
}


async def post_story(
    story_name: str,
    platforms: list[str],
    chapters: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Post a story to multiple platforms.

    Args:
        story_name: Story folder name (e.g. "Extra_Credit").
        platforms: Platform IDs (e.g. ["ib", "bsky"]).
        chapters: Specific chapter indices (None = all). [0] = full story.

    Returns:
        List of result dicts with platform, chapter, success, url, error.
    """
    story = story_reader.load_story(story_name)
    results: list[dict[str, Any]] = []

    # Determine chapters to post
    if chapters is None:
        if story.total_chapters > 0:
            chapter_list = list(range(1, story.total_chapters + 1))
        else:
            chapter_list = [0]  # Full story
    else:
        chapter_list = chapters

    for platform in platforms:
        poster = _get_poster(platform)
        for ch_idx in chapter_list:
            package = story_reader.build_package(story, ch_idx, platform)

            # Validate
            errors = poster.validate(package)
            if errors:
                result_dict = {
                    "platform": platform,
                    "chapter_index": ch_idx,
                    "chapter_title": package.chapter_title,
                    "success": False,
                    "error": "; ".join(errors),
                }
                results.append(result_dict)
                logger.warning("Validation failed for %s ch%d on %s: %s",
                               story_name, ch_idx, platform, errors)
                continue

            # Post
            result = await poster.post(package)

            # Compute file hash for change detection
            from posting.sync import hash_file
            current_hash = hash_file(package.file_path) if package.file_path else ""

            # If the post failed on the server, auto-queue for desktop
            queued_for_desktop = False
            if not result.success:
                from posting.scheduler import _runtime_mode
                if _runtime_mode == "server":
                    conn = get_connection()
                    try:
                        posting_queries.add_to_queue(
                            conn, story_name, ch_idx, platform, "post",
                            requires="desktop",
                        )
                        queued_for_desktop = True
                        logger.info(
                            "Auto-queued %s ch%d on %s for desktop (server post failed: %s)",
                            story_name, ch_idx, platform, result.error,
                        )
                    finally:
                        conn.close()

            # Record in database
            conn = get_connection()
            try:
                pub_id = posting_queries.upsert_publication(
                    conn, story_name, ch_idx, platform,
                    external_id=result.external_id,
                    external_url=result.external_url,
                    title_used=package.title,
                    description_used=package.description[:500],
                    tags_used=package.tags,
                    rating_used=package.rating,
                    format_file=package.file_path or "",
                    file_hash=current_hash,
                    word_count=package.word_count,
                    status="posted" if result.success else "failed",
                )
                posting_queries.log_posting_action(
                    conn, platform, story_name, ch_idx,
                    action="post",
                    status="success" if result.success else ("queued_desktop" if queued_for_desktop else "failed"),
                    pub_id=pub_id,
                    external_id=result.external_id,
                    external_url=result.external_url,
                    error_message=result.error,
                    duration_seconds=result.duration_seconds,
                )
            finally:
                conn.close()

            results.append({
                "platform": platform,
                "chapter_index": ch_idx,
                "chapter_title": package.chapter_title,
                "success": result.success,
                "queued_desktop": queued_for_desktop,
                "external_id": result.external_id,
                "external_url": result.external_url,
                "error": result.error,
                "duration": result.duration_seconds,
            })

            # Rate limit between chapters on the same platform
            if ch_idx != chapter_list[-1]:
                await poster._rate_limit()

    return results


async def update_story(
    story_name: str,
    platforms: list[str] | None = None,
    chapters: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Push updates to already-posted submissions.

    Looks up existing publications and sends updated metadata/files.

    Args:
        story_name: Story folder name.
        platforms: Filter by platform (None = all posted platforms).
        chapters: Filter by chapter (None = all posted chapters).

    Returns:
        List of result dicts.
    """
    story = story_reader.load_story(story_name)
    results: list[dict[str, Any]] = []

    conn = get_connection()
    try:
        pubs = posting_queries.get_publications(conn, story_name=story_name, status="posted")
    finally:
        conn.close()

    if not pubs:
        logger.warning("No publications found for %s", story_name)
        return [{"error": f"No publications found for {story_name}"}]

    for pub in pubs:
        plat = pub["platform"]
        ch_idx = pub["chapter_index"]
        ext_id = pub["external_id"]

        if platforms and plat not in platforms:
            continue
        if chapters and ch_idx not in chapters:
            continue
        if not ext_id:
            continue

        poster = _get_poster(plat)
        package = story_reader.build_package(story, ch_idx, plat)

        if not poster.supports_edit:
            logger.warning(
                "Platform %s does not support in-place editing — will delete+repost",
                plat,
            )
        result = await poster.edit(ext_id, package)

        from posting.sync import hash_file
        current_hash = hash_file(package.file_path) if package.file_path else ""

        # If the edit failed on the server, auto-queue for desktop as a fallback
        queued_for_desktop = False
        if not result.success:
            from posting.scheduler import _runtime_mode
            if _runtime_mode == "server":
                conn = get_connection()
                try:
                    posting_queries.add_to_queue(
                        conn, story_name, ch_idx, plat, "update",
                        requires="desktop",
                    )
                    queued_for_desktop = True
                    logger.info(
                        "Auto-queued %s ch%d on %s for desktop (server edit failed: %s)",
                        story_name, ch_idx, plat, result.error,
                    )
                finally:
                    conn.close()

        conn = get_connection()
        try:
            if result.success:
                posting_queries.upsert_publication(
                    conn, story_name, ch_idx, plat,
                    external_id=result.external_id or ext_id,
                    external_url=result.external_url or pub["external_url"],
                    title_used=package.title,
                    description_used=package.description[:500],
                    tags_used=package.tags,
                    rating_used=package.rating,
                    format_file=package.file_path or "",
                    file_hash=current_hash,
                    word_count=package.word_count,
                    status="posted",
                )
            posting_queries.log_posting_action(
                conn, plat, story_name, ch_idx,
                action="update",
                status="success" if result.success else ("queued_desktop" if queued_for_desktop else "failed"),
                pub_id=pub["pub_id"],
                external_id=result.external_id or ext_id,
                external_url=result.external_url,
                error_message=result.error,
                duration_seconds=result.duration_seconds,
            )
        finally:
            conn.close()

        results.append({
            "platform": plat,
            "chapter_index": ch_idx,
            "chapter_title": package.chapter_title,
            "success": result.success,
            "queued_desktop": queued_for_desktop,
            "external_id": result.external_id or ext_id,
            "external_url": result.external_url or pub["external_url"],
            "error": result.error,
            "duration": result.duration_seconds,
        })

        await poster._rate_limit()

    return results


async def update_all_changed(
    platforms: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Push updates to all publications whose archive files have changed.

    Uses change detection to find stories with modified files, then calls
    update_story() for each changed story.

    Args:
        platforms: Filter to specific platforms (None = all).

    Returns:
        Aggregated list of result dicts from all update_story() calls.
    """
    from posting.sync import get_changed_stories

    changed = get_changed_stories()
    if not changed:
        return [{"status": "no_changes", "message": "All publications are up to date"}]

    all_results: list[dict[str, Any]] = []

    for story_name, items in changed.items():
        story_platforms = sorted(set(i["platform"] for i in items))
        if platforms:
            story_platforms = [p for p in story_platforms if p in platforms]
        if not story_platforms:
            continue

        story_results = await update_story(story_name, story_platforms)
        all_results.extend(story_results)

    return all_results
