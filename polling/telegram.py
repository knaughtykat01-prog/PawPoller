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

import httpx

import config
from database.db import get_connection

from html import escape as _esc

logger = logging.getLogger(__name__)

# Milestone thresholds — when a submission crosses one of these values for a
# given metric, a one-time notification is sent.  Checked after each poll cycle.
VIEW_MILESTONES = [100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000]
FAVE_MILESTONES = [10, 25, 50, 100, 250, 500, 1000, 2500, 5000]
COMMENT_MILESTONES = [10, 25, 50, 100, 250, 500, 1000]


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

PLATFORM_EMOJI = {"ib": "🐾", "fa": "🦊", "ws": "🦎", "sf": "🐺"}
PLATFORM_NAME = {"ib": "Inkbunny", "fa": "FurAffinity", "ws": "Weasyl", "sf": "SoFurry"}


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

    view_m = _crossed_milestone(current_views, prev_views, VIEW_MILESTONES)
    if view_m:
        lines.append(f"  👁 {current_views:,} views (passed {view_m:,})")

    fave_m = _crossed_milestone(current_faves, prev_faves, FAVE_MILESTONES)
    if fave_m:
        lines.append(f"  ❤️ {current_faves:,} faves (passed {fave_m:,})")

    comment_m = _crossed_milestone(current_comments, prev_comments, COMMENT_MILESTONES)
    if comment_m:
        lines.append(f"  💬 {current_comments:,} comments (passed {comment_m:,})")

    if lines:
        header = f"<b>{emoji} {name} Milestone!</b>\n<b>{_esc(title)}</b>"
        await send_telegram(header + "\n" + "\n".join(lines))


async def check_milestones_batch(platform: str, snap_table: str, sub_table: str) -> None:
    """Compare latest two snapshots for all submissions on a platform and fire milestone alerts.

    Called at the end of each poll cycle.  Compares the two most recent snapshots
    per submission to detect threshold crossings.
    """
    settings = config.get_settings()
    if not settings.get("telegram_milestones", True):
        return

    conn = get_connection()
    try:
        subs = conn.execute(f"SELECT submission_id, title FROM {sub_table}").fetchall()
        for sub in subs:
            sid = sub["submission_id"]
            rows = conn.execute(
                f"SELECT views, favorites_count, comments_count FROM {snap_table} "
                f"WHERE submission_id = ? ORDER BY polled_at DESC LIMIT 2",
                (sid,),
            ).fetchall()
            if len(rows) < 2:
                continue
            curr, prev = dict(rows[0]), dict(rows[1])
            await check_milestones(
                platform, sid, sub["title"],
                curr["views"], curr["favorites_count"], curr["comments_count"],
                prev["views"], prev["favorites_count"], prev["comments_count"],
            )
    finally:
        conn.close()


# ── 6-Hourly Digest Report ──────────────────────────────────

def _get_6h_deltas(conn, snap_table: str, sub_table: str) -> dict:
    """Compute aggregate stat deltas over the last 6 hours for a platform.

    Returns dict with total_views_delta, total_faves_delta, total_comments_delta,
    top_gainers (up to 3 submissions with biggest view gains), and submission count.
    """
    # Get the nearest snapshot >= 6h old for each submission, compare to current.
    rows = conn.execute(
        f"""SELECT s.submission_id, s.title, s.views, s.favorites_count, s.comments_count,
                   old.views as old_views, old.favorites_count as old_faves,
                   old.comments_count as old_comments
            FROM {sub_table} s
            LEFT JOIN (
                SELECT s1.submission_id, s1.views, s1.favorites_count, s1.comments_count
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
        dv = r["views"] - old_v
        df = r["favorites_count"] - old_f
        dc = r["comments_count"] - old_c
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


def _get_platform_totals(conn, sub_table: str) -> dict:
    """Get current aggregate totals for a platform."""
    row = conn.execute(
        f"SELECT COUNT(*) as subs, COALESCE(SUM(views),0) as views, "
        f"COALESCE(SUM(favorites_count),0) as faves, "
        f"COALESCE(SUM(comments_count),0) as comments "
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
        lines.append(f"<i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC</i>")
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

            totals = _get_platform_totals(conn, sub_t)
            deltas = _get_6h_deltas(conn, snap_t, sub_t)

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

    finally:
        conn.close()
