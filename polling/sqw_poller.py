"""SquidgeWorld (SqW) poll cycle orchestration.

Mirrors the SoFurry poller pattern since the auth flow is similar
(username/password login), but with OTW Archive-specific data:
hits, kudos, comments, bookmarks, plus individual kudos user tracking.

Key differences:
  - Authentication via OTW Archive Rails login (CSRF token + form POST)
  - Work IDs are integers
  - Tracks bookmarks (unique to OTW Archive)
  - Tracks individual kudos users (like IB's faving_users)
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
from clients.sqw.client import SquidgeWorldClient
from database.db import get_connection
from database import sqw_queries

logger = logging.getLogger(__name__)

# -- Progress tracking -------------------------------------------------
sqw_poll_progress = {
    "active": False,
    "phase": "idle",
    "current": 0,
    "total": 0,
    "message": "",
}

_sqw_poll_running = False
_sqw_poll_lock = threading.Lock()
_sqw_first_poll = True

# Persistent client — reused across poll cycles
_sqw_client: SquidgeWorldClient | None = None


def _cleanup_sqw_client():
    if _sqw_client is not None:
        import asyncio
        try:
            asyncio.get_event_loop().run_until_complete(_sqw_client.close())
        except Exception:
            logger.debug("Error alert send failed", exc_info=True)


atexit.register(_cleanup_sqw_client)


def _update_sqw_progress(phase: str, current: int = 0, total: int = 0, message: str = ""):
    sqw_poll_progress["active"] = phase not in ("idle", "complete", "error")
    sqw_poll_progress["phase"] = phase
    sqw_poll_progress["current"] = current
    sqw_poll_progress["total"] = total
    sqw_poll_progress["message"] = message


def _send_sqw_notifications(new_details: list[dict]) -> None:
    """Send Windows toast notifications for SquidgeWorld activity."""
    settings = config.get_settings()
    if not settings.get("sqw_notifications_enabled", True):
        return
    if not new_details:
        return

    try:
        from winotify import Notification
    except ImportError:
        logger.debug("winotify not installed -- skipping SqW notifications")
        return

    shown = new_details[:3]
    lines = [f"{d['title']} gained activity" for d in shown]
    if len(new_details) > 3:
        lines.append(f"...and {len(new_details) - 3} more")
    toast = Notification(
        app_id="PawPoller",
        title=f"SqW: {len(new_details)} Work{'s' if len(new_details) != 1 else ''} Updated",
        msg="\n".join(lines),
    )
    toast.show()


async def _send_sqw_telegram(new_details: list[dict]) -> None:
    """Send Telegram notification for SquidgeWorld activity."""
    settings = config.get_settings()
    if not settings.get("telegram_enabled", False):
        return
    token = settings.get("telegram_bot_token")
    chat_id = settings.get("telegram_chat_id")
    if not token or not chat_id:
        return
    if not new_details:
        return

    lines = [f"<b>SqW: {len(new_details)} Work{'s' if len(new_details) != 1 else ''} Updated</b>"]
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
        logger.warning("Failed to send SqW Telegram notification: %s", e, exc_info=True)


def _send_sqw_kudos_notifications(new_kudos: list[dict]) -> None:
    """Send Windows toast notifications for new kudos."""
    settings = config.get_settings()
    if not settings.get("sqw_notifications_enabled", True):
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
        title=f"SqW: {len(new_kudos)} New Kudo{'s' if len(new_kudos) != 1 else ''}",
        msg="\n".join(lines),
    )
    toast.show()


async def _send_sqw_kudos_telegram(new_kudos: list[dict]) -> None:
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

    lines = [f"<b>🦑 SqW: {len(new_kudos)} New Kudo{'s' if len(new_kudos) != 1 else ''}</b>"]
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
        logger.warning("Failed to send SqW kudos Telegram notification: %s", e, exc_info=True)


def _get_or_create_client(settings: dict) -> SquidgeWorldClient:
    """Return the persistent SquidgeWorldClient, creating or updating as needed."""
    global _sqw_client
    sqw_user = settings.get("sqw_username", "")
    sqw_pass = settings.get("sqw_password", "")
    sqw_target = settings.get("sqw_target_user", "")

    if _sqw_client is None:
        _sqw_client = SquidgeWorldClient(
            username=sqw_user,
            password=sqw_pass,
            target_user=sqw_target,
        )
    else:
        _sqw_client.update_credentials(sqw_user, sqw_pass, sqw_target)

    return _sqw_client


async def run_sqw_poll_cycle(force_full: bool = False) -> dict:
    """Execute one complete SquidgeWorld poll cycle.

    Steps:
      1. Login and validate session
      2. Discover all works for the target user
      3. Fetch details for each work
      4. Upsert works and record snapshots
      5. Track kudos users
    """
    global _sqw_poll_running, _sqw_first_poll

    if not _sqw_poll_lock.acquire(blocking=False):
        logger.warning("SqW poll already running -- skipping")
        return {}
    _sqw_poll_running = True
    _update_sqw_progress("starting", message="Initialising SquidgeWorld poll cycle...")

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
        log_id = sqw_queries.start_sqw_poll_log(conn)
        # Step 1: Authenticate
        _update_sqw_progress("searching", message="Authenticating with SquidgeWorld...")
        # Reset login state so ensure_logged_in() attempts a fresh login
        client._logged_in = False
        target = await client.validate_session()
        if not target:
            raise ValueError("SquidgeWorld login failed -- check credentials")

        # Step 2: Discover works
        _update_sqw_progress("searching", message="Fetching works list...")
        works = await client.get_all_work_ids()
        work_ids = [w["work_id"] for w in works]
        stats["submissions_found"] = len(work_ids)
        logger.info("SqW: Found %d works", len(work_ids))

        if not work_ids:
            _update_sqw_progress("complete", message="No SquidgeWorld works found.")
            sqw_queries.finish_sqw_poll_log(conn, log_id, "success",
                                             duration_seconds=time.time() - start_time, **stats)
            conn.commit()
            return stats

        # Step 3: Fetch details
        _update_sqw_progress("fetching_details",
                             message=f"Fetching details for {len(work_ids)} works...")
        details = await client.get_work_details_batch(work_ids)
        logger.info("SqW: Fetched details for %d works", len(details))

        # Step 4: Upsert + snapshot
        poll_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        new_kudos_details: list[dict] = []

        for idx, detail in enumerate(details, 1):
            _update_sqw_progress("processing", current=idx, total=len(details),
                                 message=f"Processing work {idx}/{len(details)}...")
            try:
                wid = detail["work_id"]
                views = detail.get("views", 0)
                faves = detail.get("favorites_count", 0)
                comments = detail.get("comments_count", 0)
                bookmarks = detail.get("bookmarks_count", 0)

                sqw_queries.upsert_sqw_submission(conn, detail)
                sqw_queries.insert_sqw_snapshot(conn, wid, views, faves, comments,
                                                bookmarks, polled_at=poll_timestamp)
                stats["snapshots_inserted"] += 1

                # Step 5: Track kudos users
                try:
                    kudos_users = await client.get_kudos_users(wid)
                    # Batch insert: get existing usernames first to identify new ones
                    existing_usernames = {r["username"] for r in sqw_queries.get_sqw_kudos_users(conn, wid)}
                    new_count = sqw_queries.upsert_sqw_kudos_users_batch(conn, wid, kudos_users)
                    conn.commit()
                    stats["new_kudos_found"] += new_count
                    for ku in kudos_users:
                        if ku not in existing_usernames:
                            new_kudos_details.append({
                                "username": ku,
                                "title": detail.get("title", ""),
                            })
                except Exception as ke:
                    logger.warning("Error fetching kudos for work %s: %s", wid, ke, exc_info=True)

            except Exception as e:
                logger.warning("Error processing SqW work %s: %s",
                               detail.get("work_id"), e, exc_info=True)

        conn.commit()

        # ── Notifications (kudos) ────────────────────────────
        if _sqw_first_poll:
            logger.info("First SqW poll after startup -- suppressing %d kudos notifications",
                        len(new_kudos_details))
        else:
            if new_kudos_details:
                try:
                    _send_sqw_kudos_notifications(new_kudos_details)
                except Exception as ne:
                    logger.warning("Failed to send SqW kudos notifications: %s", ne, exc_info=True)
                try:
                    await _send_sqw_kudos_telegram(new_kudos_details)
                except Exception as te:
                    logger.warning("Failed to send SqW kudos Telegram: %s", te, exc_info=True)

        # Finalise
        duration = time.time() - start_time
        _update_sqw_progress("complete", current=len(details), total=len(details),
                             message=f"Done -- {stats['submissions_found']} works, "
                                     f"{stats['new_kudos_found']} new kudos in {duration:.1f}s")
        sqw_queries.finish_sqw_poll_log(conn, log_id, "success",
                                         duration_seconds=duration, **stats)
        logger.info("SqW poll complete in %.1fs -- %d works, %d snapshots, %d new kudos",
                     duration, stats["submissions_found"], stats["snapshots_inserted"],
                     stats["new_kudos_found"])

        # ── Telegram notifications ────────────────────────────
        if not _sqw_first_poll:
            from polling.telegram import send_poll_summary, check_milestones_batch, check_goals
            try:
                await send_poll_summary("sqw", stats, duration)
            except Exception as te:
                logger.warning("Failed to send SqW Telegram summary: %s", te, exc_info=True)
            try:
                await check_milestones_batch("sqw", "sqw_snapshots", "sqw_submissions")
            except Exception as me:
                logger.warning("Failed to check SqW milestones: %s", me, exc_info=True)
            try:
                await check_goals()
            except Exception as ge:
                logger.warning("Failed to check goals: %s", ge, exc_info=True)

        return stats

    except Exception as e:
        duration = time.time() - start_time
        _update_sqw_progress("error", message=str(e))
        logger.error("SqW poll failed: %s", e, exc_info=True)
        if conn and log_id:
            sqw_queries.finish_sqw_poll_log(conn, log_id, "error",
                                             error_message=str(e),
                                             duration_seconds=duration, **stats)
            conn.commit()
        from polling.telegram import send_poll_error
        try:
            await send_poll_error("sqw", e)
        except Exception:
            logger.debug("Error alert send failed", exc_info=True)
        raise
    finally:
        if _sqw_first_poll:
            _sqw_first_poll = False
        _sqw_poll_running = False
        _sqw_poll_lock.release()
        if conn:
            conn.close()
