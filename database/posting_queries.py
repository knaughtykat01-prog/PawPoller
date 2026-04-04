"""CRUD operations for the posting module tables.

Tables: publications, posting_queue, posting_log.
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
    """Insert or update a publication record. Returns pub_id."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    tags_json = json.dumps(tags_used or [])

    # Check if exists
    row = conn.execute(
        "SELECT pub_id, update_count FROM publications "
        "WHERE story_name = ? AND chapter_index = ? AND platform = ?",
        (story_name, chapter_index, platform),
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
                (story_name, chapter_index, platform, external_id, external_url,
                 title_used, description_used, tags_used, rating_used,
                 format_file, file_hash, word_count, status, first_posted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (story_name, chapter_index, platform, external_id, external_url,
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
) -> list[dict]:
    """Get publications with optional filters."""
    query = "SELECT * FROM publications WHERE 1=1"
    params: list = []
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
) -> list[dict]:
    """Get publications enriched with live stats from the polling submission tables.

    Joins each publication's external_id with the platform-specific submission table
    to pull in current views, faves, comments counts.
    """
    pubs = get_publications(conn, story_name=story_name, status="posted")

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
) -> dict | None:
    """Get a publication by its unique (story, chapter, platform) key."""
    row = conn.execute(
        "SELECT * FROM publications WHERE story_name = ? AND chapter_index = ? AND platform = ?",
        (story_name, chapter_index, platform),
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
        requires: Runtime mode needed — 'any', 'desktop', or 'server'.
            Desktop-only platforms (FA) should be queued with 'desktop' so the
            server scheduler skips them and they're picked up when the desktop app opens.
    """
    cursor = conn.execute(
        """INSERT INTO posting_queue
            (story_name, chapter_index, platform, action, scheduled_at,
             title_override, description_override, tags_override,
             rating_override, file_path_override, priority, requires)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (story_name, chapter_index, platform, action, scheduled_at,
         title_override, description_override, tags_override,
         rating_override, file_path_override, priority, requires),
    )
    conn.commit()
    return cursor.lastrowid


def get_pending_queue(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Get pending queue items ordered by priority then creation time."""
    rows = conn.execute(
        """SELECT * FROM posting_queue
        WHERE status = 'pending'
          AND (scheduled_at IS NULL OR scheduled_at <= datetime('now'))
        ORDER BY priority DESC, created_at ASC
        LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_queue(conn: sqlite3.Connection, include_completed: bool = False) -> list[dict]:
    """Get all queue items."""
    if include_completed:
        rows = conn.execute(
            "SELECT * FROM posting_queue ORDER BY created_at DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM posting_queue WHERE status IN ('pending', 'processing') "
            "ORDER BY priority DESC, created_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_queue_status(
    conn: sqlite3.Connection,
    queue_id: int,
    status: str,
    *,
    error: str | None = None,
    pub_id: int | None = None,
) -> None:
    """Update a queue item's status."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if status == "processing":
        conn.execute(
            "UPDATE posting_queue SET status = ?, started_at = ?, attempts = attempts + 1 WHERE queue_id = ?",
            (status, now, queue_id),
        )
    elif status in ("completed", "failed"):
        conn.execute(
            "UPDATE posting_queue SET status = ?, completed_at = ?, last_error = ?, pub_id = ? WHERE queue_id = ?",
            (status, now, error, pub_id, queue_id),
        )
    else:
        conn.execute(
            "UPDATE posting_queue SET status = ? WHERE queue_id = ?",
            (status, queue_id),
        )
    conn.commit()


def cancel_queue_item(conn: sqlite3.Connection, queue_id: int) -> bool:
    """Cancel a pending queue item."""
    cursor = conn.execute(
        "UPDATE posting_queue SET status = 'cancelled' WHERE queue_id = ? AND status = 'pending'",
        (queue_id,),
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
            (pub_id, queue_id, platform, story_name, chapter_index,
             action, status, external_id, external_url, error_message, duration_seconds)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (pub_id, queue_id, platform, story_name, chapter_index,
         action, status, external_id, external_url, error_message, duration_seconds),
    )
    conn.commit()
    return cursor.lastrowid


def get_posting_log(
    conn: sqlite3.Connection,
    story_name: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Get posting log entries, newest first."""
    query = "SELECT * FROM posting_log"
    params: list = []
    if story_name:
        query += " WHERE story_name = ?"
        params.append(story_name)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(query, params).fetchall()]
