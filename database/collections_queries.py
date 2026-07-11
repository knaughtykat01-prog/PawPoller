"""Collections — CRUD + the live rollup that resolves a collection's polymorphic
members (works / submissions / posts) into pooled analytics, locations, merged
tags and the persona(s) spanned. See docs/specs/collections.md.

The per-platform stat-column normalisation mirrors
analytics_queries.get_link_combined_stats (the unify-master pooling), so a
Collection and a Master pool stats the same way.
"""
from __future__ import annotations

import json
import sqlite3

from database import posting_queries

# platform code -> its submissions table
_TABLE_MAP = {
    "ib": "submissions", "fa": "fa_submissions", "ws": "ws_submissions",
    "sf": "sf_submissions", "sqw": "sqw_submissions", "ao3": "ao3_submissions",
    "da": "da_submissions", "wp": "wp_submissions", "ik": "ik_submissions",
    "bsky": "bsky_submissions", "tw": "tw_submissions", "mast": "mast_submissions",
    "tum": "tum_submissions", "pix": "pix_submissions", "thr": "thr_submissions",
    "ig": "ig_submissions",
}
# platform code -> (views_col, favourites_col, comments_col); None = not tracked
_METRICS = {
    "ib": ("views", "favorites_count", "comments_count"),
    "fa": ("views", "favorites_count", "comments_count"),
    "ws": ("views", "favorites_count", "comments_count"),
    "sf": ("views", "favorites_count", "comments_count"),
    "sqw": ("views", "favorites_count", "comments_count"),
    "ao3": ("views", "favorites_count", "comments_count"),
    "da": ("views", "favorites_count", "comments_count"),
    "wp": ("reads", "votes", "comments_count"),
    "ik": (None, "likes", "comments_count"),
    "bsky": (None, "likes", "replies"),
    "tw": ("views", "likes", "replies"),
    "mast": (None, "likes", "replies"),
    "tum": (None, "notes", None),
    "pix": ("views", "favorites_count", "comments_count"),
    "thr": ("views", "likes", "replies"),
    "ig": ("views", "likes", "comments"),
}


# ── CRUD ─────────────────────────────────────────────────────────

def create_collection(conn: sqlite3.Connection, name: str, cover_kind: str = "",
                      cover_ref: str = "", notes: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO collections (name, cover_kind, cover_ref, notes) VALUES (?, ?, ?, ?)",
        (name or "Untitled collection", cover_kind or "", cover_ref or "", notes or ""))
    return cur.lastrowid


def list_collections(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM collections ORDER BY updated_at DESC, id DESC").fetchall()]


def get_collection(conn: sqlite3.Connection, cid: int) -> dict | None:
    row = conn.execute("SELECT * FROM collections WHERE id = ?", (cid,)).fetchone()
    return dict(row) if row else None


def update_collection(conn: sqlite3.Connection, cid: int, **fields) -> None:
    allowed = {"name", "cover_kind", "cover_ref", "notes"}
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed and v is not None:
            sets.append(f"{k} = ?")
            params.append(v)
    if not sets:
        return
    sets.append("updated_at = datetime('now')")
    params.append(cid)
    conn.execute(f"UPDATE collections SET {', '.join(sets)} WHERE id = ?", params)


def delete_collection(conn: sqlite3.Connection, cid: int) -> None:
    conn.execute("DELETE FROM collection_members WHERE collection_id = ?", (cid,))
    conn.execute("DELETE FROM collections WHERE id = ?", (cid,))


def get_members(conn: sqlite3.Connection, cid: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT member_type, member_ref, role, added_at FROM collection_members "
        "WHERE collection_id = ? ORDER BY added_at", (cid,)).fetchall()]


def add_member(conn: sqlite3.Connection, cid: int, member_type: str,
               member_ref: str, role: str = "") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO collection_members (collection_id, member_type, member_ref, role) "
        "VALUES (?, ?, ?, ?)", (cid, member_type, member_ref, role or ""))
    conn.execute("UPDATE collections SET updated_at = datetime('now') WHERE id = ?", (cid,))


def remove_member(conn: sqlite3.Connection, cid: int, member_type: str, member_ref: str) -> None:
    conn.execute(
        "DELETE FROM collection_members WHERE collection_id = ? AND member_type = ? AND member_ref = ?",
        (cid, member_type, member_ref))
    conn.execute("UPDATE collections SET updated_at = datetime('now') WHERE id = ?", (cid,))


# ── Rollup ───────────────────────────────────────────────────────

def _acct_to_persona(conn: sqlite3.Connection) -> dict:
    try:
        return {r["account_id"]: r["persona_id"]
                for r in conn.execute("SELECT account_id, persona_id FROM accounts")
                if r["persona_id"]}
    except Exception:
        return {}


def _parse_tags(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(t) for t in raw if str(t).strip()]
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            return [str(t) for t in v if str(t).strip()]
    except Exception:
        pass
    return [t.strip() for t in str(raw).split(",") if t.strip()]


def _submission_row(conn: sqlite3.Connection, platform: str, sid: str) -> dict | None:
    tbl = _TABLE_MAP.get(platform)
    if not tbl:
        return None
    try:
        r = conn.execute(f"SELECT * FROM {tbl} WHERE submission_id = ?", (str(sid),)).fetchone()
    except Exception:
        return None
    return dict(r) if r else None


def _stats_from_row(platform: str, row: dict) -> dict:
    v, f, c = _METRICS.get(platform, ("views", "favorites_count", "comments_count"))
    return {
        "views": (row.get(v, 0) or 0) if v else None,
        "favorites": (row.get(f, 0) or 0) if f else None,
        "comments": (row.get(c, 0) or 0) if c else None,
    }


def _location_from_submission(conn, platform: str, sid: str, *, url: str = "",
                              account_id=None, source: str = "submission") -> dict | None:
    """Resolve one platform submission into a location dict (stats + link + tags)."""
    row = _submission_row(conn, platform, sid)
    if not row:
        # Still surface the location even if the poller hasn't stored it (link only).
        if not url:
            return None
        return {"platform": platform, "submission_id": str(sid), "url": url,
                "title": "", "account_id": account_id, "stats": {"views": None, "favorites": None, "comments": None},
                "keywords": [], "source": source}
    return {
        "platform": platform,
        "submission_id": str(sid),
        "url": url or row.get("link") or "",
        "title": row.get("title") or row.get("full_text") or "",
        "account_id": account_id if account_id is not None else row.get("account_id"),
        "stats": _stats_from_row(platform, row),
        "keywords": _parse_tags(row.get("keywords")),
        "source": source,
    }


def rollup_collection(conn: sqlite3.Connection, cid: int) -> dict | None:
    """Full detail for one collection: metadata + resolved locations + pooled
    totals + merged tags + persona(s) spanned + the companion story (if any)."""
    coll = get_collection(conn, cid)
    if not coll:
        return None
    members = get_members(conn, cid)
    a2p = _acct_to_persona(conn)

    locations: list[dict] = []
    story = None

    for m in members:
        mtype, mref, role = m["member_type"], m["member_ref"], m.get("role", "")
        if mtype == "submission":
            platform, _, sid = mref.partition(":")
            loc = _location_from_submission(conn, platform, sid, source="submission")
            if loc:
                locations.append(loc)
        elif mtype == "work":
            ct, _, name = mref.partition(":")
            if ct == "story" and story is None:
                story = {"name": name}
            for p in posting_queries.get_publications(conn, story_name=name, content_type=ct):
                if p.get("status") not in (None, "", "posted"):
                    continue
                loc = _location_from_submission(
                    conn, p["platform"], p.get("external_id", ""),
                    url=p.get("external_url", ""), account_id=p.get("account_id"),
                    source=f"work:{ct}")
                if loc:
                    loc["work_name"] = name
                    loc["work_type"] = ct
                    locations.append(loc)
        # 'post' members: resolved lightly for now (no per-platform stats table);
        # surfaced by the curation UI. Left out of stats rollup intentionally.

    # Pool: sum non-None metrics; merge tags; collect personas + platforms.
    tot = {"views": 0, "favorites": 0, "comments": 0}
    tags: set[str] = set()
    persona_ids: set[int] = set()
    platforms: set[str] = set()
    for loc in locations:
        for k in tot:
            val = loc["stats"].get(k)
            if val:
                tot[k] += val
        tags.update(loc.get("keywords") or [])
        platforms.add(loc["platform"])
        aid = loc.get("account_id")
        if aid in a2p:
            persona_ids.add(a2p[aid])

    return {
        **coll,
        "members": members,
        "locations": locations,
        "totals": {**tot, "platforms": len(platforms), "locations": len(locations)},
        "tags": sorted(tags),
        "persona_ids": sorted(persona_ids),
        "story": story,
    }


def list_collections_with_summary(conn: sqlite3.Connection) -> list[dict]:
    """Every collection + a light rollup (totals, platforms, personas, cover) for
    the hub grid. Reuses rollup_collection but trims the heavy per-location list."""
    out = []
    for c in list_collections(conn):
        roll = rollup_collection(conn, c["id"]) or {}
        out.append({
            **c,
            "totals": roll.get("totals", {"views": 0, "favorites": 0, "comments": 0,
                                          "platforms": 0, "locations": 0}),
            "persona_ids": roll.get("persona_ids", []),
            "member_count": len(roll.get("members", [])),
            "platforms": sorted({l["platform"] for l in roll.get("locations", [])}),
        })
    return out
