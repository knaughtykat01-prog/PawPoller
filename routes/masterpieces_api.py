"""Masterpieces API (read) — a Masterpiece is the master record for ONE image
across every site it was posted to. See docs/specs/masterpieces.md.

Canonical metadata (title / description / rating / tags / characters) lives on
disk as masterpiece.json (posting/artwork_reader.py); cross-site membership +
pooled analytics come from the masterpiece_members table (database/
masterpiece_queries.py). This router merges the two for the Library grid + the
detail view. Phase 1 is READ-ONLY — the promote/link flow that populates members
lands in Phase 3, so a fresh Masterpiece lists with zeroed pooled stats until
then (expected).
"""
import logging

from fastapi import APIRouter, HTTPException

from database.db import get_connection
from database import masterpiece_queries as mq
from posting import artwork_reader

logger = logging.getLogger(__name__)

masterpieces_router = APIRouter(prefix="/api/masterpieces", tags=["masterpieces"])


@masterpieces_router.get("")
def list_masterpieces():
    """Every Masterpiece (one per artwork folder) + a light pooled rollup.

    The canonical fields come from disk (masterpiece.json); ``summary`` carries the
    live cross-site pooling (totals / personas / member count / cover). We adopt
    each name into the thin ``masterpieces`` index on the way past so Phase 3's
    linker always has a row to hang members off.
    """
    conn = get_connection()
    try:
        out = []
        for art in artwork_reader.list_artworks():
            name = art["name"]
            mq.ensure_indexed(conn, name)
            out.append({**art, "summary": mq.summarize(conn, name)})
        conn.commit()
        return {"masterpieces": out}
    finally:
        conn.close()


@masterpieces_router.get("/{name}")
def get_masterpiece(name: str):
    """Full detail: canonical metadata (from masterpiece.json) + resolved member
    locations + pooled totals / tags / personas.

    ``canonical_tags`` is the master record's per-platform tag map; ``tags`` is the
    union actually observed on the live member uploads (empty until members exist).
    """
    try:
        art = artwork_reader.load_artwork(name)
    except FileNotFoundError:
        raise HTTPException(404, detail="Masterpiece not found")
    conn = get_connection()
    try:
        mq.ensure_indexed(conn, name)
        conn.commit()
        roll = mq.rollup_members(conn, name)
        return {
            "name": art.name,
            "title": art.title,
            "description": art.description,
            "author": art.author,
            "rating": art.rating,
            "image": art.image,
            "thumbnail": art.thumbnail,
            "characters": art.characters,
            "platforms": art.platforms,
            "created_at": art.created_at,
            "canonical_tags": art.tags_by_platform,
            "members": roll["members"],
            "locations": roll["locations"],
            "totals": roll["totals"],
            "tags": roll["tags"],
            "persona_ids": roll["persona_ids"],
        }
    finally:
        conn.close()


@masterpieces_router.get("/{name}/snapshots")
def get_masterpiece_snapshots(name: str):
    """Combined time-series (summed views/faves/comments) across every site this
    Masterpiece lives on — the same chart a Collection draws, scoped to one image."""
    try:
        artwork_reader.load_artwork(name)
    except FileNotFoundError:
        raise HTTPException(404, detail="Masterpiece not found")
    conn = get_connection()
    try:
        from database import analytics_queries
        pairs = mq.member_pairs(conn, name)
        return {"snapshots": analytics_queries.get_combined_snapshots(conn, pairs)}
    finally:
        conn.close()


@masterpieces_router.get("/{name}/suggestions")
def get_masterpiece_suggestions(name: str):
    """Native (no-AI) same-image candidates not yet linked to this Masterpiece —
    perceptual-hash + title, anchored to the master's members/canonical image.
    Warm the hash store first via POST /api/collections/hash-scan if it's cold."""
    try:
        artwork_reader.load_artwork(name)
    except FileNotFoundError:
        raise HTTPException(404, detail="Masterpiece not found")
    conn = get_connection()
    try:
        return {"suggestions": mq.suggestions(conn, name)}
    finally:
        conn.close()


# ── Write (promote + membership, Phase 3) ────────────────────────

@masterpieces_router.post("")
def promote_masterpiece(body: dict):
    """Promote a discovered/imported submission into a Masterpiece + seed its
    primary member. Body: {from: {platform, submission_id}} (spec §3.1)."""
    src = (body or {}).get("from") or {}
    platform = (src.get("platform") or "").strip()
    sid = str(src.get("submission_id") or "").strip()
    if not platform or not sid:
        raise HTTPException(400, detail="from.platform and from.submission_id are required")
    conn = get_connection()
    try:
        res = mq.promote_from_submission(conn, platform, sid)
        conn.commit()
        return {"status": res.get("status", "imported"), "name": res["name"],
                "images": res.get("images", 1)}
    except ValueError as e:
        # Un-importable submission (no image URL, FA datacenter-IP block, …).
        raise HTTPException(422, detail=str(e))
    finally:
        conn.close()


@masterpieces_router.post("/{name}/members")
def add_masterpiece_member(name: str, body: dict):
    """Attach a site-upload to this Masterpiece. Body: {platform, submission_id,
    account_id?, role?, linked_via?}."""
    try:
        artwork_reader.load_artwork(name)
    except FileNotFoundError:
        raise HTTPException(404, detail="Masterpiece not found")
    platform = (body.get("platform") or "").strip()
    sid = str(body.get("submission_id") or "").strip()
    if not platform or not sid:
        raise HTTPException(400, detail="platform and submission_id are required")
    conn = get_connection()
    try:
        # Default the member's account to the source submission's, so persona
        # rollup stays correct (the "everything lumps under the default" bug).
        acct = body.get("account_id")
        if acct is None:
            from database.collections_queries import _submission_row
            acct = (_submission_row(conn, platform, sid) or {}).get("account_id")
        mq.add_member(conn, name, platform, sid, account_id=acct,
                      role=body.get("role", "crosspost"),
                      linked_via=body.get("linked_via", "manual"))
        conn.commit()
        return {"status": "added"}
    finally:
        conn.close()


@masterpieces_router.delete("/{name}/members")
def remove_masterpiece_member(name: str, platform: str, submission_id: str):
    """Detach a site-upload (query params: platform, submission_id)."""
    conn = get_connection()
    try:
        mq.remove_member(conn, name, platform, submission_id)
        conn.commit()
        return {"status": "removed"}
    finally:
        conn.close()


# ── Canonical edit + Sync-all (Phase 5) ──────────────────────────

# Canonical rating vocabulary (spec §0-A5) — the poster maps to each site's scale.
_RATINGS = {"general", "mature", "adult"}


@masterpieces_router.patch("/{name}")
def update_masterpiece(name: str, body: dict):
    """Edit the Masterpiece's canonical record (writes ``masterpiece.json``).

    Editable fields: title / description / rating / characters / tags (the
    canonical *default* tag set — per-platform overrides are preserved). This is
    the "edit once" half; pushing it to the live uploads is POST /{name}/sync.
    """
    try:
        raw = artwork_reader.read_raw_metadata(name)
    except FileNotFoundError:
        raise HTTPException(404, detail="Masterpiece not found")

    updates: dict = {}
    if "title" in body:
        updates["title"] = str(body.get("title") or "").strip()
    if "description" in body:
        updates["description"] = str(body.get("description") or "")
    if "rating" in body:
        r = str(body.get("rating") or "").strip().lower()
        if r and r not in _RATINGS:
            raise HTTPException(400, detail="rating must be general | mature | adult")
        updates["rating"] = r
    if "characters" in body and isinstance(body["characters"], list):
        updates["characters"] = [str(c).strip() for c in body["characters"] if str(c).strip()]
    if "tags" in body and isinstance(body["tags"], list):
        # Set the canonical (default) tags; keep any real per-platform overrides
        # from the RAW file (not the cascaded ArtworkInfo).
        tags = dict(raw.get("tags") or {})
        tags["default"] = [str(t).strip() for t in body["tags"] if str(t).strip()]
        updates["tags"] = tags
    if not updates:
        raise HTTPException(400, detail="no editable fields provided")

    artwork_reader.save_artwork_metadata(name, updates)
    return {"status": "updated", "name": name}


@masterpieces_router.post("/{name}/sync")
async def sync_masterpiece(name: str, body: dict | None = None):
    """Push the canonical record to every **editable** member (metadata only —
    never re-uploads the image). Members on non-editable platforms
    (Bluesky/e621/Itaku) are returned as skipped ``post-only``. Body (optional):
    {platforms?: [...]} to restrict the sync."""
    from posting import manager
    try:
        artwork_reader.load_artwork(name)
    except FileNotFoundError:
        raise HTTPException(404, detail="Masterpiece not found")
    platforms = (body or {}).get("platforms") or None
    try:
        results = await manager.update_artwork(name, platforms=platforms)
    except Exception as e:
        logger.error("Masterpiece sync failed for %s: %s", name, e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    synced = [r for r in results if r.get("success")]
    skipped = [r for r in results if r.get("skipped")]
    failed = [r for r in results if not r.get("success") and not r.get("skipped")]
    return {
        "status": "completed",
        "synced": len(synced),
        "skipped": len(skipped),
        "failed": len(failed),
        "results": results,
    }
