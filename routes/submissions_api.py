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


def _submission_account_id(conn, platform: str, submission_id: str):
    """The account_id that owns a polled submission (from {platform}_submissions),
    or None. Lets imports/links attribute the publication to the right account."""
    from posting.sync import PLATFORM_TABLES
    cfg = PLATFORM_TABLES.get(platform)
    if not cfg:
        return None
    try:
        row = conn.execute(
            f"SELECT account_id FROM {cfg['table']} WHERE {cfg['id_col']} = ?",
            (str(submission_id),),
        ).fetchone()
        aid = row[0] if row else None
        return aid if aid else None
    except Exception:
        return None


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


# ── Discovered (unlinked) bucket + link-to-work (Phase 2) ─────────────────────

# Art vs text classification for discovered submissions. Used by the Artwork
# hub to surface discovered *visual* work (and by any view that wants to split
# a mixed platform's feed). Two platforms are content-pure for this app; the
# rest are classified from the per-platform type string (category / subtype /
# content_type) the poller already stored.
_ART_ONLY_PLATFORMS = frozenset({"da", "ik", "pix", "ig", "e621"})  # image-first platforms
_TEXT_ONLY_PLATFORMS = frozenset({"ao3", "sqw", "wp"})      # literature-only
# Substrings that mark a type string as prose vs visual. Order matters only in
# that a text hint wins over an art hint (a "story illustration" is still text).
_TEXT_TYPE_HINTS = (
    "stor", "writ", "litera", "prose", "poet", "novel", "chapter", "fiction",
)
_ART_TYPE_HINTS = (
    "art", "visual", "image", "illustration", "digital", "drawing", "sketch",
    "paint", "photo", "comic", "animation", "post",
)


def classify_kind(platform: str, type_str: str, has_image: bool | None = None) -> str:
    """Classify a discovered submission as 'art', 'text', or 'unknown'.

    Pure/unit-testable. Content-pure platforms short-circuit; mixed platforms
    (fa/sf/ib/ws/bsky/mast/thr/tw/tum) are read from their stored type string,
    text hints winning over art hints so a "Story illustration" stays text.
    When the type string is inconclusive, ``has_image`` breaks the tie: an
    image-bearing post is importable as art — this is what lets discovered art
    from ANY polled platform be caught, not just the classic art platforms.
    ``has_image=None`` (unknown) preserves the legacy "unknown" result.
    """
    if platform in _ART_ONLY_PLATFORMS:
        return "art"
    if platform in _TEXT_ONLY_PLATFORMS:
        return "text"
    t = (type_str or "").lower()
    if any(h in t for h in _TEXT_TYPE_HINTS):
        return "text"
    if any(h in t for h in _ART_TYPE_HINTS):
        return "art"
    if has_image is True:
        return "art"      # inconclusive type but has an image → importable as art
    if has_image is False:
        return "text"     # inconclusive type, no image → nothing to import
    return "unknown"


def build_discovered(platform_rows: list[tuple], linked: set) -> list[dict]:
    """Normalize per-platform submission rows into the discovered-unlinked list.

    Pure (unit-testable): given a list of ``(platform, cfg, [row_dict, ...])`` and
    the set of already-linked ``(platform, submission_id)`` pairs, return the
    submissions that have NO matching publication, normalized to one shape.
    """
    out: list[dict] = []
    for platform, cfg, rows in platform_rows:
        id_col, title_col = cfg["id_col"], cfg["title_col"]
        for d in rows:
            sid = str(d.get(id_col) or "")
            if not sid or (platform, sid) in linked:
                continue
            stype = (d.get("category") or d.get("content_type") or d.get("subtype")
                     or d.get("type_name") or "")
            thumb = (d.get("thumbnail_url") or d.get("thumb_url") or d.get("download_url")
                     or d.get("media_url") or d.get("file_url") or "")
            out.append({
                "platform": platform,
                "submission_id": sid,
                "title": d.get(title_col) or f"#{sid}",
                "thumbnail_url": d.get("thumbnail_url") or d.get("thumb_url") or "",
                "type": stype,
                "kind": classify_kind(platform, stype, has_image=bool(thumb)),
                # Prefer the poller-stored permalink; the url_template is only a
                # fallback (and can't be right for instance-scoped mast/tum URLs).
                "url": d.get("link") or cfg["url_template"].format(id=sid),
                "views": d.get("views"),
                "favorites": d.get("favorites_count") or d.get("favorites"),
                "comments": d.get("comments_count") or d.get("comments"),
                "posted_at": (d.get("posted_at") or d.get("create_datetime")
                              or d.get("created_at") or ""),
            })
    out.sort(key=lambda x: x.get("posted_at") or "", reverse=True)
    return out


def get_discovered_unlinked(conn, platform_filter: str | None = None) -> list[dict]:
    """Discovered submissions (across platforms) with no publication link.

    Excludes three sets of (platform, submission_id):
      • already published/linked (a real publication exists),
      • Masterpiece members — a piece bundled into a Masterpiece must not reappear
        as a duplicate discovered tile (dedup, 2.140.0),
      • user-ignored tiles (the Ignore list, 2.140.0).
    """
    from posting.sync import PLATFORM_TABLES
    from database import masterpiece_queries, ignored_queries
    linked = {
        (r["platform"], str(r["external_id"]))
        for r in conn.execute(
            "SELECT platform, external_id FROM publications WHERE external_id != ''")
    }
    # Fold Masterpiece members + the ignore list into the same exclusion set so
    # both the hub and any other consumer of this list get a clean result.
    linked |= masterpiece_queries.all_member_pairs(conn)
    linked |= ignored_queries.all_ignored_pairs(conn)
    platform_rows: list[tuple] = []
    for plat, cfg in PLATFORM_TABLES.items():
        if platform_filter and plat != platform_filter:
            continue
        try:
            rows = [dict(r) for r in conn.execute(f"SELECT * FROM {cfg['table']}").fetchall()]
        except Exception:
            continue  # table may not exist on this install
        platform_rows.append((plat, cfg, rows))
    return build_discovered(platform_rows, linked)


@works_router.get("/works/discovered")
def list_discovered(platform: str | None = Query(None)):
    """Submissions the pollers found that aren't linked to any local work."""
    try:
        conn = get_connection()
        try:
            items = get_discovered_unlinked(conn, platform_filter=platform)
        finally:
            conn.close()
        return {"discovered": items}
    except Exception as e:
        logger.error("Error listing discovered submissions: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


# ── Ignore list for discovered tiles (2.140.0) ────────────────────────────────
# Lets the user dismiss discovered artwork they never want in the hub (e.g. images
# scraped from tweets). Reversible via the un-ignore endpoint.

@works_router.post("/works/discovered/ignore")
def ignore_discovered(body: dict):
    """Add a discovered (platform, submission_id) to the Ignore list."""
    from database import ignored_queries
    platform = body.get("platform")
    submission_id = str(body.get("submission_id") or "")
    if not (platform and submission_id):
        raise HTTPException(400, detail="platform and submission_id are required")
    conn = get_connection()
    try:
        ignored_queries.add_ignored(conn, platform, submission_id)
    finally:
        conn.close()
    return {"status": "ignored", "platform": platform, "submission_id": submission_id}


@works_router.delete("/works/discovered/ignore/{platform}/{submission_id:path}")
def unignore_discovered(platform: str, submission_id: str):
    """Remove a (platform, submission_id) from the Ignore list (it reappears)."""
    from database import ignored_queries
    conn = get_connection()
    try:
        ignored_queries.remove_ignored(conn, platform, submission_id)
    finally:
        conn.close()
    return {"status": "unignored", "platform": platform, "submission_id": submission_id}


@works_router.get("/works/discovered/ignored")
def list_ignored_discovered():
    """The Ignore list (for a manage/restore view)."""
    from database import ignored_queries
    conn = get_connection()
    try:
        return {"ignored": ignored_queries.list_ignored(conn)}
    finally:
        conn.close()


@works_router.post("/works/link")
def link_submission(body: dict):
    """Link a discovered platform submission to an existing local work.

    Writes a publication row (`external_id` = the platform submission id) so the
    work shows that platform in the hub and the submission leaves the discovered
    bucket. ``content_type`` should be the target work's type (story | artwork).
    """
    platform = body.get("platform")
    submission_id = str(body.get("submission_id") or "")
    name = body.get("name")
    content_type = body.get("content_type", "story")
    title = body.get("title", "")
    url = body.get("url", "")
    if not (platform and submission_id and name):
        raise HTTPException(400, detail="platform, submission_id and name are required")
    try:
        conn = get_connection()
        try:
            # Attribute the publication to the account that actually owns the
            # submission (from its {platform}_submissions row), not the platform
            # default — so persona/account scoping is correct.
            acct_id = _submission_account_id(conn, platform, submission_id)
            pub_id = posting_queries.upsert_publication(
                conn,
                story_name=name,
                chapter_index=0,
                platform=platform,
                account_id=acct_id,
                content_type=content_type,
                external_id=submission_id,
                external_url=url,
                title_used=title,
                status="posted",
            )
        finally:
            conn.close()
        return {"status": "linked", "pub_id": pub_id}
    except Exception as e:
        logger.error("Link failed: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
