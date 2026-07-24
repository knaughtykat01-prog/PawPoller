"""Posting manager — orchestrates multi-platform story uploads and updates.

This is the main entry point for all posting operations. It coordinates
between the story_reader (which resolves local files and tags) and the
platform posters (which handle the actual HTTP uploads).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any

from database.db import get_connection
from database import posting_queries
from posting import story_reader
from posting.platforms.base import PlatformPoster

logger = logging.getLogger(__name__)

# Retry backoff schedule: attempt 1 → 1min, attempt 2 → 5min, attempt 3 → 30min
_RETRY_DELAYS = [60, 300, 1800]


def _schedule_retry(story_name: str, ch_idx: int, platform: str, action: str,
                    attempt: int, error: str, content_type: str = "story") -> bool:
    """Queue a retry for a failed post/update if under max attempts.

    Returns True if a retry was queued, False if max attempts exceeded.
    content_type='artwork' keeps an artwork's retry routed back to post_artwork
    by the scheduler (which branches on the queued row's content_type).
    """
    # Permanent (config) failures — retrying can never succeed, so don't queue
    # a backoff that just re-fails every minute. The classic case: posting to a
    # platform whose credentials were never entered ("… not configured"). The
    # user must connect the account first; a retry loop only spams the log.
    _err_l = (error or "").lower()
    if "not configured" in _err_l:
        logger.warning("Retry: %s ch%d on %s — permanent config error, NOT retrying "
                       "(connect the account in Settings first): %s",
                       story_name, ch_idx, platform, error[:120])
        return False

    max_attempts = 3
    if attempt >= max_attempts:
        logger.info("Retry: %s ch%d on %s — max attempts (%d) reached, giving up",
                     story_name, ch_idx, platform, max_attempts)
        return False

    delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
    scheduled = (datetime.now(timezone.utc) + timedelta(seconds=delay)).strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    try:
        posting_queries.add_to_queue(
            conn, story_name, ch_idx, platform, action,
            content_type=content_type,
            scheduled_at=scheduled,
            priority=-1,
        )
        logger.info("Retry: %s ch%d on %s queued for %s (attempt %d, error: %s)",
                     story_name, ch_idx, platform, scheduled, attempt + 1, error[:100])
    finally:
        conn.close()
    return True

# Platform poster registry — lazy-loaded to avoid circular imports.
# Keyed by (platform, account_id) so each account keeps its own authenticated
# client/session — reusing one poster across accounts would leak account A's
# logged-in session into account B's uploads.
_posters: dict[tuple[str, int | None], PlatformPoster] = {}


def _get_poster(platform: str, account_id: int | None = None) -> PlatformPoster:
    """Get or create a platform poster instance for a specific account."""
    key = (platform, account_id)
    if key not in _posters:
        if platform == "ib":
            from posting.platforms.inkbunny import InkbunnyPoster
            poster: PlatformPoster = InkbunnyPoster()
        elif platform == "bsky":
            from posting.platforms.bluesky import BlueskyPoster
            poster = BlueskyPoster()
        elif platform == "ws":
            from posting.platforms.weasyl import WeasylPoster
            poster = WeasylPoster()
        elif platform == "sf":
            from posting.platforms.sofurry import SoFurryPoster
            poster = SoFurryPoster()
        elif platform == "fa":
            from posting.platforms.furaffinity import FurAffinityPoster
            poster = FurAffinityPoster()
        elif platform == "sqw":
            from posting.platforms.squidgeworld import SquidgeWorldPoster
            poster = SquidgeWorldPoster()
        elif platform == "ao3":
            from posting.platforms.ao3 import AO3Poster
            poster = AO3Poster()
        elif platform == "ik":
            from posting.platforms.itaku import ItakuPoster
            poster = ItakuPoster()
        elif platform == "da":
            from posting.platforms.deviantart import DeviantArtPoster
            poster = DeviantArtPoster()
        elif platform == "e621":
            from posting.platforms.e621 import E621Poster
            poster = E621Poster()
        elif platform == "ig":
            from posting.platforms.instagram import InstagramPoster
            poster = InstagramPoster()
        else:
            raise ValueError(f"Unknown platform: {platform}")
        # All posters carry an account_id; account-aware posters (IB, and FA
        # once refactored) read it in _ensure_client to authenticate as the
        # right account. None means "the platform's default account".
        poster.account_id = account_id
        _posters[key] = poster
    return _posters[key]


def _resolve_account_id(platform: str, account_id: int | None) -> int:
    """Return a concrete account_id for a platform, defaulting to its default account."""
    if account_id is not None:
        return account_id
    from database import accounts as accounts_db
    conn = get_connection()
    try:
        return accounts_db.get_default_account_id(conn, platform, create=True)
    finally:
        conn.close()


def get_platform_requires(platform: str) -> str:
    """Get the runtime mode requirement for a platform."""
    try:
        poster = _get_poster(platform)
        return poster.requires_mode
    except ValueError:
        return "any"


# Error patterns that mean "the submission no longer exists on the platform".
# When we detect one of these during update_story(), we mark the publication
# as 'deleted' in the registry so the matrix flips it back to a re-postable
# state instead of repeatedly retrying an edit against a dead ID.
#
# All patterns scoped to phrasings that refer to the submission/work/URL, not
# generic "not found" (which would false-positive on unrelated errors like
# "model not found in cache" or local file-not-found exceptions).
DELETION_ERROR_PATTERNS = (
    "submission has been deleted",     # Inkbunny
    "submission not found",            # FA / generic
    "submission was not found",        # FA
    "work not found",                  # AO3
    "work has been deleted",           # AO3
    "work does not exist",             # AO3
    "page does not exist",             # generic OTW
    "no such submission",              # SF-ish
    "404 not found",                   # direct httpx error string
    "client error '404",               # httpx's formatted 404 message
)


def _looks_like_deletion(error: str | None) -> bool:
    if not error:
        return False
    low = error.lower()
    return any(p in low for p in DELETION_ERROR_PATTERNS)


PLATFORM_EMOJIS = {
    "ib": "🐾",
    "fa": "🦊",
    "ws": "🦎",
    "sf": "🐺",
    "sqw": "🦑",
    "ao3": "📖",
    "ik": "🎯",
    "da": "🎨",
    "bsky": "🦋",
}


async def post_story(
    story_name: str,
    platforms: list[str],
    chapters: list[int] | None = None,
    extras: dict[str, Any] | None = None,
    account_ids: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Post a story to multiple platforms.

    Args:
        story_name: Story folder name (e.g. "Example_Story").
        platforms: Platform IDs (e.g. ["ib", "bsky"]).
        chapters: Specific chapter indices (None = all). [0] = full story.
        extras: Per-package overrides merged into ``package.extra`` before
            posting (e.g. ``{"draft": True}`` to post as a draft on
            platforms that support it).
        account_ids: Optional ``{platform: account_id}`` selecting which account
            to post AS per platform. Platforms not listed use their default
            account.

    Returns:
        List of result dicts with platform, chapter, success, url, error.
    """
    account_ids = account_ids or {}
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
        account_id = _resolve_account_id(platform, account_ids.get(platform))
        poster = _get_poster(platform, account_id)
        for ch_idx in chapter_list:
            package = story_reader.build_package(story, ch_idx, platform)
            if extras:
                package.extra.update(extras)

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

            # If the post failed, try to auto-recover:
            # 1. Desktop-requiring platforms → queue for desktop
            # 2. Rate limit / transient errors → schedule retry with backoff
            queued_for_desktop = False
            retry_queued = False
            if not result.success:
                from posting.scheduler import _runtime_mode
                if poster.requires_mode == "desktop" and _runtime_mode == "server":
                    conn = get_connection()
                    try:
                        posting_queries.add_to_queue(
                            conn, story_name, ch_idx, platform, "post",
                            account_id=account_id,
                            requires="desktop",
                        )
                        queued_for_desktop = True
                        logger.info(
                            "Auto-queued %s ch%d on %s (account %s) for desktop (server post failed: %s)",
                            story_name, ch_idx, platform, account_id, result.error,
                        )
                    finally:
                        conn.close()
                elif not queued_for_desktop:
                    retry_queued = _schedule_retry(
                        story_name, ch_idx, platform, "post", 0, result.error or "unknown",
                    )

            # Record in database
            conn = get_connection()
            try:
                pub_id = posting_queries.upsert_publication(
                    conn, story_name, ch_idx, platform,
                    account_id=account_id,
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
                    account_id=account_id,
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
                "retry_queued": retry_queued,
                "external_id": result.external_id,
                "external_url": result.external_url,
                "error": result.error,
                "duration": result.duration_seconds,
            })

            # Rate limit between chapters on the same platform
            if ch_idx != chapter_list[-1]:
                await poster._rate_limit()

    return results


async def post_artwork(
    artwork_name: str,
    platforms: list[str],
    extras: dict[str, Any] | None = None,
    account_ids: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Post one artwork (a single image) to multiple platforms.

    The image-posting parallel to ``post_story``: same per-platform posters,
    validation, registry, and desktop-queue/retry fallbacks. The only
    differences are the source (artwork_reader, not story_reader), the fixed
    chapter_index 0, and content_type='artwork' on every registry write.

    Args:
        artwork_name: Artwork folder name in the artwork archive.
        platforms: Platform IDs (e.g. ["ib", "fa", "bsky"]).
        extras: Per-package overrides merged into ``package.extra`` before posting.
        account_ids: Optional ``{platform: account_id}`` selecting which account
            to post AS per platform. Platforms not listed use their default.

    Returns:
        List of result dicts with platform, success, url, error.
    """
    from posting import artwork_reader
    account_ids = account_ids or {}
    artwork = artwork_reader.load_artwork(artwork_name)
    results: list[dict[str, Any]] = []

    _wm_temps: list[str] = []   # watermark temp files, cleaned after the loop
    for platform in platforms:
        account_id = _resolve_account_id(platform, account_ids.get(platform))
        poster = _get_poster(platform, account_id)
        package = artwork_reader.build_artwork_package(artwork, platform)
        if extras:
            package.extra.update(extras)

        # Watermark (gap-wave-5 §1): swap in a stamped temp copy before
        # validation (so the size check sees the real bytes) and post that.
        # No-op / never raises when disabled or on any PIL error. Temps are
        # collected and deleted after the whole loop (a retry within an
        # iteration re-posts the same package, so they must outlive it).
        from posting import watermark
        _wm_path, _wm_tmp = watermark.apply(package.file_path)
        if _wm_tmp:
            package.file_path = _wm_path
            _wm_temps.append(_wm_tmp)

        # Validate
        errors = poster.validate(package)
        if errors:
            results.append({
                "platform": platform,
                "chapter_index": 0,
                "chapter_title": "",
                "success": False,
                "error": "; ".join(errors),
            })
            logger.warning("Validation failed for artwork %s on %s: %s",
                           artwork_name, platform, errors)
            continue

        # Post
        result = await poster.post(package)

        # Compute file hash for change detection (the image itself)
        from posting.sync import hash_file
        current_hash = hash_file(package.file_path) if package.file_path else ""

        # Auto-recover failures, mirroring post_story:
        #   1. Desktop-requiring platforms (FA/DA) → queue for desktop
        #   2. Rate-limit / transient errors → backoff retry
        queued_for_desktop = False
        retry_queued = False
        if not result.success:
            from posting.scheduler import _runtime_mode
            if poster.requires_mode == "desktop" and _runtime_mode == "server":
                conn = get_connection()
                try:
                    posting_queries.add_to_queue(
                        conn, artwork_name, 0, platform, "post",
                        account_id=account_id,
                        content_type="artwork",
                        requires="desktop",
                    )
                    queued_for_desktop = True
                    logger.info(
                        "Auto-queued artwork %s on %s (account %s) for desktop "
                        "(server post failed: %s)",
                        artwork_name, platform, account_id, result.error,
                    )
                finally:
                    conn.close()
            elif not queued_for_desktop:
                retry_queued = _schedule_retry(
                    artwork_name, 0, platform, "post", 0, result.error or "unknown",
                    content_type="artwork",
                )

        # Record in database (content_type='artwork' so it never collides with
        # a same-named story and the Stories views never show it).
        conn = get_connection()
        try:
            pub_id = posting_queries.upsert_publication(
                conn, artwork_name, 0, platform,
                account_id=account_id,
                content_type="artwork",
                external_id=result.external_id,
                external_url=result.external_url,
                title_used=package.title,
                description_used=package.description[:500],
                tags_used=package.tags,
                rating_used=package.rating,
                format_file=package.file_path or "",
                file_hash=current_hash,
                word_count=0,
                status="posted" if result.success else "failed",
            )
            posting_queries.log_posting_action(
                conn, platform, artwork_name, 0,
                action="post",
                account_id=account_id,
                content_type="artwork",
                status="success" if result.success else (
                    "queued_desktop" if queued_for_desktop else "failed"),
                pub_id=pub_id,
                external_id=result.external_id,
                external_url=result.external_url,
                error_message=result.error,
                duration_seconds=result.duration_seconds,
            )
            # Publishing IS mastering (spec §6.1): the artwork folder IS the
            # Masterpiece (Phase 0), so a successful upload becomes a member with
            # linked_via='publication'. This is what makes a fresh "New Masterpiece"
            # accumulate its members automatically as it is posted. Idempotent
            # (add_member = INSERT OR IGNORE + ensure_indexed); best-effort so a
            # membership-link failure never breaks an already-recorded post.
            if result.success and result.external_id:
                try:
                    from database import masterpiece_queries
                    masterpiece_queries.add_member(
                        conn, artwork_name, platform, result.external_id,
                        account_id=account_id, role="crosspost",
                        linked_via="publication")
                    conn.commit()
                except Exception:
                    logger.warning("Masterpiece member link failed for %s/%s",
                                   artwork_name, platform, exc_info=True)
        finally:
            conn.close()

        results.append({
            "platform": platform,
            "chapter_index": 0,
            "chapter_title": "",
            "success": result.success,
            "queued_desktop": queued_for_desktop,
            "retry_queued": retry_queued,
            "external_id": result.external_id,
            "external_url": result.external_url,
            "error": result.error,
            "duration": result.duration_seconds,
        })

    # Clean up watermark temp files (gap-wave-5 §1) now every post + retry is done.
    for _t in _wm_temps:
        try:
            os.remove(_t)
        except OSError:
            pass

    # Discord announce (gap G4) — once per publish if any platform succeeded.
    # Best-effort; announce_publish self-gates on config + never raises.
    succeeded = [r["platform"] for r in results if r.get("success")]
    if succeeded:
        from posting import discord
        first_url = next((r.get("external_url") for r in results
                          if r.get("success") and r.get("external_url")), None)
        await discord.announce_publish(
            kind="artwork", title=getattr(artwork, "title", "") or artwork_name,
            url=first_url, rating=getattr(artwork, "rating", ""), platforms=succeeded,
        )
    return results


async def update_story(
    story_name: str,
    platforms: list[str] | None = None,
    chapters: list[int] | None = None,
    extras: dict[str, Any] | None = None,
    account_filter: int | None = None,
) -> list[dict[str, Any]]:
    """Push updates to already-posted submissions.

    Looks up existing publications and sends updated metadata/files. Each
    publication is updated AS the account it was posted under (pub.account_id).

    Args:
        story_name: Story folder name.
        platforms: Filter by platform (None = all posted platforms).
        chapters: Filter by chapter (None = all posted chapters).
        extras: Per-package overrides merged into ``package.extra`` before
            the edit runs (e.g. ``{"skip_content_refresh": True}`` to
            push metadata only, skipping the file/chapter content
            upload where supported).
        account_filter: When set, only update publications owned by this
            account_id (used by the scheduler to update the specific account a
            queued item targeted).

    Returns:
        List of result dicts.
    """
    story = story_reader.load_story(story_name)
    results: list[dict[str, Any]] = []

    conn = get_connection()
    try:
        # Include both posted and failed publications (failed ones may need retrying)
        posted = posting_queries.get_publications(conn, story_name=story_name, status="posted")
        failed = posting_queries.get_publications(conn, story_name=story_name, status="failed")
        # Deduplicate by (story, chapter, platform, account) — prefer posted over
        # failed. account_id is part of the key so two accounts' copies of the
        # same chapter are updated independently.
        seen = set()
        pubs = []
        for p in posted + failed:
            key = (p["story_name"], p["chapter_index"], p["platform"], p["account_id"])
            if key not in seen:
                seen.add(key)
                pubs.append(p)
    finally:
        conn.close()

    if not pubs:
        logger.warning("No publications found for %s", story_name)
        return [{"error": f"No publications found for {story_name}"}]

    for pub in pubs:
        plat = pub["platform"]
        ch_idx = pub["chapter_index"]
        ext_id = pub["external_id"]
        account_id = pub["account_id"]

        if platforms and plat not in platforms:
            continue
        if chapters and ch_idx not in chapters:
            continue
        if account_filter is not None and account_id != account_filter:
            continue
        if not ext_id:
            continue

        poster = _get_poster(plat, account_id)
        package = story_reader.build_package(story, ch_idx, plat)
        if extras:
            package.extra.update(extras)

        if not poster.supports_edit:
            logger.warning(
                "Platform %s does not support in-place editing — will delete+repost",
                plat,
            )
        result = await poster.edit(ext_id, package)

        from posting.sync import hash_file
        current_hash = hash_file(package.file_path) if package.file_path else ""

        # Was the submission deleted on the platform side? Mark the
        # publication so the matrix prompts a re-post rather than
        # retrying the edit (which will keep failing).
        was_deleted = (not result.success) and _looks_like_deletion(result.error)

        # If the edit failed on the server for some OTHER reason, auto-queue
        # for desktop as a fallback. Deletion errors skip the queue — desktop
        # would hit the same wall.
        queued_for_desktop = False
        retry_queued = False
        if not result.success and not was_deleted:
            from posting.scheduler import _runtime_mode
            if poster.requires_mode == "desktop" and _runtime_mode == "server":
                conn = get_connection()
                try:
                    posting_queries.add_to_queue(
                        conn, story_name, ch_idx, plat, "update",
                        account_id=account_id,
                        requires="desktop",
                    )
                    queued_for_desktop = True
                    logger.info(
                        "Auto-queued %s ch%d on %s (account %s) for desktop (server edit failed: %s)",
                        story_name, ch_idx, plat, account_id, result.error,
                    )
                finally:
                    conn.close()
            elif not queued_for_desktop:
                retry_queued = _schedule_retry(
                    story_name, ch_idx, plat, "update", 0, result.error or "unknown",
                )
        elif was_deleted:
            logger.info(
                "Publication %s ch%d on %s was deleted upstream — marking registry",
                story_name, ch_idx, plat,
            )

        conn = get_connection()
        try:
            if was_deleted:
                # Mark as deleted so the matrix treats this slot as
                # re-postable. Keep the external_id/url for history.
                posting_queries.upsert_publication(
                    conn, story_name, ch_idx, plat,
                    account_id=account_id,
                    external_id=ext_id,
                    external_url=pub["external_url"],
                    title_used=package.title,
                    description_used=package.description[:500],
                    tags_used=package.tags,
                    rating_used=package.rating,
                    format_file=package.file_path or "",
                    file_hash=current_hash,
                    word_count=package.word_count,
                    status="deleted",
                )
            elif result.success:
                posting_queries.upsert_publication(
                    conn, story_name, ch_idx, plat,
                    account_id=account_id,
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
            log_status = (
                "success" if result.success
                else "deleted_upstream" if was_deleted
                else "queued_desktop" if queued_for_desktop
                else "failed"
            )
            posting_queries.log_posting_action(
                conn, plat, story_name, ch_idx,
                action="update",
                account_id=account_id,
                status=log_status,
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
            "retry_queued": retry_queued,
            "deleted_upstream": was_deleted,
            "external_id": result.external_id or ext_id,
            "external_url": result.external_url or pub["external_url"],
            "error": result.error,
            "duration": result.duration_seconds,
        })

        await poster._rate_limit()

    return results


async def update_artwork(
    artwork_name: str,
    platforms: list[str] | None = None,
    account_filter: int | None = None,
    extras: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Push a Masterpiece's canonical metadata to its editable members ("Sync all",
    spec §6.2). The artwork parallel of ``update_story``, but driven off the
    ``masterpiece_members`` table (so it also reaches members linked by promote /
    pHash that never had a publication) and **metadata-only** by default.

    For each member whose poster reports ``supports_edit``: rebuild the artwork
    package from ``masterpiece.json`` and call ``poster.edit(submission_id,
    package)`` with ``extra['skip_content_refresh']=True`` — we push
    title/description/tags/rating, never re-upload the image. Members on platforms
    that can't edit (Bluesky/e621/Itaku) are returned as skipped ``post-only`` and
    never touched (§0-A1). Each edit is recorded (log + publication metadata,
    content_type='artwork').

    Args:
        artwork_name: Masterpiece / artwork folder name.
        platforms: Restrict to these platforms (None = all editable members).
        account_filter: Only members owned by this account_id.
        extras: Extra package overrides (merged after skip_content_refresh).

    Returns: one result dict per member (skipped members carry ``skipped=True``).
    """
    from posting import artwork_reader
    from database import masterpiece_queries

    artwork = artwork_reader.load_artwork(artwork_name)

    conn = get_connection()
    try:
        members = masterpiece_queries.get_members(conn, artwork_name)
    finally:
        conn.close()
    if not members:
        return [{"error": f"No linked uploads for {artwork_name}"}]

    results: list[dict[str, Any]] = []
    for m in members:
        plat = m["platform"]
        ext_id = str(m["submission_id"])
        account_id = m.get("account_id")

        if platforms and plat not in platforms:
            continue
        if account_filter is not None and account_id != account_filter:
            continue
        if not ext_id:
            continue

        # Resolve None → the platform's default account (a concrete id is required
        # for _get_poster / the publication + log writes), mirroring post_artwork.
        account_id = _resolve_account_id(plat, account_id)
        try:
            poster = _get_poster(plat, account_id)
        except ValueError:
            results.append({"platform": plat, "submission_id": ext_id,
                            "success": False, "skipped": True, "reason": "no poster"})
            continue
        # Non-editable platforms are post-only — never silently overwrite them.
        if not poster.supports_edit:
            results.append({"platform": plat, "submission_id": ext_id,
                            "success": False, "skipped": True, "reason": "post-only"})
            continue

        package = artwork_reader.build_artwork_package(artwork, plat)
        package.extra["skip_content_refresh"] = True   # metadata sync only — never re-upload the image
        if extras:
            package.extra.update(extras)

        result = await poster.edit(ext_id, package)

        conn = get_connection()
        try:
            pub_id = posting_queries.upsert_publication(
                conn, artwork_name, 0, plat,
                account_id=account_id,
                content_type="artwork",
                external_id=result.external_id or ext_id,
                external_url=result.external_url or "",
                title_used=package.title,
                description_used=package.description[:500],
                tags_used=package.tags,
                rating_used=package.rating,
                status="posted" if result.success else "failed",
            )
            posting_queries.log_posting_action(
                conn, plat, artwork_name, 0,
                action="update",
                account_id=account_id,
                content_type="artwork",
                status="success" if result.success else "failed",
                pub_id=pub_id,
                external_id=result.external_id or ext_id,
                external_url=result.external_url,
                error_message=result.error,
                duration_seconds=result.duration_seconds,
            )
        finally:
            conn.close()

        results.append({
            "platform": plat,
            "submission_id": ext_id,
            "success": result.success,
            "external_url": result.external_url or "",
            # A successful edit may carry a soft note (e.g. Weasyl: file content
            # can't be replaced via API) — surface it without failing the sync.
            "note": result.error if result.success else None,
            "error": None if result.success else result.error,
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
