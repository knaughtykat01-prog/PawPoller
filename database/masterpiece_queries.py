"""Masterpieces — membership CRUD + the live rollup that pools a Masterpiece's
cross-site uploads into merged analytics, locations, tags and persona(s).

A Masterpiece is the master record for ONE image (the image analog of a story's
MASTER.md). Its canonical metadata lives on disk as ``masterpiece.json`` (see
posting/artwork_reader.py); the DB side is a thin NAME-keyed index
(``masterpieces``) plus this membership table (``masterpiece_members``) recording
which platform uploads are the same image.

Stat pooling deliberately reuses collections_queries' per-platform normalisation
(``_location_from_submission`` / ``_stats_from_row`` / ``_METRICS``) so a
Masterpiece and a Collection pool stats identically — one source of truth for
"the same piece across N sites". See docs/specs/masterpieces.md.
"""
from __future__ import annotations

import sqlite3

from database.collections_queries import _acct_to_persona, _location_from_submission


# ── Index + membership CRUD ──────────────────────────────────────

def ensure_indexed(conn: sqlite3.Connection, name: str, *,
                   source_link_id: int | None = None) -> None:
    """Register a Masterpiece name in the thin ``masterpieces`` index (idempotent).
    The disk masterpiece.json remains the source of truth; this just gives us a
    stable row for fast listing + migration provenance."""
    conn.execute(
        "INSERT OR IGNORE INTO masterpieces (name, source_link_id) VALUES (?, ?)",
        (name, source_link_id))
    if source_link_id is not None:
        conn.execute(
            "UPDATE masterpieces SET source_link_id = ?, updated_at = datetime('now') "
            "WHERE name = ? AND source_link_id IS NULL",
            (source_link_id, name))


def get_members(conn: sqlite3.Connection, name: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT masterpiece_name, platform, submission_id, account_id, role, "
        "linked_via, added_at FROM masterpiece_members "
        "WHERE masterpiece_name = ? ORDER BY added_at, platform", (name,)).fetchall()]


def add_member(conn: sqlite3.Connection, name: str, platform: str, submission_id,
               *, account_id: int | None = None, role: str = "crosspost",
               linked_via: str = "manual") -> None:
    """Link one platform upload to a Masterpiece (idempotent on the PK). Ensures
    the name is indexed first so a Masterpiece always has an index row."""
    ensure_indexed(conn, name)
    conn.execute(
        "INSERT OR IGNORE INTO masterpiece_members "
        "(masterpiece_name, platform, submission_id, account_id, role, linked_via) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, platform, str(submission_id), account_id, role or "crosspost",
         linked_via or "manual"))
    conn.execute("UPDATE masterpieces SET updated_at = datetime('now') WHERE name = ?",
                 (name,))


def remove_member(conn: sqlite3.Connection, name: str, platform: str, submission_id) -> None:
    conn.execute(
        "DELETE FROM masterpiece_members WHERE masterpiece_name = ? AND platform = ? "
        "AND submission_id = ?", (name, platform, str(submission_id)))
    conn.execute("UPDATE masterpieces SET updated_at = datetime('now') WHERE name = ?",
                 (name,))


def member_pairs(conn: sqlite3.Connection, name: str) -> list[tuple]:
    """`(platform, submission_id)` pairs for a Masterpiece — feeds the combined
    snapshot chart via analytics_queries.get_combined_snapshots."""
    return [(m["platform"], str(m["submission_id"])) for m in get_members(conn, name)]


# ── Rollup ───────────────────────────────────────────────────────

def rollup_members(conn: sqlite3.Connection, name: str) -> dict:
    """Resolve a Masterpiece's members into live locations and pool the stats.

    Mirrors collections_queries.rollup_collection: sum non-None metrics, union
    tags, collect the personas + platforms spanned. Returns pooled data ONLY —
    the canonical masterpiece.json (title/desc/rating/characters) is merged in by
    the API layer. In Phase 1 members are usually empty (no promote flow yet), so
    this returns zeroed totals for a freshly-indexed name — expected."""
    a2p = _acct_to_persona(conn)
    members = get_members(conn, name)

    locations: list[dict] = []
    for m in members:
        loc = _location_from_submission(
            conn, m["platform"], m["submission_id"],
            account_id=m.get("account_id"), source="masterpiece")
        if loc:
            loc["role"] = m.get("role") or "crosspost"
            loc["linked_via"] = m.get("linked_via") or "manual"
            locations.append(loc)

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
        "members": members,
        "locations": locations,
        "totals": {**tot, "platforms": len(platforms), "locations": len(locations)},
        "tags": sorted(tags),
        "persona_ids": sorted(persona_ids),
    }


def summarize(conn: sqlite3.Connection, name: str) -> dict:
    """Light rollup for the Library grid: pooled totals + personas + member count
    + platforms + an auto-cover (first member location that has a thumbnail)."""
    roll = rollup_members(conn, name)
    locs = roll["locations"]
    cover_thumb, cover_platform = "", ""
    for l in locs:
        if l.get("thumbnail_url"):
            cover_thumb, cover_platform = l["thumbnail_url"], l["platform"]
            break
    return {
        "totals": roll["totals"],
        "persona_ids": roll["persona_ids"],
        "member_count": len(roll["members"]),
        "platforms": sorted({l["platform"] for l in locs}),
        "cover_thumb": cover_thumb,
        "cover_platform": cover_platform,
    }
