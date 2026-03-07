"""Telegram bot command handler — two-way interaction with PawPoller.

Polls Telegram's getUpdates API for incoming commands and dispatches them
to query functions, poll triggers, and settings mutators.

Commands:
  /help                     — list all commands
  /stats                    — cross-platform totals
  /top [platform]           — top 5 submissions by views
  /trending                 — spike detection results
  /digest                   — trigger a digest report now
  /fans                     — top fans leaderboard
  /poll [ib|fa|ws|sf|all]   — force a poll cycle
  /status                   — poll status and last poll times
  /interval [platform] [min]— change poll interval
  /notify                   — show notification toggle states
  /notify [type] [on|off]   — toggle specific notification types
"""

from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from html import escape as _esc
from zoneinfo import ZoneInfo

import httpx

import config
from database.db import get_connection
from database import queries, fa_queries, ws_queries, sf_queries
from database.analytics_queries import get_top_fans, get_trending_submissions

logger = logging.getLogger(__name__)

# Track the last processed update_id to avoid processing duplicates.
_last_update_id = 0


async def _send(token: str, chat_id: str, text: str) -> None:
    """Send an HTML message back to the user."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
    except Exception as e:
        logger.warning("Bot reply failed: %s", e)


async def _poll_updates(token: str) -> list[dict]:
    """Fetch new messages from Telegram using long polling."""
    global _last_update_id
    try:
        async with httpx.AsyncClient(timeout=35.0) as client:
            resp = await client.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"offset": _last_update_id + 1, "timeout": 30},
            )
            data = resp.json()
            if not data.get("ok"):
                return []
            results = data.get("result", [])
            if results:
                _last_update_id = results[-1]["update_id"]
            return results
    except Exception as e:
        logger.warning("Bot getUpdates failed: %s", e)
        return []


# ── Command handlers ─────────────────────────────────────────

async def _cmd_help(token: str, chat_id: str, args: str) -> None:
    text = """<b>PawPoller Commands</b>

<b>Queries</b>
/stats — Cross-platform totals
/top [ib|fa|ws|sf] — Top 5 by views
/trending — Spike detection
/digest — Send digest report
/fans — Top fans leaderboard

<b>Control</b>
/poll [ib|fa|ws|sf|all] — Force poll
/status — Last poll times
/interval [ib|fa|ws|sf] [mins] — Set poll interval

<b>Notifications</b>
/notify — Show all toggle states
/notify summaries [on|off]
/notify errors [on|off]
/notify milestones [on|off]
/notify digest [on|off]
/notify faves [on|off]
/notify comments [on|off]
/notify watchers [on|off]
/notify ib [on|off]
/notify fa [on|off]
/notify ws [on|off]
/notify sf [on|off]"""
    await _send(token, chat_id, text)


async def _cmd_stats(token: str, chat_id: str, args: str) -> None:
    conn = get_connection()
    try:
        lines = ["<b>📊 PawPoller Stats</b>", ""]

        platforms = [
            ("🐾", "Inkbunny", "submissions"),
            ("🦊", "FurAffinity", "fa_submissions"),
            ("🦎", "Weasyl", "ws_submissions"),
            ("🐺", "SoFurry", "sf_submissions"),
        ]

        grand_v = grand_f = grand_c = grand_s = 0

        for emoji, name, table in platforms:
            try:
                row = conn.execute(
                    f"SELECT COUNT(*) as subs, COALESCE(SUM(views),0) as views, "
                    f"COALESCE(SUM(favorites_count),0) as faves, "
                    f"COALESCE(SUM(comments_count),0) as comments "
                    f"FROM {table}"
                ).fetchone()
                row = dict(row)
                if row["subs"] == 0:
                    continue
                grand_v += row["views"]
                grand_f += row["faves"]
                grand_c += row["comments"]
                grand_s += row["subs"]
                lines.append(f"<b>{emoji} {name}</b> ({row['subs']} subs)")
                lines.append(f"  Views: {row['views']:,}  Faves: {row['faves']:,}  Comments: {row['comments']:,}")
            except Exception:
                continue

        if grand_s > 0:
            lines.append("")
            lines.append(f"<b>📈 Total</b>: {grand_v:,} views, {grand_f:,} faves, {grand_c:,} comments")

        await _send(token, chat_id, "\n".join(lines) if grand_s > 0 else "No data yet.")
    finally:
        conn.close()


async def _cmd_top(token: str, chat_id: str, args: str) -> None:
    platform = args.strip().lower() if args.strip() else "ib"
    table_map = {"ib": "submissions", "fa": "fa_submissions", "ws": "ws_submissions", "sf": "sf_submissions"}
    emoji_map = {"ib": "🐾", "fa": "🦊", "ws": "🦎", "sf": "🐺"}
    name_map = {"ib": "Inkbunny", "fa": "FurAffinity", "ws": "Weasyl", "sf": "SoFurry"}

    if platform not in table_map:
        await _send(token, chat_id, "Usage: /top [ib|fa|ws|sf]")
        return

    conn = get_connection()
    try:
        rows = conn.execute(
            f"SELECT title, views, favorites_count, comments_count FROM {table_map[platform]} "
            f"ORDER BY views DESC LIMIT 5"
        ).fetchall()

        if not rows:
            await _send(token, chat_id, f"No {name_map[platform]} submissions found.")
            return

        lines = [f"<b>{emoji_map[platform]} {name_map[platform]} Top 5</b>", ""]
        for i, r in enumerate(rows, 1):
            r = dict(r)
            lines.append(f"{i}. <b>{_esc(r['title'][:40])}</b>")
            lines.append(f"   {r['views']:,} views | {r['favorites_count']:,} faves | {r['comments_count']:,} comments")

        await _send(token, chat_id, "\n".join(lines))
    finally:
        conn.close()


async def _cmd_trending(token: str, chat_id: str, args: str) -> None:
    conn = get_connection()
    try:
        results = get_trending_submissions(conn)
        if not results:
            await _send(token, chat_id, "No trending submissions detected.")
            return

        lines = ["<b>🔥 Trending Submissions</b>", ""]
        for r in results[:5]:
            emoji = {"ib": "🐾", "fa": "🦊", "ws": "🦎", "sf": "🐺"}.get(r["platform"], "")
            lines.append(f"{emoji} <b>{_esc(r['title'][:35])}</b> (z={r['max_z']})")
            for metric, info in r["spikes"].items():
                label = metric.replace("_count", "").replace("favorites", "faves")
                lines.append(f"   +{info['delta']} {label} (avg {info['mean']})")

        await _send(token, chat_id, "\n".join(lines))
    finally:
        conn.close()


async def _cmd_digest(token: str, chat_id: str, args: str) -> None:
    from polling.telegram import send_digest_report
    try:
        await send_digest_report()
        await _send(token, chat_id, "Digest sent.")
    except Exception as e:
        await _send(token, chat_id, f"Digest failed: {_esc(str(e)[:200])}")


async def _cmd_fans(token: str, chat_id: str, args: str) -> None:
    conn = get_connection()
    try:
        fans = get_top_fans(conn, limit=10)
        if not fans:
            await _send(token, chat_id, "No fan data yet.")
            return

        lines = ["<b>⭐ Top Fans</b>", ""]
        for i, f in enumerate(fans, 1):
            plats = ", ".join(f["platforms"])
            lines.append(f"{i}. <b>{_esc(f['username'])}</b> — score {f['score']} ({f['fave_count']} faves, {f['comment_count']} comments) [{plats}]")

        await _send(token, chat_id, "\n".join(lines))
    finally:
        conn.close()


async def _cmd_poll(token: str, chat_id: str, args: str) -> None:
    platform = args.strip().lower() if args.strip() else "all"
    valid = {"ib", "fa", "ws", "sf", "all"}
    if platform not in valid:
        await _send(token, chat_id, "Usage: /poll [ib|fa|ws|sf|all]")
        return

    targets = ["ib", "fa", "ws", "sf"] if platform == "all" else [platform]
    name_map = {"ib": "Inkbunny", "fa": "FurAffinity", "ws": "Weasyl", "sf": "SoFurry"}

    await _send(token, chat_id, f"Starting poll for: {', '.join(name_map[t] for t in targets)}...")

    from polling.poller import run_poll_cycle
    from polling.fa_poller import run_fa_poll_cycle
    from polling.ws_poller import run_ws_poll_cycle
    from polling.sf_poller import run_sf_poll_cycle

    poll_funcs = {"ib": run_poll_cycle, "fa": run_fa_poll_cycle, "ws": run_ws_poll_cycle, "sf": run_sf_poll_cycle}

    results = []
    for t in targets:
        try:
            stats = await poll_funcs[t]()
            subs = stats.get("submissions_found", 0)
            results.append(f"{name_map[t]}: {subs} subs polled")
        except Exception as e:
            results.append(f"{name_map[t]}: failed — {_esc(str(e)[:100])}")

    await _send(token, chat_id, "\n".join(results))


async def _cmd_status(token: str, chat_id: str, args: str) -> None:
    conn = get_connection()
    try:
        lines = ["<b>📋 Poll Status</b>", ""]

        # Resolve display timezone
        settings = config.get_settings()
        tz_name = settings.get("display_timezone", "UTC")
        try:
            tz = ZoneInfo(tz_name)
        except (KeyError, Exception):
            tz = timezone.utc

        poll_funcs = [
            ("🐾 Inkbunny", queries.get_last_poll),
            ("🦊 FurAffinity", fa_queries.get_fa_last_poll),
            ("🦎 Weasyl", ws_queries.get_ws_last_poll),
            ("🐺 SoFurry", sf_queries.get_sf_last_poll),
        ]

        for name, func in poll_funcs:
            try:
                poll = func(conn)
                if poll:
                    status = poll.get("status", "?")
                    raw_time = poll.get("started_at", "")
                    # Convert stored UTC timestamp to display timezone
                    if raw_time:
                        try:
                            dt = datetime.fromisoformat(raw_time.replace(" ", "T"))
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            local = dt.astimezone(tz)
                            time_str = local.strftime("%Y-%m-%d %H:%M %Z")
                        except (ValueError, TypeError):
                            time_str = raw_time
                    else:
                        time_str = "?"
                    dur = poll.get("duration_seconds")
                    dur_str = f" ({dur:.1f}s)" if dur else ""
                    err = poll.get("error_message")
                    lines.append(f"<b>{name}</b>")
                    lines.append(f"  Last: {time_str}{dur_str} — {status}")
                    if err:
                        lines.append(f"  Error: {_esc(err[:100])}")
                else:
                    lines.append(f"<b>{name}</b>: No polls recorded")
            except Exception:
                lines.append(f"<b>{name}</b>: No data")

        # Show poll intervals
        settings = config.get_settings()
        lines.append("")
        lines.append("<b>Intervals</b>")
        lines.append(f"  IB: {settings.get('poll_interval_minutes', 60)} min")
        lines.append(f"  FA: {settings.get('fa_poll_interval_minutes', 60)} min")
        lines.append(f"  WS: {settings.get('ws_poll_interval_minutes', 60)} min")
        lines.append(f"  SF: {settings.get('sf_poll_interval_minutes', 60)} min")

        await _send(token, chat_id, "\n".join(lines))
    finally:
        conn.close()


async def _cmd_interval(token: str, chat_id: str, args: str) -> None:
    parts = args.strip().lower().split()
    if len(parts) != 2:
        await _send(token, chat_id, "Usage: /interval [ib|fa|ws|sf] [minutes]")
        return

    platform, minutes_str = parts
    key_map = {
        "ib": "poll_interval_minutes",
        "fa": "fa_poll_interval_minutes",
        "ws": "ws_poll_interval_minutes",
        "sf": "sf_poll_interval_minutes",
    }
    name_map = {"ib": "Inkbunny", "fa": "FurAffinity", "ws": "Weasyl", "sf": "SoFurry"}

    if platform not in key_map:
        await _send(token, chat_id, "Platform must be: ib, fa, ws, sf")
        return

    try:
        minutes = int(minutes_str)
        if minutes < 15:
            await _send(token, chat_id, "Minimum interval is 15 minutes.")
            return
    except ValueError:
        await _send(token, chat_id, "Minutes must be a number.")
        return

    config.save_settings({key_map[platform]: minutes})
    await _send(token, chat_id, f"{name_map[platform]} poll interval set to {minutes} minutes.")


async def _cmd_notify(token: str, chat_id: str, args: str) -> None:
    settings = config.get_settings()

    # Notification type -> settings key mapping
    toggle_map = {
        "summaries": "telegram_poll_summaries",
        "errors": "telegram_error_alerts",
        "milestones": "telegram_milestones",
        "digest": "telegram_digest",
        "faves": "notification_comments_only",  # inverted — comments_only=True means faves OFF
        "comments": "notifications_enabled",  # master toggle for IB
        "watchers": "watcher_notifications_enabled",
        "ib": "notifications_enabled",
        "fa": "fa_notifications_enabled",
        "ws": "ws_notifications_enabled",
        "sf": "sf_notifications_enabled",
    }

    parts = args.strip().lower().split()

    # No args — show current state
    if not parts:
        lines = ["<b>🔔 Notification Settings</b>", ""]

        lines.append("<b>Telegram Features</b>")
        lines.append(f"  Summaries: {'on' if settings.get('telegram_poll_summaries', True) else 'off'}")
        lines.append(f"  Errors: {'on' if settings.get('telegram_error_alerts', True) else 'off'}")
        lines.append(f"  Milestones: {'on' if settings.get('telegram_milestones', True) else 'off'}")
        lines.append(f"  Digest: {'on' if settings.get('telegram_digest', True) else 'off'}")

        lines.append("")
        lines.append("<b>Platform Notifications</b>")
        lines.append(f"  IB: {'on' if settings.get('notifications_enabled', True) else 'off'}")
        lines.append(f"  FA: {'on' if settings.get('fa_notifications_enabled', True) else 'off'}")
        lines.append(f"  WS: {'on' if settings.get('ws_notifications_enabled', True) else 'off'}")
        lines.append(f"  SF: {'on' if settings.get('sf_notifications_enabled', True) else 'off'}")

        lines.append("")
        lines.append("<b>Filters</b>")
        lines.append(f"  Comments only (IB): {'on' if settings.get('notification_comments_only', False) else 'off'}")
        lines.append(f"  Watcher alerts: {'on' if settings.get('watcher_notifications_enabled', True) else 'off'}")

        await _send(token, chat_id, "\n".join(lines))
        return

    if len(parts) != 2 or parts[1] not in ("on", "off"):
        await _send(token, chat_id, "Usage: /notify [type] [on|off]\nType /help for all options.")
        return

    ntype, state = parts
    enabled = state == "on"

    if ntype not in toggle_map:
        await _send(token, chat_id, f"Unknown type: {ntype}. Type /help for options.")
        return

    key = toggle_map[ntype]

    # Special case: "faves" is inverted (comments_only=True means faves OFF)
    if ntype == "faves":
        config.save_settings({key: not enabled})
        await _send(token, chat_id, f"Fave notifications: {'on' if enabled else 'off'}")
        return

    config.save_settings({key: enabled})
    await _send(token, chat_id, f"{ntype.capitalize()} notifications: {'on' if enabled else 'off'}")


# ── Command dispatcher ───────────────────────────────────────

COMMANDS = {
    "/help": _cmd_help,
    "/start": _cmd_help,
    "/stats": _cmd_stats,
    "/top": _cmd_top,
    "/trending": _cmd_trending,
    "/digest": _cmd_digest,
    "/fans": _cmd_fans,
    "/poll": _cmd_poll,
    "/status": _cmd_status,
    "/interval": _cmd_interval,
    "/notify": _cmd_notify,
}


async def _handle_message(token: str, chat_id: str, text: str) -> None:
    """Parse and dispatch a single message."""
    text = text.strip()
    if not text.startswith("/"):
        return

    # Split "/command args" — handle @botname suffix (e.g. /stats@PawPollerBot)
    parts = text.split(None, 1)
    cmd = parts[0].split("@")[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    handler = COMMANDS.get(cmd)
    if handler:
        try:
            await handler(token, chat_id, args)
        except Exception as e:
            logger.error("Bot command %s failed: %s", cmd, e)
            await _send(token, chat_id, f"Command failed: {_esc(str(e)[:200])}")
    else:
        await _send(token, chat_id, f"Unknown command: {_esc(cmd)}\nType /help for available commands.")


# ── Main bot loop ────────────────────────────────────────────

async def run_bot() -> None:
    """Main bot loop — polls for updates and dispatches commands."""
    global _last_update_id

    settings = config.get_settings()
    if not settings.get("telegram_enabled", False):
        logger.info("Telegram bot disabled — not starting command listener")
        return

    token = settings.get("telegram_bot_token")
    chat_id = settings.get("telegram_chat_id")
    if not token or not chat_id:
        logger.info("Telegram bot not configured — skipping command listener")
        return

    logger.info("Telegram bot command listener started")

    # Flush old updates on startup so we don't process stale commands
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"offset": -1},
            )
            data = resp.json()
            results = data.get("result", [])
            if results:
                _last_update_id = results[-1]["update_id"]
                logger.info("Flushed %d old Telegram updates", len(results))
    except Exception as e:
        logger.warning("Failed to flush old updates: %s", e)

    while True:
        # Re-read settings each loop in case Telegram gets disconnected
        settings = config.get_settings()
        if not settings.get("telegram_enabled", False):
            await asyncio.sleep(30)
            continue

        token = settings.get("telegram_bot_token", "")
        if not token:
            await asyncio.sleep(30)
            continue

        updates = await _poll_updates(token)
        for update in updates:
            msg = update.get("message", {})
            text = msg.get("text", "")
            msg_chat_id = str(msg.get("chat", {}).get("id", ""))

            # Only respond to the configured chat (security)
            if msg_chat_id != str(chat_id):
                continue

            if text:
                await _handle_message(token, chat_id, text)
