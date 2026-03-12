"""Headless server entry point -- pollers + dashboard, no GUI.

Replicates main.py's daemon thread boot sequence minus all desktop
dependencies (pywebview, pystray, Pillow, winotify).  Designed for
Docker / Linux server deployment (e.g. Oracle Cloud ARM VM).

Usage:
    python server.py              # default port 8420
    python server.py --port 9000  # custom port
"""

import argparse
import logging
import os
import signal
import sys
import threading

import uvicorn

import config
from database.db import init_db


# ── Logging ───────────────────────────────────────────────────
# Dual-output: stdout for Docker log visibility + persistent file.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(config.LOGS_DIR / "server.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("server")

# CF proxy debug logging is extremely verbose (every request/response/cookie).
# Only enable when actively debugging proxy issues via PAWPOLLER_DEBUG_PROXY=1.
if os.environ.get("PAWPOLLER_DEBUG_PROXY"):
    logging.getLogger("polling.cf_proxy").setLevel(logging.DEBUG)


# ── Env-to-settings seeding ──────────────────────────────────
# On headless deployments there is no UI to configure credentials.
# If environment variables are set (e.g. via Docker .env file),
# seed them into settings.json so pollers pick them up through
# the normal config.get_settings() path.

_ENV_TO_SETTINGS = {
    "IB_USERNAME":      "username",
    "IB_PASSWORD":      "password",
    "FA_USERNAME":      "fa_username",
    "FA_COOKIE_A":      "fa_cookie_a",
    "FA_COOKIE_B":      "fa_cookie_b",
    "WS_API_KEY":       "ws_api_key",
    "SF_USERNAME":      "sf_username",
    "SF_PASSWORD":      "sf_password",
    "SF_DISPLAY_NAME":  "sf_display_name",
    "SQW_USERNAME":     "sqw_username",
    "SQW_PASSWORD":     "sqw_password",
    "SQW_TARGET_USER":  "sqw_target_user",
    "AO3_USERNAME":     "ao3_username",
    "AO3_PASSWORD":     "ao3_password",
    "AO3_TARGET_USER":  "ao3_target_user",
    "DA_COOKIE":        "da_cookie",
    "DA_TARGET_USER":   "da_target_user",
    "WP_TARGET_USER":   "wp_target_user",
    "IK_TARGET_USER":   "ik_target_user",
    "BSKY_IDENTIFIER":    "bsky_identifier",
    "BSKY_APP_PASSWORD":  "bsky_app_password",
    "TW_AUTH_TOKEN":      "tw_auth_token",
    "TW_CT0":             "tw_ct0",
    "TW_TARGET_USER":     "tw_target_user",
    "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
    "TELEGRAM_CHAT_ID":   "telegram_chat_id",
    "TELEGRAM_ENABLED":   "telegram_enabled",
    "DASHBOARD_PASSWORD":  "dashboard_password",
    "DASHBOARD_USER":      "dashboard_user",
    "CF_WORKER_URL":       "cf_worker_url",
    "CF_WORKER_KEY":       "cf_worker_key",
}

def _seed_settings_from_env():
    """Write env vars into settings.json, overwriting empty/missing values."""
    settings = config.get_settings()
    updates = {}
    for env_key, settings_key in _ENV_TO_SETTINGS.items():
        val = os.environ.get(env_key)
        if val:
            existing = settings.get(settings_key)
            # Overwrite if missing, empty, or different from env
            if not existing or existing != val:
                if settings_key == "telegram_enabled":
                    updates[settings_key] = val.lower() in ("true", "1", "yes")
                else:
                    updates[settings_key] = val
    if updates:
        config.save_settings(updates)
        logger.info("Seeded %d credential(s) from environment variables: %s",
                     len(updates), ", ".join(updates.keys()))


# ── Auth Migration ────────────────────────────────────────────


# ── Poller threads ────────────────────────────────────────────
# Identical async-loop-per-thread pattern from main.py.

def _start_poller():
    """Run IB poller in its own daemon thread with a dynamic interval."""
    import asyncio
    from polling.poller import run_poll_cycle

    async def _scheduled_poll():
        from routes.api import get_effective_credentials
        username, password = get_effective_credentials()
        if not username or not password:
            logger.info("Scheduled IB poll skipped -- no credentials configured")
            return
        try:
            await run_poll_cycle()
        except Exception as e:
            logger.error("Scheduled IB poll failed: %s", e)

    async def _run():
        logger.info("IB poller loop started")
        if not config.get_settings().get("polling_paused"):
            await _scheduled_poll()
        else:
            logger.info("IB initial poll skipped -- polling is paused")
        while True:
            settings = config.get_settings()
            interval = settings.get("poll_interval_minutes", 60)
            logger.info("Next IB poll in %d minutes", interval)
            await asyncio.sleep(interval * 60)
            if config.get_settings().get("polling_paused"):
                logger.info("IB poll skipped -- polling is paused")
                continue
            await _scheduled_poll()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception as e:
        logger.debug("IB poller thread exiting: %s", e)  # Daemon teardown


def _start_fa_poller():
    """Run FA poller in its own daemon thread with a dynamic interval."""
    import asyncio
    from polling.fa_poller import run_fa_poll_cycle

    async def _scheduled_fa_poll():
        settings = config.get_settings()
        if not settings.get("fa_username") or not settings.get("fa_cookie_a"):
            logger.info("Scheduled FA poll skipped -- no FA credentials configured")
            return
        try:
            await run_fa_poll_cycle()
        except Exception as e:
            logger.error("Scheduled FA poll failed: %s", e)

    async def _run():
        logger.info("FA poller loop started")
        if not config.get_settings().get("polling_paused"):
            await _scheduled_fa_poll()
        else:
            logger.info("FA initial poll skipped -- polling is paused")
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


def _start_ws_poller():
    """Run Weasyl poller in its own daemon thread with a dynamic interval."""
    import asyncio
    from polling.ws_poller import run_ws_poll_cycle

    async def _scheduled_ws_poll():
        settings = config.get_settings()
        if not settings.get("ws_api_key"):
            logger.info("Scheduled WS poll skipped -- no Weasyl API key configured")
            return
        try:
            await run_ws_poll_cycle()
        except Exception as e:
            logger.error("Scheduled WS poll failed: %s", e)

    async def _run():
        logger.info("WS poller loop started")
        if not config.get_settings().get("polling_paused"):
            await _scheduled_ws_poll()
        else:
            logger.info("WS initial poll skipped -- polling is paused")
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


def _start_sf_poller():
    """Run SoFurry poller in its own daemon thread with a dynamic interval."""
    import asyncio
    from polling.sf_poller import run_sf_poll_cycle

    async def _scheduled_sf_poll():
        settings = config.get_settings()
        if not settings.get("sf_username") or not settings.get("sf_password"):
            logger.info("Scheduled SF poll skipped -- no SoFurry credentials configured")
            return
        try:
            await run_sf_poll_cycle()
        except Exception as e:
            logger.error("Scheduled SF poll failed: %s", e)

    async def _run():
        logger.info("SF poller loop started")
        if not config.get_settings().get("polling_paused"):
            await _scheduled_sf_poll()
        else:
            logger.info("SF initial poll skipped -- polling is paused")
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


def _start_sqw_poller():
    """Run SquidgeWorld poller in its own daemon thread with a dynamic interval."""
    import asyncio
    from polling.sqw_poller import run_sqw_poll_cycle

    async def _scheduled_sqw_poll():
        settings = config.get_settings()
        if not settings.get("sqw_username") or not settings.get("sqw_password"):
            logger.info("Scheduled SqW poll skipped -- no SquidgeWorld credentials configured")
            return
        try:
            await run_sqw_poll_cycle()
        except Exception as e:
            logger.error("Scheduled SqW poll failed: %s", e)

    async def _run():
        logger.info("SqW poller loop started")
        if not config.get_settings().get("polling_paused"):
            await _scheduled_sqw_poll()
        else:
            logger.info("SqW initial poll skipped -- polling is paused")
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


def _start_ao3_poller():
    """Run AO3 poller in its own daemon thread with a dynamic interval."""
    import asyncio
    from polling.ao3_poller import run_ao3_poll_cycle

    async def _scheduled_ao3_poll():
        settings = config.get_settings()
        if not settings.get("ao3_username") or not settings.get("ao3_password"):
            logger.info("Scheduled AO3 poll skipped -- no AO3 credentials configured")
            return
        try:
            await run_ao3_poll_cycle()
        except Exception as e:
            logger.error("Scheduled AO3 poll failed: %s", e)

    async def _run():
        logger.info("AO3 poller loop started")
        if not config.get_settings().get("polling_paused"):
            await _scheduled_ao3_poll()
        else:
            logger.info("AO3 initial poll skipped -- polling is paused")
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


def _start_da_poller():
    """Run DeviantArt poller in its own daemon thread with a dynamic interval."""
    import asyncio
    from polling.da_poller import run_da_poll_cycle

    async def _scheduled_da_poll():
        settings = config.get_settings()
        if not settings.get("da_cookie") or not settings.get("da_target_user"):
            logger.info("Scheduled DA poll skipped -- no DeviantArt credentials configured")
            return
        try:
            await run_da_poll_cycle()
        except Exception as e:
            logger.error("Scheduled DA poll failed: %s", e)

    async def _run():
        logger.info("DA poller loop started")
        if not config.get_settings().get("polling_paused"):
            await _scheduled_da_poll()
        else:
            logger.info("DA initial poll skipped -- polling is paused")
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


def _start_wp_poller():
    """Run Wattpad poller in its own daemon thread with a dynamic interval."""
    import asyncio
    from polling.wp_poller import run_wp_poll_cycle

    async def _scheduled_wp_poll():
        settings = config.get_settings()
        if not settings.get("wp_target_user"):
            logger.info("Scheduled WP poll skipped -- no Wattpad username configured")
            return
        try:
            await run_wp_poll_cycle()
        except Exception as e:
            logger.error("Scheduled WP poll failed: %s", e)

    async def _run():
        logger.info("WP poller loop started")
        if not config.get_settings().get("polling_paused"):
            await _scheduled_wp_poll()
        else:
            logger.info("WP initial poll skipped -- polling is paused")
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


def _start_ik_poller():
    """Run Itaku poller in its own daemon thread with a dynamic interval."""
    import asyncio
    from polling.ik_poller import run_ik_poll_cycle

    async def _scheduled_ik_poll():
        settings = config.get_settings()
        if not settings.get("ik_target_user"):
            logger.info("Scheduled IK poll skipped -- no Itaku username configured")
            return
        try:
            await run_ik_poll_cycle()
        except Exception as e:
            logger.error("Scheduled IK poll failed: %s", e)

    async def _run():
        logger.info("IK poller loop started")
        if not config.get_settings().get("polling_paused"):
            await _scheduled_ik_poll()
        else:
            logger.info("IK initial poll skipped -- polling is paused")
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


def _start_bsky_poller():
    """Run Bluesky poller in its own daemon thread with a dynamic interval."""
    import asyncio
    from polling.bsky_poller import run_bsky_poll_cycle

    async def _scheduled_bsky_poll():
        settings = config.get_settings()
        if not settings.get("bsky_identifier") or not settings.get("bsky_app_password"):
            logger.info("Scheduled BSKY poll skipped -- no Bluesky credentials configured")
            return
        try:
            await run_bsky_poll_cycle()
        except Exception as e:
            logger.error("Scheduled BSKY poll failed: %s", e)

    async def _run():
        logger.info("BSKY poller loop started")
        if not config.get_settings().get("polling_paused"):
            await _scheduled_bsky_poll()
        else:
            logger.info("BSKY initial poll skipped -- polling is paused")
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


def _start_tw_poller():
    """Run X/Twitter poller in its own daemon thread with a dynamic interval."""
    import asyncio
    from polling.tw_poller import run_tw_poll_cycle

    async def _scheduled_tw_poll():
        settings = config.get_settings()
        if not settings.get("tw_auth_token") or not settings.get("tw_target_user"):
            logger.info("Scheduled TW poll skipped -- no X/Twitter credentials configured")
            return
        try:
            await run_tw_poll_cycle()
        except Exception as e:
            logger.error("Scheduled TW poll failed: %s", e)

    async def _run():
        logger.info("TW poller loop started")
        if not config.get_settings().get("polling_paused"):
            await _scheduled_tw_poll()
        else:
            logger.info("TW initial poll skipped -- polling is paused")
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


def _start_server(host: str, port: int):
    """Run uvicorn in a daemon thread."""
    logger.info("Uvicorn thread starting on %s:%d ...", host, port)
    try:
        from dashboard import app as dash_app
        uvicorn.run(dash_app, host=host, port=port, log_level="info")
    except Exception as e:
        logger.error("Uvicorn failed to start: %s", e, exc_info=True)


# ── Main ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="PawPoller headless server")
    parser.add_argument("--port", type=int, default=config.DASHBOARD_PORT,
                        help="Dashboard port (default: %(default)s)")
    parser.add_argument("--host", type=str, default="0.0.0.0",
                        help="Bind address (default: %(default)s)")
    args = parser.parse_args()

    # Graceful shutdown event
    shutdown_event = threading.Event()

    def _handle_signal(signum, frame):
        signame = signal.Signals(signum).name
        logger.info("Received %s -- shutting down.", signame)
        shutdown_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Step 1: Database
    logger.info("Initialising database...")
    init_db()

    # Step 2: Seed credentials from environment variables
    _seed_settings_from_env()

    # Step 2b: Migrate legacy plaintext password to bcrypt hash
    config.migrate_dashboard_auth()

    # Step 3: Launch daemon threads
    threads = [
        ("Uvicorn",            lambda: _start_server(args.host, args.port)),
        ("IB poller",          _start_poller),
        ("FA poller",          _start_fa_poller),
        ("WS poller",          _start_ws_poller),
        ("SF poller",          _start_sf_poller),
        ("SqW poller",         _start_sqw_poller),
        ("AO3 poller",         _start_ao3_poller),
        ("DA poller",          _start_da_poller),
        ("WP poller",          _start_wp_poller),
        ("IK poller",          _start_ik_poller),
        ("BSKY poller",        _start_bsky_poller),
        ("TW poller",          _start_tw_poller),
        ("Telegram digest",    _start_digest_scheduler),
        ("Telegram bot",       _start_telegram_bot),
    ]

    for name, target in threads:
        logger.info("Starting %s...", name)
        t = threading.Thread(target=target, daemon=True, name=name)
        t.start()

    logger.info("PawPoller server ready at http://%s:%d", args.host, args.port)

    # Step 4: Block until signal
    shutdown_event.wait()
    logger.info("Server stopped.")


if __name__ == "__main__":
    main()
