"""Unified entry point — server + poller + native desktop window.

Architecture overview
---------------------
PawPoller runs as a single process with **6 daemon threads** plus the main
thread:

  Thread 1 (daemon): Uvicorn web server   -- serves the FastAPI dashboard
  Thread 2 (daemon): Inkbunny poller       -- periodic IB stat collection
  Thread 3 (daemon): FurAffinity poller    -- periodic FA stat collection
  Thread 4 (daemon): Weasyl poller         -- periodic WS stat collection
  Thread 5 (daemon): SoFurry poller        -- periodic SF stat collection
  Thread 6 (daemon): pystray tray icon     -- system tray menu/icon

  Main thread:       pywebview window      -- native desktop GUI wrapper

All background threads are **daemon threads** so they are killed automatically
when the main thread (pywebview) exits.  This avoids zombie processes and
means we do not need explicit shutdown signalling for the pollers or server.

Each poller thread creates its own asyncio event loop because asyncio loops
are not thread-safe.  A dedicated loop per thread lets each poller use
async/await for non-blocking HTTP calls without interfering with the others.

Usage:
    python main.py          # dev mode
    PawPoller.exe   # frozen build
"""

import logging
import socket
import sys
import threading
import time
from datetime import datetime

import uvicorn

import config
from database.db import init_db


# ── Logging ───────────────────────────────────────────────────
# Dual-output logging: stdout for dev console visibility, plus a persistent
# log file under the APPDATA (frozen) or project (dev) logs directory.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(config.LOGS_DIR / "app.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")


# ── Background poller (Inkbunny) ─────────────────────────────
# Each poller below follows the same pattern:
#
# 1. Create a NEW asyncio event loop for this thread.
#    - asyncio event loops are bound to a single thread; the main thread's
#      loop (if any) cannot be reused here.  new_event_loop() + set_event_loop()
#      gives each poller its own isolated async runtime.
#
# 2. Run an infinite async loop that:
#    a) Executes one poll cycle immediately on startup (so the dashboard
#       has data right away without waiting for the first interval).
#    b) Re-reads the poll interval from settings.json EACH iteration.
#       This "dynamic interval" pattern means users can change the polling
#       frequency in the UI and it takes effect on the very next cycle
#       without restarting the app.
#    c) Sleeps for the configured interval, then polls again.
#
# 3. Credential gating: each poll cycle checks for valid credentials first
#    and silently skips if none are configured (the user might not have set
#    up that platform yet).

def _start_poller():
    """Run IB poller in its own daemon thread with a dynamic interval from settings."""
    import asyncio
    from polling.poller import run_poll_cycle

    async def _scheduled_poll():
        # Gate on credentials -- skip gracefully if user has not configured IB yet
        from routes.api import get_effective_credentials
        username, password = get_effective_credentials()
        if not username or not password:
            logger.info("Scheduled IB poll skipped — no credentials configured")
            return
        try:
            await run_poll_cycle()
        except Exception as e:
            logger.error("Scheduled IB poll failed: %s", e)

    async def _run():
        logger.info("IB poller loop started")
        while True:
            # Re-read interval each cycle so UI changes take effect without restart
            settings = config.get_settings()
            interval = max(1, int(settings.get("poll_interval_minutes", 60)))
            logger.info("Next IB poll in %d minutes", interval)
            await asyncio.sleep(interval * 60)
            if config.get_settings().get("polling_paused"):
                logger.info("IB poll skipped -- polling is paused")
                continue
            await _scheduled_poll()

    # Each poller thread needs its own event loop (asyncio loops are single-threaded)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception as e:
        logger.debug("IB poller thread exiting: %s", e)  # Daemon teardown


# ── Background FA poller ──────────────────────────────────────
# Same daemon-thread + own-event-loop + dynamic-interval pattern as IB above.
# FA uses cookie-based auth (cookie_a / cookie_b) rather than user/pass.

def _start_fa_poller():
    """Run FA poller in its own daemon thread with a dynamic interval from settings."""
    import asyncio
    from polling.fa_poller import run_fa_poll_cycle

    async def _scheduled_fa_poll():
        settings = config.get_settings()
        # FA requires both a username and at least cookie_a to authenticate
        if not settings.get("fa_username") or not settings.get("fa_cookie_a"):
            logger.info("Scheduled FA poll skipped — no FA credentials configured")
            return
        try:
            await run_fa_poll_cycle()
        except Exception as e:
            logger.error("Scheduled FA poll failed: %s", e)

    async def _run():
        logger.info("FA poller loop started")
        while True:
            settings = config.get_settings()
            interval = settings.get("fa_poll_interval_minutes", 60)
            logger.info("Next FA poll in %d minutes", interval)
            await asyncio.sleep(interval * 60)
            if config.get_settings().get("polling_paused"):
                logger.info("FA poll skipped -- polling is paused")
                continue
            await _scheduled_fa_poll()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception as e:
        logger.debug("FA poller thread exiting: %s", e)  # Daemon teardown


# ── Background WS poller ─────────────────────────────────────
# Same pattern again.  Weasyl uses a simple API key for auth.

def _start_ws_poller():
    """Run Weasyl poller in its own daemon thread with a dynamic interval from settings."""
    import asyncio
    from polling.ws_poller import run_ws_poll_cycle

    async def _scheduled_ws_poll():
        settings = config.get_settings()
        if not settings.get("ws_api_key"):
            logger.info("Scheduled WS poll skipped — no Weasyl API key configured")
            return
        try:
            await run_ws_poll_cycle()
        except Exception as e:
            logger.error("Scheduled WS poll failed: %s", e)

    async def _run():
        logger.info("WS poller loop started")
        while True:
            settings = config.get_settings()
            interval = settings.get("ws_poll_interval_minutes", 60)
            logger.info("Next WS poll in %d minutes", interval)
            await asyncio.sleep(interval * 60)
            if config.get_settings().get("polling_paused"):
                logger.info("WS poll skipped -- polling is paused")
                continue
            await _scheduled_ws_poll()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception as e:
        logger.debug("WS poller thread exiting: %s", e)  # Daemon teardown


# ── Background SF poller ─────────────────────────────────────
# Same pattern as the other pollers.  SoFurry uses email/password login.

def _start_sf_poller():
    """Run SoFurry poller in its own daemon thread with a dynamic interval from settings."""
    import asyncio
    from polling.sf_poller import run_sf_poll_cycle

    async def _scheduled_sf_poll():
        settings = config.get_settings()
        if not settings.get("sf_username") or not settings.get("sf_password"):
            logger.info("Scheduled SF poll skipped — no SoFurry credentials configured")
            return
        try:
            await run_sf_poll_cycle()
        except Exception as e:
            logger.error("Scheduled SF poll failed: %s", e)

    async def _run():
        logger.info("SF poller loop started")
        while True:
            settings = config.get_settings()
            interval = settings.get("sf_poll_interval_minutes", 60)
            logger.info("Next SF poll in %d minutes", interval)
            await asyncio.sleep(interval * 60)
            if config.get_settings().get("polling_paused"):
                logger.info("SF poll skipped -- polling is paused")
                continue
            await _scheduled_sf_poll()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception as e:
        logger.debug("SF poller thread exiting: %s", e)  # Daemon teardown


# ── Background SqW poller ────────────────────────────────────
# SquidgeWorld uses OTW Archive login (username/password + CSRF token).

def _start_sqw_poller():
    """Run SquidgeWorld poller in its own daemon thread with a dynamic interval from settings."""
    import asyncio
    from polling.sqw_poller import run_sqw_poll_cycle

    async def _scheduled_sqw_poll():
        settings = config.get_settings()
        if not settings.get("sqw_username") or not settings.get("sqw_password"):
            logger.info("Scheduled SqW poll skipped — no SquidgeWorld credentials configured")
            return
        try:
            await run_sqw_poll_cycle()
        except Exception as e:
            logger.error("Scheduled SqW poll failed: %s", e)

    async def _run():
        logger.info("SqW poller loop started")
        while True:
            settings = config.get_settings()
            interval = settings.get("sqw_poll_interval_minutes", 60)
            logger.info("Next SqW poll in %d minutes", interval)
            await asyncio.sleep(interval * 60)
            if config.get_settings().get("polling_paused"):
                logger.info("SqW poll skipped -- polling is paused")
                continue
            await _scheduled_sqw_poll()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception as e:
        logger.debug("SqW poller thread exiting: %s", e)  # Daemon teardown


# ── Background AO3 poller ─────────────────────────────────────
# AO3 uses OTW Archive login (username/password + CSRF token), same as SqW.

def _start_ao3_poller():
    """Run AO3 poller in its own daemon thread with a dynamic interval from settings."""
    import asyncio
    from polling.ao3_poller import run_ao3_poll_cycle

    async def _scheduled_ao3_poll():
        settings = config.get_settings()
        if not settings.get("ao3_username") or not settings.get("ao3_password"):
            logger.info("Scheduled AO3 poll skipped — no AO3 credentials configured")
            return
        try:
            await run_ao3_poll_cycle()
        except Exception as e:
            logger.error("Scheduled AO3 poll failed: %s", e)

    async def _run():
        logger.info("AO3 poller loop started")
        while True:
            settings = config.get_settings()
            interval = settings.get("ao3_poll_interval_minutes", 60)
            logger.info("Next AO3 poll in %d minutes", interval)
            await asyncio.sleep(interval * 60)
            if config.get_settings().get("polling_paused"):
                logger.info("AO3 poll skipped -- polling is paused")
                continue
            await _scheduled_ao3_poll()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception as e:
        logger.debug("AO3 poller thread exiting: %s", e)  # Daemon teardown


# ── Background DA poller ──────────────────────────────────────
# DeviantArt uses cookie-based auth with Eclipse _napi endpoints.

def _start_da_poller():
    """Run DeviantArt poller in its own daemon thread with a dynamic interval from settings."""
    import asyncio
    from polling.da_poller import run_da_poll_cycle

    async def _scheduled_da_poll():
        settings = config.get_settings()
        if not settings.get("da_cookie") or not settings.get("da_target_user"):
            logger.info("Scheduled DA poll skipped — no DeviantArt credentials configured")
            return
        try:
            await run_da_poll_cycle()
        except Exception as e:
            logger.error("Scheduled DA poll failed: %s", e)

    async def _run():
        logger.info("DA poller loop started")
        while True:
            settings = config.get_settings()
            interval = settings.get("da_poll_interval_minutes", 60)
            logger.info("Next DA poll in %d minutes", interval)
            await asyncio.sleep(interval * 60)
            if config.get_settings().get("polling_paused"):
                logger.info("DA poll skipped -- polling is paused")
                continue
            await _scheduled_da_poll()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception as e:
        logger.debug("DA poller thread exiting: %s", e)  # Daemon teardown


# ── Background WP poller ──────────────────────────────────────
# Wattpad has a public API — no auth needed, just a target username.

def _start_wp_poller():
    """Run Wattpad poller in its own daemon thread with a dynamic interval from settings."""
    import asyncio
    from polling.wp_poller import run_wp_poll_cycle

    async def _scheduled_wp_poll():
        settings = config.get_settings()
        if not settings.get("wp_target_user"):
            logger.info("Scheduled WP poll skipped — no Wattpad username configured")
            return
        try:
            await run_wp_poll_cycle()
        except Exception as e:
            logger.error("Scheduled WP poll failed: %s", e)

    async def _run():
        logger.info("WP poller loop started")
        while True:
            settings = config.get_settings()
            interval = settings.get("wp_poll_interval_minutes", 60)
            logger.info("Next WP poll in %d minutes", interval)
            await asyncio.sleep(interval * 60)
            if config.get_settings().get("polling_paused"):
                logger.info("WP poll skipped -- polling is paused")
                continue
            await _scheduled_wp_poll()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception as e:
        logger.debug("WP poller thread exiting: %s", e)  # Daemon teardown


# ── Background IK poller ──────────────────────────────────────
# Itaku has a public API — no auth needed, just a target username.

def _start_ik_poller():
    """Run Itaku poller in its own daemon thread with a dynamic interval from settings."""
    import asyncio
    from polling.ik_poller import run_ik_poll_cycle

    async def _scheduled_ik_poll():
        settings = config.get_settings()
        if not settings.get("ik_target_user"):
            logger.info("Scheduled IK poll skipped — no Itaku username configured")
            return
        try:
            await run_ik_poll_cycle()
        except Exception as e:
            logger.error("Scheduled IK poll failed: %s", e)

    async def _run():
        logger.info("IK poller loop started")
        while True:
            settings = config.get_settings()
            interval = settings.get("ik_poll_interval_minutes", 60)
            logger.info("Next IK poll in %d minutes", interval)
            await asyncio.sleep(interval * 60)
            if config.get_settings().get("polling_paused"):
                logger.info("IK poll skipped -- polling is paused")
                continue
            await _scheduled_ik_poll()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception as e:
        logger.debug("IK poller thread exiting: %s", e)  # Daemon teardown


# ── Background BSKY poller ─────────────────────────────────────
# Bluesky uses AT Protocol with app password auth (identifier + app_password).

def _start_bsky_poller():
    """Run Bluesky poller in its own daemon thread with a dynamic interval from settings."""
    import asyncio
    from polling.bsky_poller import run_bsky_poll_cycle

    async def _scheduled_bsky_poll():
        settings = config.get_settings()
        if not settings.get("bsky_identifier") or not settings.get("bsky_app_password"):
            logger.info("Scheduled BSKY poll skipped — no Bluesky credentials configured")
            return
        try:
            await run_bsky_poll_cycle()
        except Exception as e:
            logger.error("Scheduled BSKY poll failed: %s", e)

    async def _run():
        logger.info("BSKY poller loop started")
        while True:
            settings = config.get_settings()
            interval = settings.get("bsky_poll_interval_minutes", 60)
            logger.info("Next BSKY poll in %d minutes", interval)
            await asyncio.sleep(interval * 60)
            if config.get_settings().get("polling_paused"):
                logger.info("BSKY poll skipped -- polling is paused")
                continue
            await _scheduled_bsky_poll()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception as e:
        logger.debug("BSKY poller thread exiting: %s", e)  # Daemon teardown


# ── Background TW poller ──────────────────────────────────────
# X/Twitter uses cookie-based auth (auth_token + ct0 from browser).

def _start_tw_poller():
    """Run X/Twitter poller in its own daemon thread with a dynamic interval from settings."""
    import asyncio
    from polling.tw_poller import run_tw_poll_cycle

    async def _scheduled_tw_poll():
        settings = config.get_settings()
        if not settings.get("tw_auth_token") or not settings.get("tw_target_user"):
            logger.info("Scheduled TW poll skipped — no X/Twitter credentials configured")
            return
        try:
            await run_tw_poll_cycle()
        except Exception as e:
            logger.error("Scheduled TW poll failed: %s", e)

    async def _run():
        logger.info("TW poller loop started")
        while True:
            settings = config.get_settings()
            interval = settings.get("tw_poll_interval_minutes", 60)
            logger.info("Next TW poll in %d minutes", interval)
            await asyncio.sleep(interval * 60)
            if config.get_settings().get("polling_paused"):
                logger.info("TW poll skipped -- polling is paused")
                continue
            await _scheduled_tw_poll()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception as e:
        logger.debug("TW poller thread exiting: %s", e)  # Daemon teardown


# ── 6-Hourly Telegram Digest ─────────────────────────────────
# Sends a cross-platform stats digest every 6 hours via Telegram.
# Uses its own asyncio event loop like the pollers.

def _start_digest_scheduler():
    """Run periodic Telegram digest in its own daemon thread."""
    import asyncio
    from datetime import datetime, timezone
    from polling.telegram import send_digest_report

    def _get_digest_interval() -> int:
        """Read digest interval from settings (in seconds)."""
        hours = config.get_settings().get("telegram_digest_interval_hours", 6)
        return max(int(hours), 1) * 60 * 60

    def _seconds_until_next_digest() -> float:
        """Calculate seconds until next digest is due, respecting last sent time."""
        digest_interval = _get_digest_interval()
        MIN_STARTUP_DELAY = 300         # 5 minutes minimum after startup
        last = config.get_settings().get("last_digest_sent_at")
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
                remaining = digest_interval - elapsed
                if remaining > MIN_STARTUP_DELAY:
                    return remaining
                return MIN_STARTUP_DELAY
            except (ValueError, TypeError):
                pass
        return MIN_STARTUP_DELAY  # First ever digest — wait 5 min for pollers

    async def _run():
        initial_delay = _seconds_until_next_digest()
        logger.info("Telegram digest scheduler started (next digest in %.0f min)", initial_delay / 60)
        await asyncio.sleep(initial_delay)
        while True:
            try:
                await send_digest_report()
            except Exception as e:
                logger.error("Digest report failed: %s", e)
            await asyncio.sleep(_get_digest_interval())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception as e:
        logger.debug("Digest scheduler thread exiting: %s", e)  # Daemon teardown


# ── Telegram Bot Command Listener ─────────────────────────────
# Long-polls Telegram for incoming commands and dispatches them.

def _start_telegram_bot():
    """Run Telegram bot command listener in its own daemon thread."""
    import asyncio
    from polling.telegram_bot import run_bot

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_bot())
    except Exception as e:
        logger.debug("Telegram bot thread exiting: %s", e)  # Daemon teardown


# ── Background web server (uvicorn) ──────────────────────────
# The FastAPI dashboard is served by uvicorn in a daemon thread.
# pywebview (the native window) points its embedded browser at this
# local server, so the entire UI is just a web app rendered natively.
# Running as a daemon thread means it dies automatically when main exits.

def _start_server():
    """Run uvicorn in a daemon thread."""
    logger.info("Uvicorn thread starting...")
    try:
        # Import here (not at top-level) to avoid circular imports --
        # dashboard module may import config, and config is still
        # being initialised when top-level imports run.
        from dashboard import app as dash_app
        uvicorn.run(
            dash_app,
            host=config.DASHBOARD_HOST,
            port=config.DASHBOARD_PORT,
            log_level="info",
        )
    except Exception as e:
        logger.error("Uvicorn failed to start: %s", e, exc_info=True)


# ── System tray (pystray) ────────────────────────────────────
# The tray icon provides a "minimize to tray" experience: when the user
# closes the window with tray mode enabled, the window hides instead of
# destroying, and the tray icon becomes visible so they can restore it.
#
# Lifecycle:
#   1. Tray icon is CREATED and its thread is STARTED during main(), but
#      it begins with visible=False (via a no-op setup callback) so the
#      icon does not appear in the system tray until the user minimises.
#   2. When the user closes the window and minimize_to_tray is on,
#      _on_closing() hides the window and sets tray visible=True.
#   3. Clicking "Show" in the tray menu restores the window and hides
#      the tray icon again.
#   4. Clicking "Quit" in the tray menu destroys both the window and the
#      tray icon, which unblocks webview.start() and lets main() exit.

_tray_icon = None   # pystray.Icon instance, set in main()
_window = None      # pywebview window instance, set in main()


def _load_tray_image():
    """Load the tray icon image via Pillow."""
    from PIL import Image
    icon_path = config.resource_path("assets/tray_icon.png")
    try:
        return Image.open(str(icon_path))
    except Exception:
        # Fallback: procedurally generate a simple bar-chart icon if the
        # asset file is missing (e.g. during early dev or broken build)
        from PIL import ImageDraw
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, 62, 62], fill=(34, 37, 47, 255), outline=(108, 140, 255, 255), width=2)
        draw.rectangle([14, 38, 22, 50], fill=(108, 140, 255, 255))
        draw.rectangle([26, 28, 34, 50], fill=(108, 140, 255, 255))
        draw.rectangle([38, 18, 46, 50], fill=(108, 140, 255, 255))
        return img


def _show_window(icon=None, item=None):
    """Restore the pywebview window from tray.

    Called when the user clicks "Show" in the tray context menu (or
    double-clicks the tray icon, since Show is marked as default=True).
    """
    global _window
    if _window is not None:
        _window.show()           # Make the hidden pywebview window visible again
    if _tray_icon is not None:
        _tray_icon.visible = False  # Hide the tray icon until next minimize


def _quit_app(icon=None, item=None):
    """Full exit -- destroy window and stop tray icon.

    Stopping the tray icon ends its thread, and destroying the window
    unblocks webview.start() in main(), allowing the process to exit.
    """
    global _tray_icon, _window
    logger.info("Quit requested from tray — shutting down.")
    if _tray_icon is not None:
        _tray_icon.stop()
        _tray_icon = None
    if _window is not None:
        _window.destroy()  # Unblocks webview.start() in main()


def _create_tray_icon():
    """Create the pystray system tray icon (not yet started).

    The icon is created here but NOT run -- main() starts it in a separate
    daemon thread with a no-op setup callback to keep it initially hidden.
    """
    import pystray
    from pystray import MenuItem

    image = _load_tray_image()
    menu = pystray.Menu(
        MenuItem("Show", _show_window, default=True),  # default=True: double-click action
        MenuItem("Quit", _quit_app),
    )
    icon = pystray.Icon("PawPoller", image, "PawPoller", menu)
    return icon


def _minimize_to_tray_enabled() -> bool:
    """Check whether 'minimize to tray' is enabled in settings.

    When disabled (default), closing the window exits the app normally.
    When enabled, closing hides to tray instead.
    """
    settings = config.get_settings()
    return settings.get("minimize_to_tray", False)


def _on_closing():
    """pywebview closing callback -- intercepts the window close event.

    pywebview calls this before destroying the window.  The return value
    controls behaviour:
      - return False: CANCEL the close, keeping the window alive (hidden).
        Used when minimize_to_tray is on -- we hide the window and show
        the tray icon instead of exiting.
      - return True: ALLOW the close, which destroys the window and
        unblocks webview.start(), letting main() proceed to shutdown.
    """
    global _tray_icon, _window
    if _minimize_to_tray_enabled():
        logger.info("Minimising to system tray instead of closing.")
        if _window is not None:
            _window.hide()        # Hide window but keep process running
        if _tray_icon is not None:
            _tray_icon.visible = True  # Show tray icon so user can restore
        return False  # Cancel the close -- window stays alive but hidden
    return True  # Allow normal close -- app will exit


# ── Main ──────────────────────────────────────────────────────
# Startup sequence:
#   1. Initialise the SQLite database (create tables if first run)
#   2. Launch 4 daemon threads: web server + 3 platform pollers
#   3. Launch the system tray icon in a 5th daemon thread (hidden)
#   4. Block until the uvicorn server is accepting TCP connections
#   5. Open the pywebview native window pointing at the local server
#   6. webview.start() blocks the main thread until the window is destroyed
#   7. On exit, clean up the tray icon and let daemon threads die

def _sync_settings_on_startup():
    """Pull settings from server if credential_mode is 'cloud' and a server URL is configured."""
    import httpx

    settings = config.get_settings()
    if settings.get("credential_mode") == "local":
        logger.info("Settings sync: local-only mode, skipping")
        return

    server_url = settings.get("posting_server_url", "").rstrip("/")
    api_key = settings.get("posting_server_api_key", "")
    if not server_url or not api_key:
        logger.debug("Settings sync: no server URL or API key configured, skipping")
        return

    try:
        resp = httpx.post(
            f"{server_url}/api/settings/sync",
            json={"mode": "pull"},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning("Settings sync pull failed: HTTP %d", resp.status_code)
            return
        data = resp.json()
        if data.get("ok") and data.get("settings"):
            pulled = data["settings"]
            config.merge_synced_settings(pulled)
            logger.info("Settings sync: pulled %d keys from server", len(pulled))
        else:
            logger.warning("Settings sync: server returned ok=false")
    except Exception as e:
        logger.warning("Settings sync: pull failed (server unreachable?): %s", e)


def main():
    global _tray_icon, _window

    # --- Step 1: Database initialisation ---
    logger.info("Initialising database...")
    init_db()  # Creates tables/schema if the DB file does not exist yet

    # --- Step 1b: Sync settings from server (cloud mode) ---
    _sync_settings_on_startup()

    # --- Step 1c: Start the recurring background pull thread so settings
    # changed on another device flow back into this desktop install
    # without requiring a restart.
    try:
        import auto_sync
        auto_sync.start_pull_thread()
        logger.info("Auto-sync pull thread started (every %ds)",
                    auto_sync.AUTO_SYNC_PULL_INTERVAL_SECONDS)
    except Exception as e:
        logger.warning("Auto-sync pull thread failed to start: %s", e)

    # --- Step 2: Launch daemon threads ---
    # All threads are daemon=True so they terminate automatically when
    # the main thread (pywebview) exits.  No explicit shutdown is needed.

    logger.info("Starting web server on http://%s:%d", config.DASHBOARD_HOST, config.DASHBOARD_PORT)
    server_thread = threading.Thread(target=_start_server, daemon=True)
    server_thread.start()

    # --- Polling ownership gate ---
    # If this desktop install is paired with a remote server, the server
    # owns the poll loop. Starting our own pollers would duplicate every
    # request and double-fire "all polls complete" notifications.
    polling_owner = config.get_polling_owner("desktop")
    setup_mode = config.get_settings().get("setup_mode") or "(inferred)"
    if polling_owner == "local":
        logger.info("Polling owner: local desktop (mode=%s) — starting %d poller threads",
                    setup_mode, 11)

        logger.info("Starting background poller...")
        poller_thread = threading.Thread(target=_start_poller, daemon=True)
        poller_thread.start()

        logger.info("Starting FA background poller...")
        fa_poller_thread = threading.Thread(target=_start_fa_poller, daemon=True)
        fa_poller_thread.start()

        logger.info("Starting WS background poller...")
        ws_poller_thread = threading.Thread(target=_start_ws_poller, daemon=True)
        ws_poller_thread.start()

        logger.info("Starting SF background poller...")
        sf_poller_thread = threading.Thread(target=_start_sf_poller, daemon=True)
        sf_poller_thread.start()

        logger.info("Starting SqW background poller...")
        sqw_poller_thread = threading.Thread(target=_start_sqw_poller, daemon=True)
        sqw_poller_thread.start()

        logger.info("Starting AO3 background poller...")
        ao3_poller_thread = threading.Thread(target=_start_ao3_poller, daemon=True)
        ao3_poller_thread.start()

        logger.info("Starting DA background poller...")
        da_poller_thread = threading.Thread(target=_start_da_poller, daemon=True)
        da_poller_thread.start()

        logger.info("Starting WP background poller...")
        wp_poller_thread = threading.Thread(target=_start_wp_poller, daemon=True)
        wp_poller_thread.start()

        logger.info("Starting IK background poller...")
        ik_poller_thread = threading.Thread(target=_start_ik_poller, daemon=True)
        ik_poller_thread.start()

        logger.info("Starting BSKY background poller...")
        bsky_poller_thread = threading.Thread(target=_start_bsky_poller, daemon=True)
        bsky_poller_thread.start()

        logger.info("Starting TW background poller...")
        tw_poller_thread = threading.Thread(target=_start_tw_poller, daemon=True)
        tw_poller_thread.start()

        logger.info("Starting Telegram digest scheduler...")
        digest_thread = threading.Thread(target=_start_digest_scheduler, daemon=True)
        digest_thread.start()
    else:
        logger.info("Polling owner: remote server (mode=%s) — local pollers + digest skipped",
                    setup_mode)

    # The Telegram bot, posting scheduler, and uvicorn server run regardless
    # of polling ownership. The bot listens for /poll commands the user might
    # send manually, and posting is a desktop-side action even when paired.
    logger.info("Starting Telegram bot command listener...")
    bot_thread = threading.Thread(target=_start_telegram_bot, daemon=True)
    bot_thread.start()

    logger.info("Starting posting scheduler...")
    from posting.scheduler import start_posting_scheduler
    posting_thread = threading.Thread(target=start_posting_scheduler, daemon=True, name="Posting scheduler")
    posting_thread.start()

    # --- Step 3: System tray icon (initially hidden) ---
    _tray_icon = _create_tray_icon()
    # pystray's default setup callback sets visible=True, which would show
    # the tray icon immediately.  We pass a no-op lambda to override that
    # behaviour so the icon starts HIDDEN and only appears when the user
    # triggers minimize-to-tray via _on_closing().
    tray_thread = threading.Thread(
        target=_tray_icon.run,
        kwargs={"setup": lambda icon: None},  # No-op: keep icon hidden on start
        daemon=True,
    )
    tray_thread.start()
    logger.info("System tray icon ready.")

    # --- Step 4: Wait for the server to accept connections ---
    # The uvicorn server runs in a daemon thread and takes a moment to bind
    # the port.  We poll with TCP connect attempts (socket handshake only,
    # no HTTP request) until the port is open, with a 15-second timeout.
    # This prevents pywebview from opening a window to a server that is
    # not yet ready, which would show a blank or error page.
    url = f"http://{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}"
    logger.info("Waiting for server at %s:%d ...", config.DASHBOARD_HOST, config.DASHBOARD_PORT)
    deadline = time.time() + 15  # Absolute deadline -- 15 seconds from now
    attempts = 0
    while time.time() < deadline:
        attempts += 1
        try:
            # A successful TCP connection means uvicorn is listening
            with socket.create_connection((config.DASHBOARD_HOST, config.DASHBOARD_PORT), timeout=1.0):
                logger.info("Server ready after %d attempts (%.1fs)", attempts, time.time() - (deadline - 15))
                break
        except OSError as e:
            if attempts % 10 == 0:  # Log every ~2 seconds (10 * 0.2s) to avoid spam
                logger.info("Still waiting for server... attempt %d (%s)", attempts, e)
            time.sleep(0.2)  # 200ms between connection attempts
    else:
        # for/else: this block runs if the loop exhausted without break
        logger.error("SERVER DID NOT START within 15s after %d attempts!", attempts)
        logger.error("Server thread alive: %s", server_thread.is_alive())
        sys.exit(1)

    # --- Step 5: Open the native desktop window ---
    # pywebview creates a native OS window with an embedded browser that
    # loads the local dashboard URL.  This gives PawPoller the look and
    # feel of a native desktop app while the UI is actually a web app.
    import webview

    logger.info("Opening native window at %s", url)
    _window = webview.create_window(
        "PawPoller",
        url=url,
        width=1200,
        height=800,
        min_size=(800, 500),
    )

    # Register the closing callback so we can intercept the close event
    # and redirect to tray instead of exiting (when that setting is on).
    # pywebview uses += to add event handlers (observer pattern).
    _window.events.closing += _on_closing

    # --- Step 6: Block until the window is destroyed ---
    # webview.start() runs the native event loop on the main thread.
    # It blocks here until the window is DESTROYED (not just hidden).
    # When minimize-to-tray is active, _on_closing returns False to
    # prevent destruction, so this only unblocks on a true exit.
    #
    # On Linux force the Qt backend explicitly. pywebview's default
    # GTK backend needs PyGObject + WebKit2GTK system bindings that
    # are brittle to bundle via PyInstaller (and AppImage); Qt with
    # QtWebEngine is pip-installable, ships its own native libs, and
    # bundles cleanly. Windows and macOS use their native backend.
    _start_kwargs = {}
    if sys.platform.startswith("linux"):
        _start_kwargs["gui"] = "qt"
    webview.start(**_start_kwargs)

    # --- Step 7: Cleanup ---
    # Stop the tray icon thread if it is still running (e.g. the user
    # closed the window normally without going through tray "Quit").
    if _tray_icon is not None:
        _tray_icon.stop()

    # All daemon threads die automatically now that the main thread is exiting.
    logger.info("Window closed — shutting down.")


if __name__ == "__main__":
    main()
