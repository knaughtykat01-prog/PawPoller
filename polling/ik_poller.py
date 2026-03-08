"""Itaku (IK) poll cycle orchestration.

Simpler than other pollers since Itaku's public API requires no
authentication — only a target username is needed. Content is discovered
via the user profile endpoint and stats (likes, comments, reshares)
are fetched per-item.

Key differences from other platform pollers:
  - No login/authentication step
  - Only needs ik_target_user setting
  - No kudos/fave/comment individual user tracking — just counts
  - Unique metric: reshares (num_reshares)
  - NO views metric available on Itaku
  - Content types: images and posts
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
from ik_client.client import IKClient
from database.db import get_connection
from database import ik_queries

logger = logging.getLogger(__name__)

# -- Progress tracking -----------------------------------------------------
ik_poll_progress = {
    "active": False,
    "phase": "idle",
    "current": 0,
    "total": 0,
    "message": "",
}

_ik_poll_running = False
_ik_poll_lock = threading.Lock()
_ik_first_poll = True

# Persistent client — reused across poll cycles
_ik_client: IKClient | None = None


def _cleanup_ik_client():
    if _ik_client is not None:
        import asyncio
        try:
            asyncio.get_event_loop().run_until_complete(_ik_client.close())
        except Exception:
            pass


atexit.register(_cleanup_ik_client)


def _update_ik_progress(phase: str, current: int = 0, total: int = 0, message: str = ""):
    ik_poll_progress["active"] = phase not in ("idle", "complete", "error")
    ik_poll_progress["phase"] = phase
    ik_poll_progress["current"] = current
    ik_poll_progress["total"] = total
    ik_poll_progress["message"] = message


def _send_ik_notifications(new_details: list[dict]) -> None:
    """Send Windows toast notifications for Itaku activity."""
    settings = config.get_settings()
    if not settings.get("ik_notifications_enabled", True):
        return
    if not new_details:
        return

    try:
        from winotify import Notification
    except ImportError:
        logger.debug("winotify not installed -- skipping IK notifications")
        return

    shown = new_details[:3]
    lines = [f"{d['title']} gained activity" for d in shown]
    if len(new_details) > 3:
        lines.append(f"...and {len(new_details) - 3} more")
    toast = Notification(
        app_id="PawPoller",
        title=f"IK: {len(new_details)} Item{'s' if len(new_details) != 1 else ''} Updated",
        msg="\n".join(lines),
    )
    toast.show()


async def _send_ik_telegram(new_details: list[dict]) -> None:
    """Send Telegram notification for Itaku activity."""
    settings = config.get_settings()
    if not settings.get("telegram_enabled", False):
        return
    token = settings.get("telegram_bot_token")
    chat_id = settings.get("telegram_chat_id")
    if not token or not chat_id:
        return
    if not new_details:
        return

    lines = [f"<b>\U0001f3af IK: {len(new_details)} Item{'s' if len(new_details) != 1 else ''} Updated</b>"]
    for d in new_details[:5]:
        lines.append(f"  \u2022 {_esc(d['title'])}")
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
        logger.warning("Failed to send IK Telegram notification: %s", e)


def _get_or_create_client(settings: dict) -> IKClient:
    """Return the persistent IKClient, creating or updating as needed."""
    global _ik_client
    ik_target = settings.get("ik_target_user", "")

    if _ik_client is None:
        _ik_client = IKClient(target_user=ik_target)
    else:
        _ik_client.update_credentials(ik_target)

    return _ik_client


async def run_ik_poll_cycle(force_full: bool = False) -> dict:
    """Execute one complete Itaku poll cycle.

    Steps:
      1. Validate the target user exists
      2. Discover all content (images + posts) for the target user
      3. Fetch details for each content item
      4. Upsert items and record snapshots
    """
    global _ik_poll_running, _ik_first_poll

    if not _ik_poll_lock.acquire(blocking=False):
        logger.warning("IK poll already running -- skipping")
        return {}
    _ik_poll_running = True
    _update_ik_progress("starting", message="Initialising IK poll cycle...")

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
        log_id = ik_queries.start_ik_poll_log(conn)
        # Step 1: Validate user
        _update_ik_progress("searching", message="Validating Itaku user...")
        target = await client.validate_user()
        if not target:
            raise ValueError("Itaku user not found -- check ik_target_user setting")

        # Step 2: Discover content
        _update_ik_progress("searching", message="Fetching content list...")
        content_items = await client.get_all_content_ids()
        stats["submissions_found"] = len(content_items)
        logger.info("IK: Found %d content items", len(content_items))

        if not content_items:
            _update_ik_progress("complete", message="No Itaku content found.")
            ik_queries.finish_ik_poll_log(conn, log_id, "success",
                                          duration_seconds=time.time() - start_time, **stats)
            conn.commit()
            return stats

        # Step 3: Fetch details
        _update_ik_progress("fetching_details",
                            message=f"Fetching details for {len(content_items)} items...")
        details = await client.get_content_details_batch(content_items)
        logger.info("IK: Fetched details for %d items", len(details))

        # Step 4: Upsert + snapshot
        new_activity_details: list[dict] = []
        poll_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        for idx, detail in enumerate(details, 1):
            _update_ik_progress("processing", current=idx, total=len(details),
                                message=f"Processing item {idx}/{len(details)}...")
            try:
                sid = detail["content_id"]
                likes = detail.get("likes", 0)
                comments = detail.get("comments_count", 0)
                reshares = detail.get("reshares", 0)

                # Check for stat increases to drive notifications.
                prev = ik_queries.get_ik_submission(conn, sid)
                if prev and (likes > prev.get("likes", 0)
                             or comments > prev.get("comments_count", 0)):
                    new_activity_details.append({"title": detail.get("title", "")})

                ik_queries.upsert_ik_submission(conn, detail)
                ik_queries.insert_ik_snapshot(conn, sid, likes, comments,
                                              reshares, polled_at=poll_timestamp)
                stats["snapshots_inserted"] += 1

            except Exception as e:
                logger.warning("Error processing IK item %s: %s",
                               detail.get("content_id"), e)

        conn.commit()

        # ── Notifications ─────────────────────────────────────
        if _ik_first_poll:
            logger.info("First IK poll after startup -- suppressing %d activity notifications",
                        len(new_activity_details))
        else:
            try:
                _send_ik_notifications(new_activity_details)
            except Exception as ne:
                logger.warning("Failed to send IK notifications: %s", ne)
            try:
                await _send_ik_telegram(new_activity_details)
            except Exception as te:
                logger.warning("Failed to send IK Telegram notification: %s", te)

        # Finalise
        duration = time.time() - start_time
        _update_ik_progress("complete", current=len(details), total=len(details),
                            message=f"Done -- {stats['submissions_found']} items in {duration:.1f}s")
        ik_queries.finish_ik_poll_log(conn, log_id, "success",
                                      duration_seconds=duration, **stats)
        logger.info("IK poll complete in %.1fs -- %d items, %d snapshots",
                     duration, stats["submissions_found"], stats["snapshots_inserted"])

        # -- Telegram notifications ----------------------------------------
        if not _ik_first_poll:
            from polling.telegram import send_poll_summary, check_milestones_batch, check_goals
            try:
                await send_poll_summary("ik", stats, duration)
            except Exception as te:
                logger.warning("Failed to send IK Telegram summary: %s", te)
            try:
                await check_milestones_batch("ik", "ik_snapshots", "ik_submissions")
            except Exception as me:
                logger.warning("Failed to check IK milestones: %s", me)
            try:
                await check_goals()
            except Exception as ge:
                logger.warning("Failed to check goals: %s", ge)

        return stats

    except Exception as e:
        duration = time.time() - start_time
        _update_ik_progress("error", message=str(e))
        logger.error("IK poll failed: %s", e)
        if conn and log_id:
            ik_queries.finish_ik_poll_log(conn, log_id, "error",
                                          error_message=str(e),
                                          duration_seconds=duration, **stats)
        from polling.telegram import send_poll_error
        try:
            await send_poll_error("ik", e)
        except Exception:
            pass
        raise
    finally:
        if _ik_first_poll:
            _ik_first_poll = False
        _ik_poll_running = False
        _ik_poll_lock.release()
        if conn:
            conn.close()
