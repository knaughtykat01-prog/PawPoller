"""CRUD operations for the posting module tables.

Three tables:
    publications    Registry of what has been posted where. One row per
                    (story_name, chapter_index, platform) combination.
                    Stores the external submission ID so updates can target it.
    posting_queue   Pending uploads and updates with scheduling support.
                    Items carry a 'requires' field (desktop/server/any) so the
                    scheduler only processes items valid for the current runtime.
    posting_log     Immutable audit trail. Every post, edit, or failure is
                    recorded here for debugging and history display.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ── Publications ──────────────────────────────────────────────

def upsert_publication(
    conn: sqlite3.Connection,
    story_name: str,
    chapter_index: int,
    platform: str,
    *,
    account_id: int | None = None,
    content_type: str = "story",
    external_id: str = "",
    external_url: str = "",
    title_used: str = "",
    description_used: str = "",
    tags_used: list[str] | None = None,
    rating_used: str = "",
    format_file: str = "",
    file_hash: str = "",
    word_count: int = 0,
    status: str = "posted",
) -> int:
    """Insert or update a publication record. Returns pub_id.

    account_id selects which account the story was posted as; None resolves to
    the platform's default account, so single-account callers are unaffected.
    The publications UNIQUE key now includes account_id, so the same chapter can
    be published to two accounts on the same platform.
    """
    if account_id is None:
        from database import accounts as _accts
        account_id = _accts.get_default_account_id(conn, platform, create=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    tags_json = json.dumps(tags_used or [])

    # Check if exists (scoped to the account + content_type).
    row = conn.execute(
        "SELECT pub_id, update_count FROM publications "
        "WHERE content_type = ? AND story_name = ? AND chapter_index = ? "
        "AND platform = ? AND account_id = ?",
        (content_type, story_name, chapter_index, platform, account_id),
    ).fetchone()

    if row:
        pub_id = row["pub_id"]
        update_count = row["update_count"] + 1
        conn.execute(
            """UPDATE publications SET
                external_id = ?, external_url = ?, title_used = ?,
                description_used = ?, tags_used = ?, rating_used = ?,
                format_file = ?, file_hash = ?, word_count = ?, status = ?,
                last_updated_at = ?, update_count = ?
            WHERE pub_id = ?""",
            (external_id, external_url, title_used, description_used,
             tags_json, rating_used, format_file, file_hash, word_count, status,
             now, update_count, pub_id),
        )
    else:
        cursor = conn.execute(
            """INSERT INTO publications
                (content_type, story_name, chapter_index, platform, account_id,
                 external_id, external_url,
                 title_used, description_used, tags_used, rating_used,
                 format_file, file_hash, word_count, status, first_posted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (content_type, story_name, chapter_index, platform, account_id,
             external_id, external_url,
             title_used, description_used, tags_json, rating_used,
             format_file, file_hash, word_count, status, now),
        )
        pub_id = cursor.lastrowid

    conn.commit()
    return pub_id


def get_publications(
    conn: sqlite3.Connection,
    story_name: str | None = None,
    platform: str | None = None,
    status: str | None = None,
    content_type: str | None = "story",
) -> list[dict]:
    """Get publications with optional filters.

    content_type defaults to "story" so the Stories views never see artwork
    rows; pass "artwork" for the Artwork hub or None for everything.
    """
    query = "SELECT * FROM publications WHERE 1=1"
    params: list = []
    if content_type is not None:
        query += " AND content_type = ?"
        params.append(content_type)
    if story_name:
        query += " AND story_name = ?"
        params.append(story_name)
    if platform:
        query += " AND platform = ?"
        params.append(platform)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY story_name, chapter_index, platform"
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_publication(conn: sqlite3.Connection, pub_id: int) -> dict | None:
    """Get a single publication by ID."""
    row = conn.execute("SELECT * FROM publications WHERE pub_id = ?", (pub_id,)).fetchone()
    return dict(row) if row else None


def get_publications_with_stats(
    conn: sqlite3.Connection,
    story_name: str | None = None,
    content_type: str | None = "story",
) -> list[dict]:
    """Get publications enriched with live stats from the polling submission tables.

    Joins each publication's external_id with the platform-specific submission table
    to pull in current views, faves, comments counts. Because pollers auto-discover
    the whole gallery, artwork rows enrich from the same submission tables — pass
    content_type="artwork" for the Artwork hub.
    """
    pubs = get_publications(conn, story_name=story_name, status="posted",
                            content_type=content_type)

    # Platform table mapping: platform → (table, id_col, stat_columns)
    stat_tables = {
        "ib": ("submissions", "submission_id", ["views", "favorites_count", "comments_count"]),
        "fa": ("fa_submissions", "submission_id", ["views", "favorites_count", "comments_count"]),
        "ws": ("ws_submissions", "submission_id", ["views", "favorites_count", "comments_count"]),
        "sf": ("sf_submissions", "submission_id", ["views", "favorites_count", "comments_count"]),
        "sqw": ("sqw_submissions", "submission_id", ["hits", "kudos", "comments_count", "bookmarks"]),
        "ao3": ("ao3_submissions", "submission_id", ["hits", "kudos", "comments_count", "bookmarks"]),
        "wp": ("wp_submissions", "submission_id", ["reads", "votes", "comments_count"]),
    }

    enriched = []
    for pub in pubs:
        pub_dict = dict(pub) if not isinstance(pub, dict) else pub
        plat = pub_dict["platform"]
        ext_id = pub_dict["external_id"]

        pub_dict["stats"] = None
        if plat in stat_tables and ext_id:
            table, id_col, cols = stat_tables[plat]
            col_str = ", ".join(cols)
            try:
                row = conn.execute(
                    f"SELECT {col_str} FROM {table} WHERE {id_col} = ?",
                    (int(ext_id) if ext_id.isdigit() else ext_id,),
                ).fetchone()
                if row:
                    pub_dict["stats"] = {cols[i]: row[i] for i in range(len(cols))}
            except Exception:
                pass  # Table doesn't exist or ID mismatch

        enriched.append(pub_dict)

    return enriched


def get_publication_by_story(
    conn: sqlite3.Connection,
    story_name: str,
    chapter_index: int,
    platform: str,
    account_id: int | None = None,
    content_type: str = "story",
) -> dict | None:
    """Get a publication by its (content_type, story, chapter, platform[, account]) key.

    account_id None resolves to the platform's default account so existing
    single-account callers keep getting the default account's row. content_type
    defaults to "story"; the Artwork hub passes "artwork".
    """
    if account_id is None:
        from database import accounts as _accts
        account_id = _accts.get_default_account_id(conn, platform, create=True)
    row = conn.execute(
        "SELECT * FROM publications WHERE content_type = ? AND story_name = ? "
        "AND chapter_index = ? AND platform = ? AND account_id = ?",
        (content_type, story_name, chapter_index, platform, account_id),
    ).fetchone()
    return dict(row) if row else None


# ── Posting Queue ─────────────────────────────────────────────

def add_to_queue(
    conn: sqlite3.Connection,
    story_name: str,
    chapter_index: int,
    platform: str,
    action: str = "post",
    *,
    account_id: int | None = None,
    content_type: str = "story",
    scheduled_at: str | None = None,
    title_override: str | None = None,
    description_override: str | None = None,
    tags_override: str | None = None,
    rating_override: str | None = None,
    file_path_override: str | None = None,
    priority: int = 0,
    requires: str = "any",
) -> int:
    """Add an item to the posting queue. Returns queue_id.

    Args:
        account_id: Which account to post as; None → the platform's default.
            The scheduler posts queued items as this account (important for the
            desktop FA auto-queue so the right account is used).
        requires: Runtime mode needed — 'any', 'desktop', or 'server'.
            Desktop-only platforms (FA) should be queued with 'desktop' so the
            server scheduler skips them and they're picked up when the desktop app opens.
    """
    if account_id is None:
        from database import accounts as _accts
        account_id = _accts.get_default_account_id(conn, platform, create=True)
    cursor = conn.execute(
        """INSERT INTO posting_queue
            (content_type, story_name, chapter_index, platform, account_id, action,
             scheduled_at, title_override, description_override, tags_override,
             rating_override, file_path_override, priority, requires)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (content_type, story_name, chapter_index, platform, account_id, action,
         scheduled_at, title_override, description_override, tags_override,
         rating_override, file_path_override, priority, requires),
    )
    conn.commit()
    return cursor.lastrowid


def get_pending_queue(
    conn: sqlite3.Connection,
    limit: int = 20,
    runtime_mode: str | None = None,
) -> list[dict]:
    """Get pending queue items ordered by priority then creation time.

    When ``runtime_mode`` is provided, only items whose ``requires`` field is
    ``'any'`` or matches the mode are returned. This stops a head-of-line block
    where stale ``requires='desktop'`` rows (e.g. from a removed FA auto-queue
    path) sit at the top of the FIFO and starve newer compatible items past
    the LIMIT — the bug item 8 hit when items 1–7 were April-dated zombies.
    """
    if runtime_mode is None:
        rows = conn.execute(
            """SELECT * FROM posting_queue
            WHERE status = 'pending'
              AND (scheduled_at IS NULL OR scheduled_at <= datetime('now'))
            ORDER BY priority DESC, created_at ASC
            LIMIT ?""",
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM posting_queue
            WHERE status = 'pending'
              AND (scheduled_at IS NULL OR scheduled_at <= datetime('now'))
              AND requires IN ('any', ?)
            ORDER BY priority DESC, created_at ASC
            LIMIT ?""",
            (runtime_mode, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_queue(
    conn: sqlite3.Connection,
    include_completed: bool = False,
    story_name: str | None = None,
    content_type: str | None = "story",
) -> list[dict]:
    """Get queue items, optionally filtered by story.

    The story_name filter is used by the story detail page to render only
    that story's pending items as a callout card. content_type defaults to
    "story" so the Stories queue view never shows artwork; the Artwork hub
    passes "artwork".
    """
    params: list = []
    if include_completed:
        query = "SELECT * FROM posting_queue"
        order = " ORDER BY created_at DESC"
    else:
        query = "SELECT * FROM posting_queue WHERE status IN ('pending', 'processing')"
        order = " ORDER BY priority DESC, created_at ASC"

    if story_name:
        if "WHERE" in query:
            query += " AND story_name = ?"
        else:
            query += " WHERE story_name = ?"
        params.append(story_name)

    if content_type is not None:
        if "WHERE" in query:
            query += " AND content_type = ?"
        else:
            query += " WHERE content_type = ?"
        params.append(content_type)

    rows = conn.execute(query + order, params).fetchall()
    return [dict(r) for r in rows]


def update_queue_status(
    conn: sqlite3.Connection,
    queue_id: int,
    status: str,
    *,
    error: str | None = None,
    pub_id: int | None = None,
) -> None:
    """Update a queue item's status.

    Refuses to overwrite a 'cancelled' row. The scheduler resets a row
    to 'pending' on failure for retry; without this guard, a user-issued
    cancel mid-flight gets clobbered by the scheduler's failure handler
    the moment the in-flight post errors out, and the next scheduler
    tick picks the row back up. The guard makes cancel actually stick.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if status == "processing":
        conn.execute(
            "UPDATE posting_queue SET status = ?, started_at = ?, attempts = attempts + 1 "
            "WHERE queue_id = ? AND status != 'cancelled'",
            (status, now, queue_id),
        )
    elif status in ("completed", "failed"):
        conn.execute(
            "UPDATE posting_queue SET status = ?, completed_at = ?, last_error = ?, pub_id = ? "
            "WHERE queue_id = ? AND status != 'cancelled'",
            (status, now, error, pub_id, queue_id),
        )
    else:
        conn.execute(
            "UPDATE posting_queue SET status = ? WHERE queue_id = ? AND status != 'cancelled'",
            (status, queue_id),
        )
    conn.commit()


def cancel_queue_item(conn: sqlite3.Connection, queue_id: int) -> bool:
    """Cancel a queue item if it's in a cancellable state.

    Cancellable: pending, retrying, failed (rare manual cleanup after
    a giving-up event). 'processing' rows are mid-flight in the
    scheduler — cancel marks them, and the scheduler treats
    'cancelled' as a terminal state when it completes the in-flight
    work, so the next retry won't fire.
    """
    cursor = conn.execute(
        "UPDATE posting_queue SET status = 'cancelled' "
        "WHERE queue_id = ? AND status IN ('pending', 'retrying', 'processing', 'failed')",
        (queue_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def cancel_all_for(conn: sqlite3.Connection, *, platform: str | None = None,
                   story_name: str | None = None,
                   chapter_index: int | None = None,
                   content_type: str | None = None) -> int:
    """Bulk-cancel queue items matching the filter. Used by the editor's
    'cancel all retries for X' affordance and the diagnostics cleanup
    flow when a poster bug spams the queue.

    Returns the number of rows cancelled. Filters compose with AND
    semantics; all filters None means cancel-everything-non-terminal
    which is rarely what callers want — explicit non-None args strongly
    recommended.
    """
    sql = (
        "UPDATE posting_queue SET status = 'cancelled' "
        "WHERE status IN ('pending', 'retrying', 'processing', 'failed')"
    )
    params: list = []
    if platform is not None:
        sql += " AND platform = ?"
        params.append(platform)
    if story_name is not None:
        sql += " AND story_name = ?"
        params.append(story_name)
    if chapter_index is not None:
        sql += " AND chapter_index = ?"
        params.append(chapter_index)
    if content_type is not None:
        sql += " AND content_type = ?"
        params.append(content_type)
    cursor = conn.execute(sql, params)
    conn.commit()
    return cursor.rowcount


def delete_publication(
    conn: sqlite3.Connection,
    story_name: str,
    chapter_index: int,
    platform: str,
    content_type: str = "story",
) -> bool:
    """Remove the publications row for (story, chapter, platform).

    Used by the "forget publication" affordance in the publish-check
    panel when the user has manually deleted the upstream submission
    and wants PawPoller's local memory cleared so the cell reverts to
    'ready' (next post is a fresh create, not an edit).

    Returns True if a row was deleted, False if no matching row existed.

    Two tables carry a ``pub_id`` foreign key back to ``publications`` —
    ``posting_queue`` and the immutable ``posting_log`` audit trail. With
    ``PRAGMA foreign_keys = ON`` a bare ``DELETE FROM publications`` raises
    ``FOREIGN KEY constraint failed`` the moment the row has ever been posted
    (a ``posting_log`` row references it). So we unlink the children first —
    both ``pub_id`` columns are nullable, so we NULL them rather than delete:
    the queue item keeps its story/chapter/platform identity and the audit
    log stays intact, they just lose the back-reference to the forgotten row.
    """
    rows = conn.execute(
        "SELECT pub_id FROM publications "
        "WHERE content_type = ? AND story_name = ? AND chapter_index = ? AND platform = ?",
        (content_type, story_name, chapter_index, platform),
    ).fetchall()
    if not rows:
        return False
    pub_ids = [r[0] for r in rows]
    placeholders = ",".join("?" * len(pub_ids))
    conn.execute(
        f"UPDATE posting_queue SET pub_id = NULL WHERE pub_id IN ({placeholders})",
        pub_ids,
    )
    conn.execute(
        f"UPDATE posting_log SET pub_id = NULL WHERE pub_id IN ({placeholders})",
        pub_ids,
    )
    cursor = conn.execute(
        f"DELETE FROM publications WHERE pub_id IN ({placeholders})",
        pub_ids,
    )
    conn.commit()
    return cursor.rowcount > 0


def update_publication_url(
    conn: sqlite3.Connection,
    story_name: str,
    chapter_index: int,
    platform: str,
    content_type: str = "story",
    *,
    external_url: str,
    external_id: str,
) -> bool:
    """Overwrite the URL + external ID of an existing publications row.

    Used by the "set URL manually" affordance when PawPoller's stored
    URL is wrong or empty but the upstream submission exists — letting
    the user paste the live URL and have edit/drift work correctly
    against it.

    Returns True if a row was updated, False if no matching row existed.
    """
    cursor = conn.execute(
        "UPDATE publications "
        "SET external_url = ?, external_id = ? "
        "WHERE content_type = ? AND story_name = ? AND chapter_index = ? AND platform = ?",
        (external_url, external_id, content_type, story_name, chapter_index, platform),
    )
    conn.commit()
    return cursor.rowcount > 0


# ── Posting Log ───────────────────────────────────────────────

def log_posting_action(
    conn: sqlite3.Connection,
    platform: str,
    story_name: str,
    chapter_index: int,
    action: str,
    status: str,
    *,
    account_id: int = 0,
    content_type: str = "story",
    pub_id: int | None = None,
    queue_id: int | None = None,
    external_id: str | None = None,
    external_url: str | None = None,
    error_message: str | None = None,
    duration_seconds: float | None = None,
) -> int:
    """Append an entry to the posting log. Returns log_id."""
    cursor = conn.execute(
        """INSERT INTO posting_log
            (pub_id, queue_id, platform, story_name, chapter_index, account_id, content_type,
             action, status, external_id, external_url, error_message, duration_seconds)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (pub_id, queue_id, platform, story_name, chapter_index, account_id, content_type,
         action, status, external_id, external_url, error_message, duration_seconds),
    )
    conn.commit()
    return cursor.lastrowid


def get_posting_log(
    conn: sqlite3.Connection,
    story_name: str | None = None,
    limit: int = 50,
    content_type: str | None = "story",
) -> list[dict]:
    """Get posting log entries, newest first.

    content_type defaults to "story" so the Stories log view never shows
    artwork; the Artwork hub passes "artwork", None returns everything.
    """
    query = "SELECT * FROM posting_log"
    params: list = []
    conds = []
    if content_type is not None:
        conds.append("content_type = ?")
        params.append(content_type)
    if story_name:
        conds.append("story_name = ?")
        params.append(story_name)
    if conds:
        query += " WHERE " + " AND ".join(conds)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(query, params).fetchall()]
