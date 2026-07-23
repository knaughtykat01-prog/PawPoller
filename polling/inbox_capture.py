"""Stage-A1 inbox comment capture (gap G3) — shared by the bsky/mast/e621/da pollers.

The delta check is capture-count based, not snapshot based: fetch a submission's
thread when the platform's fresh comment/reply count exceeds how many rows we've
already captured for it. Self-healing (a missed fetch retries next cycle) and
schema-decoupled. Capped per cycle so a first-run backfill spreads across
cycles instead of hammering a platform.

Poller rule respected: callers invoke this AFTER their post-loop commit, and the
network fetches here run with no write transaction open (each upsert commits
itself immediately).

Our OWN comments are stored too (so captured counts track platform counts and
the fetch doesn't re-trigger forever) but are auto-marked handled — the inbox
shows them only as context, never as things to answer.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_CAP = 25   # max thread fetches per platform per cycle


async def capture(conn, platform: str, candidates: list[dict], fetch, *,
                  account_id: int | None = None, own_author: str = "") -> int:
    """Capture comment content for submissions that look behind.

    Args:
        candidates: [{submission_id, fresh_count, title, ...}] — one per polled
            submission (fresh_count = the platform's current comment count).
        fetch: async fn(candidate) -> [{comment_id, author, body, commented_at,
            permalink, meta?}] — one platform-specific thread fetch.
        own_author: our account's handle/username — its comments auto-handle.

    Returns the number of NEW comments captured.
    """
    from database import inbox_queries

    todo = []
    for c in candidates:
        if (c.get("fresh_count") or 0) <= 0 or not c.get("submission_id"):
            continue
        have = inbox_queries.count_for_submission(conn, platform, c["submission_id"])
        if c["fresh_count"] > have:
            todo.append(c)
        if len(todo) >= _CAP:
            break
    if not todo:
        return 0

    own = (own_author or "").lower().lstrip("@")
    captured = 0
    for c in todo:
        try:
            comments = await fetch(c)          # network — no write txn open
        except Exception as e:  # noqa: BLE001 — capture must never fail a poll
            logger.warning("%s inbox capture fetch failed for %s: %s",
                           platform, str(c["submission_id"])[:60], e)
            continue
        for r in comments or []:
            if not r.get("comment_id"):
                continue
            is_new = inbox_queries.upsert_platform_comment(
                conn, platform, r["comment_id"], c["submission_id"],
                author=r.get("author", ""), body=r.get("body", ""),
                commented_at=r.get("commented_at"),
                permalink=r.get("permalink", ""),
                submission_title=c.get("title", ""),
                account_id=account_id, meta=r.get("meta") or {},
            )
            if is_new:
                captured += 1
                if own and r.get("author", "").lower().lstrip("@").split("@")[0] == own.split("@")[0]:
                    inbox_queries.set_handled(conn, platform, r["comment_id"], True)
    if captured:
        logger.info("%s inbox capture: %d new comment(s) across %d submission(s)",
                    platform, captured, len(todo))
    return captured
