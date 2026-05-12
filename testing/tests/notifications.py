"""Notification diagnostics.

Two destructive (Telegram send, Windows toast) gated behind confirm.
The digest builder is read-only.
"""

from __future__ import annotations

import time

import httpx

import config
from testing.registry import TestContext, register_test


@register_test(
    test_id="notifications.telegram.test_message",
    name="Send a test Telegram message",
    category="Notifications",
    description=(
        "DESTRUCTIVE: sends 'PawPoller diagnostics test: <timestamp>' "
        "to the configured chat. Use to confirm the bot + chat_id pair "
        "actually delivers messages."
    ),
    destructive=True,
    requires_creds=["telegram_bot_token", "telegram_chat_id"],
    timeout_seconds=15.0,
)
async def t_telegram_send(ctx: TestContext) -> None:
    s = config.get_settings()
    token = s["telegram_bot_token"]
    chat = s["telegram_chat_id"]
    text = f"PawPoller diagnostics test: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
    async with httpx.AsyncClient(timeout=10.0) as cli:
        resp = await cli.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat, "text": text},
        )
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        ctx.detail("status", resp.status_code)
        ctx.detail("ok", data.get("ok"))
        ctx.detail("message_id", data.get("result", {}).get("message_id"))
        assert resp.status_code == 200 and data.get("ok"), f"send failed: {data}"


@register_test(
    test_id="notifications.toast.send",
    name="Fire a Windows toast",
    category="Notifications",
    description=(
        "DESTRUCTIVE (visual only): shows a 'PawPoller Diagnostics' "
        "toast. Skipped on non-Windows / when winotify isn't installed."
    ),
    destructive=True,
    timeout_seconds=10.0,
)
async def t_toast(ctx: TestContext) -> None:
    try:
        from winotify import Notification
    except ImportError:
        raise ctx.skip("winotify not installed (desktop-only test)")
    n = Notification(
        app_id="PawPoller",
        title="Diagnostics",
        msg="Toast test from PawPoller Diagnostics suite",
        duration="short",
    )
    n.show()
    ctx.detail("dispatched", True)


@register_test(
    test_id="notifications.digest.data_fetch",
    name="Telegram digest data-fetch helpers",
    category="Notifications",
    description=(
        "Exercise the read-only data helpers behind send_digest_report() — "
        "_get_digest_deltas() and _get_platform_totals() — across all "
        "polling platforms. Confirms the queries the digest depends on "
        "still execute against the current schema. Does NOT send a digest."
    ),
)
async def t_digest_data_fetch(ctx: TestContext) -> None:
    try:
        from polling import telegram as tg
    except ImportError:
        raise ctx.skip("polling.telegram unavailable")
    deltas_fn = getattr(tg, "_get_digest_deltas", None)
    totals_fn = getattr(tg, "_get_platform_totals", None)
    if deltas_fn is None or totals_fn is None:
        raise ctx.skip(
            "digest data helpers (_get_digest_deltas / _get_platform_totals) "
            "not exposed on polling.telegram in this build"
        )
    from database.db import get_connection

    # The platforms the digest iterates over and their (snap_table, sub_table).
    platforms = {
        "inkbunny": ("daily_snapshots", "submissions"),
        "furaffinity": ("fa_daily_snapshots", "fa_submissions"),
        "weasyl": ("ws_daily_snapshots", "ws_submissions"),
        "sofurry": ("sf_daily_snapshots", "sf_submissions"),
        "squidgeworld": ("sqw_daily_snapshots", "sqw_works"),
        "ao3": ("ao3_daily_snapshots", "ao3_works"),
        "deviantart": ("da_daily_snapshots", "da_deviations"),
        "wattpad": ("wp_daily_snapshots", "wp_stories"),
        "itaku": ("ik_daily_snapshots", "ik_content"),
        "bluesky": ("bsky_daily_snapshots", "bsky_posts"),
    }
    conn = get_connection()
    try:
        ok: list[str] = []
        errors: dict[str, str] = {}
        for plat, (snap_t, sub_t) in platforms.items():
            try:
                deltas = deltas_fn(conn, snap_t, sub_t, plat, 6)
                totals = totals_fn(conn, sub_t, plat)
                assert isinstance(deltas, dict), f"{plat} deltas not a dict"
                assert isinstance(totals, dict), f"{plat} totals not a dict"
                ok.append(plat)
            except Exception as exc:  # noqa: BLE001
                errors[plat] = f"{type(exc).__name__}: {exc}"
        ctx.detail("ok", ok)
        ctx.detail("errors", errors)
        assert not errors, f"{len(errors)} platforms erred: {list(errors)}"
    finally:
        conn.close()
