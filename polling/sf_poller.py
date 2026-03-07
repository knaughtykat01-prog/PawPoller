"""SoFurry (SF) poll cycle orchestration.

Mirrors the Weasyl poller pattern (polling/ws_poller.py) since SoFurry has
similar data availability: views, likes, and comment counts only.

Key differences:
  - Authentication via email/password login (not API key)
  - Data collected by scraping web pages (not API calls)
  - Submission IDs are alphanumeric strings (not integers)
  - No individual comment or fave-user tracking
"""

from __future__ import annotations
import logging
import threading
import time
from datetime import datetime, timezone

import httpx

import config
from sf_client.client import SoFurryClient
from database.db import get_connection
from database import sf_queries

logger = logging.getLogger(__name__)

# -- Progress tracking -------------------------------------------------
sf_poll_progress = {
    "active": False,
    "phase": "idle",
    "current": 0,
    "total": 0,
    "message": "",
}

_sf_poll_running = False
_sf_poll_lock = threading.Lock()
_sf_first_poll = True

# Persistent client — reused across poll cycles to avoid re-logging in
# every time.  Recreated only when credentials change in settings.
_sf_client: SoFurryClient | None = None


def _update_sf_progress(phase: str, current: int = 0, total: int = 0, message: str = ""):
    sf_poll_progress["active"] = phase not in ("idle", "complete", "error")
    sf_poll_progress["phase"] = phase
    sf_poll_progress["current"] = current
    sf_poll_progress["total"] = total
    sf_poll_progress["message"] = message


def _send_sf_notifications(new_details: list[dict]) -> None:
    """Send Windows toast notifications for SoFurry activity."""
    settings = config.get_settings()
    if not settings.get("sf_notifications_enabled", True):
        return
    if not new_details:
        return

    try:
        from winotify import Notification
    except ImportError:
        logger.debug("winotify not installed -- skipping SF notifications")
        return

    shown = new_details[:3]
    lines = [f"{d['title']} gained activity" for d in shown]
    if len(new_details) > 3:
        lines.append(f"...and {len(new_details) - 3} more")
    toast = Notification(
        app_id="PawPoller",
        title=f"SF: {len(new_details)} Submission{'s' if len(new_details) != 1 else ''} Updated",
        msg="\n".join(lines),
    )
    toast.show()


async def _send_sf_telegram(new_details: list[dict]) -> None:
    """Send Telegram notification for SoFurry activity."""
    settings = config.get_settings()
    if not settings.get("telegram_enabled", False):
        return
    token = settings.get("telegram_bot_token")
    chat_id = settings.get("telegram_chat_id")
    if not token or not chat_id:
        return
    if not new_details:
        return

    lines = [f"<b>SF: {len(new_details)} Submission{'s' if len(new_details) != 1 else ''} Updated</b>"]
    for d in new_details[:5]:
        lines.append(f"  * {d['title']}")
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
        logger.warning("Failed to send SF Telegram notification: %s", e)


def _get_or_create_client(settings: dict) -> SoFurryClient:
    """Return the persistent SoFurryClient, creating or updating as needed.

    If the credentials in settings have changed since the last poll, the
    existing client is updated (which invalidates the cached session so
    the next poll will re-login).  A brand-new client is only created on
    first use.
    """
    global _sf_client
    sf_user = settings.get("sf_username", "")
    sf_pass = settings.get("sf_password", "")
    sf_display = settings.get("sf_display_name", "")
    sf_totp = settings.get("sf_totp_code", "")

    if _sf_client is None:
        _sf_client = SoFurryClient(
            username=sf_user,
            password=sf_pass,
            display_name=sf_display,
            totp_code=sf_totp,
        )
    else:
        _sf_client.update_credentials(sf_user, sf_pass, sf_display, sf_totp)

    return _sf_client


async def run_sf_poll_cycle(force_full: bool = False) -> dict:
    """Execute one complete SoFurry poll cycle.

    Steps:
      1. Login and validate session
      2. Discover all gallery submissions
      3. Fetch details for each submission
      4. Upsert submissions and record snapshots
    """
    global _sf_poll_running, _sf_first_poll

    if not _sf_poll_lock.acquire(blocking=False):
        logger.warning("SF poll already running -- skipping")
        return {}
    _sf_poll_running = True
    _update_sf_progress("starting", message="Initialising SoFurry poll cycle...")

    conn = get_connection()
    log_id = sf_queries.start_sf_poll_log(conn)
    start_time = time.time()

    stats = {
        "submissions_found": 0,
        "snapshots_inserted": 0,
    }

    settings = config.get_settings()
    client = _get_or_create_client(settings)

    try:
        # Step 1: Authenticate (reuses existing session if still valid)
        _update_sf_progress("searching", message="Authenticating with SoFurry...")
        username = await client.validate_session()
        if not username:
            raise ValueError("SoFurry login failed -- check credentials")

        # Step 2: Discover gallery
        _update_sf_progress("searching", message="Fetching gallery...")
        gallery = await client.get_all_gallery_ids()
        submission_ids = [s["submission_id"] for s in gallery]
        stats["submissions_found"] = len(submission_ids)
        logger.info("SF: Found %d submissions", len(submission_ids))

        if not submission_ids:
            _update_sf_progress("complete", message="No SoFurry submissions found.")
            sf_queries.finish_sf_poll_log(conn, log_id, "success",
                                          duration_seconds=time.time() - start_time, **stats)
            return stats

        # Step 3: Fetch details
        _update_sf_progress("fetching_details",
                            message=f"Fetching details for {len(submission_ids)} submissions...")
        details = await client.get_submission_details_batch(submission_ids)
        logger.info("SF: Fetched details for %d submissions", len(details))

        # Step 4: Upsert + snapshot
        poll_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        for idx, detail in enumerate(details, 1):
            _update_sf_progress("processing", current=idx, total=len(details),
                                message=f"Processing submission {idx}/{len(details)}...")
            try:
                sub_id = detail["submission_id"]
                views = detail.get("views", 0)
                faves = detail.get("favorites_count", 0)
                comments = detail.get("comments_count", 0)

                sf_queries.upsert_sf_submission(conn, detail)
                sf_queries.insert_sf_snapshot(conn, sub_id, views, faves, comments,
                                              polled_at=poll_timestamp)
                stats["snapshots_inserted"] += 1

            except Exception as e:
                logger.warning("Error processing SF submission %s: %s",
                               detail.get("submission_id"), e)

        conn.commit()

        # Finalise
        duration = time.time() - start_time
        _update_sf_progress("complete", current=len(details), total=len(details),
                            message=f"Done -- {stats['submissions_found']} submissions in {duration:.1f}s")
        sf_queries.finish_sf_poll_log(conn, log_id, "success",
                                      duration_seconds=duration, **stats)
        logger.info("SF poll complete in %.1fs -- %d submissions, %d snapshots",
                     duration, stats["submissions_found"], stats["snapshots_inserted"])

        # ── Telegram notifications ────────────────────────────
        if not _sf_first_poll:
            from polling.telegram import send_poll_summary, check_milestones_batch, check_goals
            try:
                await send_poll_summary("sf", stats, duration)
            except Exception as te:
                logger.warning("Failed to send SF Telegram summary: %s", te)
            try:
                await check_milestones_batch("sf", "sf_snapshots", "sf_submissions")
            except Exception as me:
                logger.warning("Failed to check SF milestones: %s", me)
            try:
                await check_goals()
            except Exception as ge:
                logger.warning("Failed to check goals: %s", ge)

        return stats

    except Exception as e:
        duration = time.time() - start_time
        _update_sf_progress("error", message=str(e))
        logger.error("SF poll failed: %s", e)
        sf_queries.finish_sf_poll_log(conn, log_id, "error",
                                      error_message=str(e),
                                      duration_seconds=duration, **stats)
        # Send error alert via Telegram
        from polling.telegram import send_poll_error
        try:
            await send_poll_error("sf", e)
        except Exception:
            pass
        raise
    finally:
        if _sf_first_poll:
            _sf_first_poll = False
        _sf_poll_running = False
        _sf_poll_lock.release()
        # NOTE: client is NOT closed here — it persists across poll cycles
        # to reuse the authenticated session and avoid re-logging in.
        conn.close()
