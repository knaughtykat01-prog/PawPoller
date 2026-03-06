"""FurAffinity (FA) poll cycle orchestration.

Mirrors the Inkbunny poller pattern (see polling/poller.py) with two key
differences driven by FA's data-access constraints:

  1. **No faving-user tracking** -- FurAffinity does not expose per-submission
     fave lists through FAExport or its public pages, so the FA poller has
     no step 5 equivalent.  The ``stats`` dict omits ``new_faves_found``
     entirely.

  2. **Comment fetching via FAExport API** -- Instead of scraping raw HTML
     (as the IB poller does), comments are retrieved through the FAExport
     JSON endpoint.  This is more reliable but still rate-limited, so the
     same delta-based "only fetch when count changes" optimisation applies.

The rest of the structure (progress dict, concurrency guard, six-step
cycle, notification dispatch) is intentionally identical to the IB poller
so that the frontend can treat all platform pollers uniformly.
"""

from __future__ import annotations
import asyncio
import logging
import threading
import time
from datetime import datetime, timezone

import httpx

import config
from fa_client.client import FAClient
from database.db import get_connection
from database import fa_queries

logger = logging.getLogger(__name__)

# ── Progress tracking ────────────────────────────────────────
# Shared mutable dict read by /api/fa/poll/progress -- same pattern as
# the IB poller's poll_progress.  Prefixed with ``fa_`` so the two dicts
# can coexist at module level without collision.
fa_poll_progress = {
    "active": False,
    "phase": "idle",
    "current": 0,
    "total": 0,
    "message": "",
}

# Concurrency guard -- same purpose as _poll_running in the IB poller.
# Prevents overlapping FA poll cycles.  The Lock protects the
# check-and-set from race conditions; the boolean remains as a
# readable status indicator.
_fa_poll_running = False
_fa_poll_lock = threading.Lock()

# First-poll suppression: silent baseline on first poll after startup.
_fa_first_poll = True


def _update_fa_progress(phase: str, current: int = 0, total: int = 0, message: str = ""):
    """Mutate the shared fa_poll_progress dict so the frontend can display
    real-time status.  Mirrors _update_progress() in the IB poller."""
    fa_poll_progress["active"] = phase not in ("idle", "complete", "error")
    fa_poll_progress["phase"] = phase
    fa_poll_progress["current"] = current
    fa_poll_progress["total"] = total
    fa_poll_progress["message"] = message


def _send_fa_notifications(new_comment_details: list[dict],
                           new_watcher_names: list[str] | None = None) -> None:
    """Send Windows toast notifications for new FA comments and watchers.

    Unlike the IB poller, this does not handle faves -- there is no fave
    notification because FA does not expose per-submission fave lists.
    The toast is prefixed with "FA:" so users can distinguish it from
    IB notifications at a glance.  Truncated to 3 items like the IB version.
    """
    if new_watcher_names is None:
        new_watcher_names = []

    settings = config.get_settings()
    if not settings.get("fa_notifications_enabled", True):
        return
    if not new_comment_details and not new_watcher_names:
        return

    try:
        from winotify import Notification
    except ImportError:
        logger.debug("winotify not installed — skipping FA notifications")
        return

    # --- Comment toast (truncated to 3 items) ---
    if new_comment_details:
        shown = new_comment_details[:3]
        lines = [f"{d['username']} commented on {d['title']}" for d in shown]
        if len(new_comment_details) > 3:
            lines.append(f"...and {len(new_comment_details) - 3} more")
        toast = Notification(
            app_id="PawPoller",
            title=f"FA: {len(new_comment_details)} New Comment{'s' if len(new_comment_details) != 1 else ''}",
            msg="\n".join(lines),
        )
        toast.show()

    # --- Watcher toast (truncated to 3 items) ---
    if new_watcher_names and settings.get("fa_watcher_notifications_enabled", True):
        shown = new_watcher_names[:3]
        lines = [f"{name} started watching you" for name in shown]
        if len(new_watcher_names) > 3:
            lines.append(f"...and {len(new_watcher_names) - 3} more")
        toast = Notification(
            app_id="PawPoller",
            title=f"FA: {len(new_watcher_names)} New Watcher{'s' if len(new_watcher_names) != 1 else ''}",
            msg="\n".join(lines),
        )
        toast.show()


async def _send_fa_telegram(new_comment_details: list[dict],
                            new_watcher_names: list[str] | None = None) -> None:
    """Send Telegram notification for new FA comments and watchers.

    Format differs from the IB Telegram message: no faves section, and
    the header uses a fox emoji to visually distinguish FA alerts from IB
    alerts in the chat.  Truncated to 5 items, same as IB.  Uses Telegram
    HTML parse_mode for bold formatting.
    """
    if new_watcher_names is None:
        new_watcher_names = []

    settings = config.get_settings()
    if not settings.get("telegram_enabled", False):
        return
    token = settings.get("telegram_bot_token")
    chat_id = settings.get("telegram_chat_id")
    if not token or not chat_id:
        return
    if not new_comment_details and not new_watcher_names:
        return

    lines = []
    # --- Comments section ---
    if new_comment_details:
        lines.append(f"<b>🦊 FA: {len(new_comment_details)} New Comment{'s' if len(new_comment_details) != 1 else ''}</b>")
        for d in new_comment_details[:5]:
            lines.append(f"  • <b>{d['username']}</b> commented on {d['title']}")
        if len(new_comment_details) > 5:
            lines.append(f"  ...and {len(new_comment_details) - 5} more")

    # --- Watchers section ---
    if new_watcher_names:
        if lines:
            lines.append("")  # Visual separator before watchers
        lines.append(f"<b>🦊 FA: {len(new_watcher_names)} New Watcher{'s' if len(new_watcher_names) != 1 else ''}</b>")
        for name in new_watcher_names[:5]:
            lines.append(f"  • <b>{name}</b> started watching")
        if len(new_watcher_names) > 5:
            lines.append(f"  ...and {len(new_watcher_names) - 5} more")

    text = "\n".join(lines)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
    except Exception as e:
        logger.warning("Failed to send FA Telegram notification: %s", e)


async def run_fa_poll_cycle(force_full: bool = False) -> dict:
    """Execute one complete FurAffinity poll cycle.

    Follows the same pattern as the IB poller (run_poll_cycle) but with a
    reduced step count because FA's data model is more limited:

      1. **Gallery discovery** -- fetch all submission IDs via FAExport.
         (No auth step needed here; FAExport uses cookies set on the client.)
      2. **Detail fetch**      -- batch-fetch metadata for each submission.
      3. **Upsert + snapshot** -- write/update submission rows and record
                                  point-in-time stats.
      4. **Comments**          -- fetch comments via the FAExport API when
                                  the comment count has changed (or force_full).

    There is **no faving-user step** because FurAffinity does not expose
    per-submission fave lists through FAExport or any public endpoint.
    The stats dict therefore has no ``new_faves_found`` key.

    Args:
        force_full: When True, re-fetch comments for every submission
            regardless of whether their counts changed.

    Returns:
        Stats dict with keys: submissions_found, snapshots_inserted,
        new_comments_found.  Empty dict if a poll was already running.
    """
    global _fa_poll_running, _fa_first_poll

    # Concurrency guard -- identical pattern to the IB poller.
    # The Lock makes the check-and-set atomic so two near-simultaneous
    # callers cannot both slip through.
    if not _fa_poll_lock.acquire(blocking=False):
        logger.warning("FA poll already running — skipping")
        return {}
    _fa_poll_running = True
    _update_fa_progress("starting", message="Initialising FA poll cycle...")

    conn = get_connection()
    log_id = fa_queries.start_fa_poll_log(conn)
    start_time = time.time()

    # Note: no "new_faves_found" key -- FA doesn't provide faving user data.
    stats = {
        "submissions_found": 0,
        "snapshots_inserted": 0,
        "new_comments_found": 0,
        "new_watchers_found": 0,
    }

    # FA authentication uses cookie_a / cookie_b rather than a session ID.
    # These are stored in the user's settings and passed to the FAClient
    # constructor directly.
    settings = config.get_settings()
    client = FAClient(
        username=settings.get("fa_username", ""),
        cookie_a=settings.get("fa_cookie_a", ""),
        cookie_b=settings.get("fa_cookie_b", ""),
    )

    try:
        # ── Step 1: Discover gallery submissions via FAExport ──
        # FAExport provides a JSON list of submission IDs for a user's
        # gallery, which avoids the need to scrape FA's HTML gallery pages.
        _update_fa_progress("searching", message="Fetching gallery from FAExport...")
        gallery = await client.get_all_gallery_ids()
        submission_ids = [s["submission_id"] for s in gallery]
        stats["submissions_found"] = len(submission_ids)
        logger.info("FA: Found %d submissions", len(submission_ids))

        if not submission_ids:
            _update_fa_progress("complete", message="No FA submissions found.")
            fa_queries.finish_fa_poll_log(conn, log_id, "success", duration_seconds=time.time() - start_time, **stats)
            return stats

        # ── Step 2: Fetch details for each submission ──────────
        _update_fa_progress("fetching_details", message=f"Fetching details for {len(submission_ids)} submissions...")
        details = await client.get_submission_details_batch(submission_ids)
        logger.info("FA: Fetched details for %d submissions", len(details))

        # ── Step 3 & 4: Upsert + snapshot, then conditional comments ──
        new_comment_details = []
        poll_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        for idx, detail in enumerate(details, 1):
            _update_fa_progress("processing", current=idx, total=len(details),
                                message=f"Processing submission {idx}/{len(details)}...")

            # Per-submission try/except -- same resilience pattern as IB.
            try:
                sub_id = detail["submission_id"]
                views = detail.get("views", 0)
                faves = detail.get("favorites_count", 0)
                comments = detail.get("comments_count", 0)

                # Grab the previous comment count *before* the snapshot
                # overwrites it -- needed for the delta check below.
                prev_comments = fa_queries.get_fa_previous_comments_count(conn, sub_id)

                # Step 3: Upsert submission and record snapshot.
                fa_queries.upsert_fa_submission(conn, detail)
                fa_queries.insert_fa_snapshot(conn, sub_id, views, faves, comments, polled_at=poll_timestamp)
                stats["snapshots_inserted"] += 1

                # ── Step 4: Fetch comments (conditional) ───────
                # Uses the FAExport /submission/{id}.json endpoint to get
                # comments as structured JSON, unlike the IB poller which
                # scrapes HTML.  Same delta-based optimisation: only fetch
                # when count has changed or on force_full.
                should_fetch_comments = force_full and comments > 0
                if not should_fetch_comments:
                    if (prev_comments is not None and comments > prev_comments) or \
                       (prev_comments is None and comments > 0):
                        should_fetch_comments = True

                if should_fetch_comments:
                    logger.info("FA submission %d: fetching comments (count=%d, force=%s)", sub_id, comments, force_full)
                    # Rate-limit delay before each comment fetch.
                    await asyncio.sleep(config.FA_REQUEST_DELAY_SECONDS)
                    try:
                        scraped = await client.get_submission_comments(sub_id)
                        for c in scraped:
                            is_new = fa_queries.upsert_fa_comment(conn, c)
                            if is_new:
                                stats["new_comments_found"] += 1
                                new_comment_details.append({
                                    "username": c.get("username", ""),
                                    "title": detail.get("title", ""),
                                })
                    except Exception as ce:
                        # Comment fetch failure is non-fatal.
                        logger.warning("Failed to fetch FA comments for %d: %s", sub_id, ce)

            except Exception as e:
                # Per-submission error: log and continue with the next one.
                logger.warning("Error processing FA submission %s: %s", detail.get("submission_id"), e)

        conn.commit()

        # ── Step 5: Fetch watchers ───────────────────────────
        # Fetch the full watcher list and upsert each one.  New watchers
        # (not previously recorded) are counted for stats and notifications.
        new_watcher_names = []
        try:
            _update_fa_progress("fetching_watchers", message="Fetching watcher list...")
            watchers = await client.get_all_watchers()
            for username in watchers:
                is_new = fa_queries.upsert_fa_watcher(conn, username)
                if is_new:
                    stats["new_watchers_found"] += 1
                    new_watcher_names.append(username)
            conn.commit()
        except Exception as we:
            logger.warning("Failed to fetch FA watchers: %s", we)

        # ── Notifications (comments + watchers on FA) ────────────
        # Skip on first poll after startup (silent baseline).
        # Note: _fa_first_poll is cleared in the `finally` block so it
        # gets reset even if this poll fails with an exception.
        if _fa_first_poll:
            logger.info("First FA poll after startup — suppressing %d comment, %d watcher notifications",
                        len(new_comment_details), len(new_watcher_names))
        else:
            try:
                _send_fa_notifications(new_comment_details, new_watcher_names)
            except Exception as ne:
                logger.warning("Failed to send FA notifications: %s", ne)

            try:
                await _send_fa_telegram(new_comment_details, new_watcher_names)
            except Exception as te:
                logger.warning("Failed to send FA Telegram notification: %s", te)

        # ── Finalise ───────────────────────────────────────────
        duration = time.time() - start_time
        _update_fa_progress("complete", current=len(details), total=len(details),
                            message=f"Done — {stats['submissions_found']} submissions in {duration:.1f}s")
        fa_queries.finish_fa_poll_log(conn, log_id, "success", duration_seconds=duration, **stats)
        logger.info("FA poll complete in %.1fs — %d submissions, %d snapshots, %d new comments, %d new watchers",
                     duration, stats["submissions_found"], stats["snapshots_inserted"],
                     stats["new_comments_found"], stats["new_watchers_found"])
        return stats

    except Exception as e:
        # Top-level failure -- record partial stats and propagate.
        duration = time.time() - start_time
        _update_fa_progress("error", message=str(e))
        logger.error("FA poll failed: %s", e)
        fa_queries.finish_fa_poll_log(conn, log_id, "error", error_message=str(e), duration_seconds=duration, **stats)
        raise
    finally:
        # Always clear the guard and release resources.
        # Also clear _fa_first_poll so that a failed first attempt doesn't
        # suppress notifications on the next successful poll.
        if _fa_first_poll:
            _fa_first_poll = False
        _fa_poll_running = False
        _fa_poll_lock.release()
        await client.close()
        conn.close()
