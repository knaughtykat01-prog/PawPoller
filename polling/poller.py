"""Full poll cycle orchestration for Inkbunny (IB).

This module implements the main Inkbunny polling loop. A single poll cycle
walks through six sequential steps:
  1. Authenticate (restore cached SID or create a new session)
  2. Search for all user submissions
  3. Fetch full submission details in batches
  4. Upsert each submission into the DB and record a stat snapshot
  5. Fetch faving users (only when the fave count has changed)
  6. Scrape comments (only when the comment count has changed)

Notifications (Windows toast and Telegram) are sent at the end of the cycle
summarising any *new* faves or comments discovered.
"""

from __future__ import annotations
import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from html import escape as _esc

import config
from clients.ib.client import InkbunnyClient
from database.db import get_connection
from database import queries
from polling import notifications

logger = logging.getLogger(__name__)

# ── Progress tracking ────────────────────────────────────────
# Mutable dict that acts as shared state between the poller and the
# FastAPI /api/poll/progress endpoint.  The web handler simply reads this
# dict to report real-time progress to the frontend without needing a
# queue or event bus.  Keys:
#   active  -- True while a poll is in flight
#   phase   -- human-readable phase name (e.g. "searching", "processing")
#   current -- numerator for progress bars (e.g. submission 3 of 10)
#   total   -- denominator for progress bars
#   message -- free-text status line shown in the UI
poll_progress = {
    "active": False,
    "phase": "idle",
    "current": 0,
    "total": 0,
    "message": "",
}

# Simple boolean guard that prevents a second poll cycle from starting
# while one is already in progress.  Checked at the top of run_poll_cycle()
# and unconditionally cleared in its `finally` block.  The boolean remains
# as a readable status indicator; the Lock protects the check-and-set from
# race conditions when two callers arrive near-simultaneously.
_poll_running = False
_poll_lock = threading.Lock()

# First-poll suppression: the very first poll after app startup is treated as
# a silent baseline — data is collected and stored but no notifications are
# sent.  This prevents a flood of "new" alerts for items that already existed
# before the restart.  Set to True initially; cleared after the first cycle.
_first_poll = True


def _update_progress(phase: str, current: int = 0, total: int = 0, message: str = ""):
    """Mutate the shared poll_progress dict so the /api/poll/progress endpoint
    can relay the current state to the frontend.  The ``active`` flag is
    derived automatically: any phase other than idle / complete / error
    means the poll is still running."""
    poll_progress["active"] = phase not in ("idle", "complete", "error")
    poll_progress["phase"] = phase
    poll_progress["current"] = current
    poll_progress["total"] = total
    poll_progress["message"] = message


def _send_notifications(new_fave_details: list[dict], new_comment_details: list[dict],
                        new_watcher_details: list[dict] | None = None) -> None:
    """Send Windows toast notifications for new faves/comments/watchers.

    Three separate toasts so the user can distinguish at a glance.
    Filters applied per-section:

      - ``notification_comments_only``: drops the fave toast entirely
        (lets users with high fave volume mute that channel while still
        getting comment alerts).
      - ``notification_min_faves_delta``: drops the fave toast when the
        new-fave count is below the threshold.
      - ``watcher_notifications_enabled``: gates the watcher toast.
    """
    if new_watcher_details is None:
        new_watcher_details = []

    settings = config.get_settings()
    if settings.get("notification_comments_only", False):
        new_fave_details = []
    min_faves = settings.get("notification_min_faves_delta", 0)
    if min_faves > 0 and len(new_fave_details) < min_faves:
        new_fave_details = []

    notifications.maybe_show_toast(
        settings,
        "notifications_enabled",
        f"{len(new_fave_details)} New Fave"
        f"{'s' if len(new_fave_details) != 1 else ''}",
        [f"{d['username']} faved {d['title']}" for d in new_fave_details],
    )
    notifications.maybe_show_toast(
        settings,
        "notifications_enabled",
        f"{len(new_comment_details)} New Comment"
        f"{'s' if len(new_comment_details) != 1 else ''}",
        [f"{d['username']} commented on {d['title']}"
         for d in new_comment_details],
    )
    if settings.get("watcher_notifications_enabled", True):
        notifications.maybe_show_toast(
            settings,
            "notifications_enabled",
            f"{len(new_watcher_details)} New Watcher"
            f"{'s' if len(new_watcher_details) != 1 else ''}",
            [f"{d['username']} started watching you"
             for d in new_watcher_details],
        )


async def _send_telegram(new_fave_details: list[dict], new_comment_details: list[dict],
                         new_watcher_details: list[dict] | None = None) -> None:
    """Send a single Telegram message summarising the cycle's activity.

    Faves, comments, watchers go in three sections separated by blank
    lines so the chat doesn't get three pings for one cycle. Filters
    mirror the toast path for parity (comments-only, min-faves-delta).
    """
    if new_watcher_details is None:
        new_watcher_details = []

    settings = config.get_settings()
    if not settings.get("telegram_enabled", False):
        return
    token = settings.get("telegram_bot_token")
    chat_id = settings.get("telegram_chat_id")
    if not token or not chat_id:
        return

    if settings.get("notification_comments_only", False):
        new_fave_details = []
    min_faves = settings.get("notification_min_faves_delta", 0)
    if min_faves > 0 and len(new_fave_details) < min_faves:
        new_fave_details = []

    sections: list[str] = []
    if new_fave_details:
        sections.append(notifications.format_telegram_summary(
            f"<b>❤️ {len(new_fave_details)} New Fave"
            f"{'s' if len(new_fave_details) != 1 else ''}</b>",
            [f"<b>{_esc(d['username'])}</b> faved {_esc(d['title'])}"
             for d in new_fave_details],
        ))
    if new_comment_details:
        sections.append(notifications.format_telegram_summary(
            f"<b>💬 {len(new_comment_details)} New Comment"
            f"{'s' if len(new_comment_details) != 1 else ''}</b>",
            [f"<b>{_esc(d['username'])}</b> commented on {_esc(d['title'])}"
             for d in new_comment_details],
        ))
    if new_watcher_details:
        sections.append(notifications.format_telegram_summary(
            f"<b>👀 {len(new_watcher_details)} New Watcher"
            f"{'s' if len(new_watcher_details) != 1 else ''}</b>",
            [f"<b>{_esc(d['username'])}</b> started watching"
             for d in new_watcher_details],
        ))
    if not sections:
        return
    await notifications.send_telegram(
        token, chat_id, "\n\n".join(sections), log_label="IB",
    )


async def run_poll_cycle(force_full: bool = False) -> dict:
    """Execute one complete Inkbunny poll cycle.

    The cycle has six logical steps:
      1. **Auth**        -- restore a cached SID or log in for a new one.
      2. **Search**      -- query the IB API for all of the user's submissions.
      3. **Details**     -- batch-fetch full metadata for every submission.
      4. **Upsert+Snap** -- write/update each submission row and record a
                            point-in-time stats snapshot (views, faves, comments).
      5. **Faves**       -- fetch the list of users who faved each submission.
      6. **Comments**    -- scrape comments for each submission.

    Steps 5 and 6 are *conditional* -- they only fire when the respective
    count has changed since the last poll (or on a force_full run).  This
    avoids unnecessary API calls and respects Inkbunny's rate limits.

    Args:
        force_full: When True, re-fetch faving users and comments for
            *every* submission regardless of whether their counts changed.
            Useful for back-filling data after a schema migration or when
            the DB has been reset.

    Returns:
        A stats dict with keys: submissions_found, snapshots_inserted,
        new_faves_found, new_comments_found.  Returns an empty dict if
        a poll was already running and this call was skipped.
    """
    global _poll_running, _first_poll

    # ── Concurrency guard ──────────────────────────────────────
    # Only one poll cycle may run at a time.  If a second call arrives
    # (e.g. the user clicks "Poll Now" while an auto-poll is running)
    # we return immediately with an empty dict rather than queuing.
    # The Lock makes the check-and-set atomic so two near-simultaneous
    # callers cannot both slip through.
    if not _poll_lock.acquire(blocking=False):
        logger.warning("Poll already running — skipping")
        return {}
    _poll_running = True
    _update_progress("starting", message="Initialising poll cycle...")

    conn = None
    log_id = None
    start_time = time.time()

    stats = {
        "submissions_found": 0,
        "snapshots_inserted": 0,
        "new_faves_found": 0,
        "new_comments_found": 0,
        "new_watchers_found": 0,
    }

    # Read credentials at poll time (not from frozen module-level constants)
    # so that env-seeded settings.json values are picked up.
    settings = config.get_settings()
    ib_user = settings.get("username", "") or config.INKBUNNY_USERNAME
    ib_pass = settings.get("password", "") or config.INKBUNNY_PASSWORD
    client = InkbunnyClient(username=ib_user, password=ib_pass)

    try:
        conn = get_connection()
        log_id = queries.start_poll_log(conn)
        # ── Step 1: Authenticate ───────────────────────────────
        # Try to reuse a cached session ID (SID) to avoid logging in on
        # every cycle.  If the cached SID has expired the client will
        # automatically fall back to a fresh login.
        _update_progress("logging_in", message="Authenticating with Inkbunny...")
        cached = queries.get_cached_session(conn)
        cached_sid = cached["sid"] if cached else None
        cached_uid = cached.get("user_id", 0) if cached else 0
        if cached_uid:
            client.user_id = cached_uid
        sid = await client.ensure_session(cached_sid)
        queries.save_session(conn, sid, client.username, client.user_id)

        # ── Step 2: Search for all user submissions ────────────
        _update_progress("searching", message="Searching for submissions...")
        search_results = await client.search_user_submissions()
        submission_ids = [s["submission_id"] for s in search_results]
        stats["submissions_found"] = len(submission_ids)
        logger.info("Found %d submissions", len(submission_ids))

        if not submission_ids:
            _update_progress("complete", message="No submissions found.")
            queries.finish_poll_log(conn, log_id, "success", duration_seconds=time.time() - start_time, **stats)
            conn.commit()
            return stats

        # ── Step 3: Fetch full details in batches ──────────────
        # The IB API accepts multiple submission IDs per request, so the
        # client batches them internally to minimise round-trips.
        _update_progress("fetching_details", message=f"Fetching details for {len(submission_ids)} submissions...")
        details = await client.get_submission_details(submission_ids)
        logger.info("Fetched details for %d submissions", len(details))

        # ── Step 4-6: Process each submission ──────────────────
        # Accumulate notification details for the end-of-cycle alerts.
        new_fave_details = []
        new_comment_details = []
        new_watcher_details = []
        poll_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        for idx, detail in enumerate(details, 1):
            _update_progress("processing", current=idx, total=len(details),
                             message=f"Processing submission {idx}/{len(details)}...")

            # Each submission is wrapped in its own try/except so that a
            # single malformed response does not abort the entire cycle.
            # Errors are logged as warnings; the loop continues with the
            # next submission.
            try:
                db_dict = detail.to_db_dict()
                sub_id = db_dict["submission_id"]
                views = db_dict["views"]
                faves = db_dict["favorites_count"]
                comments = db_dict["comments_count"]

                # Grab the previously stored fave and comment counts *before*
                # the snapshot overwrites them -- we need the old values for
                # the delta checks that gate conditional fetching.
                prev_faves = queries.get_previous_favorites_count(conn, sub_id)
                prev_comments = queries.get_previous_comments_count(conn, sub_id)

                # Step 4: Upsert the submission row and record a snapshot.
                # The snapshot captures a point-in-time record of views,
                # faves, and comments for historical charting.
                queries.upsert_submission(conn, db_dict)
                queries.insert_snapshot(conn, sub_id, views, faves, comments, polled_at=poll_timestamp)
                stats["snapshots_inserted"] += 1

                # ── Step 5: Fetch faving users (conditional) ───
                # Fetching faving users is an extra API call per submission
                # which hits Inkbunny's rate limits quickly.  To avoid
                # unnecessary requests we only fetch when:
                #   a) force_full is True (manual "re-scrape everything"), OR
                #   b) the fave count has *increased* since the last poll, OR
                #   c) this is the first time we've seen this submission
                #      and it already has faves.
                # A small delay (FAVE_REQUEST_DELAY_SECONDS) is inserted
                # before each call to stay within rate limits.
                should_fetch_faves = force_full and faves > 0
                if not should_fetch_faves:
                    if prev_faves is not None and faves > prev_faves:
                        should_fetch_faves = True
                    elif prev_faves is None and faves > 0:
                        should_fetch_faves = True

                if should_fetch_faves:
                    logger.info("Submission %d: fetching faving users (faves=%d, force=%s)", sub_id, faves, force_full)
                    await asyncio.sleep(config.FAVE_REQUEST_DELAY_SECONDS)
                    faving_users = await client.get_faving_users(sub_id)
                    # Batch insert: get existing user_ids first to identify new ones
                    existing_ids = {r["user_id"] for r in queries.get_faving_users(conn, sub_id)}
                    new_count = queries.upsert_faving_users_batch(conn, sub_id, faving_users)
                    conn.commit()
                    stats["new_faves_found"] += new_count
                    for user in faving_users:
                        if user["user_id"] not in existing_ids:
                            new_fave_details.append({"username": user["username"], "title": db_dict.get("title", "")})

                # ── Step 6: Scrape comments (conditional) ──────
                # Same delta-based logic as faves: only scrape when the
                # comment count has increased or on force_full.  Comments
                # are scraped from the submission page HTML rather than a
                # dedicated API endpoint (Inkbunny doesn't expose one).
                should_fetch_comments = force_full and comments > 0
                if not should_fetch_comments:
                    if (prev_comments is not None and comments > prev_comments) or \
                       (prev_comments is None and comments > 0):
                        should_fetch_comments = True

                if should_fetch_comments:
                    logger.info("Submission %d: scraping comments (count=%d, force=%s)", sub_id, comments, force_full)
                    await asyncio.sleep(config.COMMENT_REQUEST_DELAY_SECONDS)
                    try:
                        scraped = await client.scrape_comments(sub_id)
                        for c in scraped:
                            is_new = queries.upsert_comment(conn, c)
                            if is_new:
                                stats["new_comments_found"] += 1
                                new_comment_details.append({"username": c.get("username", ""), "title": db_dict.get("title", "")})
                    except Exception as ce:
                        # Comment scraping failures are non-fatal --
                        # the rest of the submission data is still valid.
                        logger.warning("Failed to scrape comments for %d: %s", sub_id, ce, exc_info=True)

            except Exception as e:
                # Per-submission error handling: log and continue so one
                # bad submission doesn't prevent the rest from being polled.
                logger.warning("Error processing submission %s: %s", detail.submission_id, e, exc_info=True)

        # Commit all upserts and snapshots in a single transaction.
        conn.commit()

        # ── Step 7: Scrape watchers ──────────────────────────
        # Fetch the full watcher list and upsert each one.  New watchers
        # (not previously recorded) are counted for stats and notifications.
        try:
            _update_progress("fetching_watchers", message="Scraping watcher list...")
            watchers = await client.scrape_watchers()
            for username in watchers:
                is_new = queries.upsert_watcher(conn, username)
                if is_new:
                    stats["new_watchers_found"] += 1
                    new_watcher_details.append({"username": username})
            # Remove watchers no longer on the live list (banned/deleted/unwatched)
            if watchers:
                removed = queries.remove_stale_watchers(conn, watchers)
                if removed:
                    logger.info("Pruned %d stale watchers from DB", removed)
            conn.commit()
        except Exception as we:
            logger.warning("Failed to scrape watchers: %s", we, exc_info=True)

        # ── Notifications ──────────────────────────────────────
        # Fire-and-forget: notification failures are logged but never
        # propagate -- the poll data is already safely committed.
        # Skip notifications on the first poll after startup — this is a
        # silent baseline collection to avoid flooding with old items.
        # Note: _first_poll is cleared in the `finally` block so it gets
        # reset even if this poll fails with an exception.
        if _first_poll:
            logger.info("First poll after startup — suppressing %d fave, %d comment, %d watcher notifications",
                        len(new_fave_details), len(new_comment_details), len(new_watcher_details))
        else:
            try:
                _send_notifications(new_fave_details, new_comment_details, new_watcher_details)
            except Exception as ne:
                logger.warning("Failed to send notifications: %s", ne, exc_info=True)

            try:
                await _send_telegram(new_fave_details, new_comment_details, new_watcher_details)
            except Exception as te:
                logger.warning("Failed to send Telegram notification: %s", te, exc_info=True)

        # ── Finalise ───────────────────────────────────────────
        duration = time.time() - start_time
        _update_progress("complete", current=len(details), total=len(details),
                         message=f"Done — {stats['submissions_found']} submissions in {duration:.1f}s")
        queries.finish_poll_log(conn, log_id, "success", duration_seconds=duration, **stats)
        logger.info("Poll complete in %.1fs — %d submissions, %d snapshots, %d new faves, %d new comments, %d new watchers",
                     duration, stats["submissions_found"], stats["snapshots_inserted"],
                     stats["new_faves_found"], stats["new_comments_found"], stats["new_watchers_found"])

        # ── Telegram summaries + milestones ───────────────────
        from polling.telegram import send_poll_summary, check_milestones_batch, check_goals
        if not _first_poll:
            try:
                await send_poll_summary("ib", stats, duration)
            except Exception as te:
                logger.warning("Failed to send IB Telegram summary: %s", te, exc_info=True)
            try:
                await check_milestones_batch("ib", "snapshots", "submissions")
            except Exception as me:
                logger.warning("Failed to check IB milestones: %s", me, exc_info=True)
            try:
                await check_goals()
            except Exception as ge:
                logger.warning("Failed to check goals: %s", ge, exc_info=True)

        return stats

    except Exception as e:
        # Top-level failure (auth error, network outage, etc.) -- record
        # partial stats and re-raise so the scheduler knows the cycle failed.
        duration = time.time() - start_time
        _update_progress("error", message=str(e))
        logger.error("Poll failed: %s", e, exc_info=True)
        if conn and log_id:
            queries.finish_poll_log(conn, log_id, "error", error_message=str(e), duration_seconds=duration, **stats)
            conn.commit()
        # Send error alert via Telegram
        from polling.telegram import send_poll_error
        try:
            await send_poll_error("ib", e)
        except Exception:
            logger.debug("Error alert send failed", exc_info=True)
        raise
    finally:
        # Always release the concurrency guard, close the HTTP client, and
        # return the DB connection -- even if the cycle raised an exception.
        # Also clear _first_poll so that a failed first attempt doesn't
        # suppress notifications on the next successful poll.
        if _first_poll:
            _first_poll = False
        _poll_running = False
        _poll_lock.release()
        await client.close()
        if conn:
            conn.close()
