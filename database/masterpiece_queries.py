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

from database.collections_queries import _acct_to_persona, _location_from_submission, _submission_row


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


def all_member_pairs(conn: sqlite3.Connection) -> set[tuple]:
    """Every `(platform, submission_id)` that belongs to ANY Masterpiece.

    Used by the Artwork hub's discovered list to drop tiles that are already
    Masterpiece members — a piece bundled into a Masterpiece shouldn't reappear
    as a duplicate discovered tile (2.140.0)."""
    return {
        (r["platform"], str(r["submission_id"]))
        for r in conn.execute(
            "SELECT platform, submission_id FROM masterpiece_members")
    }


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


# ── Promote (create a Masterpiece from a discovered/imported submission) ──

def promote_from_submission(conn: sqlite3.Connection, platform: str, submission_id) -> dict:
    """Materialise a Masterpiece from a platform submission the pollers already
    discovered, and seed its **primary** member (spec §3.1).

    Reuses ``posting.artwork_importer.import_artwork`` for the heavy lifting
    (download full-res where available, write the folder + ``masterpiece.json`` +
    a publication with the right ``account_id``) — that path is idempotent
    (re-promoting a submission returns the existing folder). Then:
      • ensure the name is indexed,
      • add the source ``(platform, submission_id, account_id)`` as ``role='primary'``,
      • compute + store the canonical image's perceptual hash (feeds same-image
        suggestions) both in ``image_hashes`` and on ``masterpiece.json``.

    Returns ``{name, status, images}``. Raises ValueError on an un-importable
    submission (surfaced by the route as a 4xx). Import runs on its own
    connections and commits before we touch ``conn``.
    """
    from posting import artwork_importer

    res = artwork_importer.import_artwork(platform, str(submission_id))
    name = res["name"]
    ensure_indexed(conn, name)

    row = _submission_row(conn, platform, str(submission_id)) or {}
    add_member(conn, name, platform, submission_id, account_id=row.get("account_id"),
               role="primary", linked_via="manual")

    # Perceptual hash of the canonical image — best-effort, never fails the promote.
    try:
        from database import image_hash
        from posting import artwork_reader
        art = artwork_reader.load_artwork(name)
        if art.image:
            ph = image_hash.dhash_from_path(str(art.path / art.image))
            if ph:
                image_hash.ensure_table(conn)
                image_hash.store(conn, platform, str(submission_id), ph, source="masterpiece")
                artwork_reader.save_artwork_metadata(name, {"phash": ph})
    except Exception:
        pass

    return {"name": name, "status": res.get("status", "imported"),
            "images": res.get("images", 1)}


# ── Same-image suggestions (native pHash, no AI) ─────────────────

def suggestions(conn: sqlite3.Connection, name: str) -> list[dict]:
    """Cross-platform "this same image also lives here?" candidates for a
    Masterpiece — NOT already members (spec §3.1 step 4).

    Anchored, native, no-AI: seed from the perceptual hashes of the Masterpiece's
    existing members **and** a fresh hash of its canonical image, then scan the
    ``image_hashes`` store for rows within ``HAMMING_THRESHOLD`` of any seed. The
    store is warmed by ``POST /api/collections/hash-scan`` (local artwork + an
    allowlisted thumbnail scan); if it is cold this simply returns few/none, so the
    frontend offers a "scan for matches" action first.

    Returns ``[{platform, submission_id, similarity, reason:'image', title,
    thumbnail_url, account_id}, …]`` sorted by similarity, best 20.
    """
    from database import image_hash

    members = set(member_pairs(conn, name))
    seeds: set[str] = set()
    for plat, sid in members:
        r = conn.execute(
            "SELECT phash FROM image_hashes WHERE platform = ? AND submission_id = ?",
            (plat, str(sid))).fetchone()
        if r and r["phash"]:
            seeds.add(r["phash"])
    # Fresh hash of the canonical image so suggestions work even when no member
    # has been hashed yet (zero network — local file).
    try:
        from posting import artwork_reader
        art = artwork_reader.load_artwork(name)
        if art.image:
            ph = image_hash.dhash_from_path(str(art.path / art.image))
            if ph:
                seeds.add(ph)
    except Exception:
        pass
    if not seeds:
        return []

    out: dict[tuple, dict] = {}
    for row in image_hash.all_hashes(conn):
        key = (row["platform"], str(row["submission_id"]))
        if key in members:
            continue
        d = min(image_hash.hamming(row["phash"], s) for s in seeds)
        if d > image_hash.HAMMING_THRESHOLD:
            continue
        sim = round(1.0 - d / 64.0, 3)
        cur = out.get(key)
        if cur is not None and cur["similarity"] >= sim:
            continue
        loc = _location_from_submission(conn, key[0], key[1], source="suggestion") or {}
        out[key] = {
            "platform": key[0],
            "submission_id": key[1],
            "similarity": sim,
            "reason": "image",
            "title": loc.get("title", ""),
            "thumbnail_url": loc.get("thumbnail_url", ""),
            "account_id": loc.get("account_id"),
        }
    return sorted(out.values(), key=lambda c: c["similarity"], reverse=True)[:20]


# ── submission_links → Masterpieces migration (Phase 7, §7) ──────

def migrate_links_to_masterpieces(conn: sqlite3.Connection) -> int:
    """One-time, idempotent, **reversible** fold of each Cross-Platform
    ``submission_link`` (an old art "master") into a Masterpiece (spec §7).

    Mirrors ``collections_queries.migrate_links_to_collections``: each link with
    ≥2 members becomes one Masterpiece — a ``masterpieces`` index row +
    ``masterpiece_members`` (the first title-resolving member is ``role='primary'``,
    ``linked_via='migration'``). The ``submission_links`` rows are left **intact**
    (fully reversible); idempotency + provenance via ``masterpieces.source_link_id``.
    Returns the number newly created.

    **Known limitation (spec §9):** a migrated Masterpiece is *index-only* — it has
    no canonical folder/image yet, so it won't appear in the folder-based Library
    grid (which enumerates `list_artworks()`) until "materialised" via the promote
    flow. This function is therefore provided for explicit invocation, NOT wired to
    startup (so it can't silently mint grid-invisible Masterpieces). On installs
    where ``submission_links`` is empty it is a no-op.
    """
    try:
        link_rows = conn.execute("SELECT link_id FROM submission_links").fetchall()
    except Exception:
        return 0  # link tables absent on this DB — nothing to migrate
    try:
        migrated = {r["source_link_id"] for r in conn.execute(
            "SELECT source_link_id FROM masterpieces WHERE source_link_id IS NOT NULL")}
    except Exception:
        return 0  # masterpieces table / source_link_id not present yet
    n = 0
    for lr in link_rows:
        lid = lr["link_id"]
        if lid in migrated:
            continue
        members = conn.execute(
            "SELECT platform, submission_id FROM submission_link_members WHERE link_id = ?",
            (lid,)).fetchall()
        if len(members) < 2:
            continue  # a link needs 2+ members to be a meaningful master
        # Name from the first member that resolves a title (fallback: link id).
        name = ""
        for m in members:
            row = _submission_row(conn, m["platform"], str(m["submission_id"]))
            if row and (row.get("title") or row.get("full_text")):
                name = (row.get("title") or row.get("full_text") or "").strip()[:120]
                break
        if not name:
            name = f"Linked piece #{lid}"
        # Never collide with an existing Masterpiece/folder name (masterpieces.name
        # is UNIQUE); suffix if needed.
        base, k = name, 2
        while conn.execute("SELECT 1 FROM masterpieces WHERE name = ?", (name,)).fetchone():
            name, k = f"{base} ({k})", k + 1
        conn.execute("INSERT INTO masterpieces (name, source_link_id) VALUES (?, ?)", (name, lid))
        first = True
        for m in members:
            # account_id from the source row → correct persona rollup (§7 preserve).
            row = _submission_row(conn, m["platform"], str(m["submission_id"])) or {}
            conn.execute(
                "INSERT OR IGNORE INTO masterpiece_members "
                "(masterpiece_name, platform, submission_id, account_id, role, linked_via) "
                "VALUES (?, ?, ?, ?, ?, 'migration')",
                (name, m["platform"], str(m["submission_id"]), row.get("account_id"),
                 "primary" if first else "crosspost"))
            first = False
        n += 1
    return n
