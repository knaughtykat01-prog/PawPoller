"""FurAffinity (FA) poll cycle orchestration.

Mirrors the Inkbunny poller pattern (see polling/poller.py) with two key
differences driven by FA's data-access constraints:

  1. **No faving-user tracking** -- FurAffinity does not expose per-submission
     fave lists through FAExport or its public pages, so the FA poller has
     no step 5 equivalent.  The ``stats`` dict omits ``new_faves_found``
     entirely.

  2. **Comment fetching via FAExport API** -- Instead of scraping raw HTML
     (as the IB poller does), comments are retrieved through the FAExport
     JSON endpoint.  This is more reliable but still rate-limited, so the
     same delta-based "only fetch when count changes" optimisation applies.

The rest of the structure (progress dict, concurrency guard, six-step
cycle, notification dispatch) is intentionally identical to the IB poller
so that the frontend can treat all platform pollers uniformly.
"""

from __future__ import annotations
import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from html import escape as _esc

import httpx

import config
from fa_client.client import FAClient
from database.db import get_connection
from database import fa_queries

logger = logging.getLogger(__name__)

# ── Progress tracking ────────────────────────────────────────
# Shared mutable dict read by /api/fa/poll/progress -- same pattern as
# the IB poller's poll_progress.  Prefixed with ``fa_`` so the two dicts
# can coexist at module level without collision.
fa_poll_progress = {
    "active": False,
    "phase": "idle",
    "current": 0,
    "total": 0,
    "message": "",
}

# Concurrency guard -- same purpose as _poll_running in the IB poller.
# Prevents overlapping FA poll cycles.  The Lock protects the
# check-and-set from race conditions; the boolean remains as a
# readable status indicator.
_fa_poll_running = False
_fa_poll_lock = threading.Lock()

# First-poll suppression: silent baseline on first poll after startup.
_fa_first_poll = True

# ── Watcher spam filter ──────────────────────────────────────
# FA attracts waves of bot/spam watchers with obvious patterns.
# This filter suppresses notifications (not DB storage) for them.
import re

# Why the spam keyword filter exists:
# FA has a persistent problem with bot accounts whose usernames contain
# gambling, adult-service, or crypto keywords.  These watchers are stored in
# the DB for completeness (accurate watcher counts), but notifications are
# suppressed to avoid alert fatigue from obvious spam.
_SPAM_KEYWORDS = re.compile(
    r"(1xbet|promo|casino|betting|slot|poker|viagra|cialis|crypto|forex|"
    r"onlyfans|escort|dating|hookup|webcam|livecam|sexchat|porno)",
    re.IGNORECASE,
)
# Alphanumeric soup: mostly digits with a few letters, or long gibberish
# e.g. "2charlottec262ye0", "123gaa", "a8k3m2x9p1"
_ALPHANUM_SOUP = re.compile(r"^(?=.*\d)[a-z0-9]{8,}$", re.IGNORECASE)

# Bulk threshold: if more than this many new watchers in one cycle,
# it's almost certainly a spam wave — summarise instead of listing names.
_SPAM_WAVE_THRESHOLD = 20


def _is_spam_watcher(username: str) -> bool:
    """Heuristic check for bot/spam watcher usernames."""
    if _SPAM_KEYWORDS.search(username):
        return True
    # Alternating letters+digits pattern (e.g. "a8k3m2x9p1")
    if _ALPHANUM_SOUP.match(username):
        digit_ratio = sum(c.isdigit() for c in username) / len(username)
        if digit_ratio >= 0.4:
            return True
    return False


def _update_fa_progress(phase: str, current: int = 0, total: int = 0, message: str = ""):
    """Mutate the shared fa_poll_progress dict so the frontend can display
    real-time status.  Mirrors _update_progress() in the IB poller."""
    fa_poll_progress["active"] = phase not in ("idle", "complete", "error")
    fa_poll_progress["phase"] = phase
    fa_poll_progress["current"] = current
    fa_poll_progress["total"] = total
    fa_poll_progress["message"] = message


def _send_fa_notifications(new_comment_details: list[dict],
                           new_watcher_names: list[str] | None = None) -> None:
    """Send Windows toast notifications for new FA comments and watchers.

    Unlike the IB poller, this does not handle faves -- there is no fave
    notification because FA does not expose per-submission fave lists.
    The toast is prefixed with "FA:" so users can distinguish it from
    IB notifications at a glance.  Truncated to 3 items like the IB version.
    """
    if new_watcher_names is None:
        new_watcher_names = []

    settings = config.get_settings()
    if not settings.get("fa_notifications_enabled", True):
        return
    if not new_comment_details and not new_watcher_names:
        return

    try:
        from winotify import Notification
    except ImportError:
        logger.debug("winotify not installed — skipping FA notifications")
        return

    # --- Comment toast (truncated to 3 items) ---
    if new_comment_details:
        shown = new_comment_details[:3]
        lines = [f"{d['username']} commented on {d['title']}" for d in shown]
        if len(new_comment_details) > 3:
            lines.append(f"...and {len(new_comment_details) - 3} more")
        toast = Notification(
            app_id="PawPoller",
            title=f"FA: {len(new_comment_details)} New Comment{'s' if len(new_comment_details) != 1 else ''}",
            msg="\n".join(lines),
        )
        toast.show()

    # --- Watcher toast (pre-filtered confirmed watchers) ---
    if new_watcher_names and settings.get("fa_watcher_notifications_enabled", True):
        shown = new_watcher_names[:3]
        lines = [f"{name} started watching you" for name in shown]
        if len(new_watcher_names) > 3:
            lines.append(f"...and {len(new_watcher_names) - 3} more")
        toast = Notification(
            app_id="PawPoller",
            title=f"FA: {len(new_watcher_names)} New Watcher{'s' if len(new_watcher_names) != 1 else ''}",
            msg="\n".join(lines),
        )
        toast.show()


async def _send_fa_telegram(new_comment_details: list[dict],
                            new_watcher_names: list[str] | None = None) -> None:
    """Send Telegram notification for new FA comments and watchers.

    Format differs from the IB Telegram message: no faves section, and
    the header uses a fox emoji to visually distinguish FA alerts from IB
    alerts in the chat.  Truncated to 5 items, same as IB.  Uses Telegram
    HTML parse_mode for bold formatting.
    """
    if new_watcher_names is None:
        new_watcher_names = []

    settings = config.get_settings()
    if not settings.get("telegram_enabled", False):
        return
    token = settings.get("telegram_bot_token")
    chat_id = settings.get("telegram_chat_id")
    if not token or not chat_id:
        return
    if not new_comment_details and not new_watcher_names:
        return

    lines = []
    # --- Comments section ---
    if new_comment_details:
        lines.append(f"<b>🦊 FA: {len(new_comment_details)} New Comment{'s' if len(new_comment_details) != 1 else ''}</b>")
        for d in new_comment_details[:5]:
            lines.append(f"  • <b>{_esc(d['username'])}</b> commented on {_esc(d['title'])}")
        if len(new_comment_details) > 5:
            lines.append(f"  ...and {len(new_comment_details) - 5} more")

    # --- Watchers section (pre-filtered: confirmed, non-spam, un-notified) ---
    if new_watcher_names and settings.get("fa_watcher_notifications_enabled", True):
        if lines:
            lines.append("")  # Visual separator before watchers
        lines.append(f"<b>🦊 FA: {len(new_watcher_names)} New Watcher{'s' if len(new_watcher_names) != 1 else ''}</b>")
        for name in new_watcher_names[:5]:
            lines.append(f"  • <b>{_esc(name)}</b> started watching")
        if len(new_watcher_names) > 5:
            lines.append(f"  ...and {len(new_watcher_names) - 5} more")

    if not lines:
        return  # Everything was filtered out — nothing to send

    text = "\n".join(lines)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
    except Exception as e:
        logger.warning("Failed to send FA Telegram notification: %s", e)


async def run_fa_poll_cycle(force_full: bool = False) -> dict:
    """Execute one complete FurAffinity poll cycle.

    Follows the same pattern as the IB poller (run_poll_cycle) but with a
    reduced step count because FA's data model is more limited:

      1. **Gallery discovery** -- fetch all submission IDs via FAExport.
         (No auth step needed here; FAExport uses cookies set on the client.)
      2. **Detail fetch**      -- batch-fetch metadata for each submission.
      3. **Upsert + snapshot** -- write/update submission rows and record
                                  point-in-time stats.
      4. **Comments**          -- fetch comments via the FAExport API when
                                  the comment count has changed (or force_full).

    There is **no faving-user step** because FurAffinity does not expose
    per-submission fave lists through FAExport or any public endpoint.
    The stats dict therefore has no ``new_faves_found`` key.

    Args:
        force_full: When True, re-fetch comments for every submission
            regardless of whether their counts changed.

    Returns:
        Stats dict with keys: submissions_found, snapshots_inserted,
        new_comments_found.  Empty dict if a poll was already running.
    """
    global _fa_poll_running, _fa_first_poll

    # Concurrency guard -- identical pattern to the IB poller.
    # The Lock makes the check-and-set atomic so two near-simultaneous
    # callers cannot both slip through.
    if not _fa_poll_lock.acquire(blocking=False):
        logger.warning("FA poll already running — skipping")
        return {}
    _fa_poll_running = True
    _update_fa_progress("starting", message="Initialising FA poll cycle...")

    conn = None
    log_id = None
    start_time = time.time()

    # Note: no "new_faves_found" key -- FA doesn't provide faving user data.
    stats = {
        "submissions_found": 0,
        "snapshots_inserted": 0,
        "new_comments_found": 0,
        "new_watchers_found": 0,
    }

    # FA authentication uses cookie_a / cookie_b rather than a session ID.
    # These are stored in the user's settings and passed to the FAClient
    # constructor directly.
    settings = config.get_settings()
    client = FAClient(
        username=settings.get("fa_username", ""),
        cookie_a=settings.get("fa_cookie_a", ""),
        cookie_b=settings.get("fa_cookie_b", ""),
    )

    try:
        conn = get_connection()
        log_id = fa_queries.start_fa_poll_log(conn)
        # ── Step 1: Discover gallery submissions via FAExport ──
        # FAExport provides a JSON list of submission IDs for a user's
        # gallery, which avoids the need to scrape FA's HTML gallery pages.
        _update_fa_progress("searching", message="Fetching gallery from FAExport...")
        gallery = await client.get_all_gallery_ids()
        submission_ids = [s["submission_id"] for s in gallery]
        stats["submissions_found"] = len(submission_ids)
        logger.info("FA: Found %d submissions", len(submission_ids))

        if not submission_ids:
            _update_fa_progress("complete", message="No FA submissions found.")
            fa_queries.finish_fa_poll_log(conn, log_id, "success", duration_seconds=time.time() - start_time, **stats)
            conn.commit()
            return stats

        # ── Step 2: Fetch details for each submission ──────────
        _update_fa_progress("fetching_details", message=f"Fetching details for {len(submission_ids)} submissions...")
        details = await client.get_submission_details_batch(submission_ids)
        logger.info("FA: Fetched details for %d submissions", len(details))

        # ── Step 3 & 4: Upsert + snapshot, then conditional comments ──
        new_comment_details = []
        poll_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        for idx, detail in enumerate(details, 1):
            _update_fa_progress("processing", current=idx, total=len(details),
                                message=f"Processing submission {idx}/{len(details)}...")

            # Per-submission try/except -- same resilience pattern as IB.
            try:
                sub_id = detail["submission_id"]
                views = detail.get("views", 0)
                faves = detail.get("favorites_count", 0)
                comments = detail.get("comments_count", 0)

                # Grab the previous comment count *before* the snapshot
                # overwrites it -- needed for the delta check below.
                prev_comments = fa_queries.get_fa_previous_comments_count(conn, sub_id)

                # Step 3: Upsert submission and record snapshot.
                fa_queries.upsert_fa_submission(conn, detail)
                fa_queries.insert_fa_snapshot(conn, sub_id, views, faves, comments, polled_at=poll_timestamp)
                stats["snapshots_inserted"] += 1

                # ── Step 4: Fetch comments (conditional) ───────
                # Uses the FAExport /submission/{id}.json endpoint to get
                # comments as structured JSON, unlike the IB poller which
                # scrapes HTML.  Same delta-based optimisation: only fetch
                # when count has changed or on force_full.
                should_fetch_comments = force_full and comments > 0
                if not should_fetch_comments:
                    if (prev_comments is not None and comments > prev_comments) or \
                       (prev_comments is None and comments > 0):
                        should_fetch_comments = True

                if should_fetch_comments:
                    logger.info("FA submission %d: fetching comments (count=%d, force=%s)", sub_id, comments, force_full)
                    # Rate-limit delay before each comment fetch.
                    await asyncio.sleep(config.FA_REQUEST_DELAY_SECONDS)
                    try:
                        scraped = await client.get_submission_comments(sub_id)
                        for c in scraped:
                            is_new = fa_queries.upsert_fa_comment(conn, c)
                            if is_new:
                                stats["new_comments_found"] += 1
                                new_comment_details.append({
                                    "username": c.get("username", ""),
                                    "title": detail.get("title", ""),
                                })
                    except Exception as ce:
                        # Comment fetch failure is non-fatal.
                        logger.warning("Failed to fetch FA comments for %d: %s", sub_id, ce)

            except Exception as e:
                # Per-submission error: log and continue with the next one.
                logger.warning("Error processing FA submission %s: %s", detail.get("submission_id"), e)

        conn.commit()

        # ── Step 5: Fetch watchers (confirmation delay + spam protection) ──
        #
        # Why watchers start as "pending" and need 2 cycles to confirm:
        # FA attracts waves of spam/bot watchers that appear briefly then vanish.
        # By requiring a watcher to be present in 2 consecutive polls, we filter
        # out ephemeral bots without false-positiving on real users who simply
        # haven't been scraped yet.  Only confirmed watchers trigger notifications.
        #
        # Flow:
        #   a) Upsert all watchers from FAExport (new ones start as pending/unconfirmed)
        #   b) Confirm pending watchers that were seen again (survived 2+ cycles)
        #   c) Profile-sniff newly confirmed watchers to catch bots with zero activity
        #   d) Keyword-filter remaining watchers
        #   e) Notify only confirmed, non-spam, non-notified watchers
        #
        new_watcher_names = []
        confirmed_watcher_names = []
        try:
            _update_fa_progress("fetching_watchers", message="Fetching watcher list...")
            watchers = await client.get_all_watchers()
            for username in watchers:
                is_new = fa_queries.upsert_fa_watcher(conn, username)
                if is_new:
                    stats["new_watchers_found"] += 1
                    new_watcher_names.append(username)
            # Remove watchers no longer on the live list (banned/deleted/unwatched)
            if watchers:
                removed = fa_queries.remove_stale_fa_watchers(conn, watchers)
                if removed:
                    logger.info("FA: pruned %d stale watchers from DB", removed)
            conn.commit()

            if new_watcher_names:
                logger.info("FA: %d new watchers discovered (pending confirmation)", len(new_watcher_names))
                # Keyword-filter obvious spam immediately and mark in DB
                keyword_spam = [n for n in new_watcher_names if _is_spam_watcher(n)]
                if keyword_spam:
                    fa_queries.mark_watchers_spam(conn, keyword_spam)
                    conn.commit()
                    logger.info("FA watcher keyword filter: %d/%d flagged as obvious bots (e.g. %s)",
                                len(keyword_spam), len(new_watcher_names), ", ".join(keyword_spam[:3]))

            # Confirm pending watchers that survived from a previous cycle
            confirmed_watcher_names = fa_queries.confirm_pending_watchers(conn)
            conn.commit()

            if confirmed_watcher_names:
                logger.info("FA: %d watchers confirmed (seen in 2+ consecutive polls)", len(confirmed_watcher_names))

                # Profile sniff confirmed watchers to catch zero-activity bots.
                # Only sniff watchers not already flagged by keyword filter.
                # Cap at 10 to avoid excessive FAExport requests.
                to_sniff = [n for n in confirmed_watcher_names if not _is_spam_watcher(n)][:10]
                if to_sniff:
                    _update_fa_progress("sniffing_profiles", message=f"Checking {len(to_sniff)} watcher profiles...")
                    try:
                        sniff_results = await client.sniff_watcher_profiles(to_sniff)
                        profile_spam = [name for name, is_spam in sniff_results.items() if is_spam]
                        if profile_spam:
                            fa_queries.mark_watchers_spam(conn, profile_spam)
                            conn.commit()
                            logger.info("FA profile sniff: %d/%d confirmed watchers flagged as bots (zero activity)",
                                        len(profile_spam), len(to_sniff))
                    except Exception as pe:
                        logger.warning("FA profile sniff failed (non-fatal): %s", pe)

        except Exception as we:
            logger.warning("Failed to fetch FA watchers: %s", we)

        # ── Step 6: Fetch profile pageviews ───────────────────────
        # FAExport's /user/{name}.json returns a "pageviews" field representing
        # how many times the user's profile page has been visited. We snapshot
        # this value each poll cycle for historical charting.
        try:
            _update_fa_progress("fetching_profile", message="Fetching profile stats...")
            profile = await client.get_user_profile(client.username)
            if profile and "pageviews" in profile:
                from fa_client.client import _safe_int
                pv = _safe_int(profile["pageviews"])
                fa_queries.insert_fa_profile_stats(conn, pv, polled_at=poll_timestamp)
                conn.commit()
                logger.info("FA: Profile pageviews recorded: %d", pv)
        except Exception as pe:
            logger.warning("Failed to fetch FA profile stats: %s", pe)

        # ── Notifications (comments + confirmed watchers) ───────────
        # Skip on first poll after startup (silent baseline).
        # Watcher notifications respect fa_watcher_notification_mode:
        #   "immediate" (default) = notify per-poll as watchers confirm
        #   "daily"               = accumulate, sent via send_fa_watcher_digest()
        #   "off"                 = never notify about watchers
        settings = config.get_settings()
        watcher_mode = settings.get("fa_watcher_notification_mode", "immediate")
        notify_watchers = []
        if not _fa_first_poll and watcher_mode == "immediate":
            notify_watchers = fa_queries.get_unnotified_confirmed_watchers(conn)

        if _fa_first_poll:
            logger.info("First FA poll after startup — suppressing %d comment, %d watcher notifications",
                        len(new_comment_details), len(new_watcher_names))
        else:
            # Comments always notify immediately; watchers depend on mode
            try:
                _send_fa_notifications(new_comment_details, notify_watchers)
            except Exception as ne:
                logger.warning("Failed to send FA notifications: %s", ne)

            try:
                await _send_fa_telegram(new_comment_details, notify_watchers)
            except Exception as te:
                logger.warning("Failed to send FA Telegram notification: %s", te)

            # Mark as notified so we don't re-send
            if notify_watchers:
                fa_queries.mark_watchers_notified(conn, notify_watchers)
                conn.commit()

        # ── Finalise ───────────────────────────────────────────
        duration = time.time() - start_time
        _update_fa_progress("complete", current=len(details), total=len(details),
                            message=f"Done — {stats['submissions_found']} submissions in {duration:.1f}s")
        fa_queries.finish_fa_poll_log(conn, log_id, "success", duration_seconds=duration, **stats)
        logger.info("FA poll complete in %.1fs — %d submissions, %d snapshots, %d new comments, %d new watchers",
                     duration, stats["submissions_found"], stats["snapshots_inserted"],
                     stats["new_comments_found"], stats["new_watchers_found"])

        # ── Telegram summaries + milestones ───────────────────
        from polling.telegram import send_poll_summary, check_milestones_batch, check_goals
        if not _fa_first_poll:
            try:
                await send_poll_summary("fa", stats, duration)
            except Exception as te:
                logger.warning("Failed to send FA Telegram summary: %s", te)
            try:
                await check_milestones_batch("fa", "fa_snapshots", "fa_submissions")
            except Exception as me:
                logger.warning("Failed to check FA milestones: %s", me)
            try:
                await check_goals()
            except Exception as ge:
                logger.warning("Failed to check goals: %s", ge)

        return stats

    except Exception as e:
        # Top-level failure -- record partial stats and propagate.
        duration = time.time() - start_time
        _update_fa_progress("error", message=str(e))
        logger.error("FA poll failed: %s", e)
        if conn and log_id:
            fa_queries.finish_fa_poll_log(conn, log_id, "error", error_message=str(e), duration_seconds=duration, **stats)
            conn.commit()
        # Send error alert via Telegram
        from polling.telegram import send_poll_error
        try:
            await send_poll_error("fa", e)
        except Exception:
            pass
        raise
    finally:
        # Always clear the guard and release resources.
        # Also clear _fa_first_poll so that a failed first attempt doesn't
        # suppress notifications on the next successful poll.
        if _fa_first_poll:
            _fa_first_poll = False
        _fa_poll_running = False
        _fa_poll_lock.release()
        await client.close()
        if conn:
            conn.close()


async def send_fa_watcher_digest() -> None:
    """Send a daily digest of confirmed watchers that haven't been notified yet.

    Called by the digest scheduler when fa_watcher_notification_mode is "daily".
    Collects all unnotified confirmed non-spam watchers and sends a single
    Telegram message summarising them.
    """
    settings = config.get_settings()
    if settings.get("fa_watcher_notification_mode", "immediate") != "daily":
        return
    if not settings.get("telegram_enabled", False):
        return
    token = settings.get("telegram_bot_token")
    chat_id = settings.get("telegram_chat_id")
    if not token or not chat_id:
        return

    conn = get_connection()
    try:
        pending = fa_queries.get_unnotified_confirmed_watchers(conn)
        if not pending:
            return

        lines = [f"<b>🦊 FA Daily Watcher Digest: {len(pending)} New Watcher{'s' if len(pending) != 1 else ''}</b>"]
        for name in pending[:10]:
            lines.append(f"  • <b>{_esc(name)}</b>")
        if len(pending) > 10:
            lines.append(f"  ...and {len(pending) - 10} more")

        text = "\n".join(lines)
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                await http.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                )
        except Exception as e:
            logger.warning("Failed to send FA watcher digest: %s", e)
            return

        fa_queries.mark_watchers_notified(conn, pending)
        conn.commit()
        logger.info("FA watcher digest sent: %d watchers", len(pending))
    finally:
        conn.close()
