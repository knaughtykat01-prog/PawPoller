"""REST API endpoints for the analytics dashboard.

This is the primary Inkbunny (IB) routes module. It handles:
  - Authentication (login/logout with credential cascade)
  - Polling controls (trigger, full-resync, progress)
  - Submission data retrieval (list, detail, snapshots, comparison)
  - CSV export via DictWriter -> StreamingResponse
  - Group CRUD (create, read, update, delete groups and members)
  - Analytics (top fans, trending submissions)
  - Cross-platform link management (link submissions across IB/FA/WS)
  - Auto-update (check for new versions, download and apply)
  - Thumbnail proxy (CORS bypass for Inkbunny CDN images)
  - Telegram notification setup (bot token, chat_id discovery)
  - User preferences (poll intervals, notification filters)
  - Settings management (credentials, preferences, Telegram config)
"""

from __future__ import annotations
import csv
import io
import logging
import sqlite3
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Query, HTTPException, UploadFile, File
from fastapi.responses import Response, StreamingResponse

from database.db import get_connection, init_db
from database import queries, fa_queries, ws_queries, sf_queries, group_queries, analytics_queries
from polling.poller import run_poll_cycle, poll_progress
from clients.ib.client import InkbunnyClient
import config
import updater

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/health")
async def health_check():
    """Lightweight health check for Docker HEALTHCHECK and monitoring.

    Returns 200 with {"status": "ok", "version": "..."} if the web
    server is responsive. Does not check individual poller health —
    that would add latency and coupling. The point is to detect a
    completely dead container.

    2.16.8: added `version` so monitoring/CI can confirm a deploy
    actually rolled out without parsing the dashboard HTML.
    """
    return {"status": "ok", "version": config.APP_VERSION}


# In-memory credentials for "don't remember me" logins.
# When the user logs in without ticking "remember me", credentials are stored
# here in the process memory rather than persisted to settings.json on disk.
# They survive for the lifetime of the server process but are lost on restart.
# Protected by _cred_lock to prevent race conditions between the web server
# thread (writes) and poller threads (reads).
import threading
_session_credentials: dict = {}
_cred_lock = threading.Lock()


def get_effective_credentials() -> tuple[str, str]:
    """Return (username, password) using a three-tier credential cascade.

    The cascade checks sources in priority order:
      1. Session memory (_session_credentials) -- set by "don't remember me" logins
      2. settings.json on disk -- set by "remember me" logins or the settings page
      3. config module globals (INKBUNNY_USERNAME / INKBUNNY_PASSWORD) -- loaded at
         startup from environment variables or .env file

    This allows temporary logins to override persisted credentials, and persisted
    credentials to override the initial config defaults.
    """
    with _cred_lock:
        if _session_credentials.get("username") and _session_credentials.get("password"):
            return _session_credentials["username"], _session_credentials["password"]
    settings = config.get_settings()
    username = settings.get("username") or config.INKBUNNY_USERNAME
    password = settings.get("password") or config.INKBUNNY_PASSWORD
    return username, password


# Long-lived httpx client for proxying thumbnail requests.
# Reused across requests to benefit from connection pooling.
_thumb_client = httpx.AsyncClient(timeout=15.0)


# ── Authentication ────────────────────────────────────────────
# Inkbunny uses username/password authentication. The login flow validates
# credentials against the real Inkbunny API before accepting them locally.
# Passwords are NEVER returned in any API response -- only a boolean
# "has_password" flag is exposed via GET /settings/credentials.

@router.get("/auth/status")
def auth_status():
    """Check whether credentials exist and whether there is any data yet.

    Used by the frontend on initial load to decide whether to show the
    login page or the main dashboard. Checks the credential cascade for
    any available username/password, and queries the DB for submission count.
    """
    username, password = get_effective_credentials()
    has_credentials = bool(username and password)
    has_data = False
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) as c FROM submissions").fetchone()["c"]
        has_data = count > 0
    except Exception:
        pass
    finally:
        conn.close()
    return {"has_credentials": has_credentials, "has_data": has_data}


@router.post("/auth/login")
async def auth_login(body: dict):
    """Validate credentials against the real Inkbunny API; optionally persist them.

    Auth flow:
      1. Receive username + password from the frontend
      2. Create a temporary InkbunnyClient and attempt login against the live API
      3. If the API rejects (wrong password, banned, etc.), parse the error and
         return a 401 with the Inkbunny-provided error message
      4. On success, hot-reload the config globals so the background poller
         immediately picks up the new credentials without a server restart
      5. If "remember" is true, persist to settings.json on disk
         If "remember" is false, store in _session_credentials (in-memory only)
    """
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    remember = body.get("remember", False)

    if not username or not password:
        raise HTTPException(400, "Username and password are required")

    # Test login against the live Inkbunny API to validate credentials
    client = InkbunnyClient(username=username, password=password)
    try:
        await client.login()
    except Exception as e:
        # Extract a clean error message from the Inkbunny API response dict.
        # The raw exception string contains the full dict repr; we pull out
        # just the human-readable 'error_message' value for the frontend.
        err_str = str(e)
        if "error_message" in err_str:
            import re
            match = re.search(r"'error_message':\s*'([^']+)'", err_str)
            if match:
                err_str = match.group(1)
        raise HTTPException(401, detail=err_str)
    finally:
        await client.close()

    # Hot-reload: update the config module globals in-place so the background
    # poller uses these new credentials on its next cycle, without needing
    # a full server restart. Lock ensures poller reads consistent username+password.
    with _cred_lock:
        config.INKBUNNY_USERNAME = username
        config.INKBUNNY_PASSWORD = password

        if remember:
            # Persist to settings.json so credentials survive server restarts
            config.save_settings({"username": username, "password": password})
        else:
            # Store in process memory only -- lost on restart
            _session_credentials["username"] = username
            _session_credentials["password"] = password

    return {"status": "success", "message": "Authenticated successfully"}


@router.post("/auth/logout")
def auth_logout():
    """Clear all credentials from every tier of the cascade and reset state.

    Clears:
      1. In-memory session credentials
      2. Config module globals (prevents poller from re-using old creds)
      3. settings.json on disk (removes persisted username/password)
      4. Cached API session in the database (forces full re-auth on next poll)
    """
    with _cred_lock:
        _session_credentials.clear()
        config.INKBUNNY_USERNAME = ""
        config.INKBUNNY_PASSWORD = ""
    # Remove from settings.json on disk
    config.delete_settings_keys(["username", "password"])
    # Clear the cached Inkbunny API session (SID) from the database so the
    # next poll cycle will perform a fresh login rather than reusing a stale SID
    conn = get_connection()
    try:
        queries.clear_session(conn)
    except Exception:
        pass
    finally:
        conn.close()
    return {"status": "success", "message": "Logged out"}


# ── Poll Controls ─────────────────────────────────────────────
# Two polling actions are available:
#   - poll/trigger: Normal incremental poll -- fetches only new/changed data
#   - poll/full-resync: Forces a complete re-scrape of all faves, comments,
#     and submission details regardless of whether changes were detected.
#     Useful when data appears out of sync or after a schema migration.

@router.get("/poll/progress")
def get_poll_progress():
    """Return the current poll progress state.

    The poll_progress dict is updated in real-time by the poller module
    during a poll cycle. It contains fields like current step, total steps,
    and a human-readable message for the frontend progress bar.
    """
    return dict(poll_progress)


@router.get("/poll/all-progress")
def get_all_poll_progress():
    """Return progress state for every platform in one call.

    2.16.9: collapses what used to be 9 simultaneous fetches into one.
    The frontend ticker fires every 10s (idle) / 1.5s (active), so the
    fan-out spammed 9× errors into DevTools whenever the session
    cookie blipped. Each value is a dict with `active`, `phase`,
    `current`, `total`, `message` — the same shape every per-platform
    /api/{p}/poll/progress already returns.

    Imports are local so a missing poller module (e.g. partial deploy)
    can't take the whole endpoint down — that platform's slot just
    becomes None. Per-platform endpoints stay alive for direct callers
    and backwards compatibility.
    """
    progress = {}

    def _safe(key, importer):
        try:
            progress[key] = dict(importer())
        except Exception as e:
            logger.debug("all-progress: %s import failed: %s", key, e)
            progress[key] = None

    _safe("ib", lambda: poll_progress)
    _safe("fa", lambda: __import__("polling.fa_poller", fromlist=["fa_poll_progress"]).fa_poll_progress)
    _safe("ws", lambda: __import__("polling.ws_poller", fromlist=["ws_poll_progress"]).ws_poll_progress)
    _safe("sf", lambda: __import__("polling.sf_poller", fromlist=["sf_poll_progress"]).sf_poll_progress)
    _safe("sqw", lambda: __import__("polling.sqw_poller", fromlist=["sqw_poll_progress"]).sqw_poll_progress)
    _safe("ao3", lambda: __import__("polling.ao3_poller", fromlist=["ao3_poll_progress"]).ao3_poll_progress)
    _safe("da", lambda: __import__("polling.da_poller", fromlist=["da_poll_progress"]).da_poll_progress)
    _safe("wp", lambda: __import__("polling.wp_poller", fromlist=["wp_poll_progress"]).wp_poll_progress)
    _safe("ik", lambda: __import__("polling.ik_poller", fromlist=["ik_poll_progress"]).ik_poll_progress)
    _safe("bsky", lambda: __import__("polling.bsky_poller", fromlist=["bsky_poll_progress"]).bsky_poll_progress)
    _safe("tw", lambda: __import__("polling.tw_poller", fromlist=["tw_poll_progress"]).tw_poll_progress)

    return progress


@router.get("/status")
def get_status():
    """Polling status, last/next poll time, total submissions."""
    conn = get_connection()
    try:
        last_poll = queries.get_last_poll(conn)
        count = conn.execute("SELECT COUNT(*) as c FROM submissions").fetchone()["c"]
        snap_count = conn.execute("SELECT COUNT(*) as c FROM snapshots").fetchone()["c"]
        return {
            "total_submissions": count,
            "total_snapshots": snap_count,
            "last_poll": last_poll,
        }
    except Exception as e:
        logger.error("Error in /api/status: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@router.get("/summary")
def get_summary():
    """Dashboard summary: totals, top 5, fastest growing, recent faves, growth rates.

    Returns an aggregate dashboard payload including growth_rates (views/faves/comments
    deltas over recent poll windows) merged into the summary dict.
    """
    conn = get_connection()
    try:
        summary = queries.get_summary(conn)
        summary["growth_rates"] = queries.get_growth_rates(conn)
        summary["total_watchers"] = queries.get_watchers_count(conn)
        summary["recent_watchers"] = queries.get_recent_watchers(conn, limit=10)
        return summary
    except Exception as e:
        logger.error("Error in /api/summary: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


# ── Submission Data ───────────────────────────────────────────

@router.get("/submissions")
def get_submissions(
    sort_by: str = Query("views", description="Sort field"),
    order: str = Query("desc", description="Sort order"),
    search: str = Query("", description="Search title/keywords"),
    rating: str = Query("", description="Filter by rating"),
    type_name: str = Query("", description="Filter by type"),
):
    """All submissions with latest stats, sortable/filterable.

    Fetches all submissions from the database, then applies in-memory filtering
    for search text, rating, and type. Deltas (change since last poll) are
    merged in from a separate query so the frontend can show +/- indicators.
    """
    conn = get_connection()
    try:
        subs = queries.get_all_submissions(conn, sort_by=sort_by, order=order)
        # Get per-submission deltas (views/faves/comments change since last poll)
        deltas = queries.get_submission_deltas(conn)

        # In-memory filtering -- applied after DB fetch because the query module
        # handles sorting but not arbitrary text/rating/type filtering
        if search:
            search_lower = search.lower()
            subs = [s for s in subs if search_lower in s["title"].lower() or search_lower in (s.get("keywords") or "").lower()]
        if rating:
            subs = [s for s in subs if str(s.get("rating_id")) == rating or s.get("rating_name", "").lower() == rating.lower()]
        if type_name:
            subs = [s for s in subs if s.get("type_name", "").lower() == type_name.lower()]

        # Merge delta values into each submission dict for the frontend
        for s in subs:
            d = deltas.get(s["submission_id"], {})
            s["views_delta"] = d.get("views_delta", 0)
            s["faves_delta"] = d.get("faves_delta", 0)
            s["comments_delta"] = d.get("comments_delta", 0)

        return {"submissions": subs, "total": len(subs)}
    except Exception as e:
        logger.error("Error in /api/submissions: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@router.get("/submissions/{submission_id}")
def get_submission(submission_id: int):
    """Full detail + snapshot history + faving users + comments + growth rates.

    Returns the complete picture for a single submission detail page:
    the submission metadata, all historical snapshots (for charting),
    the list of users who faved it, all comments, and per-metric growth rates.
    """
    conn = get_connection()
    try:
        sub = queries.get_submission(conn, submission_id)
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")
        snapshots = queries.get_snapshots(conn, submission_id)
        faving = queries.get_faving_users(conn, submission_id)
        comments = queries.get_comments(conn, submission_id)
        growth_rates = queries.get_submission_growth_rates(conn, submission_id)
        tags = _get_submission_tags(conn, "ib", submission_id)
        sub_dict = dict(sub) if not isinstance(sub, dict) else sub
        sub_dict["tags"] = tags
        return {"submission": sub_dict, "snapshots": snapshots, "faving_users": faving, "comments": comments, "growth_rates": growth_rates}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in /api/submissions/%d: %s", submission_id, e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@router.get("/submissions/{submission_id}/snapshots")
def get_submission_snapshots(
    submission_id: int,
    start: Optional[str] = Query(None, description="Start datetime"),
    end: Optional[str] = Query(None, description="End datetime"),
):
    """Time-series data for a single submission, with optional date range filtering."""
    conn = get_connection()
    try:
        return {"snapshots": queries.get_snapshots(conn, submission_id, start, end)}
    except Exception as e:
        logger.error("Error in /api/submissions/%d/snapshots: %s", submission_id, e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@router.get("/aggregate")
def get_aggregate(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    """Aggregate time-series across all submissions.

    Sums views/faves/comments across every submission at each poll timestamp,
    providing a single combined time-series for the "all submissions" chart.
    """
    conn = get_connection()
    try:
        return {"snapshots": queries.get_aggregate_snapshots(conn, start, end)}
    except Exception as e:
        logger.error("Error in /api/aggregate: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@router.get("/comparison")
def get_comparison(
    ids: str = Query(..., description="Comma-separated submission IDs"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    """Multi-submission time-series for overlay charts.

    Accepts up to 10 comma-separated submission IDs and returns per-submission
    snapshot series keyed by ID, plus a titles map for chart legends.
    Capped at 10 to keep response sizes reasonable for the frontend chart library.
    """
    try:
        submission_ids = [int(x.strip()) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, "Invalid submission IDs")
    if len(submission_ids) > 10:
        raise HTTPException(400, "Max 10 submissions for comparison")

    conn = get_connection()
    try:
        data = queries.get_comparison_snapshots(conn, submission_ids, start, end)
        titles = {}
        for sid in submission_ids:
            sub = queries.get_submission(conn, sid)
            if sub:
                titles[sid] = sub["title"]
        # Convert int keys to string keys for JSON serialisation compatibility
        return {"series": {str(k): v for k, v in data.items()}, "titles": {str(k): v for k, v in titles.items()}}
    except Exception as e:
        logger.error("Error in /api/comparison: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@router.get("/watchers")
def get_watchers():
    """Recent watchers list with total count."""
    conn = get_connection()
    try:
        watchers = queries.get_recent_watchers(conn, limit=50)
        count = queries.get_watchers_count(conn)
        return {"watchers": watchers, "total": count}
    finally:
        conn.close()


@router.get("/poll_log")
def get_poll_log(limit: int = Query(50, ge=1, le=200)):
    """Recent poll history -- shows timestamps, durations, and results of past polls."""
    conn = get_connection()
    try:
        return {"polls": queries.get_poll_log(conn, limit)}
    except Exception as e:
        logger.error("Error in /api/poll_log: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@router.post("/poll/trigger")
async def trigger_poll():
    """Manual 'refresh now' -- runs an incremental poll cycle inline.

    This is a normal poll: it checks for new submissions and updated stats,
    but only re-scrapes faves/comments for submissions whose counts changed.
    Compare with /poll/full-resync which forces a complete re-scrape of everything.
    """
    try:
        stats = await run_poll_cycle()
        return {"status": "success", "stats": stats}
    except Exception as e:
        logger.error("Error in /api/poll/trigger: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


@router.post("/poll/full-resync")
async def full_resync():
    """Force full resync -- re-scrapes ALL faves and comments regardless of changes.

    Unlike poll/trigger which only fetches fave/comment details for submissions
    whose counts changed, this forces a complete re-scrape of every submission's
    faving users and comments. Useful for:
      - Recovering from data inconsistencies
      - After schema migrations that add new tracked fields
      - When faving user lists appear incomplete
    """
    try:
        stats = await run_poll_cycle(force_full=True)
        return {"status": "success", "stats": stats}
    except Exception as e:
        logger.error("Error in /api/poll/full-resync: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


@router.post("/poll/pause")
async def pause_polling():
    """Pause all scheduled background polling across all platforms.

    Sets the polling_paused flag in settings.json.  Poller loops check this
    flag each cycle and skip when paused.  Manual Poll Now still works.
    Sends a Telegram notification.
    """
    config.save_settings({"polling_paused": True})
    logger.info("Polling PAUSED by user")
    try:
        from polling.telegram import send_telegram
        await send_telegram("⏸ <b>Polling paused</b>\nAll scheduled background polls are now skipped.\nManual polls still work.")
    except Exception:
        pass
    return {"status": "success", "polling_paused": True}


@router.post("/poll/resume")
async def resume_polling():
    """Resume scheduled background polling across all platforms."""
    config.save_settings({"polling_paused": False})
    logger.info("Polling RESUMED by user")
    try:
        from polling.telegram import send_telegram
        await send_telegram("▶️ <b>Polling resumed</b>\nScheduled background polls will run on their normal intervals.")
    except Exception:
        pass
    return {"status": "success", "polling_paused": False}


@router.get("/poll/paused")
def get_poll_paused():
    """Return current polling pause state."""
    settings = config.get_settings()
    return {"polling_paused": settings.get("polling_paused", False)}


@router.post("/session/clear")
def clear_session():
    """Clear the cached Inkbunny API session (SID) from the database.

    Forces a fresh login on the next poll cycle. Useful when the session
    has expired or become invalid (e.g., after a password change on Inkbunny).
    """
    conn = get_connection()
    try:
        queries.clear_session(conn)
        return {"status": "success", "message": "Session cleared — next poll will re-authenticate"}
    except Exception as e:
        logger.error("Error in /api/session/clear: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


# ── Settings: Credentials ────────────────────────────────────
# Security note: passwords are NEVER returned in API responses.
# GET /settings/credentials returns the username and a boolean "has_password"
# flag only, so the frontend can show whether a password is saved without
# ever exposing the actual password value.

@router.get("/settings/credentials")
def get_credentials():
    """Return saved username and whether a password exists (never the password itself).

    This endpoint deliberately omits the password value for security.
    The frontend uses "has_password" to show a placeholder in the password
    field and to know whether the user needs to re-enter it.
    """
    settings = config.get_settings()
    return {
        "username": settings.get("username", ""),
        "has_password": bool(settings.get("password")),
    }


@router.post("/settings/credentials")
def save_credentials(body: dict):
    """Save Inkbunny credentials to settings.json and hot-reload config globals.

    If only the username is provided (no password), the existing password in
    settings.json is preserved. This allows the frontend to update the username
    without requiring the user to re-enter their password.
    """
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    if not username:
        raise HTTPException(400, "Username is required")

    # Only include password in the update if one was actually provided,
    # so we don't accidentally blank out an existing saved password
    update = {"username": username}
    if password:
        update["password"] = password

    config.save_settings(update)

    # Hot-reload: update config module globals so the poller uses new
    # credentials immediately without requiring a server restart
    config.INKBUNNY_USERNAME = username
    if password:
        config.INKBUNNY_PASSWORD = password

    return {"status": "success", "message": "Credentials saved"}


# ── Settings: Preferences ────────────────────────────────────
# Preferences control application behaviour like poll intervals, notification
# filters, and system tray/startup settings. Each preference is individually
# optional in the request body -- only provided fields are updated.

@router.get("/settings/preferences")
def get_preferences():
    """Return all application preferences with sensible defaults.

    Covers every user-configurable preference across all 11 platforms:
      - notifications_enabled / {platform}_ : master toggle per platform
      - poll_interval_minutes / {platform}_ : how often to poll (from allowed set)
      - notification_comments_only / {platform}_ : only notify on new comments
      - watcher_notifications_enabled / fa_ : toggle watcher alerts per platform
      - notification_min_faves_delta : minimum new-fave count to trigger notification
      - notification_min_views_delta : stored for future use (no view-based notifications yet)
      - display_timezone : timezone for Telegram messages and UI timestamps
      - milestone_* : threshold arrays for Telegram milestone alerts
    """
    settings = config.get_settings()
    return {
        # ── Application ────────────────────────────────────────────
        "minimize_to_tray": settings.get("minimize_to_tray", False),
        "run_on_startup": config.get_run_on_startup(),
        "display_timezone": settings.get("display_timezone", "UTC"),
        "theme": settings.get("theme", "dark"),
        "mobile_mode": settings.get("mobile_mode", "auto"),
        "auto_sync_enabled": settings.get("auto_sync_enabled", True),
        # ── Per-platform notification master toggles ───────────────
        "notifications_enabled": settings.get("notifications_enabled", True),
        "fa_notifications_enabled": settings.get("fa_notifications_enabled", True),
        "ws_notifications_enabled": settings.get("ws_notifications_enabled", True),
        "sf_notifications_enabled": settings.get("sf_notifications_enabled", True),
        "sqw_notifications_enabled": settings.get("sqw_notifications_enabled", True),
        "ao3_notifications_enabled": settings.get("ao3_notifications_enabled", True),
        "da_notifications_enabled": settings.get("da_notifications_enabled", True),
        "wp_notifications_enabled": settings.get("wp_notifications_enabled", True),
        "ik_notifications_enabled": settings.get("ik_notifications_enabled", True),
        "bsky_notifications_enabled": settings.get("bsky_notifications_enabled", True),
        "tw_notifications_enabled": settings.get("tw_notifications_enabled", True),
        # ── Watcher / follower notification toggles ────────────────
        "watcher_notifications_enabled": settings.get("watcher_notifications_enabled", True),
        "fa_watcher_notifications_enabled": settings.get("fa_watcher_notifications_enabled", True),
        # ── Per-platform poll intervals (minutes) ──────────────────
        "poll_interval_minutes": settings.get("poll_interval_minutes", 60),
        "fa_poll_interval_minutes": settings.get("fa_poll_interval_minutes", 60),
        "ws_poll_interval_minutes": settings.get("ws_poll_interval_minutes", 60),
        "sf_poll_interval_minutes": settings.get("sf_poll_interval_minutes", 60),
        "sqw_poll_interval_minutes": settings.get("sqw_poll_interval_minutes", 60),
        "ao3_poll_interval_minutes": settings.get("ao3_poll_interval_minutes", 60),
        "da_poll_interval_minutes": settings.get("da_poll_interval_minutes", 60),
        "wp_poll_interval_minutes": settings.get("wp_poll_interval_minutes", 60),
        "ik_poll_interval_minutes": settings.get("ik_poll_interval_minutes", 60),
        "bsky_poll_interval_minutes": settings.get("bsky_poll_interval_minutes", 60),
        "tw_poll_interval_minutes": settings.get("tw_poll_interval_minutes", 60),
        # ── Notification filter preferences ────────────────────────
        # When enabled, notifications are only sent for new comments
        # (suppressing fave/activity alerts for that platform).
        "notification_comments_only": settings.get("notification_comments_only", False),
        "fa_notification_comments_only": settings.get("fa_notification_comments_only", False),
        "ws_notification_comments_only": settings.get("ws_notification_comments_only", False),
        "sf_notification_comments_only": settings.get("sf_notification_comments_only", False),
        # Minimum delta thresholds: fave notifications are suppressed unless
        # the new-fave count in a cycle meets or exceeds this value.
        # notification_min_views_delta is stored but not yet consumed -- no
        # platform currently generates view-change-based notifications.
        "notification_min_views_delta": settings.get("notification_min_views_delta", 0),
        "notification_min_faves_delta": settings.get("notification_min_faves_delta", 0),
        # ── Milestone thresholds (Telegram) ────────────────────────
        "milestone_views": settings.get("milestone_views", [100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000]),
        "milestone_faves": settings.get("milestone_faves", [10, 25, 50, 100, 250, 500, 1000, 2500, 5000]),
        "milestone_comments": settings.get("milestone_comments", [10, 25, 50, 100, 250, 500, 1000]),
    }


@router.post("/settings/preferences")
def save_preferences(body: dict):
    """Save application preferences and apply startup registry change.

    Each field is individually optional -- only provided keys are updated.
    Special handling:
      - run_on_startup: modifies the Windows registry (or equivalent) via config
      - *_poll_interval_minutes: validated against the allowed set {15, 30, 60, 120, 240}
        to prevent abuse or unreasonably fast polling that could get the user
        rate-limited by platform APIs. Invalid values are silently ignored.
    """
    update = {}

    # ── Application toggles ────────────────────────────────────
    if "minimize_to_tray" in body:
        update["minimize_to_tray"] = bool(body["minimize_to_tray"])
    if "telegram_enabled" in body:
        update["telegram_enabled"] = bool(body["telegram_enabled"])
    if "auto_sync_enabled" in body:
        update["auto_sync_enabled"] = bool(body["auto_sync_enabled"])
    # Theme — accepted as opaque string; client-side validates against the
    # THEMES catalogue so unknown ids never reach here. Whitelist anyway as
    # belt-and-braces against rogue clients.
    if "theme" in body:
        theme_val = str(body["theme"])
        if theme_val in {"dark", "light", "ink_copper", "parchment",
                         "midnight_press", "forest", "velvet", "high_contrast"}:
            update["theme"] = theme_val
    # Mobile UX override. `auto` (default) follows viewport via matchMedia;
    # `on` forces the mobile layout on every screen size; `off` suppresses
    # the new mobile-mode-only enhancements (existing media queries still
    # fire on small viewports). Whitelisted to a known set.
    if "mobile_mode" in body:
        mm_val = str(body["mobile_mode"])
        if mm_val in {"auto", "on", "off"}:
            update["mobile_mode"] = mm_val

    # ── Per-platform notification master toggles ───────────────
    # Each platform poller checks its own *_notifications_enabled flag
    # before sending Windows toasts or Telegram alerts.
    for key in (
        "notifications_enabled",         # IB
        "fa_notifications_enabled",
        "ws_notifications_enabled",
        "sf_notifications_enabled",
        "sqw_notifications_enabled",
        "ao3_notifications_enabled",
        "da_notifications_enabled",
        "wp_notifications_enabled",
        "ik_notifications_enabled",
        "bsky_notifications_enabled",
        "tw_notifications_enabled",
    ):
        if key in body:
            update[key] = bool(body[key])

    # ── Watcher / follower notification toggles ────────────────
    # Separate from the master toggle so users can get submission alerts
    # without watcher alerts (or vice versa).
    if "watcher_notifications_enabled" in body:
        update["watcher_notifications_enabled"] = bool(body["watcher_notifications_enabled"])
    if "fa_watcher_notifications_enabled" in body:
        update["fa_watcher_notifications_enabled"] = bool(body["fa_watcher_notifications_enabled"])

    # ── Notification filter preferences ────────────────────────
    # When enabled, suppress fave/activity notifications and only alert
    # on new comments.  Each platform's poller applies its own filter.
    for key in (
        "notification_comments_only",     # IB
        "fa_notification_comments_only",
        "ws_notification_comments_only",
        "sf_notification_comments_only",
    ):
        if key in body:
            update[key] = bool(body[key])

    # Minimum delta thresholds: fave notifications are suppressed unless
    # the new-fave count in a cycle meets or exceeds this value.
    if "notification_min_views_delta" in body:
        update["notification_min_views_delta"] = max(0, int(body["notification_min_views_delta"]))
    if "notification_min_faves_delta" in body:
        update["notification_min_faves_delta"] = max(0, int(body["notification_min_faves_delta"]))

    # ── Per-platform poll intervals ────────────────────────────
    # The allowed set {15, 30, 60, 120, 240} minutes is chosen to balance
    # data freshness against API rate limits. Values outside this set are
    # silently rejected to prevent misconfiguration.
    _ALLOWED_INTERVALS = (15, 30, 60, 120, 240)
    for key in (
        "poll_interval_minutes",          # IB
        "fa_poll_interval_minutes",
        "ws_poll_interval_minutes",
        "sf_poll_interval_minutes",
        "sqw_poll_interval_minutes",
        "ao3_poll_interval_minutes",
        "da_poll_interval_minutes",
        "wp_poll_interval_minutes",
        "ik_poll_interval_minutes",
        "bsky_poll_interval_minutes",
        "tw_poll_interval_minutes",
    ):
        if key in body:
            val = int(body[key])
            if val in _ALLOWED_INTERVALS:
                update[key] = val

    # ── Timezone ───────────────────────────────────────────────
    if "display_timezone" in body:
        update["display_timezone"] = str(body["display_timezone"])

    # ── Milestone threshold arrays ─────────────────────────────
    # Validate as sorted positive integer lists
    for ms_key in ("milestone_views", "milestone_faves", "milestone_comments"):
        if ms_key in body:
            try:
                vals = sorted(int(v) for v in body[ms_key] if int(v) > 0)
                if vals:
                    update[ms_key] = vals
            except (TypeError, ValueError):
                pass

    # ── Windows startup registry ───────────────────────────────
    # Handled separately because it modifies the system registry
    # (Windows) or launch agents (macOS) rather than settings.json
    if "run_on_startup" in body:
        enabled = bool(body["run_on_startup"])
        config.set_run_on_startup(enabled)
    if update:
        config.save_settings(update)
    return {"status": "success", "message": "Preferences saved"}


# ── Settings: Telegram ────────────────────────────────────────
# Telegram setup flow:
#   1. User creates a bot via @BotFather and gets a bot token
#   2. User sends /start to their bot on Telegram
#   3. Frontend POSTs the bot token to /settings/telegram
#   4. Backend calls Telegram's getUpdates API to find the chat_id
#      from the /start message the user sent
#   5. Both bot_token and chat_id are saved to settings.json
#   6. Notifications can now be sent via the bot to that chat
#
# The token is never fully exposed via GET -- only a boolean "token_set" flag.

@router.get("/settings/telegram")
def get_telegram():
    """Return Telegram connection status (never expose the full token).

    Returns boolean flags so the frontend can show connection state without
    leaking sensitive credentials. The full bot token is never sent to the client.
    """
    settings = config.get_settings()
    token = settings.get("telegram_bot_token", "")
    chat_id = settings.get("telegram_chat_id", "")
    return {
        "token_set": bool(token),
        "chat_id_set": bool(chat_id),
        "enabled": settings.get("telegram_enabled", False),
        "connected": bool(token and chat_id),
    }


@router.post("/settings/telegram")
async def connect_telegram(body: dict):
    """Accept bot token, call getUpdates to auto-discover the chat_id, save both.

    The setup flow works by leveraging Telegram's getUpdates endpoint:
      1. Validate the bot token by calling the Telegram API
      2. If the token is invalid, Telegram returns ok=false and we reject it
      3. Iterate through recent updates (messages) looking for any chat object
         -- this finds the /start message the user sent to the bot
      4. Extract the chat_id from that message
      5. If no messages found, the user hasn't sent /start yet -- return a
         helpful error message telling them to do so
      6. Save token + chat_id + enabled flag to settings.json
    """
    bot_token = body.get("bot_token", "").strip()
    if not bot_token:
        raise HTTPException(400, "Bot token is required")

    # Call Telegram's getUpdates to validate the token and find the chat_id
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://api.telegram.org/bot{bot_token}/getUpdates")
            data = resp.json()
    except Exception as e:
        raise HTTPException(502, f"Failed to contact Telegram API: {e}")

    if not data.get("ok"):
        raise HTTPException(400, "Invalid bot token — Telegram rejected it")

    # Search through recent updates for any message containing a chat object.
    # This finds the /start message (or any message) the user sent to the bot,
    # which gives us the chat_id needed to send notifications back to them.
    # We also check my_chat_member events which are generated when the user
    # first interacts with the bot.
    chat_id = None
    for result in data.get("result", []):
        msg = result.get("message") or result.get("my_chat_member", {})
        chat = msg.get("chat") if isinstance(msg, dict) else None
        if chat and chat.get("id"):
            chat_id = str(chat["id"])
            break

    if not chat_id:
        raise HTTPException(
            404,
            "No messages found. Please send /start to your bot on Telegram first, then try again.",
        )

    # Persist all Telegram config and enable notifications
    config.save_settings({
        "telegram_bot_token": bot_token,
        "telegram_chat_id": chat_id,
        "telegram_enabled": True,
    })

    return {"status": "success", "message": f"Connected — chat ID {chat_id}"}


@router.post("/settings/telegram/test")
async def test_telegram():
    """Send a test message via the configured Telegram bot.

    Verifies end-to-end connectivity: reads saved token/chat_id from settings,
    sends a formatted HTML message through the Telegram Bot API, and reports
    success or failure back to the frontend.
    """
    settings = config.get_settings()
    token = settings.get("telegram_bot_token")
    chat_id = settings.get("telegram_chat_id")
    if not token or not chat_id:
        raise HTTPException(400, "Telegram is not connected")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": "✅ <b>PawPoller</b>\nTest notification — Telegram is working!", "parse_mode": "HTML"},
            )
            data = resp.json()
    except Exception as e:
        raise HTTPException(502, f"Failed to send message: {e}")

    if not data.get("ok"):
        desc = data.get("description", "Unknown error")
        raise HTTPException(502, f"Telegram error: {desc}")

    return {"status": "success", "message": "Test message sent"}


@router.post("/settings/telegram/disconnect")
def disconnect_telegram():
    """Clear Telegram token and chat_id from settings, disable notifications."""
    config.delete_settings_keys(["telegram_bot_token", "telegram_chat_id"])
    config.save_settings({"telegram_enabled": False})
    return {"status": "success", "message": "Telegram disconnected"}


@router.get("/settings/telegram/features")
def get_telegram_features():
    """Return Telegram notification feature toggles."""
    settings = config.get_settings()
    return {
        "poll_summaries": settings.get("telegram_poll_summaries", True),
        "error_alerts": settings.get("telegram_error_alerts", True),
        "milestones": settings.get("telegram_milestones", True),
        "digest": settings.get("telegram_digest", True),
        "digest_interval_hours": settings.get("telegram_digest_interval_hours", 6),
    }


@router.post("/settings/telegram/features")
def set_telegram_features(body: dict):
    """Update Telegram notification feature toggles."""
    update = {}
    for key in ("telegram_poll_summaries", "telegram_error_alerts",
                "telegram_milestones", "telegram_digest"):
        short = key.replace("telegram_", "")
        if short in body:
            update[key] = bool(body[short])
    if "digest_interval_hours" in body:
        val = int(body["digest_interval_hours"])
        update["telegram_digest_interval_hours"] = max(1, min(val, 168))
    if update:
        config.save_settings(update)
    return {"status": "success"}


@router.post("/settings/telegram/digest")
async def send_digest_now():
    """Manually trigger a 6-hourly digest report."""
    from polling.telegram import send_digest_report
    try:
        await send_digest_report()
        return {"status": "success", "message": "Digest sent"}
    except Exception as e:
        raise HTTPException(500, f"Failed to send digest: {e}")


# ── CSV Export ────────────────────────────────────────────────
# CSV export uses the DictWriter -> StreamingResponse pattern:
#   1. Query returns a list of dicts (rows from the database)
#   2. DictWriter writes header + rows into a StringIO buffer
#   3. The buffer content is wrapped in a StreamingResponse with
#      Content-Disposition header for browser download
#   4. If no rows exist, a simple "No data" text response is returned
#
# This avoids loading the entire CSV into memory as a string before
# sending, though for practical dataset sizes it would not matter.

def _sanitize_csv_value(val):
    """Prevent CSV formula injection (OWASP recommendation).

    Excel/LibreOffice treat cells starting with =, +, -, @, \\t, \\r as
    formulas.  A malicious submission title like '=CMD("calc")' would
    execute when the exported CSV is opened.  Prefixing with a single
    quote neutralises the formula while remaining human-readable.
    """
    if isinstance(val, str) and val and val[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + val
    return val


def _csv_response(rows: list[dict], filename: str) -> StreamingResponse:
    """Generate a CSV StreamingResponse from a list of dicts.

    Uses csv.DictWriter to auto-generate the header row from dict keys,
    then writes all rows.  String values are sanitised against CSV formula
    injection before writing.  The result is wrapped in a StreamingResponse
    with a Content-Disposition attachment header so browsers trigger a download.
    """
    if not rows:
        return StreamingResponse(iter(["No data"]), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows({k: _sanitize_csv_value(v) for k, v in r.items()} for r in rows)
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export/submissions")
def export_ib_submissions():
    """Export all Inkbunny submissions as a CSV file download."""
    conn = get_connection()
    try:
        subs = queries.get_all_submissions(conn)
        return _csv_response(subs, "inkbunny_submissions.csv")
    finally:
        conn.close()


@router.get("/export/snapshots")
def export_ib_snapshots(id: Optional[int] = Query(None)):
    """Export snapshots as CSV. If an ID is provided, export only that submission's
    snapshots; otherwise export all snapshots across all submissions."""
    conn = get_connection()
    try:
        if id:
            snaps = queries.get_snapshots(conn, id)
        else:
            snaps = [dict(r) for r in conn.execute("SELECT * FROM snapshots ORDER BY polled_at ASC").fetchall()]
        return _csv_response(snaps, f"inkbunny_snapshots{'_' + str(id) if id else ''}.csv")
    finally:
        conn.close()


# ── Groups ───────────────────────────────────────────────────
# Groups allow users to organise submissions into named collections
# for aggregate tracking. Each group can contain members from any
# platform (IB, FA, WS). Standard CRUD operations are provided:
#   - GET    /groups              : list all groups
#   - POST   /groups              : create a new group
#   - PUT    /groups/{id}         : update group name/description
#   - DELETE /groups/{id}         : delete a group and its memberships
#   - POST   /groups/{id}/members : add a submission to a group
#   - DELETE /groups/{id}/members : remove a submission from a group
#   - GET    /groups/{id}/stats   : aggregate stats for all group members

@router.get("/groups")
def list_groups():
    """List all groups with their metadata."""
    conn = get_connection()
    try:
        return {"groups": group_queries.get_all_groups(conn)}
    finally:
        conn.close()


@router.post("/groups")
def create_group(body: dict):
    """Create a new group with a name and optional description."""
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Group name is required")
    conn = get_connection()
    try:
        group_id = group_queries.create_group(conn, name, body.get("description", ""))
        return {"status": "success", "group_id": group_id}
    finally:
        conn.close()


@router.put("/groups/{group_id}")
def update_group(group_id: int, body: dict):
    """Update a group's name and/or description."""
    conn = get_connection()
    try:
        group_queries.update_group(conn, group_id, body.get("name"), body.get("description"))
        return {"status": "success"}
    finally:
        conn.close()


@router.delete("/groups/{group_id}")
def delete_group(group_id: int):
    """Delete a group and all its membership records."""
    conn = get_connection()
    try:
        group_queries.delete_group(conn, group_id)
        return {"status": "success"}
    finally:
        conn.close()


@router.post("/groups/{group_id}/members")
def add_group_member(group_id: int, body: dict):
    """Add a submission to a group. Requires platform (ib/fa/ws) and submission_id.

    Members are identified by the combination of platform + submission_id,
    since submission IDs are only unique within each platform.
    """
    platform = body.get("platform", "")
    submission_id = body.get("submission_id")
    if not platform or not submission_id:
        raise HTTPException(400, "platform and submission_id are required")
    conn = get_connection()
    try:
        added = group_queries.add_group_member(conn, group_id, platform, int(submission_id))
        return {"status": "success", "added": added}
    finally:
        conn.close()


@router.delete("/groups/{group_id}/members")
def remove_group_member(group_id: int, platform: str = Query(...), submission_id: int = Query(...)):
    """Remove a submission from a group by platform + submission_id."""
    conn = get_connection()
    try:
        group_queries.remove_group_member(conn, group_id, platform, submission_id)
        return {"status": "success"}
    finally:
        conn.close()


@router.get("/groups/{group_id}/stats")
def get_group_stats(group_id: int):
    """Get aggregate statistics for all submissions in a group.

    Returns combined views/faves/comments totals and per-member breakdowns
    across all platforms represented in the group.
    """
    conn = get_connection()
    try:
        return group_queries.get_group_stats(conn, group_id)
    finally:
        conn.close()


# ── Analytics ────────────────────────────────────────────────
# Analytics endpoints provide cross-submission insights:
#   - top-fans: users who have faved the most submissions (loyal followers)
#   - trending: submissions with above-average growth in a recent time window,
#     identified by a multiplier threshold against the baseline growth rate

@router.get("/analytics/top-fans")
def get_top_fans(limit: int = Query(20, ge=1, le=100)):
    """Get the top fans -- users who have faved the most submissions.

    Aggregates faving_users across all submissions to find the most engaged
    followers. Limited to a configurable count (default 20, max 100).
    """
    conn = get_connection()
    try:
        return {"fans": analytics_queries.get_top_fans(conn, limit)}
    finally:
        conn.close()


@router.get("/analytics/trending")
def get_trending(hours: int = Query(24, ge=1), threshold: float = Query(2.0, ge=0.5)):
    """Get trending submissions -- those with above-average growth recently.

    Parameters:
      - hours: lookback window (e.g., 24 = last 24 hours)
      - threshold: multiplier above average growth to qualify as "trending"
        (e.g., 2.0 means a submission must be growing at 2x the average rate)
    """
    conn = get_connection()
    try:
        return {"trending": analytics_queries.get_trending_submissions(conn, hours, threshold)}
    finally:
        conn.close()


# ── Cross-Platform Links ────────────────────────────────────
# Links connect the same artwork/story posted across multiple platforms
# (e.g., the same piece on IB, FA, and WS). This enables combined stats
# views and comparison charts across platforms for the same content.
#   - GET    /links              : list all links with their members
#   - POST   /links              : create a link (requires >= 2 members)
#   - DELETE /links/{id}         : delete a link
#   - GET    /links/{id}/stats   : combined stats across all linked submissions
#   - GET    /links/{id}/snapshots : combined time-series for charting
#   - GET    /links/suggestions  : auto-detected links based on title similarity

@router.get("/links")
def list_links():
    """List all cross-platform links with their member submissions."""
    conn = get_connection()
    try:
        return {"links": analytics_queries.get_links(conn)}
    finally:
        conn.close()


@router.post("/links")
def create_link(body: dict):
    """Create a cross-platform link between 2+ submissions.

    Each member is a {platform, submission_id} pair. At least 2 members
    are required (linking a single submission to itself is meaningless).
    """
    members = body.get("members", [])
    if len(members) < 2:
        raise HTTPException(400, "At least 2 members required")
    conn = get_connection()
    try:
        link_id = analytics_queries.create_link(conn, members)
        return {"status": "success", "link_id": link_id}
    finally:
        conn.close()


@router.delete("/links/{link_id}")
def delete_link(link_id: int):
    """Delete a cross-platform link and its membership records."""
    conn = get_connection()
    try:
        analytics_queries.delete_link(conn, link_id)
        return {"status": "success"}
    finally:
        conn.close()


@router.get("/links/{link_id}/stats")
def get_link_stats(link_id: int):
    """Get combined statistics across all submissions in a link.

    Aggregates views/faves/comments from all linked submissions to show
    the total reach of a piece of content across platforms.
    """
    conn = get_connection()
    try:
        return analytics_queries.get_link_combined_stats(conn, link_id)
    finally:
        conn.close()


@router.get("/links/{link_id}/snapshots")
def get_link_snapshots(link_id: int):
    """Get combined time-series snapshots for all submissions in a link.

    Merges snapshot data from all linked submissions into a unified
    time-series for cross-platform growth charting.
    """
    conn = get_connection()
    try:
        return {"snapshots": analytics_queries.get_link_combined_snapshots(conn, link_id)}
    finally:
        conn.close()


@router.get("/links/suggestions")
def get_link_suggestions():
    """Auto-suggest potential cross-platform links based on title similarity.

    Scans submissions across IB, FA, and WS for matching or similar titles
    that likely represent the same content posted on multiple platforms.
    """
    conn = get_connection()
    try:
        return {"suggestions": analytics_queries.auto_suggest_links(conn)}
    finally:
        conn.close()


# ── Auto-Update ──────────────────────────────────────────────
# The auto-update system has two steps:
#   1. GET  /update/check : checks GitHub releases (or similar) for a newer
#      version. Returns version info and download_url if an update is available.
#   2. POST /update/apply : downloads the update zip from the provided URL,
#      extracts it over the current installation, and triggers a restart.
# This two-step approach lets the frontend show the user what version is
# available before they commit to applying the update.

@router.get("/update/check")
def check_update():
    """Check for available updates. Returns version info and download URL if newer."""
    return updater.check_for_update()


@router.post("/update/apply")
def apply_update(body: dict):
    """Download and apply an update from the given URL.

    Flow:
      1. Download the update zip from the provided download_url
      2. Extract and overwrite the current installation files
      3. Return success -- the server will restart to load the new version
    """
    download_url = body.get("download_url", "")
    if not download_url:
        raise HTTPException(400, "download_url is required")
    # Security: only allow downloads from the official GitHub repository
    parsed = urlparse(download_url)
    if not parsed.hostname or not (
        parsed.hostname == "github.com"
        or parsed.hostname.endswith(".github.com")
        or parsed.hostname == "api.github.com"
        or parsed.hostname.endswith(".githubusercontent.com")
    ):
        raise HTTPException(400, "Only GitHub URLs are allowed for updates")
    try:
        zip_path = updater.download_update(download_url)
        updater.apply_update(zip_path)
        return {"status": "success", "message": "Update applied — restarting..."}
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── Thumbnail Proxy ──────────────────────────────────────────
# Inkbunny's CDN (metapix.net) does not set CORS headers, so the browser
# blocks direct image loads from the frontend. This endpoint proxies
# thumbnail requests through the local server to bypass CORS restrictions.
#
# Security: a domain whitelist restricts proxying to metapix.net only,
# preventing this endpoint from being used as an open proxy to arbitrary URLs.
# Responses are cached for 24 hours (86400 seconds) to reduce repeat fetches.

@router.get("/thumb")
async def proxy_thumbnail(url: str = Query(..., description="Inkbunny thumbnail URL")):
    """Proxy Inkbunny thumbnails to avoid cross-origin blocking.

    Only allows URLs from the metapix.net domain (Inkbunny's CDN).
    This whitelist prevents abuse of this proxy endpoint for arbitrary URLs.
    Responses include a Cache-Control header for 24-hour browser caching.
    """
    parsed = urlparse(url)
    # Domain whitelist: only proxy requests to Inkbunny's CDN (metapix.net)
    if not parsed.hostname or not (
        parsed.hostname == "metapix.net" or parsed.hostname.endswith(".metapix.net")
    ):
        raise HTTPException(400, "Only Inkbunny CDN URLs allowed")
    try:
        resp = await _thumb_client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "image/jpeg")
        return Response(content=resp.content, media_type=content_type,
                        headers={"Cache-Control": "public, max-age=86400"})
    except Exception as e:
        logger.warning("Thumb proxy failed for %s: %s", url, e)
        raise HTTPException(502, detail="Failed to fetch thumbnail")


# ── Pinned Submissions ────────────────────────────────────────

@router.get("/pins")
def get_pins():
    """Return the list of pinned submissions with current stats."""
    settings = config.get_settings()
    pins = settings.get("pinned_submissions", [])
    result = []
    conn = get_connection()
    try:
        table_map = {"ib": "submissions", "fa": "fa_submissions", "ws": "ws_submissions", "sf": "sf_submissions", "sqw": "sqw_submissions", "ao3": "ao3_submissions", "da": "da_submissions", "wp": "wp_submissions", "ik": "ik_submissions", "bsky": "bsky_submissions", "tw": "tw_submissions"}
        for pin in pins:
            table = table_map.get(pin.get("platform"))
            if not table:
                continue
            try:
                row = conn.execute(
                    f"SELECT * FROM {table} WHERE submission_id = ?",
                    (pin["submission_id"],),
                ).fetchone()
            except Exception:
                continue
            if row:
                d = dict(row)
                d["platform"] = pin["platform"]
                result.append(d)
    finally:
        conn.close()
    return {"pins": result}


@router.post("/pins")
def add_pin(body: dict):
    """Pin a submission. Body: { platform, submission_id }. Max 10 pins."""
    platform = body.get("platform", "")
    sub_id = body.get("submission_id")
    if not platform or sub_id is None:
        raise HTTPException(400, "platform and submission_id required")
    settings = config.get_settings()
    pins = settings.get("pinned_submissions", [])
    if any(p["platform"] == platform and str(p["submission_id"]) == str(sub_id) for p in pins):
        return {"status": "already_pinned"}
    if len(pins) >= 10:
        raise HTTPException(400, "Maximum 10 pins allowed")
    pins.append({"platform": platform, "submission_id": sub_id})
    config.save_settings({"pinned_submissions": pins})
    return {"status": "pinned"}


@router.delete("/pins")
def remove_pin(platform: str = Query(...), submission_id: str = Query(...)):
    """Unpin a submission."""
    settings = config.get_settings()
    pins = settings.get("pinned_submissions", [])
    pins = [p for p in pins if not (p["platform"] == platform and str(p["submission_id"]) == str(submission_id))]
    config.save_settings({"pinned_submissions": pins})
    return {"status": "unpinned"}


# ── Goal Tracking ─────────────────────────────────────────────

@router.get("/goals")
def get_goals():
    """Return all goals with computed current values and progress."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM goals ORDER BY created_at DESC").fetchall()
        result = []
        table_map = {"ib": "submissions", "fa": "fa_submissions", "ws": "ws_submissions", "sf": "sf_submissions", "sqw": "sqw_submissions", "ao3": "ao3_submissions", "da": "da_submissions", "wp": "wp_submissions", "ik": "ik_submissions", "bsky": "bsky_submissions", "tw": "tw_submissions"}
        for row in rows:
            g = dict(row)
            metric = g["metric"]
            current = 0
            title = None
            # Validate metric against the shared whitelist before SQL interpolation
            if metric not in config.ALLOWED_GOAL_METRICS:
                g["current_value"] = 0
                g["submission_title"] = None
                g["progress_pct"] = 0
                result.append(g)
                continue
            if g["scope"] == "submission" and g["submission_id"]:
                table = table_map.get(g["platform"])
                if table:
                    try:
                        sub = conn.execute(
                            f"SELECT title, {metric} FROM {table} WHERE submission_id = ?",
                            (g["submission_id"],),
                        ).fetchone()
                        if sub:
                            title = sub["title"]
                            current = sub[metric] or 0
                    except Exception:
                        pass
            else:
                if g["platform"] == "all":
                    for tbl in table_map.values():
                        try:
                            r = conn.execute(f"SELECT COALESCE(SUM({metric}), 0) as total FROM {tbl}").fetchone()
                            current += r["total"]
                        except Exception:
                            pass
                else:
                    table = table_map.get(g["platform"])
                    if table:
                        try:
                            r = conn.execute(f"SELECT COALESCE(SUM({metric}), 0) as total FROM {table}").fetchone()
                            current = r["total"]
                        except Exception:
                            pass
            g["current_value"] = current
            g["submission_title"] = title
            g["progress_pct"] = min(100, round((current / g["target_value"]) * 100)) if g["target_value"] > 0 else 0
            result.append(g)
        return {"goals": result}
    finally:
        conn.close()


@router.post("/goals")
def create_goal(body: dict):
    """Create a new goal. Body: { platform, scope, submission_id?, metric, target_value }."""
    platform = body.get("platform", "ib")
    scope = body.get("scope", "account")
    sub_id = body.get("submission_id")
    metric = body.get("metric", "views")
    target = int(body.get("target_value", 0))
    if metric not in config.ALLOWED_GOAL_METRICS:
        raise HTTPException(400, "Invalid metric")
    if target <= 0:
        raise HTTPException(400, "Target must be positive")
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO goals (platform, scope, submission_id, metric, target_value) VALUES (?, ?, ?, ?, ?)",
            (platform, scope, sub_id, metric, target),
        )
        conn.commit()
        return {"status": "created"}
    finally:
        conn.close()


@router.delete("/goals/{goal_id}")
def delete_goal(goal_id: int):
    """Delete a goal."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM goals WHERE goal_id = ?", (goal_id,))
        conn.commit()
        return {"status": "deleted"}
    finally:
        conn.close()


def _get_submission_tags(conn, platform: str, submission_id) -> list:
    """Get tags assigned to a specific submission."""
    try:
        rows = conn.execute(
            "SELECT t.tag_id, t.name, t.color FROM tags t "
            "JOIN submission_tags st ON t.tag_id = st.tag_id "
            "WHERE st.platform = ? AND st.submission_id = ?",
            (platform, submission_id),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []

# ── Tags / Submission Categorisation ──────────────────────────

@router.get("/tags")
def get_tags():
    """Return all tags with submission counts."""
    conn = get_connection()
    try:
        tags = conn.execute("SELECT * FROM tags ORDER BY name").fetchall()
        result = []
        for t in tags:
            d = dict(t)
            count = conn.execute("SELECT COUNT(*) as c FROM submission_tags WHERE tag_id = ?", (t["tag_id"],)).fetchone()
            d["submission_count"] = count["c"]
            result.append(d)
        return {"tags": result}
    finally:
        conn.close()


@router.post("/tags")
def create_tag(body: dict):
    """Create a tag. Body: { name, color? }."""
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Tag name required")
    color = body.get("color", "#6c8cff")
    conn = get_connection()
    try:
        cursor = conn.execute("INSERT INTO tags (name, color) VALUES (?, ?)", (name, color))
        conn.commit()
        return {"status": "created", "tag_id": cursor.lastrowid}
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Tag already exists")
    finally:
        conn.close()


@router.delete("/tags/{tag_id}")
def delete_tag(tag_id: int):
    """Delete a tag and all its associations."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM tags WHERE tag_id = ?", (tag_id,))
        conn.commit()
        return {"status": "deleted"}
    finally:
        conn.close()


@router.post("/tags/{tag_id}/submissions")
def add_tag_to_submission(tag_id: int, body: dict):
    """Assign a tag to a submission. Body: { platform, submission_id }."""
    platform = body.get("platform")
    sub_id = body.get("submission_id")
    if not platform or sub_id is None:
        raise HTTPException(400, "platform and submission_id required")
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO submission_tags (tag_id, platform, submission_id) VALUES (?, ?, ?)",
            (tag_id, platform, sub_id),
        )
        conn.commit()
        return {"status": "tagged"}
    finally:
        conn.close()


@router.delete("/tags/{tag_id}/submissions")
def remove_tag_from_submission(tag_id: int, platform: str = Query(...), submission_id: str = Query(...)):
    """Remove a tag from a submission."""
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM submission_tags WHERE tag_id = ? AND platform = ? AND submission_id = ?",
            (tag_id, platform, submission_id),
        )
        conn.commit()
        return {"status": "untagged"}
    finally:
        conn.close()


@router.get("/tags/{tag_id}/stats")
def get_tag_stats(tag_id: int):
    """Aggregate stats for all submissions with a given tag."""
    conn = get_connection()
    try:
        members = conn.execute("SELECT platform, submission_id FROM submission_tags WHERE tag_id = ?", (tag_id,)).fetchall()
        table_map = {"ib": "submissions", "fa": "fa_submissions", "ws": "ws_submissions", "sf": "sf_submissions", "sqw": "sqw_submissions", "ao3": "ao3_submissions", "da": "da_submissions", "wp": "wp_submissions", "ik": "ik_submissions", "bsky": "bsky_submissions", "tw": "tw_submissions"}
        # Platform-specific column mappings for stats aggregation
        _metrics = {
            "ib": ("views", "favorites_count", "comments_count"),
            "fa": ("views", "favorites_count", "comments_count"),
            "ws": ("views", "favorites_count", "comments_count"),
            "sf": ("views", "favorites_count", "comments_count"),
            "sqw": ("views", "favorites_count", "comments_count"),
            "ao3": ("views", "favorites_count", "comments_count"),
            "da": ("views", "favorites_count", "comments_count"),
            "wp": ("reads", "votes", "comments_count"),
            "ik": (None, "likes", "comments_count"),
            "bsky": (None, "likes", "replies"),
            "tw": ("views", "likes", "replies"),
        }
        total_views = total_faves = total_comments = 0
        subs = []
        for m in members:
            plat = m["platform"]
            table = table_map.get(plat)
            if not table:
                continue
            try:
                row = conn.execute(
                    f"SELECT * FROM {table} WHERE submission_id = ?",
                    (m["submission_id"],),
                ).fetchone()
            except Exception:
                continue
            if row:
                d = dict(row)
                d["platform"] = plat
                v_col, f_col, c_col = _metrics.get(plat, ("views", "favorites_count", "comments_count"))
                total_views += d.get(v_col, 0) or 0 if v_col else 0
                total_faves += d.get(f_col, 0) or 0 if f_col else 0
                total_comments += d.get(c_col, 0) or 0 if c_col else 0
                subs.append(d)
        return {"total_views": total_views, "total_favorites": total_faves, "total_comments": total_comments, "submissions": subs}
    finally:
        conn.close()


# ── Backup & Restore ──────────────────────────────────────────

@router.get("/backup/database")
def download_backup():
    """Download a consistent backup of the SQLite database."""
    conn = get_connection()
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    db_bytes = config.DB_PATH.read_bytes()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=db_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="pawpoller_backup_{ts}.db"'},
    )


@router.post("/backup/restore")
async def restore_backup(file: UploadFile = File(...)):
    """Restore the database from an uploaded .db file."""
    content = await file.read()
    if len(content) < 100:
        raise HTTPException(400, "File too small to be a valid database")
    # Validate it's a SQLite file (magic bytes)
    if content[:16] != b"SQLite format 3\x00":
        raise HTTPException(400, "Not a valid SQLite database file")
    # Write to a temp file and validate expected tables exist
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        test_conn = sqlite3.connect(tmp_path)
        tables = {r[0] for r in test_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        test_conn.close()
        if "submissions" not in tables:
            raise HTTPException(400, "Database does not contain expected PawPoller tables")
        # Checkpoint current DB and replace
        conn = get_connection()
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
        shutil.copy2(tmp_path, str(config.DB_PATH))
        # Remove stale WAL/SHM files from the old database to prevent
        # SQLite from replaying them against the restored database.
        wal_path = Path(str(config.DB_PATH) + "-wal")
        shm_path = Path(str(config.DB_PATH) + "-shm")
        if wal_path.exists():
            wal_path.unlink()
        if shm_path.exists():
            shm_path.unlink()
        init_db()
        return {"status": "restored", "tables_found": len(tables)}
    finally:
        try:
            import os
            os.unlink(tmp_path)
        except OSError:
            pass


# ── Application Logs ─────────────────────────────────────────

@router.get("/logs")
def get_logs(lines: int = Query(200, ge=10, le=2000), file: str = Query("server")):
    """Return the last N lines of a log file.

    Reads from LOGS_DIR/{file}.log.  Only whitelisted filenames are allowed
    to prevent path traversal.  Returns newest lines last (natural log order).
    """
    allowed = {"server", "app", "polling"}
    if file not in allowed:
        raise HTTPException(400, f"Invalid log file. Allowed: {', '.join(sorted(allowed))}")
    log_path = config.LOGS_DIR / f"{file}.log"
    if not log_path.exists():
        return {"lines": [], "file": file, "total_lines": 0}
    try:
        # Read the file and return the tail
        all_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
        return {"lines": tail, "file": file, "total_lines": len(all_lines)}
    except OSError as e:
        raise HTTPException(500, f"Failed to read log file: {e}")


# ── Historical Analytics ──────────────────────────────────────

@router.get("/analytics/historical")
def get_historical_analytics(weeks: int = Query(12)):
    """Return historical analytics: best periods, fastest growing, weekly growth."""
    conn = get_connection()
    try:
        weeks = min(52, max(1, weeks))
        result = {
            "best_month": None,
            "fastest_growing": None,
            "weekly_growth": [],
            "milestone_history": [],
        }

        # Best month: find the month with the highest total views gained
        # Each tuple: (platform_key, snap_table, sub_table, views_col, faves_col, comments_col)
        # views_col is None for platforms without a views column (e.g. Itaku)
        table_pairs = [
            ("ib",  "snapshots",       "submissions",       "views", "favorites_count", "comments_count"),
            ("fa",  "fa_snapshots",    "fa_submissions",    "views", "favorites_count", "comments_count"),
            ("ws",  "ws_snapshots",    "ws_submissions",    "views", "favorites_count", "comments_count"),
            ("sf",  "sf_snapshots",    "sf_submissions",    "views", "favorites_count", "comments_count"),
            ("sqw", "sqw_snapshots",   "sqw_submissions",   "views", "favorites_count", "comments_count"),
            ("ao3", "ao3_snapshots",   "ao3_submissions",   "views", "favorites_count", "comments_count"),
            ("da",  "da_snapshots",    "da_submissions",    "views", "favorites_count", "comments_count"),
            ("wp",  "wp_snapshots",    "wp_submissions",    "reads", "votes",           "comments_count"),
            ("ik",  "ik_snapshots",    "ik_submissions",    None,    "likes",           "comments_count"),
        ]

        month_data = {}
        for plat, snap_t, _, v_col, f_col, c_col in table_pairs:
            try:
                # Build column expressions, using 0 for missing columns
                v_expr = f"MAX({v_col}) - MIN({v_col})" if v_col else "0"
                f_expr = f"MAX({f_col}) - MIN({f_col})" if f_col else "0"
                c_expr = f"MAX({c_col}) - MIN({c_col})" if c_col else "0"
                rows = conn.execute(f"""
                    SELECT strftime('%Y-%m', polled_at) as month,
                           {v_expr} as views_delta,
                           {f_expr} as faves_delta,
                           {c_expr} as comments_delta
                    FROM {snap_t}
                    GROUP BY month, submission_id
                """).fetchall()
                for r in rows:
                    m = r["month"]
                    if m not in month_data:
                        month_data[m] = {"month": m, "views": 0, "faves": 0, "comments": 0}
                    month_data[m]["views"] += r["views_delta"] or 0
                    month_data[m]["faves"] += r["faves_delta"] or 0
                    month_data[m]["comments"] += r["comments_delta"] or 0
            except Exception:
                pass

        if month_data:
            months_list = list(month_data.values())
            best_views = max(months_list, key=lambda x: x["views"])
            best_faves = max(months_list, key=lambda x: x["faves"])
            best_comments = max(months_list, key=lambda x: x["comments"])
            result["best_month"] = {
                "views": {"period": best_views["month"], "delta": best_views["views"]},
                "faves": {"period": best_faves["month"], "delta": best_faves["faves"]},
                "comments": {"period": best_comments["month"], "delta": best_comments["comments"]},
            }

        # Fastest growing all-time: top submissions by views gained across platforms
        fastest = []
        for plat, snap_t, sub_t, v_col, f_col, _ in table_pairs:
            if not v_col:
                # Skip platforms without a views column for "fastest growing by views"
                continue
            try:
                rows = conn.execute(f"""
                    SELECT s.submission_id, s.title, s.{v_col} as current_views,
                           s.{f_col} as current_faves,
                           MAX(sn.{v_col}) - MIN(sn.{v_col}) as views_gained,
                           JULIANDAY('now') - JULIANDAY(MIN(sn.polled_at)) as days_tracked
                    FROM {sub_t} s
                    JOIN {snap_t} sn ON s.submission_id = sn.submission_id
                    GROUP BY s.submission_id
                    HAVING views_gained > 0
                    ORDER BY views_gained DESC
                    LIMIT 5
                """).fetchall()
                for row in rows:
                    days = max(1, row["days_tracked"] or 1)
                    fastest.append({
                        "platform": plat.upper(),
                        "title": row["title"],
                        "views": row["current_views"],
                        "faves": row["current_faves"],
                        "views_per_day": (row["views_gained"] or 0) / days,
                    })
            except Exception:
                pass
        fastest.sort(key=lambda x: x["views_per_day"], reverse=True)
        result["fastest_growing"] = fastest[:10]

        # Weekly growth report
        weekly = {}
        for plat, snap_t, _, v_col, f_col, c_col in table_pairs:
            try:
                v_expr = f"MAX({v_col}) - MIN({v_col})" if v_col else "0"
                f_expr = f"MAX({f_col}) - MIN({f_col})" if f_col else "0"
                c_expr = f"MAX({c_col}) - MIN({c_col})" if c_col else "0"
                rows = conn.execute(f"""
                    SELECT strftime('%Y-W%W', polled_at) as week_label,
                           {v_expr} as views_delta,
                           {f_expr} as faves_delta,
                           {c_expr} as comments_delta
                    FROM {snap_t}
                    WHERE polled_at >= datetime('now', ? || ' days')
                    GROUP BY week_label, submission_id
                """, (str(-(weeks * 7)),)).fetchall()
                for r in rows:
                    w = r["week_label"]
                    if w not in weekly:
                        weekly[w] = {"week_label": w, "views_delta": 0, "faves_delta": 0, "comments_delta": 0}
                    weekly[w]["views_delta"] += r["views_delta"] or 0
                    weekly[w]["faves_delta"] += r["faves_delta"] or 0
                    weekly[w]["comments_delta"] += r["comments_delta"] or 0
            except Exception:
                pass
        result["weekly_growth"] = sorted(weekly.values(), key=lambda x: x["week_label"])

        return result
    finally:
        conn.close()
