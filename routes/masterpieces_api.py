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
