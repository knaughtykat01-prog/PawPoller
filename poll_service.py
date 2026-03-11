"""Background polling service — runs independently of the dashboard.

Usage:
    python poll_service.py              # Continuous mode (APScheduler loop)
    python poll_service.py --once       # Single poll then exit (for Task Scheduler)
    python poll_service.py --status     # Show last poll time, DB stats
"""

from __future__ import annotations
import argparse
import asyncio
import logging
import sys
from datetime import datetime

import config
from database.db import init_db, get_connection
from database import queries
from polling.poller import run_poll_cycle

# ── Logging setup ──────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(config.LOGS_DIR / "polling.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("poll_service")


# ── Commands ───────────────────────────────────────────────────
# The service supports three operating modes:
#   1. Continuous (default) — runs as a long-lived daemon using APScheduler to
#      trigger poll cycles on a recurring interval. Ideal for always-on servers.
#   2. Once (--once) — executes a single poll cycle then exits. Designed for
#      Windows Task Scheduler or cron, where the OS handles scheduling.
#   3. Status (--status) — read-only mode that queries the database and prints
#      aggregate stats. No polling occurs.

async def do_poll_once():
    """Run a single poll cycle."""
    logger.info("Starting single poll cycle...")
    try:
        # run_poll_cycle is async (it makes HTTP requests to FA), so we await it.
        # On failure, exit with code 1 so Task Scheduler can detect the error.
        stats = await run_poll_cycle()
        logger.info("Poll complete: %s", stats)
    except Exception as e:
        logger.error("Poll failed: %s", e)
        sys.exit(1)


def do_status():
    """Show last poll time and DB stats."""
    # Opens a direct SQLite connection (not async — status is a quick synchronous
    # read). All data comes from the local database, no network calls needed.
    conn = get_connection()
    try:
        # queries.get_last_poll retrieves the most recent row from the poll_log
        # table, which records start time, status, duration, and any error.
        last_poll = queries.get_last_poll(conn)

        # Aggregate stats pulled directly from the submissions table — total
        # submission count, sum of views, and sum of favorites across all tracked
        # submissions. COALESCE handles the case where the table is empty.
        totals = conn.execute(
            "SELECT COUNT(*) as subs, COALESCE(SUM(views),0) as views, "
            "COALESCE(SUM(favorites_count),0) as faves FROM submissions"
        ).fetchone()
        # Snapshots = historical data points captured per poll cycle.
        snap_count = conn.execute("SELECT COUNT(*) as c FROM snapshots").fetchone()["c"]
        # Faving users = distinct users who have favorited any tracked submission.
        fave_users = conn.execute("SELECT COUNT(*) as c FROM faving_users").fetchone()["c"]

        print("\n=== PawPoller Status ===")
        print(f"  Database: {config.DB_PATH}")
        print(f"  Submissions tracked: {totals['subs']}")
        print(f"  Total views: {totals['views']:,}")
        print(f"  Total favorites: {totals['faves']:,}")
        print(f"  Snapshots stored: {snap_count:,}")
        print(f"  Faving users tracked: {fave_users:,}")
        print()
        if last_poll:
            print(f"  Last poll: {last_poll['started_at']}")
            print(f"  Status: {last_poll['status']}")
            if last_poll['duration_seconds']:
                print(f"  Duration: {last_poll['duration_seconds']:.1f}s")
            if last_poll['error_message']:
                print(f"  Error: {last_poll['error_message']}")
        else:
            print("  No polls recorded yet.")
        print()
    finally:
        conn.close()


def do_continuous():
    """Run continuously with APScheduler polling every hour."""
    # APScheduler imports are deferred to here so the scheduler dependency is
    # only loaded when continuous mode is actually used (not for --once/--status).
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    logger.info("Starting continuous polling service (every %d hour(s))...", config.POLL_INTERVAL_HOURS)

    # AsyncIOScheduler integrates with the asyncio event loop — it runs jobs as
    # coroutines on the same loop, avoiding thread-safety issues with the async
    # poller code.
    scheduler = AsyncIOScheduler()

    # Wrapper that catches exceptions so a single failed poll doesn't crash the
    # scheduler. APScheduler would remove the job on unhandled exceptions.
    async def scheduled_poll():
        if config.get_settings().get("polling_paused"):
            logger.info("Scheduled poll skipped -- polling is paused")
            return
        try:
            await run_poll_cycle()
        except Exception as e:
            logger.error("Scheduled poll failed: %s", e)

    # IntervalTrigger fires every N hours. next_run_time=datetime.now() forces
    # an immediate first run on startup instead of waiting for the first interval
    # to elapse — so you get data right away, not an hour later.
    scheduler.add_job(
        scheduled_poll,
        trigger=IntervalTrigger(hours=config.POLL_INTERVAL_HOURS),
        id="pawpoller_poll",
        name="PawPoller hourly poll",
        next_run_time=datetime.now(),
    )

    # asyncio.run() creates a new event loop and runs until the coroutine
    # completes. The inner `while True: await asyncio.sleep(1)` keeps the loop
    # alive so APScheduler can fire jobs on its schedule. Without this keep-alive
    # loop, asyncio.run() would return immediately after scheduler.start() since
    # start() is non-blocking. Ctrl+C triggers KeyboardInterrupt for clean shutdown.
    async def run():
        scheduler.start()
        logger.info("Scheduler started. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down...")
            scheduler.shutdown(wait=False)

    asyncio.run(run())


# ── Main ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="PawPoller Polling Service")
    parser.add_argument("--once", action="store_true", help="Single poll then exit")
    parser.add_argument("--status", action="store_true", help="Show status and stats")
    args = parser.parse_args()

    # DB init runs unconditionally for all modes — creates tables if they don't
    # exist yet, and is a no-op if they already do. This means you can run
    # --status on a fresh install without a separate setup step.
    init_db()

    if args.status:
        # Status is synchronous (direct SQLite reads), no event loop needed.
        do_status()
    elif args.once:
        # asyncio.run() creates a temporary event loop, runs the single async
        # poll cycle to completion, then tears down the loop and exits.
        asyncio.run(do_poll_once())
    else:
        # Default: long-running continuous mode with its own event loop and
        # APScheduler inside.
        do_continuous()


if __name__ == "__main__":
    main()
