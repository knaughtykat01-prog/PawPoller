"""Posting scheduler — daemon thread that processes the posting queue.

Runs as a background thread (like the pollers), checking the posting_queue
table every 60 seconds for pending items that are ready to process.

Items can be:
  - Immediate: scheduled_at is NULL → process on next check
  - Scheduled: scheduled_at is a future datetime → process when due
  - Retryable: failed items with attempts < max_attempts

The scheduler is started in main.py (desktop) and server.py (headless)
alongside the polling threads.
"""

from __future__ import annotations

import asyncio
import logging
import time

import config
from database.db import get_connection
from database import posting_queries
from posting import manager, story_reader

logger = logging.getLogger(__name__)

# How often to check the queue (seconds)
SCHEDULER_CHECK_INTERVAL = 60


def start_posting_scheduler() -> None:
    """Entry point for the posting scheduler daemon thread.

    Creates its own asyncio event loop (standard pattern for PawPoller threads).
    Runs indefinitely, checking the queue on each iteration.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_scheduler_loop())
    except Exception as e:
        logger.debug("Posting scheduler thread exiting: %s", e)


async def _scheduler_loop() -> None:
    """Main scheduler loop."""
    logger.info("Posting scheduler started")

    # Brief startup delay to let other services initialize
    await asyncio.sleep(5)

    while True:
        try:
            settings = config.get_settings()
            if not settings.get("posting_enabled", False):
                await asyncio.sleep(SCHEDULER_CHECK_INTERVAL)
                continue

            # Get next pending item
            conn = get_connection()
            try:
                items = posting_queries.get_pending_queue(conn, limit=1)
            finally:
                conn.close()

            if items:
                item = items[0]
                await _process_queue_item(item)
                # Brief pause between queue items to avoid busy-looping
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(SCHEDULER_CHECK_INTERVAL)

        except Exception as e:
            logger.error("Posting scheduler error: %s", e, exc_info=True)
            await asyncio.sleep(SCHEDULER_CHECK_INTERVAL)


async def _process_queue_item(item: dict) -> None:
    """Process a single posting queue item."""
    queue_id = item["queue_id"]
    story_name = item["story_name"]
    chapter_index = item["chapter_index"]
    platform = item["platform"]
    action = item["action"]

    logger.info(
        "Processing queue item #%d: %s %s ch%d on %s",
        queue_id, action, story_name, chapter_index, platform,
    )

    # Mark as processing
    conn = get_connection()
    try:
        posting_queries.update_queue_status(conn, queue_id, "processing")
    finally:
        conn.close()

    try:
        if action == "post":
            results = await manager.post_story(
                story_name, [platform], [chapter_index]
            )
        elif action == "update":
            results = await manager.update_story(
                story_name, [platform], [chapter_index]
            )
        else:
            raise ValueError(f"Unknown action: {action}")

        # Check results
        if results and results[0].get("success"):
            conn = get_connection()
            try:
                # Find the pub_id that was created/updated
                pub = posting_queries.get_publication_by_story(
                    conn, story_name, chapter_index, platform
                )
                pub_id = pub["pub_id"] if pub else None
                posting_queries.update_queue_status(
                    conn, queue_id, "completed", pub_id=pub_id
                )
            finally:
                conn.close()
            logger.info("Queue item #%d completed successfully", queue_id)

            # Send Telegram notification
            await _notify_completion(story_name, chapter_index, platform, action, True)
        else:
            error = results[0].get("error", "Unknown error") if results else "No results"
            # Retry if under max_attempts, otherwise mark as failed
            retry = item["attempts"] < item["max_attempts"]
            conn = get_connection()
            try:
                posting_queries.update_queue_status(
                    conn, queue_id, "pending" if retry else "failed", error=error
                )
            finally:
                conn.close()
            if retry:
                logger.warning("Queue item #%d failed (attempt %d/%d), will retry: %s",
                               queue_id, item["attempts"], item["max_attempts"], error)
            else:
                logger.warning("Queue item #%d failed permanently: %s", queue_id, error)
                await _notify_completion(story_name, chapter_index, platform, action, False, error)

    except Exception as e:
        conn = get_connection()
        try:
            posting_queries.update_queue_status(conn, queue_id, "failed", error=str(e))
        finally:
            conn.close()
        logger.error("Queue item #%d exception: %s", queue_id, e, exc_info=True)
        await _notify_completion(story_name, chapter_index, platform, action, False, str(e))


async def _notify_completion(
    story_name: str, chapter_index: int, platform: str,
    action: str, success: bool, error: str | None = None,
) -> None:
    """Send a Telegram notification about queue item completion."""
    try:
        settings = config.get_settings()
        if not settings.get("telegram_enabled"):
            return

        from polling.telegram import send_telegram
        emoji = manager.PLATFORM_EMOJIS.get(platform, "📦")
        ch_label = f"Ch{chapter_index}" if chapter_index > 0 else "Full"
        story_display = story_name.replace("_", " ")

        if success:
            text = f"✅ {action.title()} complete: {emoji} {platform.upper()} {story_display} {ch_label}"
        else:
            text = f"❌ {action.title()} failed: {emoji} {platform.upper()} {story_display} {ch_label}\n{error or ''}"

        await send_telegram(text)
    except Exception:
        pass  # Don't let notification failures break the scheduler
