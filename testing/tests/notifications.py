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
    test_id="notifications.digest.builder",
    name="Telegram digest text builder",
    category="Notifications",
    description="Build (but do not send) the 6-hour digest text. Read-only.",
)
async def t_digest_builder(ctx: TestContext) -> None:
    try:
        from polling import telegram as tg
    except ImportError:
        raise ctx.skip("polling.telegram unavailable")
    builder = (
        getattr(tg, "build_digest_text", None)
        or getattr(tg, "format_digest_report", None)
        or getattr(tg, "build_digest_report", None)
    )
    if builder is None:
        raise ctx.skip("no digest builder helper exposed on polling.telegram")
    text = builder() if callable(builder) else ""
    if hasattr(text, "__await__"):  # in case async
        text = await text
    ctx.detail("bytes", len(str(text)))
    ctx.detail("preview", str(text)[:120])
    assert isinstance(text, str), f"digest builder returned {type(text).__name__}"
