"""Weasyl (WS) poll cycle orchestration.

This is the simplest of the three platform pollers.  Weasyl's public API
provides submission metadata (views, faves, comments counts) but does
**not** expose:

  - **Faving user lists** -- there is no endpoint to discover *who* faved
    a submission, so there is no fave-user tracking step at all.
  - **Comment content or authors** -- the API returns a comment *count*
    but not the individual comments, so there is no comment-scraping step.

As a result the poll cycle is just three steps:
  1. Validate the API key and resolve the username.
  2. Discover all gallery submissions.
  3. Fetch details and record snapshots (views / faves / comments counts).

Notifications are basic "submission updated" alerts rather than the
per-user fave/comment breakdowns that IB and FA provide.
"""

from __future__ import annotations
import logging
import threading
import time
from datetime import datetime, timezone
from html import escape as _esc

import httpx

import config
from weasyl_client.client import WeasylClient
from database.db import get_connection
from database import ws_queries

logger = logging.getLogger(__name__)

# ── Progress tracking ────────────────────────────────────────
# Same shared-dict pattern as the IB and FA pollers, read by the
# /api/ws/poll/progress endpoint.
ws_poll_progress = {
    "active": False,
    "phase": "idle",
    "current": 0,
    "total": 0,
    "message": "",
}

# Concurrency guard -- identical pattern to the other pollers.
# The Lock protects the check-and-set from race conditions; the
# boolean remains as a readable status indicator.
_ws_poll_running = False
_ws_poll_lock = threading.Lock()
_ws_first_poll = True


def _update_ws_progress(phase: str, current: int = 0, total: int = 0, message: str = ""):
    """Mutate the shared ws_poll_progress dict for the frontend.
    Same pattern as _update_progress() in the IB poller."""
    ws_poll_progress["active"] = phase not in ("idle", "complete", "error")
    ws_poll_progress["phase"] = phase
    ws_poll_progress["current"] = current
    ws_poll_progress["total"] = total
    ws_poll_progress["message"] = message


def _send_ws_notifications(new_details: list[dict], detail_type: str = "activity") -> None:
    """Send Windows toast notifications for Weasyl activity.

    Because Weasyl's API does not expose *who* faved or commented, these
    notifications are generic "submission gained activity" alerts rather
    than the per-user breakdowns that IB and FA provide.  Still truncated
    to 3 items and prefixed with "WS:" for platform distinction.

    When ``ws_notification_comments_only`` is True, these activity
    notifications (which are triggered by fave-count increases) are
    suppressed entirely.
    """
    settings = config.get_settings()
    if not settings.get("ws_notifications_enabled", True):
        return
    # WS activity notifications fire on fave-count increases, so
    # comments_only suppresses them (WS has no separate comment alerts).
    if settings.get("ws_notification_comments_only", False):
        return
    if not new_details:
        return

    try:
        from winotify import Notification
    except ImportError:
        logger.debug("winotify not installed — skipping WS notifications")
        return

    shown = new_details[:3]
    lines = [f"{d['title']} gained activity" for d in shown]
    if len(new_details) > 3:
        lines.append(f"...and {len(new_details) - 3} more")
    toast = Notification(
        app_id="PawPoller",
        title=f"WS: {len(new_details)} Submission{'s' if len(new_details) != 1 else ''} Updated",
        msg="\n".join(lines),
    )
    toast.show()


async def _send_ws_telegram(new_details: list[dict]) -> None:
    """Send Telegram notification for Weasyl activity.

    Simpler than the IB/FA Telegram messages: just lists submission titles
    without usernames (since WS API doesn't tell us *who* interacted).
    Uses a lizard emoji header to distinguish from IB/FA alerts.
    Truncated to 5 items like the other pollers.

    Same ``ws_notification_comments_only`` filter as the toast path --
    suppress fave-triggered activity alerts when the user only wants
    comment notifications.
    """
    settings = config.get_settings()
    if not settings.get("telegram_enabled", False):
        return
    token = settings.get("telegram_bot_token")
    chat_id = settings.get("telegram_chat_id")
    if not token or not chat_id:
        return
    # WS activity notifications fire on fave-count increases, so
    # comments_only suppresses them (WS has no separate comment alerts).
    if settings.get("ws_notification_comments_only", False):
        return
    if not new_details:
        return

    # Title-only bullets since we don't have per-user interaction data.
    lines = [f"<b>🦎 WS: {len(new_details)} Submission{'s' if len(new_details) != 1 else ''} Updated</b>"]
    for d in new_details[:5]:
        lines.append(f"  • {_esc(d['title'])}")
    if len(new_details) > 5:
        lines.append(f"  ...and {len(new_details) - 5} more")

    text = "\n".join(lines)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
    except Exception as e:
        logger.warning("Failed to send WS Telegram notification: %s", e, exc_info=True)


async def run_ws_poll_cycle(force_full: bool = False) -> dict:
    """Execute one complete Weasyl poll cycle.

    This is the most streamlined of the three pollers because Weasyl's API
    does not provide user-level fave or comment data.  The cycle is:

      1. **Validate API key** -- call the whoami endpoint to confirm the
         key is valid and resolve the username.  This is a prerequisite
         before any gallery fetch; an invalid key raises immediately.
      2. **Gallery discovery** -- paginate through the user's gallery to
         collect all submission IDs.
      3. **Detail fetch**      -- batch-fetch metadata for each submission.
      4. **Upsert + snapshot** -- write/update submission rows and record
                                  point-in-time stats (views, faves, comments).

    There are **no fave-user or comment steps** -- the stats dict only has
    ``submissions_found`` and ``snapshots_inserted``.

    The ``force_full`` parameter is accepted for interface consistency with
    the IB and FA pollers but has no special effect here since there are no
    conditional fetch steps to force.

    Args:
        force_full: Accepted for API consistency but currently unused.

    Returns:
        Stats dict with keys: submissions_found, snapshots_inserted.
        Empty dict if a poll was already running.
    """
    global _ws_poll_running, _ws_first_poll

    # Concurrency guard -- same pattern as the other pollers.
    # The Lock makes the check-and-set atomic so two near-simultaneous
    # callers cannot both slip through.
    if not _ws_poll_lock.acquire(blocking=False):
        logger.warning("WS poll already running — skipping")
        return {}
    _ws_poll_running = True
    _update_ws_progress("starting", message="Initialising Weasyl poll cycle...")

    conn = None
    log_id = None
    start_time = time.time()

    # Minimal stats dict -- no fave or comment tracking for Weasyl.
    stats = {
        "submissions_found": 0,
        "snapshots_inserted": 0,
    }

    settings = config.get_settings()
    client = WeasylClient(api_key=settings.get("ws_api_key", ""))

    try:
        conn = get_connection()
        log_id = ws_queries.start_ws_poll_log(conn)
        # ── Step 1: Validate API key ───────────────────────────
        # The Weasyl API requires a valid API key for all requests.
        # We call validate_key() first to fail fast with a clear error
        # rather than getting cryptic 401s during the gallery fetch.
        _update_ws_progress("searching", message="Validating API key and fetching gallery...")
        username = await client.validate_key()
        if not username:
            raise ValueError("Weasyl API key is invalid or not set")

        # ── Step 2: Discover gallery submissions ───────────────
        gallery = await client.get_all_gallery_ids()
        submission_ids = [s["submission_id"] for s in gallery]
        stats["submissions_found"] = len(submission_ids)
        logger.info("WS: Found %d submissions", len(submission_ids))

        if not submission_ids:
            _update_ws_progress("complete", message="No Weasyl submissions found.")
            ws_queries.finish_ws_poll_log(conn, log_id, "success", duration_seconds=time.time() - start_time, **stats)
            conn.commit()
            return stats

        # ── Step 3: Fetch details for each submission ──────────
        _update_ws_progress("fetching_details", message=f"Fetching details for {len(submission_ids)} submissions...")
        details = await client.get_submission_details_batch(submission_ids)
        logger.info("WS: Fetched details for %d submissions", len(details))

        # ── Step 4: Upsert submissions and insert snapshots ────
        # This is the final step -- no conditional fave/comment fetching.
        # We just record the aggregate counts for historical charting.
        new_activity_details: list[dict] = []
        poll_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        for idx, detail in enumerate(details, 1):
            _update_ws_progress("processing", current=idx, total=len(details),
                                message=f"Processing submission {idx}/{len(details)}...")
            try:
                sub_id = detail["submission_id"]
                views = detail.get("views", 0)
                faves = detail.get("favorites_count", 0)
                comments = detail.get("comments_count", 0)

                # Check for stat increases to drive notifications.
                prev_faves = ws_queries.get_ws_previous_favorites_count(conn, sub_id)
                if prev_faves is not None and faves > prev_faves:
                    new_activity_details.append({"title": detail.get("title", "")})

                ws_queries.upsert_ws_submission(conn, detail)
                ws_queries.insert_ws_snapshot(conn, sub_id, views, faves, comments, polled_at=poll_timestamp)
                stats["snapshots_inserted"] += 1

            except Exception as e:
                # Per-submission error handling -- same resilience pattern
                # as IB/FA: log and continue with the next submission.
                logger.warning("Error processing WS submission %s: %s", detail.get("submission_id"), e, exc_info=True)

        conn.commit()

        # ── Notifications ─────────────────────────────────────
        if _ws_first_poll:
            logger.info("First WS poll after startup — suppressing %d activity notifications",
                        len(new_activity_details))
        else:
            try:
                _send_ws_notifications(new_activity_details)
            except Exception as ne:
                logger.warning("Failed to send WS notifications: %s", ne, exc_info=True)
            try:
                await _send_ws_telegram(new_activity_details)
            except Exception as te:
                logger.warning("Failed to send WS Telegram notification: %s", te, exc_info=True)

        # ── Finalise ───────────────────────────────────────────
        duration = time.time() - start_time
        _update_ws_progress("complete", current=len(details), total=len(details),
                            message=f"Done — {stats['submissions_found']} submissions in {duration:.1f}s")
        ws_queries.finish_ws_poll_log(conn, log_id, "success", duration_seconds=duration, **stats)
        logger.info("WS poll complete in %.1fs — %d submissions, %d snapshots",
                     duration, stats["submissions_found"], stats["snapshots_inserted"])

        # ── Telegram notifications ────────────────────────────
        if not _ws_first_poll:
            from polling.telegram import send_poll_summary, check_milestones_batch, check_goals
            try:
                await send_poll_summary("ws", stats, duration)
            except Exception as te:
                logger.warning("Failed to send WS Telegram summary: %s", te, exc_info=True)
            try:
                await check_milestones_batch("ws", "ws_snapshots", "ws_submissions")
            except Exception as me:
                logger.warning("Failed to check WS milestones: %s", me, exc_info=True)
            try:
                await check_goals()
            except Exception as ge:
                logger.warning("Failed to check goals: %s", ge, exc_info=True)

        return stats

    except Exception as e:
        # Top-level failure -- record partial stats and propagate.
        duration = time.time() - start_time
        _update_ws_progress("error", message=str(e))
        logger.error("WS poll failed: %s", e, exc_info=True)
        if conn and log_id:
            ws_queries.finish_ws_poll_log(conn, log_id, "error", error_message=str(e), duration_seconds=duration, **stats)
            conn.commit()
        # Send error alert via Telegram
        from polling.telegram import send_poll_error
        try:
            await send_poll_error("ws", e)
        except Exception:
            logger.debug("Error alert send failed", exc_info=True)
        raise
    finally:
        # Always clear the guard and release resources.
        if _ws_first_poll:
            _ws_first_poll = False
        _ws_poll_running = False
        _ws_poll_lock.release()
        await client.close()
        if conn:
            conn.close()
