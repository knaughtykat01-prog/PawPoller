"""Centralised Telegram notification helpers.

Provides reusable send function and higher-level notification builders:
  - Poll cycle summaries (per-platform)
  - Poll error alerts
  - Milestone alerts (view/fave/comment thresholds)
  - 6-hourly cross-platform digest reports
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

import config
from database.db import get_connection

from html import escape as _esc

logger = logging.getLogger(__name__)

# Platform-specific column name mapping.
# Most platforms use views/favorites_count/comments_count, but some differ:
#   Wattpad: reads/votes/comments_count/num_lists (no views column)
#   Itaku: likes/comments_count/reshares (no views column at all)
#   DeviantArt: also has downloads
PLATFORM_METRICS = {
    "ib":  {"views": "views", "faves": "favorites_count", "comments": "comments_count"},
    "fa":  {"views": "views", "faves": "favorites_count", "comments": "comments_count"},
    "ws":  {"views": "views", "faves": "favorites_count", "comments": "comments_count"},
    "sf":  {"views": "views", "faves": "favorites_count", "comments": "comments_count"},
    "sqw": {"views": "views", "faves": "favorites_count", "comments": "comments_count"},
    "ao3": {"views": "views", "faves": "favorites_count", "comments": "comments_count"},
    "da":  {"views": "views", "faves": "favorites_count", "comments": "comments_count"},
    "wp":  {"views": "reads", "faves": "votes", "comments": "comments_count"},
    "ik":  {"views": None,   "faves": "likes", "comments": "comments_count"},
    "bsky": {"views": None,  "faves": "likes", "comments": "replies"},
    "tw":  {"views": "views", "faves": "likes", "comments": "replies"},
}

# Default milestone thresholds — overridden by settings.json if configured.
_DEFAULT_VIEW_MILESTONES = [100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000]
_DEFAULT_FAVE_MILESTONES = [10, 25, 50, 100, 250, 500, 1000, 2500, 5000]
_DEFAULT_COMMENT_MILESTONES = [10, 25, 50, 100, 250, 500, 1000]


def _get_milestones() -> dict:
    """Return current milestone thresholds from settings, falling back to defaults."""
    s = config.get_settings()
    return {
        "views": s.get("milestone_views", _DEFAULT_VIEW_MILESTONES),
        "faves": s.get("milestone_faves", _DEFAULT_FAVE_MILESTONES),
        "comments": s.get("milestone_comments", _DEFAULT_COMMENT_MILESTONES),
    }


def format_tz(dt: datetime | None = None) -> str:
    """Format a datetime in the user's configured display_timezone.

    If *dt* is None, uses the current UTC time.  Falls back to UTC if the
    configured timezone is invalid.  Returns 'YYYY-MM-DD HH:MM TZ'.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    tz_name = config.get_settings().get("display_timezone", "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, Exception):
        tz = timezone.utc
    local = dt.astimezone(tz)
    abbr = local.strftime("%Z")
    return f"{local.strftime('%Y-%m-%d %H:%M')} {abbr}"


# ── Core send helper ─────────────────────────────────────────

async def send_telegram(text: str) -> bool:
    """Send an HTML-formatted Telegram message.  Returns True on success."""
    settings = config.get_settings()
    if not settings.get("telegram_enabled", False):
        return False
    token = settings.get("telegram_bot_token")
    chat_id = settings.get("telegram_chat_id")
    if not token or not chat_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
        return True
    except Exception as e:
        logger.warning("Failed to send Telegram message: %s", e)
        return False


# ── Poll cycle summary ───────────────────────────────────────

PLATFORM_EMOJI = {"ib": "🐾", "fa": "🦊", "ws": "🦎", "sf": "🐺", "sqw": "🦑", "ao3": "📖", "da": "🎨", "wp": "📙", "ik": "🎯", "bsky": "🦋", "tw": "🐦"}
PLATFORM_NAME = {"ib": "Inkbunny", "fa": "FurAffinity", "ws": "Weasyl", "sf": "SoFurry", "sqw": "SquidgeWorld", "ao3": "AO3", "da": "DeviantArt", "wp": "Wattpad", "ik": "Itaku", "bsky": "Bluesky", "tw": "X/Twitter"}


async def send_poll_summary(platform: str, stats: dict, duration: float) -> None:
    """Send a compact poll cycle summary for a single platform."""
    settings = config.get_settings()
    if not settings.get("telegram_poll_summaries", True):
        return

    emoji = PLATFORM_EMOJI.get(platform, "")
    name = PLATFORM_NAME.get(platform, platform.upper())
    subs = stats.get("submissions_found", 0)
    snaps = stats.get("snapshots_inserted", 0)

    lines = [f"<b>{emoji} {name} Poll Complete</b>"]
    lines.append(f"  {subs} submissions, {snaps} snapshots in {duration:.1f}s")

    # IB-specific fields
    new_faves = stats.get("new_faves_found", 0)
    new_comments = stats.get("new_comments_found", 0)
    new_watchers = stats.get("new_watchers_found", 0)
    activity = []
    if new_faves:
        activity.append(f"+{new_faves} fave{'s' if new_faves != 1 else ''}")
    if new_comments:
        activity.append(f"+{new_comments} comment{'s' if new_comments != 1 else ''}")
    if new_watchers:
        activity.append(f"+{new_watchers} watcher{'s' if new_watchers != 1 else ''}")
    if activity:
        lines.append(f"  New: {', '.join(activity)}")

    await send_telegram("\n".join(lines))


# ── Poll error alert ─────────────────────────────────────────

async def send_poll_error(platform: str, error: Exception) -> None:
    """Send an alert when a poll cycle fails."""
    settings = config.get_settings()
    if not settings.get("telegram_error_alerts", True):
        return

    emoji = PLATFORM_EMOJI.get(platform, "")
    name = PLATFORM_NAME.get(platform, platform.upper())
    err_msg = _esc(str(error)[:200])  # Truncate long errors, escape HTML
    text = f"<b>{emoji} {name} Poll Failed</b>\n  {err_msg}"
    await send_telegram(text)


# ── Milestone alerts ─────────────────────────────────────────

def _crossed_milestone(current: int, previous: int, milestones: list[int]) -> int | None:
    """Return the highest milestone crossed between previous and current, or None."""
    crossed = None
    for m in milestones:
        if previous < m <= current:
            crossed = m
    return crossed


async def check_milestones(platform: str, submission_id: int, title: str,
                           current_views: int, current_faves: int, current_comments: int,
                           prev_views: int, prev_faves: int, prev_comments: int) -> None:
    """Check if a submission crossed any milestone thresholds and notify."""
    settings = config.get_settings()
    if not settings.get("telegram_milestones", True):
        return

    emoji = PLATFORM_EMOJI.get(platform, "")
    name = PLATFORM_NAME.get(platform, platform.upper())
    lines = []

    ms = _get_milestones()
    view_m = _crossed_milestone(current_views, prev_views, ms["views"])
    if view_m:
        lines.append(f"  👁 {current_views:,} views (passed {view_m:,})")

    fave_m = _crossed_milestone(current_faves, prev_faves, ms["faves"])
    if fave_m:
        lines.append(f"  ❤️ {current_faves:,} faves (passed {fave_m:,})")

    comment_m = _crossed_milestone(current_comments, prev_comments, ms["comments"])
    if comment_m:
        lines.append(f"  💬 {current_comments:,} comments (passed {comment_m:,})")

    if lines:
        header = f"<b>{emoji} {name} Milestone!</b>\n<b>{_esc(title)}</b>"
        await send_telegram(header + "\n" + "\n".join(lines))


async def check_milestones_batch(platform: str, snap_table: str, sub_table: str) -> None:
    """Compare latest two snapshots for all submissions on a platform and fire milestone alerts.

    Called at the end of each poll cycle.  Compares the two most recent snapshots
    per submission to detect threshold crossings.
    Uses platform-aware column names via PLATFORM_METRICS.
    """
    settings = config.get_settings()
    if not settings.get("telegram_milestones", True):
        return

    metrics = PLATFORM_METRICS.get(platform, PLATFORM_METRICS["ib"])
    views_col = metrics["views"]
    faves_col = metrics["faves"]
    comments_col = metrics["comments"]

    # Build SELECT columns, skipping None (e.g. Itaku has no views)
    select_cols = []
    if views_col:
        select_cols.append(views_col)
    if faves_col:
        select_cols.append(faves_col)
    if comments_col:
        select_cols.append(comments_col)

    if not select_cols:
        return

    conn = get_connection()
    try:
        subs = conn.execute(f"SELECT submission_id, title FROM {sub_table}").fetchall()
        for sub in subs:
            sid = sub["submission_id"]
            rows = conn.execute(
                f"SELECT {', '.join(select_cols)} FROM {snap_table} "
                f"WHERE submission_id = ? ORDER BY polled_at DESC LIMIT 2",
                (sid,),
            ).fetchall()
            if len(rows) < 2:
                continue
            curr, prev = dict(rows[0]), dict(rows[1])
            await check_milestones(
                platform, sid, sub["title"],
                curr.get(views_col, 0) if views_col else 0,
                curr.get(faves_col, 0) if faves_col else 0,
                curr.get(comments_col, 0) if comments_col else 0,
                prev.get(views_col, 0) if views_col else 0,
                prev.get(faves_col, 0) if faves_col else 0,
                prev.get(comments_col, 0) if comments_col else 0,
            )
    finally:
        conn.close()


# ── Goal Completion Check ─────────────────────────────────────

async def check_goals() -> None:
    """Check all active goals and send notifications for newly completed ones."""
    settings = config.get_settings()
    if not settings.get("telegram_enabled", False):
        return

    # Use the shared whitelist from config — single source of truth for
    # valid metric column names that are safe to interpolate into SQL.
    ALLOWED_METRICS = config.ALLOWED_GOAL_METRICS
    conn = get_connection()
    try:
        goals = conn.execute("SELECT * FROM goals WHERE completed_at IS NULL").fetchall()
        table_map = {"ib": "submissions", "fa": "fa_submissions", "ws": "ws_submissions", "sf": "sf_submissions", "sqw": "sqw_submissions", "ao3": "ao3_submissions", "da": "da_submissions", "wp": "wp_submissions", "ik": "ik_submissions", "bsky": "bsky_submissions", "tw": "tw_submissions"}

        for g in goals:
            g = dict(g)
            metric = g["metric"]
            if metric not in ALLOWED_METRICS:
                continue
            current = 0
            title = None

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
                    for plat_key, tbl in table_map.items():
                        try:
                            r = conn.execute(f"SELECT COALESCE(SUM({metric}), 0) as total FROM {tbl}").fetchone()
                            current += r["total"]
                        except Exception:
                            # Column doesn't exist on this platform — skip
                            pass
                else:
                    table = table_map.get(g["platform"])
                    if table:
                        try:
                            r = conn.execute(f"SELECT COALESCE(SUM({metric}), 0) as total FROM {table}").fetchone()
                            current = r["total"]
                        except Exception:
                            pass

            if current >= g["target_value"] and g["target_value"] > 0:
                # Use rowcount to prevent duplicate notifications from concurrent pollers
                cursor = conn.execute(
                    "UPDATE goals SET completed_at = datetime('now') WHERE goal_id = ? AND completed_at IS NULL",
                    (g["goal_id"],),
                )
                conn.commit()
                if cursor.rowcount == 0:
                    continue
                emoji = PLATFORM_EMOJI.get(g["platform"], "🎯")
                metric_labels = {
                    "views": "views", "favorites_count": "faves", "comments_count": "comments",
                    "reads": "reads", "votes": "votes", "likes": "likes",
                    "reshares": "reshares", "downloads": "downloads", "num_lists": "lists",
                }
                metric_label = metric_labels.get(metric, metric)
                sub_label = f"\n<b>{_esc(title)}</b>" if title else ""
                await send_telegram(
                    f"<b>{emoji} Goal Reached!</b>{sub_label}\n"
                    f"  🎯 {current:,} / {g['target_value']:,} {metric_label}"
                )
    finally:
        conn.close()


# ── 6-Hourly Digest Report ──────────────────────────────────

def _get_6h_deltas(conn, snap_table: str, sub_table: str, platform: str) -> dict:
    """Compute aggregate stat deltas over the last 6 hours for a platform.

    Returns dict with total_views_delta, total_faves_delta, total_comments_delta,
    top_gainers (up to 3 submissions with biggest view/fave gains), and submission count.
    Uses platform-aware column names via PLATFORM_METRICS.
    """
    metrics = PLATFORM_METRICS.get(platform, PLATFORM_METRICS["ib"])
    views_col = metrics["views"]
    faves_col = metrics["faves"]
    comments_col = metrics["comments"]

    # Build dynamic SELECT columns for the current sub table
    current_cols = ["s.submission_id", "s.title"]
    old_select_cols = []  # columns from the old snapshot subquery
    old_join_cols = []    # columns to select in the inner snapshot subquery

    if views_col:
        current_cols.append(f"s.{views_col}")
        old_select_cols.append(f"s1.{views_col} as old_views")
        old_join_cols.append(f"s1.{views_col}")
    if faves_col:
        current_cols.append(f"s.{faves_col}")
        old_select_cols.append(f"s1.{faves_col} as old_faves")
        old_join_cols.append(f"s1.{faves_col}")
    if comments_col:
        current_cols.append(f"s.{comments_col}")
        old_select_cols.append(f"s1.{comments_col} as old_comments")
        old_join_cols.append(f"s1.{comments_col}")

    old_cols_str = ", ".join(old_select_cols) if old_select_cols else "1 as _dummy"

    rows = conn.execute(
        f"""SELECT {', '.join(current_cols)},
                   {', '.join(f'old.{c.split(" as ")[1]}' for c in old_select_cols) if old_select_cols else '1 as _dummy2'}
            FROM {sub_table} s
            LEFT JOIN (
                SELECT s1.submission_id, {old_cols_str}
                FROM {snap_table} s1
                INNER JOIN (
                    SELECT submission_id, MAX(polled_at) as max_polled
                    FROM {snap_table}
                    WHERE polled_at <= datetime('now', '-6 hours')
                    GROUP BY submission_id
                ) s2 ON s1.submission_id = s2.submission_id AND s1.polled_at = s2.max_polled
            ) old ON s.submission_id = old.submission_id"""
    ).fetchall()

    total_views_delta = 0
    total_faves_delta = 0
    total_comments_delta = 0
    gainers = []

    for r in rows:
        r = dict(r)
        old_v = r.get("old_views") or 0
        old_f = r.get("old_faves") or 0
        old_c = r.get("old_comments") or 0
        dv = (r.get(views_col, 0) or 0) - old_v if views_col else 0
        df = (r.get(faves_col, 0) or 0) - old_f if faves_col else 0
        dc = (r.get(comments_col, 0) or 0) - old_c if comments_col else 0
        total_views_delta += max(dv, 0)
        total_faves_delta += max(df, 0)
        total_comments_delta += max(dc, 0)
        if dv > 0 or df > 0:
            gainers.append({"title": r["title"], "views": dv, "faves": df, "comments": dc})

    gainers.sort(key=lambda x: x["views"], reverse=True)

    return {
        "submissions": len(rows),
        "views_delta": total_views_delta,
        "faves_delta": total_faves_delta,
        "comments_delta": total_comments_delta,
        "top_gainers": gainers[:3],
    }


def _get_platform_totals(conn, sub_table: str, platform: str) -> dict:
    """Get current aggregate totals for a platform.

    Uses platform-aware column names via PLATFORM_METRICS.
    """
    metrics = PLATFORM_METRICS.get(platform, PLATFORM_METRICS["ib"])
    views_col = metrics["views"]
    faves_col = metrics["faves"]
    comments_col = metrics["comments"]

    views_expr = f"COALESCE(SUM({views_col}),0)" if views_col else "0"
    faves_expr = f"COALESCE(SUM({faves_col}),0)" if faves_col else "0"
    comments_expr = f"COALESCE(SUM({comments_col}),0)" if comments_col else "0"

    row = conn.execute(
        f"SELECT COUNT(*) as subs, {views_expr} as views, "
        f"{faves_expr} as faves, "
        f"{comments_expr} as comments "
        f"FROM {sub_table}"
    ).fetchone()
    return dict(row)


async def send_digest_report() -> None:
    """Build and send the 6-hourly cross-platform digest report."""
    settings = config.get_settings()
    if not settings.get("telegram_enabled", False):
        return
    if not settings.get("telegram_digest", True):
        return

    conn = get_connection()
    try:
        lines = [f"<b>📊 PawPoller 6-Hour Digest</b>"]
        lines.append(f"<i>{format_tz()}</i>")
        lines.append("")

        grand_views = 0
        grand_faves = 0
        grand_comments = 0
        grand_total_views = 0
        grand_total_faves = 0
        grand_total_comments = 0

        platforms = [
            ("ib", "snapshots", "submissions"),
            ("fa", "fa_snapshots", "fa_submissions"),
            ("ws", "ws_snapshots", "ws_submissions"),
            ("sf", "sf_snapshots", "sf_submissions"),
            ("sqw", "sqw_snapshots", "sqw_submissions"),
            ("ao3", "ao3_snapshots", "ao3_submissions"),
            ("da", "da_snapshots", "da_submissions"),
            ("wp", "wp_snapshots", "wp_submissions"),
            ("ik", "ik_snapshots", "ik_submissions"),
            ("bsky", "bsky_snapshots", "bsky_submissions"),
            ("tw", "tw_snapshots", "tw_submissions"),
        ]

        for plat, snap_t, sub_t in platforms:
            emoji = PLATFORM_EMOJI[plat]
            name = PLATFORM_NAME[plat]

            # Check if platform has any data
            try:
                count = conn.execute(f"SELECT COUNT(*) as c FROM {sub_t}").fetchone()["c"]
            except Exception:
                continue
            if count == 0:
                continue

            totals = _get_platform_totals(conn, sub_t, plat)
            deltas = _get_6h_deltas(conn, snap_t, sub_t, plat)

            grand_views += deltas["views_delta"]
            grand_faves += deltas["faves_delta"]
            grand_comments += deltas["comments_delta"]
            grand_total_views += totals["views"]
            grand_total_faves += totals["faves"]
            grand_total_comments += totals["comments"]

            lines.append(f"<b>{emoji} {name}</b> ({totals['subs']} subs)")
            lines.append(
                f"  Views: {totals['views']:,} (+{deltas['views_delta']:,})"
                f"  Faves: {totals['faves']:,} (+{deltas['faves_delta']:,})"
            )
            lines.append(
                f"  Comments: {totals['comments']:,} (+{deltas['comments_delta']:,})"
            )

            # Top gainers for this platform
            for g in deltas["top_gainers"]:
                parts = []
                if g["views"] > 0:
                    parts.append(f"+{g['views']} views")
                if g["faves"] > 0:
                    parts.append(f"+{g['faves']} faves")
                if parts:
                    lines.append(f"    🔥 {_esc(g['title'][:30])}: {', '.join(parts)}")

            lines.append("")

        # Skip digest entirely if no platforms had data
        if grand_total_views == 0 and grand_total_faves == 0 and grand_total_comments == 0:
            return

        # Grand totals
        lines.append("<b>📈 Combined Totals</b>")
        lines.append(
            f"  Views: {grand_total_views:,} (+{grand_views:,})"
            f"  Faves: {grand_total_faves:,} (+{grand_faves:,})"
        )
        lines.append(
            f"  Comments: {grand_total_comments:,} (+{grand_comments:,})"
        )

        await send_telegram("\n".join(lines))

        # Persist timestamp so restarts don't re-send within the 6h window
        config.save_settings({"last_digest_sent_at": datetime.now(timezone.utc).isoformat()})

        # Piggyback: send FA watcher daily digest if in "daily" mode
        try:
            from polling.fa_poller import send_fa_watcher_digest
            await send_fa_watcher_digest()
        except Exception as e:
            logger.warning("FA watcher digest failed: %s", e)

    finally:
        conn.close()
