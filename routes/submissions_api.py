"""Unified works ("Submissions") hub API.

Read-only aggregation over the local archives + the publications registry that
powers the central Submissions hub: every WORK (story or artwork) the user
manages, grouped per work, with its published platforms and persona.

Note: the per-platform *discovered* submission analytics live at
``/api/submissions`` (analytics). This is the per-WORK view, so it lives at
``/api/works``. Phase 1 of docs/specs/submissions-hub.md (read-only; cards link
to the existing per-work detail views).
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query

from database.db import get_connection
from database import accounts as accounts_db
from database import personas as personas_db
from database import posting_queries

logger = logging.getLogger(__name__)
works_router = APIRouter(prefix="/api")


def _persona_maps(conn):
    """Return (account_id -> persona_id, persona_id -> persona dict)."""
    personas = {p["persona_id"]: p for p in personas_db.list_personas(conn)}
    acct_to_persona = {
        a["account_id"]: a.get("persona_id")
        for a in accounts_db.list_accounts(conn)
        if a.get("persona_id")
    }
    return acct_to_persona, personas


def assemble_works(
    *,
    stories: list[dict],
    artworks: list[dict],
    pubs: list[dict],
    acct_to_persona: dict,
    personas: dict,
    type: str = "all",
    persona: int | None = None,
    search: str | None = None,
    sort: str = "recent",
) -> dict:
    """Pure grouping/filter/sort over already-fetched data (unit-testable).

    Groups publications per (content_type, work name) so each work knows the
    platforms it's posted to and the persona(s) behind those accounts, then
    merges with the local story/artwork archives and applies the filters.
    """
    pub_map: dict[tuple, list] = {}
    for p in pubs:
        pub_map.setdefault((p.get("content_type", "story"), p["story_name"]), []).append(p)

    def enrich(ct: str, name: str):
        wp = pub_map.get((ct, name), [])
        platforms = sorted({p["platform"] for p in wp if p.get("status") == "posted"})
        pids = sorted({
            acct_to_persona[p["account_id"]]
            for p in wp
            if p.get("account_id") in acct_to_persona
        })
        return platforms, len(wp), pids

    works: list[dict] = []

    if type in ("all", "story"):
        for s in stories:
            platforms, count, pids = enrich("story", s["name"])
            cover = (s.get("images") or {}).get("cover", "")
            wc = s.get("word_count") or 0
            works.append({
                "content_type": "story",
                "name": s["name"],
                "title": s.get("title") or s["name"].replace("_", " "),
                "rating": s.get("rating", ""),
                "platforms": platforms,
                "publication_count": count,
                "persona_ids": pids,
                "persona_names": [personas[i]["name"] for i in pids if i in personas],
                "thumb_url": (
                    f"/api/posting/image?story={quote(s['name'])}&file={quote(cover)}"
                    if cover else ""
                ),
                "detail_route": f"#/posting/story/{quote(s['name'])}",
                "meta": (f"{s.get('chapters', 0) or 0} ch · {wc:,} words" if wc else ""),
                "created_at": "",
            })

    if type in ("all", "artwork"):
        for a in artworks:
            platforms, count, pids = enrich("artwork", a["name"])
            img = a.get("image", "")
            works.append({
                "content_type": "artwork",
                "name": a["name"],
                "title": a.get("title") or a["name"].replace("_", " "),
                "rating": a.get("rating", ""),
                "platforms": platforms,
                "publication_count": count,
                "persona_ids": pids,
                "persona_names": [personas[i]["name"] for i in pids if i in personas],
                "thumb_url": (
                    f"/api/artwork/image?name={quote(a['name'])}&file={quote(img)}"
                    if img else ""
                ),
                "detail_route": f"#/artwork/image/{quote(a['name'])}",
                "meta": "",
                "created_at": a.get("created_at", ""),
            })

    if persona:
        works = [w for w in works if persona in w["persona_ids"]]
    if search:
        q = search.lower()
        works = [w for w in works if q in w["title"].lower() or q in w["name"].lower()]

    if sort == "title":
        works.sort(key=lambda w: w["title"].lower())
    elif sort == "platforms":
        works.sort(key=lambda w: len(w["platforms"]), reverse=True)
    else:  # recent
        works.sort(key=lambda w: (w.get("created_at") or ""), reverse=True)

    return {
        "works": works,
        "personas": [
            {"id": p["persona_id"], "name": p["name"], "color": p.get("color", "")}
            for p in personas.values()
        ],
    }


@works_router.get("/works")
def list_works(
    type: str = Query("all"),          # all | story | artwork
    persona: int | None = Query(None),
    search: str | None = Query(None),
    sort: str = Query("recent"),       # recent | title | platforms
):
    """Unified per-work list (stories + artwork) for the Submissions hub.

    The frontend caches the full list and filters client-side; these query
    params mirror that so the endpoint is also useful directly / for tests.
    """
    from posting import story_reader, artwork_reader
    try:
        conn = get_connection()
        try:
            # content_type=None returns BOTH stories and artwork.
            pubs = posting_queries.get_publications(conn, content_type=None)
            acct_to_persona, personas = _persona_maps(conn)
        finally:
            conn.close()
        return assemble_works(
            stories=story_reader.list_stories(),
            artworks=artwork_reader.list_artworks(),
            pubs=pubs,
            acct_to_persona=acct_to_persona,
            personas=personas,
            type=type, persona=persona, search=search, sort=sort,
        )
    except Exception as e:
        logger.error("Error listing works: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
