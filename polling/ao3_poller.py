"""Archive of Our Own (AO3) poll cycle orchestration.

Mirrors the SquidgeWorld poller since both run on OTW Archive software.
AO3 uses Cloudflare instead of Anubis, with a higher rate limit (3s)
since it's a volunteer-run site.

Key differences from SqW:
  - No Anubis challenge solver
  - Cloudflare 403/429 handling in the client
  - Higher rate limiting (3s between requests)
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
from ao3_client.client import AO3Client
from database.db import get_connection
from database import ao3_queries

logger = logging.getLogger(__name__)

# -- Progress tracking -------------------------------------------------
ao3_poll_progress = {
    "active": False,
    "phase": "idle",
    "current": 0,
    "total": 0,
    "message": "",
}

_ao3_poll_running = False
_ao3_poll_lock = threading.Lock()
_ao3_first_poll = True

# Persistent client — reused across poll cycles
_ao3_client: AO3Client | None = None


def _cleanup_ao3_client():
    if _ao3_client is not None:
        import asyncio
        try:
            asyncio.get_event_loop().run_until_complete(_ao3_client.close())
        except Exception:
            pass


atexit.register(_cleanup_ao3_client)


def _update_ao3_progress(phase: str, current: int = 0, total: int = 0, message: str = ""):
    ao3_poll_progress["active"] = phase not in ("idle", "complete", "error")
    ao3_poll_progress["phase"] = phase
    ao3_poll_progress["current"] = current
    ao3_poll_progress["total"] = total
    ao3_poll_progress["message"] = message


def _send_ao3_notifications(new_details: list[dict]) -> None:
    """Send Windows toast notifications for AO3 activity."""
    settings = config.get_settings()
    if not settings.get("ao3_notifications_enabled", True):
        return
    if not new_details:
        return

    try:
        from winotify import Notification
    except ImportError:
        logger.debug("winotify not installed -- skipping AO3 notifications")
        return

    shown = new_details[:3]
    lines = [f"{d['title']} gained activity" for d in shown]
    if len(new_details) > 3:
        lines.append(f"...and {len(new_details) - 3} more")
    toast = Notification(
        app_id="PawPoller",
        title=f"AO3: {len(new_details)} Work{'s' if len(new_details) != 1 else ''} Updated",
        msg="\n".join(lines),
    )
    toast.show()


async def _send_ao3_telegram(new_details: list[dict]) -> None:
    """Send Telegram notification for AO3 activity."""
    settings = config.get_settings()
    if not settings.get("telegram_enabled", False):
        return
    token = settings.get("telegram_bot_token")
    chat_id = settings.get("telegram_chat_id")
    if not token or not chat_id:
        return
    if not new_details:
        return

    lines = [f"<b>AO3: {len(new_details)} Work{'s' if len(new_details) != 1 else ''} Updated</b>"]
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
        logger.warning("Failed to send AO3 Telegram notification: %s", e)


def _send_ao3_kudos_notifications(new_kudos: list[dict]) -> None:
    """Send Windows toast notifications for new kudos."""
    settings = config.get_settings()
    if not settings.get("ao3_notifications_enabled", True):
        return
    if not new_kudos:
        return

    try:
        from winotify import Notification
    except ImportError:
        return

    shown = new_kudos[:3]
    lines = [f"{d['username']} left kudos on {d['title']}" for d in shown]
    if len(new_kudos) > 3:
        lines.append(f"...and {len(new_kudos) - 3} more")
    toast = Notification(
        app_id="PawPoller",
        title=f"AO3: {len(new_kudos)} New Kudo{'s' if len(new_kudos) != 1 else ''}",
        msg="\n".join(lines),
    )
    toast.show()


async def _send_ao3_kudos_telegram(new_kudos: list[dict]) -> None:
    """Send Telegram notification for new kudos."""
    settings = config.get_settings()
    if not settings.get("telegram_enabled", False):
        return
    token = settings.get("telegram_bot_token")
    chat_id = settings.get("telegram_chat_id")
    if not token or not chat_id:
        return
    if not new_kudos:
        return

    lines = [f"<b>📖 AO3: {len(new_kudos)} New Kudo{'s' if len(new_kudos) != 1 else ''}</b>"]
    for d in new_kudos[:5]:
        lines.append(f"  • {_esc(d['username'])} → {_esc(d['title'])}")
    if len(new_kudos) > 5:
        lines.append(f"  ...and {len(new_kudos) - 5} more")

    text = "\n".join(lines)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
    except Exception as e:
        logger.warning("Failed to send AO3 kudos Telegram notification: %s", e)


def _get_or_create_client(settings: dict) -> AO3Client:
    """Return the persistent AO3Client, creating or updating as needed."""
    global _ao3_client
    ao3_user = settings.get("ao3_username", "")
    ao3_pass = settings.get("ao3_password", "")
    ao3_target = settings.get("ao3_target_user", "")

    if _ao3_client is None:
        _ao3_client = AO3Client(
            username=ao3_user,
            password=ao3_pass,
            target_user=ao3_target,
        )
    else:
        _ao3_client.update_credentials(ao3_user, ao3_pass, ao3_target)

    return _ao3_client


async def run_ao3_poll_cycle(force_full: bool = False) -> dict:
    """Execute one complete AO3 poll cycle.

    Steps:
      1. Login and validate session
      2. Discover all works for the target user
      3. Fetch details for each work
      4. Upsert works and record snapshots
      5. Track kudos users
    """
    global _ao3_poll_running, _ao3_first_poll

    if not _ao3_poll_lock.acquire(blocking=False):
        logger.warning("AO3 poll already running -- skipping")
        return {}
    _ao3_poll_running = True
    _update_ao3_progress("starting", message="Initialising AO3 poll cycle...")

    conn = None
    log_id = None
    start_time = time.time()

    stats = {
        "submissions_found": 0,
        "snapshots_inserted": 0,
        "new_kudos_found": 0,
    }

    settings = config.get_settings()
    client = _get_or_create_client(settings)

    try:
        conn = get_connection()
        log_id = ao3_queries.start_ao3_poll_log(conn)
        # Step 1: Authenticate
        _update_ao3_progress("searching", message="Authenticating with AO3...")
        target = await client.validate_session()
        if not target:
            raise ValueError("AO3 login failed -- check credentials")

        # Step 2: Discover works
        _update_ao3_progress("searching", message="Fetching works list...")
        works = await client.get_all_work_ids()
        work_ids = [w["work_id"] for w in works]
        stats["submissions_found"] = len(work_ids)
        logger.info("AO3: Found %d works", len(work_ids))

        if not work_ids:
            _update_ao3_progress("complete", message="No AO3 works found.")
            ao3_queries.finish_ao3_poll_log(conn, log_id, "success",
                                             duration_seconds=time.time() - start_time, **stats)
            conn.commit()
            return stats

        # Step 3: Fetch details
        _update_ao3_progress("fetching_details",
                             message=f"Fetching details for {len(work_ids)} works...")
        details = await client.get_work_details_batch(work_ids)
        logger.info("AO3: Fetched details for %d works", len(details))

        # Step 4: Upsert + snapshot
        poll_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        new_kudos_details: list[dict] = []

        for idx, detail in enumerate(details, 1):
            _update_ao3_progress("processing", current=idx, total=len(details),
                                 message=f"Processing work {idx}/{len(details)}...")
            try:
                wid = detail["work_id"]
                views = detail.get("views", 0)
                faves = detail.get("favorites_count", 0)
                comments = detail.get("comments_count", 0)
                bookmarks = detail.get("bookmarks_count", 0)

                ao3_queries.upsert_ao3_submission(conn, detail)
                ao3_queries.insert_ao3_snapshot(conn, wid, views, faves, comments,
                                                bookmarks, polled_at=poll_timestamp)
                stats["snapshots_inserted"] += 1

                # Step 5: Track kudos users
                try:
                    kudos_users = await client.get_kudos_users(wid)
                    for ku in kudos_users:
                        is_new = ao3_queries.upsert_ao3_kudos_user(conn, wid, ku)
                        if is_new:
                            stats["new_kudos_found"] += 1
                            new_kudos_details.append({
                                "username": ku,
                                "title": detail.get("title", ""),
                            })
                except Exception as ke:
                    logger.warning("Error fetching kudos for work %s: %s", wid, ke)

            except Exception as e:
                logger.warning("Error processing AO3 work %s: %s",
                               detail.get("work_id"), e)

        conn.commit()

        # ── Notifications (kudos) ────────────────────────────
        if _ao3_first_poll:
            logger.info("First AO3 poll after startup -- suppressing %d kudos notifications",
                        len(new_kudos_details))
        else:
            if new_kudos_details:
                try:
                    _send_ao3_kudos_notifications(new_kudos_details)
                except Exception as ne:
                    logger.warning("Failed to send AO3 kudos notifications: %s", ne)
                try:
                    await _send_ao3_kudos_telegram(new_kudos_details)
                except Exception as te:
                    logger.warning("Failed to send AO3 kudos Telegram: %s", te)

        # Finalise
        duration = time.time() - start_time
        _update_ao3_progress("complete", current=len(details), total=len(details),
                             message=f"Done -- {stats['submissions_found']} works, "
                                     f"{stats['new_kudos_found']} new kudos in {duration:.1f}s")
        ao3_queries.finish_ao3_poll_log(conn, log_id, "success",
                                         duration_seconds=duration, **stats)
        logger.info("AO3 poll complete in %.1fs -- %d works, %d snapshots, %d new kudos",
                     duration, stats["submissions_found"], stats["snapshots_inserted"],
                     stats["new_kudos_found"])

        # ── Telegram notifications ────────────────────────────
        if not _ao3_first_poll:
            from polling.telegram import send_poll_summary, check_milestones_batch, check_goals
            try:
                await send_poll_summary("ao3", stats, duration)
            except Exception as te:
                logger.warning("Failed to send AO3 Telegram summary: %s", te)
            try:
                await check_milestones_batch("ao3", "ao3_snapshots", "ao3_submissions")
            except Exception as me:
                logger.warning("Failed to check AO3 milestones: %s", me)
            try:
                await check_goals()
            except Exception as ge:
                logger.warning("Failed to check goals: %s", ge)

        return stats

    except Exception as e:
        duration = time.time() - start_time
        _update_ao3_progress("error", message=str(e))
        logger.error("AO3 poll failed: %s", e)
        if conn and log_id:
            ao3_queries.finish_ao3_poll_log(conn, log_id, "error",
                                             error_message=str(e),
                                             duration_seconds=duration, **stats)
        from polling.telegram import send_poll_error
        try:
            await send_poll_error("ao3", e)
        except Exception:
            pass
        raise
    finally:
        if _ao3_first_poll:
            _ao3_first_poll = False
        _ao3_poll_running = False
        _ao3_poll_lock.release()
        if conn:
            conn.close()
