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
import atexit
import logging
import threading
import time
from datetime import datetime, timezone
from html import escape as _esc

import config
from clients.sf.client import SoFurryClient
from database.db import get_connection
from database import sf_queries
from polling import notifications

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


def _cleanup_sf_client():
    if _sf_client is not None:
        import asyncio
        try:
            asyncio.get_event_loop().run_until_complete(_sf_client.close())
        except Exception:
            logger.debug("Error alert send failed", exc_info=True)


atexit.register(_cleanup_sf_client)


def _update_sf_progress(phase: str, current: int = 0, total: int = 0, message: str = ""):
    sf_poll_progress["active"] = phase not in ("idle", "complete", "error")
    sf_poll_progress["phase"] = phase
    sf_poll_progress["current"] = current
    sf_poll_progress["total"] = total
    sf_poll_progress["message"] = message


def _send_sf_notifications(new_details: list[dict]) -> None:
    """Send Windows toast notifications for SoFurry activity.

    SF tracks aggregate stat changes (views, faves, comments combined)
    without distinguishing the change type, so ``sf_notification_comments_only``
    suppresses these generic alerts entirely. Follower notifications are
    unaffected — they use a separate code path.
    """
    settings = config.get_settings()
    if settings.get("sf_notification_comments_only", False):
        return
    n = len(new_details)
    notifications.maybe_show_toast(
        settings,
        "sf_notifications_enabled",
        f"SF: {n} Submission{'s' if n != 1 else ''} Updated",
        [f"{d['title']} gained activity" for d in new_details],
    )


async def _send_sf_telegram(new_details: list[dict]) -> None:
    """Send Telegram notification for SoFurry activity.

    Same ``sf_notification_comments_only`` filter as the toast path.
    """
    settings = config.get_settings()
    if settings.get("sf_notification_comments_only", False):
        return
    n = len(new_details)
    await notifications.maybe_send_telegram_summary(
        settings,
        f"<b>SF: {n} Submission{'s' if n != 1 else ''} Updated</b>",
        [_esc(d['title']) for d in new_details],
        log_label="SF",
    )


def _send_sf_follower_notifications(new_follower_names: list[str]) -> None:
    """Send Windows toast notifications for new SF followers."""
    settings = config.get_settings()
    n = len(new_follower_names)
    notifications.maybe_show_toast(
        settings,
        "sf_notifications_enabled",
        f"SF: {n} New Follower{'s' if n != 1 else ''}",
        [f"  {name}" for name in new_follower_names],
    )


async def _send_sf_follower_telegram(new_follower_names: list[str]) -> None:
    """Send Telegram notification for new SF followers."""
    settings = config.get_settings()
    n = len(new_follower_names)
    await notifications.maybe_send_telegram_summary(
        settings,
        f"<b>🐾 SF: {n} New Follower{'s' if n != 1 else ''}</b>",
        [_esc(name) for name in new_follower_names],
        log_label="SF follower",
    )


def _get_or_create_client(settings: dict) -> SoFurryClient:
    """Return the persistent SoFurryClient, creating or updating as needed.

    If the credentials in settings have changed since the last poll, the
    existing client is updated (which invalidates the cached session so
    the next poll will re-login) and saved cookies are cleared.

    On first creation, restores any saved session cookies from settings.json
    so the app can skip re-login if the remember_web cookie is still valid.
    """
    global _sf_client
    sf_user = settings.get("sf_username", "")
    sf_pass = settings.get("sf_password", "")
    sf_display = settings.get("sf_display_name", "")
    sf_totp = settings.get("sf_totp_code", "")

    from polling.cf_proxy import proxy_kwargs
    sf_proxy = proxy_kwargs(settings, "sf")

    if _sf_client is None:
        _sf_client = SoFurryClient(
            username=sf_user,
            password=sf_pass,
            display_name=sf_display,
            totp_code=sf_totp,
            **sf_proxy,
        )
        # Restore saved session cookies (if any) to skip login.
        # Only useful when NOT using the CF proxy (direct login).
        if not sf_proxy:
            saved_cookies = settings.get("sf_session_cookies")
            if saved_cookies:
                _sf_client.import_cookies(saved_cookies)
    else:
        changed = _sf_client.update_credentials(sf_user, sf_pass, sf_display, sf_totp)
        if changed:
            config.delete_settings_keys(["sf_session_cookies"])
            logger.info("SF credentials changed -- cleared saved session cookies")

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

    conn = None
    log_id = None
    start_time = time.time()

    stats = {
        "submissions_found": 0,
        "snapshots_inserted": 0,
        "new_watchers_found": 0,
    }

    settings = config.get_settings()
    client = _get_or_create_client(settings)

    try:
        conn = get_connection()
        log_id = sf_queries.start_sf_poll_log(conn)
        # Step 1+2: Login and fetch gallery.
        # When using the CF Worker proxy, login + gallery happen in one
        # Worker invocation (x-proxy-login) to avoid IP rotation breaking
        # SoFurry's IP-pinned sessions.
        _update_sf_progress("searching", message="Authenticating + fetching gallery...")
        gallery = await client.get_all_gallery_ids()
        if not gallery and not client._logged_in:
            raise ValueError("SoFurry login failed -- check credentials (is SF_USERNAME an email?)")
        submission_ids = [s["submission_id"] for s in gallery]
        stats["submissions_found"] = len(submission_ids)
        logger.info("SF: Found %d submissions", len(submission_ids))

        # Persist session cookies after a successful authenticated gallery fetch.
        # Only useful for direct login (not CF proxy, which rotates IPs).
        if not settings.get("cf_worker_url"):
            cookie_data = client.export_cookies()
            if cookie_data:
                config.save_settings({"sf_session_cookies": cookie_data})
                logger.info("SF: Saved session cookies to settings.json")

        if not submission_ids:
            _update_sf_progress("complete", message="No SoFurry submissions found.")
            sf_queries.finish_sf_poll_log(conn, log_id, "success",
                                          duration_seconds=time.time() - start_time, **stats)
            conn.commit()
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
                               detail.get("submission_id"), e, exc_info=True)

        conn.commit()

        # ── Step 5: Scrape followers ────────────────────────────
        new_follower_names: list[str] = []
        try:
            _update_sf_progress("fetching_watchers", message="Scraping follower list...")
            followers = await client.scrape_followers()
            for username in followers:
                is_new = sf_queries.upsert_sf_watcher(conn, username)
                if is_new:
                    stats["new_watchers_found"] += 1
                    new_follower_names.append(username)
            # Prune followers no longer on the live list
            if followers:
                removed = sf_queries.remove_stale_sf_watchers(conn, followers)
                if removed:
                    logger.info("SF: pruned %d stale followers from DB", removed)
            conn.commit()
        except Exception as we:
            logger.warning("Failed to scrape SF followers: %s", we, exc_info=True)

        # ── Notifications (followers) ────────────────────────────
        if _sf_first_poll:
            logger.info("First SF poll after startup -- suppressing %d follower notifications",
                        len(new_follower_names))
        else:
            if new_follower_names:
                try:
                    _send_sf_follower_notifications(new_follower_names)
                except Exception as ne:
                    logger.warning("Failed to send SF follower notifications: %s", ne, exc_info=True)
                try:
                    await _send_sf_follower_telegram(new_follower_names)
                except Exception as te:
                    logger.warning("Failed to send SF follower Telegram notification: %s", te, exc_info=True)

        # Finalise
        duration = time.time() - start_time
        _update_sf_progress("complete", current=len(details), total=len(details),
                            message=f"Done -- {stats['submissions_found']} submissions, {stats['new_watchers_found']} new followers in {duration:.1f}s")
        sf_queries.finish_sf_poll_log(conn, log_id, "success",
                                      duration_seconds=duration, **stats)
        logger.info("SF poll complete in %.1fs -- %d submissions, %d snapshots, %d new followers",
                     duration, stats["submissions_found"], stats["snapshots_inserted"],
                     stats["new_watchers_found"])

        # ── Telegram notifications ────────────────────────────
        if not _sf_first_poll:
            from polling.telegram import send_poll_summary, check_milestones_batch, check_goals
            try:
                await send_poll_summary("sf", stats, duration)
            except Exception as te:
                logger.warning("Failed to send SF Telegram summary: %s", te, exc_info=True)
            try:
                await check_milestones_batch("sf", "sf_snapshots", "sf_submissions")
            except Exception as me:
                logger.warning("Failed to check SF milestones: %s", me, exc_info=True)
            try:
                await check_goals()
            except Exception as ge:
                logger.warning("Failed to check goals: %s", ge, exc_info=True)

        return stats

    except Exception as e:
        duration = time.time() - start_time
        _update_sf_progress("error", message=str(e))
        logger.error("SF poll failed: %s", e, exc_info=True)
        if conn and log_id:
            sf_queries.finish_sf_poll_log(conn, log_id, "error",
                                          error_message=str(e),
                                          duration_seconds=duration, **stats)
            conn.commit()
        # Send error alert via Telegram
        from polling.telegram import send_poll_error
        try:
            await send_poll_error("sf", e)
        except Exception:
            logger.debug("Error alert send failed", exc_info=True)
        raise
    finally:
        if _sf_first_poll:
            _sf_first_poll = False
        _sf_poll_running = False
        _sf_poll_lock.release()
        # NOTE: client is NOT closed here — it persists across poll cycles
        # to reuse the authenticated session and avoid re-logging in.
        if conn:
            conn.close()
