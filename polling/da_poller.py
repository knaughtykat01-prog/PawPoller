"""DeviantArt (DA) poll cycle orchestration.

Mirrors the AO3 poller pattern (simpler than FA, no comments scraping,
no watchers). DeviantArt uses cookie-based auth with Eclipse _napi endpoints.

Key differences from other pollers:
  - Uses DAClient with cookie_value and target_user
  - Settings keys: da_cookie, da_target_user
  - Stats: submissions_found, snapshots_inserted (no kudos/comments tracking)
  - Notifications: "DA:" prefix
  - Downloads metric tracked in addition to views/favorites/comments
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
from da_client.client import DAClient
from database.db import get_connection
from database import da_queries

logger = logging.getLogger(__name__)

# -- Progress tracking -------------------------------------------------
da_poll_progress = {
    "active": False,
    "phase": "idle",
    "current": 0,
    "total": 0,
    "message": "",
}

_da_poll_running = False
_da_poll_lock = threading.Lock()
_da_first_poll = True

# Persistent client — reused across poll cycles
_da_client: DAClient | None = None


def _cleanup_da_client():
    if _da_client is not None:
        import asyncio
        try:
            asyncio.get_event_loop().run_until_complete(_da_client.close())
        except Exception:
            pass


atexit.register(_cleanup_da_client)


def _update_da_progress(phase: str, current: int = 0, total: int = 0, message: str = ""):
    da_poll_progress["active"] = phase not in ("idle", "complete", "error")
    da_poll_progress["phase"] = phase
    da_poll_progress["current"] = current
    da_poll_progress["total"] = total
    da_poll_progress["message"] = message


def _send_da_notifications(new_details: list[dict]) -> None:
    """Send Windows toast notifications for DA activity."""
    settings = config.get_settings()
    if not settings.get("da_notifications_enabled", True):
        return
    if not new_details:
        return

    try:
        from winotify import Notification
    except ImportError:
        logger.debug("winotify not installed -- skipping DA notifications")
        return

    shown = new_details[:3]
    lines = [f"{d['title']} gained activity" for d in shown]
    if len(new_details) > 3:
        lines.append(f"...and {len(new_details) - 3} more")
    toast = Notification(
        app_id="PawPoller",
        title=f"DA: {len(new_details)} Deviation{'s' if len(new_details) != 1 else ''} Updated",
        msg="\n".join(lines),
    )
    toast.show()


async def _send_da_telegram(new_details: list[dict]) -> None:
    """Send Telegram notification for DA activity."""
    settings = config.get_settings()
    if not settings.get("telegram_enabled", False):
        return
    token = settings.get("telegram_bot_token")
    chat_id = settings.get("telegram_chat_id")
    if not token or not chat_id:
        return
    if not new_details:
        return

    lines = [f"<b>🎨 DA: {len(new_details)} Deviation{'s' if len(new_details) != 1 else ''} Updated</b>"]
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
        logger.warning("Failed to send DA Telegram notification: %s", e)


def _get_or_create_client(settings: dict) -> DAClient:
    """Return the persistent DAClient, creating or updating as needed."""
    global _da_client
    da_cookie = settings.get("da_cookie", "")
    da_target = settings.get("da_target_user", "")

    if _da_client is None:
        _da_client = DAClient(
            cookie_value=da_cookie,
            target_user=da_target,
            proxy_url=settings.get("cf_worker_url", ""),
            proxy_key=settings.get("cf_worker_key", ""),
        )
    else:
        _da_client.update_credentials(da_cookie, da_target)

    return _da_client


async def run_da_poll_cycle(force_full: bool = False) -> dict:
    """Execute one complete DA poll cycle.

    Steps:
      1. Validate cookies by accessing gallery page
      2. Discover all deviations for the target user
      3. Fetch details for each deviation
      4. Upsert deviations and record snapshots
    """
    global _da_poll_running, _da_first_poll

    if not _da_poll_lock.acquire(blocking=False):
        logger.warning("DA poll already running -- skipping")
        return {}
    _da_poll_running = True
    _update_da_progress("starting", message="Initialising DA poll cycle...")

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
        log_id = da_queries.start_da_poll_log(conn)
        # Step 1: Validate cookies
        _update_da_progress("searching", message="Validating DA cookies...")
        valid = await client.validate_cookies()
        if not valid:
            raise ValueError("DA cookie validation failed -- check cookies")

        # Step 2: Discover deviations
        _update_da_progress("searching", message="Fetching deviations list...")
        deviations = await client.get_all_deviation_ids()
        deviation_ids = [d["deviation_id"] for d in deviations]
        stats["submissions_found"] = len(deviation_ids)
        logger.info("DA: Found %d deviations", len(deviation_ids))

        if not deviation_ids:
            _update_da_progress("complete", message="No DA deviations found.")
            da_queries.finish_da_poll_log(conn, log_id, "success",
                                          duration_seconds=time.time() - start_time, **stats)
            conn.commit()
            return stats

        # Step 3: Fetch details
        _update_da_progress("fetching_details",
                            message=f"Fetching details for {len(deviation_ids)} deviations...")
        details = await client.get_deviation_details_batch(deviation_ids)
        logger.info("DA: Fetched details for %d deviations", len(details))

        # Step 4: Upsert + snapshot
        new_activity_details: list[dict] = []
        poll_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        for idx, detail in enumerate(details, 1):
            _update_da_progress("processing", current=idx, total=len(details),
                                message=f"Processing deviation {idx}/{len(details)}...")
            try:
                dev_id = detail["deviation_id"]
                views = detail.get("views", 0)
                faves = detail.get("favorites_count", 0)
                comments = detail.get("comments_count", 0)
                downloads = detail.get("downloads", 0)

                # Check for stat increases to drive notifications.
                prev = da_queries.get_da_submission(conn, dev_id)
                if prev and (faves > prev.get("favorites_count", 0)
                             or comments > prev.get("comments_count", 0)):
                    new_activity_details.append({"title": detail.get("title", "")})

                da_queries.upsert_da_submission(conn, detail)
                da_queries.insert_da_snapshot(conn, dev_id, views, faves, comments,
                                             downloads, polled_at=poll_timestamp)
                stats["snapshots_inserted"] += 1

            except Exception as e:
                logger.warning("Error processing DA deviation %s: %s",
                               detail.get("deviation_id"), e)

        conn.commit()

        # ── Notifications ─────────────────────────────────────
        if _da_first_poll:
            logger.info("First DA poll after startup -- suppressing %d activity notifications",
                        len(new_activity_details))
        else:
            try:
                _send_da_notifications(new_activity_details)
            except Exception as ne:
                logger.warning("Failed to send DA notifications: %s", ne)
            try:
                await _send_da_telegram(new_activity_details)
            except Exception as te:
                logger.warning("Failed to send DA Telegram notification: %s", te)

        # Finalise
        duration = time.time() - start_time
        _update_da_progress("complete", current=len(details), total=len(details),
                            message=f"Done -- {stats['submissions_found']} deviations "
                                    f"in {duration:.1f}s")
        da_queries.finish_da_poll_log(conn, log_id, "success",
                                      duration_seconds=duration, **stats)
        logger.info("DA poll complete in %.1fs -- %d deviations, %d snapshots",
                     duration, stats["submissions_found"], stats["snapshots_inserted"])

        # ── Telegram notifications ────────────────────────────
        if not _da_first_poll:
            from polling.telegram import send_poll_summary, check_milestones_batch, check_goals
            try:
                await send_poll_summary("da", stats, duration)
            except Exception as te:
                logger.warning("Failed to send DA Telegram summary: %s", te)
            try:
                await check_milestones_batch("da", "da_snapshots", "da_submissions")
            except Exception as me:
                logger.warning("Failed to check DA milestones: %s", me)
            try:
                await check_goals()
            except Exception as ge:
                logger.warning("Failed to check goals: %s", ge)

        return stats

    except Exception as e:
        duration = time.time() - start_time
        _update_da_progress("error", message=str(e))
        logger.error("DA poll failed: %s", e)
        if conn and log_id:
            da_queries.finish_da_poll_log(conn, log_id, "error",
                                          error_message=str(e),
                                          duration_seconds=duration, **stats)
        from polling.telegram import send_poll_error
        try:
            await send_poll_error("da", e)
        except Exception:
            pass
        raise
    finally:
        if _da_first_poll:
            _da_first_poll = False
        _da_poll_running = False
        _da_poll_lock.release()
        if conn:
            conn.close()
