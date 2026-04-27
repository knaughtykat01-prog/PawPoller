"""X/Twitter (TW) poll cycle orchestration.

Uses internal GraphQL endpoints with cookie-based auth, the same
approach as the DeviantArt integration.

Key differences from other pollers:
  - Uses TWClient with auth_token, ct0, and target_user
  - Settings keys: tw_auth_token, tw_ct0, tw_target_user
  - Stats: views, likes, retweets, replies, quotes, bookmarks (6 metrics)
  - Notifications: "TW:" prefix, bird emoji
  - Higher rate limit delay (2.0s) due to X's aggressive rate limiting
"""

from __future__ import annotations
import atexit
import logging
import threading
import time
from datetime import datetime, timezone
from html import escape as _esc

import httpx

import config
from clients.tw.client import TWClient
from database.db import get_connection
from database import tw_queries

logger = logging.getLogger(__name__)

# -- Progress tracking --------------------------------------------------------
tw_poll_progress = {
    "active": False,
    "phase": "idle",
    "current": 0,
    "total": 0,
    "message": "",
}

_tw_poll_running = False
_tw_poll_lock = threading.Lock()
_tw_first_poll = True

# Persistent client — reused across poll cycles
_tw_client: TWClient | None = None


def _cleanup_tw_client():
    if _tw_client is not None:
        import asyncio
        try:
            asyncio.get_event_loop().run_until_complete(_tw_client.close())
        except Exception:
            logger.debug("Error alert send failed", exc_info=True)


atexit.register(_cleanup_tw_client)


def _update_tw_progress(phase: str, current: int = 0, total: int = 0, message: str = ""):
    tw_poll_progress["active"] = phase not in ("idle", "complete", "error")
    tw_poll_progress["phase"] = phase
    tw_poll_progress["current"] = current
    tw_poll_progress["total"] = total
    tw_poll_progress["message"] = message


def _send_tw_notifications(new_details: list[dict]) -> None:
    """Send Windows toast notifications for X/Twitter activity."""
    settings = config.get_settings()
    if not settings.get("tw_notifications_enabled", True):
        return
    if not new_details:
        return

    try:
        from winotify import Notification
    except ImportError:
        logger.debug("winotify not installed -- skipping TW notifications")
        return

    shown = new_details[:3]
    lines = [f"{d['title'][:50]} gained activity" for d in shown]
    if len(new_details) > 3:
        lines.append(f"...and {len(new_details) - 3} more")
    toast = Notification(
        app_id="PawPoller",
        title=f"TW: {len(new_details)} Tweet{'s' if len(new_details) != 1 else ''} Updated",
        msg="\n".join(lines),
    )
    toast.show()


async def _send_tw_telegram(new_details: list[dict]) -> None:
    """Send Telegram notification for X/Twitter activity."""
    settings = config.get_settings()
    if not settings.get("telegram_enabled", False):
        return
    token = settings.get("telegram_bot_token")
    chat_id = settings.get("telegram_chat_id")
    if not token or not chat_id:
        return
    if not new_details:
        return

    lines = [f"<b>\U0001f426 TW: {len(new_details)} Tweet{'s' if len(new_details) != 1 else ''} Updated</b>"]
    for d in new_details[:5]:
        lines.append(f"  \u2022 {_esc(d['title'][:50])}")
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
        logger.warning("Failed to send TW Telegram notification: %s", e, exc_info=True)


def _get_or_create_client(settings: dict) -> TWClient:
    """Return the persistent TWClient, creating or updating as needed."""
    global _tw_client
    tw_auth_token = settings.get("tw_auth_token", "")
    tw_ct0 = settings.get("tw_ct0", "")
    tw_target = settings.get("tw_target_user", "")

    if _tw_client is None:
        _tw_client = TWClient(
            auth_token=tw_auth_token,
            ct0=tw_ct0,
            target_user=tw_target,
        )
    else:
        _tw_client.update_credentials(tw_auth_token, tw_ct0, tw_target)

    return _tw_client


async def run_tw_poll_cycle(force_full: bool = False) -> dict:
    """Execute one complete X/Twitter poll cycle.

    Steps:
      1. Validate cookies by resolving target user
      2. Discover all tweets for the target user
      3. Fetch details for each tweet
      4. Upsert tweets and record snapshots
    """
    global _tw_poll_running, _tw_first_poll

    if not _tw_poll_lock.acquire(blocking=False):
        logger.warning("TW poll already running -- skipping")
        return {}
    _tw_poll_running = True
    _update_tw_progress("starting", message="Initialising TW poll cycle...")

    conn = None
    log_id = None
    start_time = time.time()

    stats = {
        "submissions_found": 0,
        "snapshots_inserted": 0,
    }

    settings = config.get_settings()
    client = _get_or_create_client(settings)

    try:
        conn = get_connection()
        log_id = tw_queries.start_tw_poll_log(conn)

        # Step 1: Validate cookies
        _update_tw_progress("searching", message="Validating X/Twitter cookies...")
        if not client.auth_token or not client.ct0:
            raise ValueError("X/Twitter credentials missing — set auth_token and ct0 in Settings")
        valid = await client.validate_cookies()
        if not valid:
            raise ValueError("X/Twitter cookie validation failed -- update auth_token and ct0 in Settings")

        # Step 2: Discover tweets
        _update_tw_progress("searching", message="Fetching tweet list...")
        tweet_items = await client.get_all_tweet_ids()
        stats["submissions_found"] = len(tweet_items)
        logger.info("TW: Found %d tweets", len(tweet_items))

        if not tweet_items:
            _update_tw_progress("complete", message="No tweets found.")
            tw_queries.finish_tw_poll_log(conn, log_id, "success",
                                          duration_seconds=time.time() - start_time, **stats)
            conn.commit()
            return stats

        # Step 3: Fetch details
        _update_tw_progress("fetching_details",
                            message=f"Fetching details for {len(tweet_items)} tweets...")
        details = await client.get_tweet_details_batch(tweet_items)
        logger.info("TW: Fetched details for %d tweets", len(details))

        # Step 4: Upsert + snapshot
        new_activity_details: list[dict] = []
        poll_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        for idx, detail in enumerate(details, 1):
            _update_tw_progress("processing", current=idx, total=len(details),
                                message=f"Processing tweet {idx}/{len(details)}...")
            try:
                tweet_id = detail["tweet_id"]
                views = detail.get("views", 0)
                likes = detail.get("likes", 0)
                retweets = detail.get("retweets", 0)
                replies_count = detail.get("replies", 0)
                quotes = detail.get("quotes", 0)
                bookmarks = detail.get("bookmarks", 0)

                # Check for stat increases to drive notifications
                prev = tw_queries.get_tw_submission(conn, tweet_id)
                if prev and (likes > prev.get("likes", 0)
                             or retweets > prev.get("retweets", 0)):
                    new_activity_details.append({"title": detail.get("title", "")})

                tw_queries.upsert_tw_submission(conn, detail)
                tw_queries.insert_tw_snapshot(conn, tweet_id, views, likes,
                                              retweets, replies_count, quotes,
                                              bookmarks, polled_at=poll_timestamp)
                stats["snapshots_inserted"] += 1

            except Exception as e:
                logger.warning("Error processing TW tweet %s: %s",
                               detail.get("tweet_id"), e, exc_info=True)

        conn.commit()

        # ── Notifications ─────────────────────────────────────
        if _tw_first_poll:
            logger.info("First TW poll after startup -- suppressing %d activity notifications",
                        len(new_activity_details))
        else:
            try:
                _send_tw_notifications(new_activity_details)
            except Exception as ne:
                logger.warning("Failed to send TW notifications: %s", ne, exc_info=True)
            try:
                await _send_tw_telegram(new_activity_details)
            except Exception as te:
                logger.warning("Failed to send TW Telegram notification: %s", te, exc_info=True)

        # Finalise
        duration = time.time() - start_time
        _update_tw_progress("complete", current=len(details), total=len(details),
                            message=f"Done -- {stats['submissions_found']} tweets in {duration:.1f}s")
        tw_queries.finish_tw_poll_log(conn, log_id, "success",
                                      duration_seconds=duration, **stats)
        logger.info("TW poll complete in %.1fs -- %d tweets, %d snapshots",
                     duration, stats["submissions_found"], stats["snapshots_inserted"])

        # -- Telegram notifications ----------------------------------------
        if not _tw_first_poll:
            from polling.telegram import send_poll_summary, check_milestones_batch, check_goals
            try:
                await send_poll_summary("tw", stats, duration)
            except Exception as te:
                logger.warning("Failed to send TW Telegram summary: %s", te, exc_info=True)
            try:
                await check_milestones_batch("tw", "tw_snapshots", "tw_submissions")
            except Exception as me:
                logger.warning("Failed to check TW milestones: %s", me, exc_info=True)
            try:
                await check_goals()
            except Exception as ge:
                logger.warning("Failed to check goals: %s", ge, exc_info=True)

        return stats

    except Exception as e:
        duration = time.time() - start_time
        _update_tw_progress("error", message=str(e))
        logger.error("TW poll failed: %s", e, exc_info=True)
        if conn and log_id:
            tw_queries.finish_tw_poll_log(conn, log_id, "error",
                                          error_message=str(e),
                                          duration_seconds=duration, **stats)
            conn.commit()
        from polling.telegram import send_poll_error
        try:
            await send_poll_error("tw", e)
        except Exception:
            logger.debug("Error alert send failed", exc_info=True)
        raise
    finally:
        if _tw_first_poll:
            _tw_first_poll = False
        _tw_poll_running = False
        _tw_poll_lock.release()
        if conn:
            conn.close()
