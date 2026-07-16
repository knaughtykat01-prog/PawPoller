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
