"""Centralised Telegram notification helpers.

Provides reusable send function and higher-level notification builders:
  - Poll cycle summaries (per-platform)
  - Poll error alerts
  - Milestone alerts (view/fave/comment thresholds)
  - Periodic cross-platform digest reports (configurable interval)
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

# When True, individual per-platform summaries and error alerts are
# suppressed.  Set by the unified poll orchestrator in server.py so it
# can send ONE consolidated message instead of 7+ individual ones.
# Manual /poll commands leave this False so you still get per-platform output.
orchestrated_poll_active = False


async def send_poll_summary(platform: str, stats: dict, duration: float) -> None:
    """Send a compact poll cycle summary for a single platform.

    Suppressed during orchestrated polls (server.py sends a consolidated
    summary instead).  Still fires for manual /poll commands.
    """
    if orchestrated_poll_active:
        return
    settings = config.get_settings()
    if not settings.get("telegram_poll_summaries", True):
        return

    emoji = PLATFORM_EMOJI.get(platform, "")
    name = PLATFORM_NAME.get(platform, platform.upper())
    subs = stats.get("submissions_found", 0)
    snaps = stats.get("snapshots_inserted", 0)

    lines = [f"<b>{emoji} {name} Poll Complete</b>"]
    lines.append(f"  {subs} submissions, {snaps} snapshots in {duration:.1f}s")

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


# ── Poll error classification ───────────────────────────────

_ERROR_PATTERNS: list[tuple[str, str, str]] = [
    # (substring to match, short label, hint)
    ("login failed", "Login blocked", "Likely Cloudflare/rate-limit, not bad creds"),
    ("Shields are up", "Cloudflare challenge", "AO3 is blocking automated access"),
    ("429 Too Many Requests", "Rate limited", "Will back off automatically"),
    ("429", "Rate limited", "Platform is throttling requests"),
    ("403 Forbidden", "Access denied", "Platform may be blocking datacenter IPs"),
    ("403", "Blocked", "May need proxy or updated cookies"),
    ("404 Not Found", "Not found", "API endpoint may have changed"),
    ("check credentials", "Auth issue", "Verify creds in dashboard if this persists"),
    ("timeout", "Timed out", "Platform may be slow or unreachable"),
    ("ConnectError", "Connection failed", "Platform may be down"),
    ("ConnectTimeout", "Connection timed out", "Platform unreachable"),
    ("RemoteProtocolError", "Connection dropped", "Platform closed the connection"),
    ("SSL", "SSL error", "Certificate or TLS issue"),
]


def _classify_error(error_str: str) -> tuple[str, str]:
    """Map a raw error string to a user-friendly (label, hint) pair."""
    lower = error_str.lower()
    for pattern, label, hint in _ERROR_PATTERNS:
        if pattern.lower() in lower:
            return label, hint
    return "Error", ""


def _format_error_for_telegram(platform: str, error_str: str) -> str:
    """Build a user-friendly error line for Telegram messages."""
    label, hint = _classify_error(error_str)
    name = PLATFORM_NAME.get(platform, platform.upper())
    emoji = PLATFORM_EMOJI.get(platform, "")
    line = f"❌ {emoji} {name}: {_esc(label)}"
    if hint:
        line += f"\n     <i>{_esc(hint)}</i>"
    return line


# ── Poll error alert ─────────────────────────────────────────

async def send_poll_error(platform: str, error: Exception) -> None:
    """Send an alert when a poll cycle fails.

    Suppressed during orchestrated polls — errors are included in the
    consolidated summary instead.
    """
    if orchestrated_poll_active:
        return
    settings = config.get_settings()
    if not settings.get("telegram_error_alerts", True):
        return

    emoji = PLATFORM_EMOJI.get(platform, "")
    name = PLATFORM_NAME.get(platform, platform.upper())
    error_str = str(error)[:200]
    label, hint = _classify_error(error_str)
    lines = [f"<b>{emoji} {name} Poll Failed</b>"]
    lines.append(f"  {_esc(label)}")
    if hint:
        lines.append(f"  <i>{_esc(hint)}</i>")
    lines.append(f"  <code>{_esc(error_str[:120])}</code>")
    await send_telegram("\n".join(lines))


# ── Consolidated poll summary (used by orchestrator) ─────────

async def send_consolidated_poll_summary(results: list[dict], duration: float) -> None:
    """Send ONE summary message for an orchestrated poll cycle.

    *results* is a list of dicts, each with:
      - platform: short code (e.g. "ib")
      - stats: poll stats dict (on success), OR
      - error: error message string (on failure)

    Format:
      All OK  → "✅ All 6 Polls Complete (25s) ..."
      Partial → "⚠️ 5/6 Polls Complete (18s) ... ❌ FA: error"
    """
    settings = config.get_settings()
    if not settings.get("telegram_poll_summaries", True):
        return
    if not results:
        return

    ok = [r for r in results if "stats" in r]
    failed = [r for r in results if "error" in r]

    if not failed:
        header = f"✅ All {len(ok)} Polls Complete ({duration:.0f}s)"
    else:
        header = f"⚠️ {len(ok)}/{len(results)} Polls Complete ({duration:.0f}s)"

    lines = [f"<b>{header}</b>"]

    # Platform summary line: "🐾 IB: 9  🦊 FA: 7  🐺 SF: 8"
    parts = []
    for r in ok:
        emoji = PLATFORM_EMOJI.get(r["platform"], "")
        subs = r["stats"].get("submissions_found", 0)
        parts.append(f"{emoji}{subs}")
    if parts:
        lines.append("  " + "  ".join(parts))

    # Aggregate new activity across all platforms
    total_faves = sum(r["stats"].get("new_faves_found", 0) for r in ok)
    total_comments = sum(r["stats"].get("new_comments_found", 0) for r in ok)
    total_watchers = sum(r["stats"].get("new_watchers_found", 0) for r in ok)
    activity = []
    if total_faves:
        activity.append(f"+{total_faves} fave{'s' if total_faves != 1 else ''}")
    if total_comments:
        activity.append(f"+{total_comments} comment{'s' if total_comments != 1 else ''}")
    if total_watchers:
        activity.append(f"+{total_watchers} watcher{'s' if total_watchers != 1 else ''}")
    if activity:
        lines.append(f"  {', '.join(activity)}")

    # Failed platforms — classified error messages
    for r in failed:
        lines.append(_format_error_for_telegram(r["platform"], r["error"]))

    await send_telegram("\n".join(lines))


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
    """Check all active goals and send notifications for newly completed ones.

    Suppressed during orchestrated polls — the orchestrator calls this once
    after all platforms finish so we avoid 11 redundant DB scans.
    """
    if orchestrated_poll_active:
        return
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


# ── Periodic Digest Report ───────────────────────────────────

def _get_digest_deltas(conn, snap_table: str, sub_table: str, platform: str, hours: int = 6) -> dict:
    """Compute aggregate stat deltas over the last *hours* for a platform.

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
                    WHERE polled_at <= datetime('now', '-' || ? || ' hours')
                    GROUP BY submission_id
                ) s2 ON s1.submission_id = s2.submission_id AND s1.polled_at = s2.max_polled
            ) old ON s.submission_id = old.submission_id""",
        (str(hours),),
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
    """Build and send the periodic cross-platform digest report."""
    settings = config.get_settings()
    if not settings.get("telegram_enabled", False):
        return
    if not settings.get("telegram_digest", True):
        return

    digest_hours = settings.get("telegram_digest_interval_hours", 6)

    conn = get_connection()
    try:
        lines = [f"<b>📊 PawPoller {digest_hours}-Hour Digest</b>"]
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
            deltas = _get_digest_deltas(conn, snap_t, sub_t, plat, digest_hours)

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


# ── Weekly Digest Report ────────────────────────────────────

# Watcher/follower tables per platform (table_name, count_filter).
# Only platforms with watcher tracking are listed.
_WATCHER_TABLES = {
    "ib":  ("watchers", "1=1"),
    "fa":  ("fa_watchers", "confirmed=1 AND is_spam=0"),
    "sf":  ("sf_watchers", "1=1"),
}


def _get_watcher_stats(conn, platform: str, days: int = 7) -> dict | None:
    """Return total and new watcher/follower counts for a platform.

    Returns None if the platform has no watcher table or no data.
    """
    entry = _WATCHER_TABLES.get(platform)
    if not entry:
        return None
    table, where = entry
    try:
        total = conn.execute(
            f"SELECT COUNT(*) as c FROM {table} WHERE {where}"
        ).fetchone()["c"]
        new = conn.execute(
            f"SELECT COUNT(*) as c FROM {table} "
            f"WHERE {where} AND first_seen_at >= datetime('now', '-' || ? || ' days')",
            (str(days),),
        ).fetchone()["c"]
        return {"total": total, "new": new}
    except Exception:
        return None


async def send_weekly_digest_report() -> None:
    """Build and send the weekly cross-platform digest report.

    Uses 7-day deltas, includes watcher/follower counts, and shows the
    top 5 gainers across all platforms.  Stores ``last_weekly_digest_sent_at``
    to prevent duplicates across restarts and manual triggers.
    """
    settings = config.get_settings()
    if not settings.get("telegram_enabled", False):
        return
    if not settings.get("telegram_weekly_digest", True):
        return

    conn = get_connection()
    try:
        now = datetime.now(timezone.utc)
        # Build "week of" header in the user's display timezone
        tz_name = settings.get("display_timezone", "UTC")
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc
        local_now = now.astimezone(tz)
        from datetime import timedelta
        week_start = (local_now - timedelta(days=7)).strftime("%b %d")
        week_end = local_now.strftime("%b %d, %Y")

        lines = [f"<b>📅 PawPoller Weekly Digest</b>"]
        lines.append(f"<i>Week of {week_start} — {week_end}</i>")
        lines.append("")

        grand_views = 0
        grand_faves = 0
        grand_comments = 0
        grand_total_views = 0
        grand_total_faves = 0
        grand_total_comments = 0
        all_gainers = []

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

            try:
                count = conn.execute(f"SELECT COUNT(*) as c FROM {sub_t}").fetchone()["c"]
            except Exception:
                continue
            if count == 0:
                continue

            totals = _get_platform_totals(conn, sub_t, plat)
            deltas = _get_digest_deltas(conn, snap_t, sub_t, plat, hours=168)

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

            # Watcher/follower stats
            watcher = _get_watcher_stats(conn, plat)
            if watcher:
                label = "Followers" if plat == "sf" else "Watchers"
                new_str = f" (+{watcher['new']})" if watcher["new"] > 0 else ""
                lines.append(f"  {label}: {watcher['total']:,}{new_str}")

            # Collect gainers for cross-platform top 5
            for g in deltas["top_gainers"]:
                g["platform"] = plat
                g["emoji"] = emoji
                all_gainers.append(g)

            lines.append("")

        # Skip if no platforms had data
        if grand_total_views == 0 and grand_total_faves == 0 and grand_total_comments == 0:
            return

        # Top 5 gainers across all platforms
        all_gainers.sort(key=lambda x: x["views"] + x["faves"] * 10, reverse=True)
        if all_gainers:
            lines.append("<b>🏆 Top Gainers This Week</b>")
            for g in all_gainers[:5]:
                parts = []
                if g["views"] > 0:
                    parts.append(f"+{g['views']:,} views")
                if g["faves"] > 0:
                    parts.append(f"+{g['faves']:,} faves")
                if parts:
                    lines.append(f"  {g['emoji']} {_esc(g['title'][:35])}: {', '.join(parts)}")
            lines.append("")

        # Grand totals
        lines.append("<b>📈 Weekly Combined</b>")
        lines.append(
            f"  Views: {grand_total_views:,} (+{grand_views:,})"
            f"  Faves: {grand_total_faves:,} (+{grand_faves:,})"
        )
        lines.append(
            f"  Comments: {grand_total_comments:,} (+{grand_comments:,})"
        )

        await send_telegram("\n".join(lines))

        config.save_settings({"last_weekly_digest_sent_at": datetime.now(timezone.utc).isoformat()})

    finally:
        conn.close()
