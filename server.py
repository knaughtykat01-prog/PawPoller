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
    "MAST_INSTANCE_URL":  "mast_instance_url",
    "MAST_ACCESS_TOKEN":  "mast_access_token",
    "TUM_API_KEY":        "tum_api_key",
    "TUM_BLOG":           "tum_blog",
    "PIX_REFRESH_TOKEN":  "pix_refresh_token",
    "PIX_USER_ID":        "pix_user_id",
    "THR_ACCESS_TOKEN":   "thr_access_token",
    "THR_USER_ID":        "thr_user_id",
    "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
    "TELEGRAM_CHAT_ID":   "telegram_chat_id",
    "TELEGRAM_ENABLED":   "telegram_enabled",
    "DASHBOARD_PASSWORD":  "dashboard_password",
    "DASHBOARD_USER":      "dashboard_user",
    "CF_WORKER_URL":       "cf_worker_url",
    "CF_WORKER_KEY":       "cf_worker_key",
}

def _seed_settings_from_env():
    """One-time bootstrap from env vars into settings on a fresh install.

    Only fills in fields that are MISSING or EMPTY — never overwrites an
    existing value. The UI is the source of truth for credentials once
    they've been set; .env exists purely to bootstrap a brand-new container
    so the first poll cycle has something to authenticate with.

    Previously this function clobbered any UI-set value that differed from
    the env var, which meant credentials silently reverted to .env on every
    container restart. If you need to *change* a credential, do it through
    the Settings UI.
    """
    settings = config.get_settings()
    updates = {}
    for env_key, settings_key in _ENV_TO_SETTINGS.items():
        val = os.environ.get(env_key)
        if not val:
            continue
        existing = settings.get(settings_key)
        if existing:
            # UI/vault already has a value — leave it alone.
            continue
        if settings_key == "telegram_enabled":
            updates[settings_key] = val.lower() in ("true", "1", "yes")
        else:
            updates[settings_key] = val
    if updates:
        config.save_settings(updates)
        logger.info("Seeded %d credential(s) from environment (first-run only): %s",
                     len(updates), ", ".join(updates.keys()))


# ── Auth Migration ────────────────────────────────────────────


def _start_poll_orchestrator():
    """Unified poll + digest scheduler.  One thread, one clock.

    Replaces the 11 separate per-platform poller threads AND the digest
    scheduler.  Every cycle:
      1. Poll all configured platforms concurrently
      2. Send ONE consolidated Telegram summary
      3. If regular digest is due → send digest
      4. If weekly digest is due → send weekly digest
      5. Sleep for poll_interval_minutes

    The poll interval is intended to be a divisor of the digest interval
    (e.g. poll every 4h, digest every 12h = digest fires every 3rd cycle).
    This guarantees fresh data for every digest without double-polling.

    Runs regardless of polling_paused for the sleep/schedule logic, but
    skips actual polling when paused.  Manual /poll commands still work
    via the bot thread calling the individual poll functions directly.
    """
    import asyncio
    import time as _time
    from datetime import datetime, timezone
    from polling.telegram import (
        send_digest_report, send_weekly_digest_report,
        send_consolidated_poll_summary, check_goals,
    )
    import polling.telegram as _tg

    def _get_poll_interval() -> int:
        """Read unified poll interval from settings (in seconds)."""
        minutes = config.get_settings().get("poll_interval_minutes", 240)
        return max(int(minutes), 15) * 60

    def _get_digest_interval() -> int:
        hours = config.get_settings().get("telegram_digest_interval_hours", 6)
        return max(int(hours), 1) * 60 * 60

    def _seconds_until_next(key: str, interval_seconds: int) -> float:
        MIN_STARTUP_DELAY = 300
        last = config.get_settings().get(key)
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
                remaining = interval_seconds - elapsed
                if remaining > MIN_STARTUP_DELAY:
                    return remaining
                return 0  # Due now (or overdue)
            except (ValueError, TypeError):
                pass
        return 0  # No record — due now

    def _digest_due() -> bool:
        return _seconds_until_next("last_digest_sent_at", _get_digest_interval()) <= 60

    def _session_check_due() -> bool:
        # Re-validate platform sessions ~every 6 h (independent of the digest
        # and of polling pause). Startup runs an immediate check separately.
        return _seconds_until_next("last_session_check_at", 6 * 60 * 60) <= 60

    def _weekly_digest_due() -> bool:
        settings = config.get_settings()
        if not settings.get("telegram_weekly_digest", True):
            return False
        return _seconds_until_next("last_weekly_digest_sent_at", 7 * 24 * 60 * 60) <= 60

    async def _poll_all() -> list[dict]:
        """Poll all configured platforms concurrently.

        Returns a list of result dicts, each with 'platform' and either
        'stats' (success) or 'error' (failure).
        """
        from polling.poller import run_poll_cycle
        from polling.fa_poller import run_fa_poll_cycle
        from polling.ws_poller import run_ws_poll_cycle
        from polling.sf_poller import run_sf_poll_cycle
        from polling.sqw_poller import run_sqw_poll_cycle
        from polling.ao3_poller import run_ao3_poll_cycle
        from polling.da_poller import run_da_poll_cycle
        from polling.wp_poller import run_wp_poll_cycle
        from polling.ik_poller import run_ik_poll_cycle
        from polling.bsky_poller import run_bsky_poll_cycle
        from polling.tw_poller import run_tw_poll_cycle
        from polling.mast_poller import run_mast_poll_cycle
        from polling.tum_poller import run_tum_poll_cycle
        from polling.pix_poller import run_pix_poll_cycle
        from polling.thr_poller import run_thr_poll_cycle

        settings = config.get_settings()
        from polling.notifications import describe_error
        from database.db import get_connection
        from database import accounts as accounts_db

        # Account-aware platforms enumerate their ENABLED accounts (polled
        # sequentially within a platform to respect per-IP rate limits). Other
        # platforms still poll once via their legacy single-account path until
        # their pollers learn account_id.
        account_aware = {"ib": run_poll_cycle, "fa": run_fa_poll_cycle,
                         "ws": run_ws_poll_cycle, "da": run_da_poll_cycle,
                         "wp": run_wp_poll_cycle, "ik": run_ik_poll_cycle,
                         "bsky": run_bsky_poll_cycle, "tw": run_tw_poll_cycle,
                         "sf": run_sf_poll_cycle, "sqw": run_sqw_poll_cycle,
                         "ao3": run_ao3_poll_cycle, "mast": run_mast_poll_cycle,
                         "tum": run_tum_poll_cycle, "pix": run_pix_poll_cycle,
                         "thr": run_thr_poll_cycle}

        # Ensure every configured platform has its default account row (covers
        # creds added since the last startup migration), then read enabled ones.
        conn = get_connection()
        try:
            accounts_db.seed_default_accounts(conn, settings)
            enabled_accounts = accounts_db.list_accounts(conn, enabled_only=True)
        finally:
            conn.close()
        accts_by_platform: dict[str, list] = {}
        for a in enabled_accounts:
            accts_by_platform.setdefault(a["platform"], []).append(a)

        # All 15 platforms are now account-aware — no legacy single-account path.
        legacy_checks: list = []

        async def _poll_accounts(platform, fn, accts):
            """Poll each enabled account on one platform, in sequence."""
            out = []
            check = accounts_db.DEFAULT_CRED_CHECKS.get(platform, lambda s: True)
            for a in accts:
                creds = config.resolve_account_credentials(
                    platform, a["account_id"], bool(a["is_default"]), settings)
                if not check(creds):
                    continue  # account has no usable credentials — skip
                label = a.get("label") or platform
                # Tag this account onto the task context so per-cycle instant
                # alerts (maybe_send_telegram_summary) can label which account /
                # persona they belong to. Isolated per gathered platform task.
                from polling.notifications import current_alert_account
                current_alert_account.set((platform, a["account_id"]))
                try:
                    stats = await fn(a["account_id"])
                    out.append({"platform": platform, "account_id": a["account_id"],
                                "label": label, "stats": stats or {}})
                except Exception as e:  # noqa: BLE001 — one account must not kill the cycle
                    out.append({"platform": platform, "account_id": a["account_id"],
                                "label": label, "error": describe_error(e)})
            return out

        async def _poll_legacy(platform, fn):
            try:
                stats = await fn()
                return [{"platform": platform, "stats": stats or {}}]
            except Exception as e:  # noqa: BLE001
                return [{"platform": platform, "error": describe_error(e)}]

        # Build one task group per platform — account-aware platforms poll their
        # accounts sequentially inside the group; groups run concurrently.
        tasks = []
        for plat, fn in account_aware.items():
            accts = accts_by_platform.get(plat, [])
            if accts:
                tasks.append(_poll_accounts(plat, fn, accts))
        for creds_ok, plat, fn in legacy_checks:
            if creds_ok:
                tasks.append(_poll_legacy(plat, fn))

        if not tasks:
            logger.info("No platforms configured — skipping poll cycle")
            return []

        logger.info("Polling %d platform group(s)...", len(tasks))

        # Suppress individual per-platform Telegram summaries/errors —
        # we send one consolidated message after all polls complete.
        _tg.orchestrated_poll_active = True
        try:
            grouped = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            _tg.orchestrated_poll_active = False

        results = []
        for g in grouped:
            if isinstance(g, Exception):
                logger.warning("Poll task group crashed: %s", describe_error(g))
                continue
            results.extend(g)
        for r in results:
            if "error" in r:
                logger.warning("Poll %s failed: %s", r["platform"], r["error"])
        return results

    async def _run():
        # Brief startup delay so uvicorn is ready and settings are seeded.
        await asyncio.sleep(5)
        _first_cycle = True
        poll_interval = _get_poll_interval()
        logger.info("Poll orchestrator started (interval: %d min)",
                     poll_interval // 60)

        # Validate platform sessions once, up front, so the dashboard banner +
        # Settings status dots reflect real cookie/token validity within a
        # minute of startup — independent of the poll-skip logic below (which
        # can defer the first poll by hours). 8 serial probes; gentle on limits.
        try:
            from polling.session_check import check_all as _check_sessions
            await _check_sessions()
            config.save_settings({"last_session_check_at": datetime.now(timezone.utc).isoformat()})
        except Exception as e:
            logger.warning("Initial session check failed: %s", e)

        # Skip the immediate first poll if the last cycle was recent enough.
        # This prevents hammering platforms on every app restart / deploy.
        secs_until = _seconds_until_next("last_poll_completed_at", poll_interval)
        if secs_until > 60:
            wait_min = int(secs_until / 60)
            logger.info("Skipping startup poll — last cycle was recent, next in %d min", wait_min)
            _first_cycle = False
            await asyncio.sleep(secs_until)

        while True:
            paused = config.get_settings().get("polling_paused", False)

            # Session validity is independent of polling — re-check on its own
            # ~6 h cadence even while polling is paused, so the banner stays
            # honest about expired cookies.
            if _session_check_due():
                try:
                    from polling.session_check import check_all as _check_sessions
                    await _check_sessions()
                    config.save_settings({"last_session_check_at": datetime.now(timezone.utc).isoformat()})
                except Exception as e:
                    logger.warning("Session check failed: %s", e)

            if not paused:
                start = _time.time()
                results = await _poll_all()
                duration = _time.time() - start

                # Record completion time so next restart knows when we last polled
                config.save_settings({
                    "last_poll_completed_at": datetime.now(timezone.utc).isoformat(),
                })

                if _first_cycle:
                    logger.info("First poll cycle complete — notifications suppressed "
                                "(%d platforms in %.1fs)", len(results), duration)
                    _first_cycle = False
                else:
                    # Consolidated Telegram summary
                    try:
                        await send_consolidated_poll_summary(results, duration)
                    except Exception as e:
                        logger.warning("Consolidated summary failed: %s", e)

                    # Single goal check for all platforms (replaces 11
                    # per-poller check_goals calls suppressed during
                    # orchestrated polls).
                    try:
                        await check_goals()
                    except Exception as e:
                        logger.warning("Goal check failed: %s", e)

                    # Check if regular digest is due
                    if _digest_due():
                        try:
                            await send_digest_report()
                        except Exception as e:
                            logger.error("Digest report failed: %s", e)

                    # Weekly digest piggy-backs on the regular cycle
                    if _weekly_digest_due():
                        try:
                            await send_weekly_digest_report()
                        except Exception as e:
                            logger.error("Weekly digest report failed: %s", e)
            else:
                logger.info("Poll cycle skipped — polling is paused")

            interval_min = _get_poll_interval() // 60
            logger.info("Next poll cycle in %d minutes", interval_min)
            await asyncio.sleep(_get_poll_interval())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception as e:
        logger.debug("Poll orchestrator thread exiting: %s", e)


# ── Legacy per-platform starters (removed) ───────────────────
# The 11 individual _start_XX_poller() functions and _start_digest_scheduler()
# have been replaced by _start_poll_orchestrator() above.  The poll cycle
# functions themselves (polling/*.py) are unchanged and still callable by
# the /poll bot command for manual single-platform triggers.



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
        uvicorn.run(
            dash_app, host=host, port=port, log_level="info",
            # Behind a reverse proxy (the maintainer's Caddy terminates TLS for
            # pawpoller.syncopates.app), honour X-Forwarded-Proto/-For so
            # request.url.scheme is https — the dashboard session cookie's
            # Secure flag depends on it (routes/dashboard_auth.py) — and
            # request.client.host is the real client, not the proxy. Default
            # trusts only 127.0.0.1; PAWPOLLER_FORWARDED_IPS widens it.
            proxy_headers=True,
            forwarded_allow_ips=config.DASHBOARD_FORWARDED_IPS,
        )
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

    # SECURITY: don't silently expose an unauthenticated dashboard.
    if args.host not in ("127.0.0.1", "::1", "localhost") and not config.is_dashboard_auth_required():
        logger.warning(
            "SECURITY: binding to %s with NO dashboard password set — the "
            "dashboard and its API (including stored platform credentials) are "
            "exposed with no authentication. Set DASHBOARD_PASSWORD (or complete "
            "setup), and/or bind to 127.0.0.1 behind a reverse proxy.",
            args.host,
        )

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

    # Step 2c: Force setup_mode = "server" on first run. The headless
    # container is unambiguously the server side of any pairing — we
    # never want it to fall through to "standalone" inference and stop
    # polling for itself, and we never want it to try to push settings
    # to a configured posting_server_url (that'd be a loopback storm).
    _settings_now = config.get_settings()
    if _settings_now.get("setup_mode") != config.SETUP_MODE_SERVER:
        config.save_settings({"setup_mode": config.SETUP_MODE_SERVER})
        logger.info("setup_mode set to 'server' (was %r)",
                    _settings_now.get("setup_mode"))

    # Step 3: Launch daemon threads
    # The poll orchestrator replaces the old 11 per-platform poller threads
    # and the digest scheduler with a single unified clock thread.
    from posting.scheduler import start_posting_scheduler

    threads = [
        ("Uvicorn",             lambda: _start_server(args.host, args.port)),
        ("Poll orchestrator",   _start_poll_orchestrator),
        ("Telegram bot",        _start_telegram_bot),
        ("Posting scheduler",   start_posting_scheduler),
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
