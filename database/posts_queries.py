"""Data-access helpers for the Posts (microblog) module — 2.49.0.

Thin CRUD over the ``posts`` + ``post_publications`` tables. No business logic
lives here (that's ``posting/post_publisher.py``); these just read/write rows
and hand back plain dicts. Timestamps are supplied by the caller so the pure
helpers stay side-effect free and testable.
"""
from __future__ import annotations

import sqlite3


# ── posts ──────────────────────────────────────────────────────────

def create_post(conn: sqlite3.Connection, *, body: str, rating: str = "general",
                image_path: str = "", image_alt: str = "", now: str = "") -> int:
    """Insert a draft post and return its post_id."""
    cur = conn.execute(
        "INSERT INTO posts (body, rating, image_path, image_alt, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (body, rating, image_path, image_alt, now, now),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_post(conn: sqlite3.Connection, post_id: int, *, now: str = "", **fields) -> None:
    """Patch a post's editable columns (body/rating/image_path/image_alt)."""
    allowed = {"body", "rating", "image_path", "image_alt"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            vals.append(v)
    if not sets:
        return
    sets.append("updated_at = ?")
    vals.append(now)
    vals.append(post_id)
    conn.execute(f"UPDATE posts SET {', '.join(sets)} WHERE post_id = ?", vals)
    conn.commit()


def get_post(conn: sqlite3.Connection, post_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM posts WHERE post_id = ?", (post_id,)).fetchone()
    return dict(row) if row else None


def list_posts(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    """Posts newest-first, each with its publications list attached."""
    rows = conn.execute(
        "SELECT * FROM posts ORDER BY post_id DESC LIMIT ?", (limit,)
    ).fetchall()
    posts = [dict(r) for r in rows]
    if not posts:
        return []
    ids = [p["post_id"] for p in posts]
    ph = ",".join("?" * len(ids))
    pubs = conn.execute(
        f"SELECT * FROM post_publications WHERE post_id IN ({ph}) ORDER BY id", ids
    ).fetchall()
    by_post: dict[int, list] = {}
    for pub in pubs:
        by_post.setdefault(pub["post_id"], []).append(dict(pub))
    for p in posts:
        p["publications"] = by_post.get(p["post_id"], [])
    return posts


def delete_post(conn: sqlite3.Connection, post_id: int) -> None:
    conn.execute("DELETE FROM post_publications WHERE post_id = ?", (post_id,))
    conn.execute("DELETE FROM posts WHERE post_id = ?", (post_id,))
    conn.commit()


# ── post_publications ──────────────────────────────────────────────

def upsert_post_publication(conn: sqlite3.Connection, *, post_id: int, platform: str,
                            account_id: int = 0, status: str = "pending",
                            external_id: str = "", external_url: str = "",
                            error: str = "", now: str = "") -> int:
    """Insert or update the (post, platform, account) publication row."""
    conn.execute(
        "INSERT INTO post_publications "
        "(post_id, platform, account_id, status, external_id, external_url, error, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(post_id, platform, account_id) DO UPDATE SET "
        "status=excluded.status, external_id=excluded.external_id, "
        "external_url=excluded.external_url, error=excluded.error",
        (post_id, platform, account_id, status, external_id, external_url, error, now),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM post_publications WHERE post_id=? AND platform=? AND account_id=?",
        (post_id, platform, account_id),
    ).fetchone()
    return int(row["id"]) if row else 0


def get_post_publications(conn: sqlite3.Connection, post_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM post_publications WHERE post_id = ? ORDER BY id", (post_id,)
    ).fetchall()
    return [dict(r) for r in rows]
