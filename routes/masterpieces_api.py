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
import re

from fastapi import APIRouter, File, HTTPException, UploadFile

from database.db import get_connection
from database import masterpiece_queries as mq
from posting import artwork_reader

logger = logging.getLogger(__name__)

# Same archive cap the artwork uploader enforces (routes/artwork_api.py).
_MAX_IMAGE_BYTES = 50 * 1024 * 1024

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
        st = mq.statuses(conn)
        for art in artwork_reader.list_artworks():
            name = art["name"]
            mq.ensure_indexed(conn, name)
            out.append({**art, "summary": mq.summarize(conn, name),
                        "status": st.get(name, "")})
        conn.commit()
        return {"masterpieces": out}
    finally:
        conn.close()


# ── De-duplication (2.144.0) ──────────────────────────────────────────────────
# NOTE: these MUST be declared before the generic /{name} route, else Starlette
# captures "/duplicates" as name="duplicates".

@masterpieces_router.get("/duplicates")
def masterpiece_duplicates():
    """Groups of Masterpieces whose hero images are near-identical (perceptual
    hash), so the user can merge same-image duplicates. Each group is sorted with
    the best merge-survivor first (most views, then most sites)."""
    from database import image_hash
    conn = get_connection()
    try:
        image_hash.hash_masterpieces(conn)                     # populate + prune
        dismissed = mq.not_duplicate_pairs(conn)               # user "not the same" decisions
        groups = image_hash.duplicate_masterpiece_groups(conn, dismissed=dismissed)
        result = []
        for g in groups:
            items = []
            for name in g:
                try:
                    art = artwork_reader.load_artwork(name)
                except FileNotFoundError:
                    continue
                s = mq.summarize(conn, name)
                items.append({
                    "name": name,
                    "title": art.title or name,
                    "image": art.image,
                    "thumbnail": art.thumbnail or "",
                    "cover_thumb": s.get("cover_thumb", ""),
                    "cover_platform": s.get("cover_platform", ""),
                    "views": (s.get("totals") or {}).get("views", 0),
                    "sites": s.get("member_count", 0),
                })
            if len(items) >= 2:
                items.sort(key=lambda x: (x["views"], x["sites"]), reverse=True)
                result.append(items)
        return {"groups": result}
    finally:
        conn.close()


@masterpieces_router.get("/variant-suggestions")
def masterpiece_variant_suggestions():
    """Likely VARIANT families grouped by TITLE — the complement to /duplicates.

    /duplicates finds the same IMAGE cross-posted; this finds the same PIECE in
    different renders (``Foo`` + ``Foo (Rough)``, SFW + NSFW), which hash-matching
    can't — they're different images. Each family suggests a hero + per-member
    variant key/label derived from the title suffix, ready for /merge-as-variant.

    A title heuristic is fuzzy, so this only SUGGESTS; the UI reviews each family.
    """
    from database import variant_suggest
    conn = get_connection()
    try:
        arts = artwork_reader.list_artworks()
        # Views feed hero selection + ordering; summarize is the same source the
        # dup finder uses, so the two review lists rank consistently.
        items = []
        summaries = {}
        for a in arts:
            s = mq.summarize(conn, a["name"])
            summaries[a["name"]] = s
            items.append({"name": a["name"], "title": a.get("title") or a["name"],
                          "views": (s.get("totals") or {}).get("views", 0)})
        dismissed = variant_suggest.not_variant_pairs(conn)
        families = variant_suggest.suggest_families(items, dismissed=dismissed)

        by_name = {a["name"]: a for a in arts}
        out = []
        for fam in families:
            members = []
            for m in fam["members"]:
                art = by_name.get(m["name"], {})
                s = summaries.get(m["name"], {})
                members.append({
                    **m,
                    "image": art.get("image", ""),
                    "cover_thumb": s.get("cover_thumb", ""),
                    "cover_platform": s.get("cover_platform", ""),
                    "sites": s.get("member_count", 0),
                })
            out.append({"base": fam["base"], "members": members})
        return {"families": out}
    finally:
        conn.close()


@masterpieces_router.post("/not-variant")
def masterpiece_not_variant(body: dict):
    """Remember that a suggested family is NOT variants of one piece, so the
    by-title finder stops offering it. Separate from /not-duplicate on purpose."""
    from database import variant_suggest
    names = [n for n in (body.get("names") or []) if isinstance(n, str) and n.strip()]
    if len(names) < 2:
        raise HTTPException(400, detail="names must list 2+ Masterpieces")
    conn = get_connection()
    try:
        added = variant_suggest.add_not_variant(conn, names)
        return {"status": "dismissed", "pairs_added": added}
    finally:
        conn.close()


@masterpieces_router.get("/match")
def masterpiece_match(platform: str, submission_id: str):
    """Does this discovered upload look like an EXISTING Masterpiece?

    Prevents new duplicates forming at promote time (backlog M): before minting a
    fresh Masterpiece from a discovered piece we check its stored thumbnail hash
    against every Masterpiece hero hash. Returns the closest match within the
    near-duplicate threshold, or ``{"match": null}``.

    Deliberately a SUGGESTION, never automatic — near-identical hashes are not
    proof of sameness (an SFW and NSFW edit of one ref sheet hash the same), so
    the caller asks the user before linking instead of creating.
    """
    from database import image_hash
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT phash FROM image_hashes WHERE platform = ? AND submission_id = ?",
            (platform, str(submission_id))).fetchone()
        if not row:
            return {"match": None}          # not hashed yet → no opinion
        image_hash.hash_masterpieces(conn)  # make sure hero hashes are current
        best, best_d = None, 65
        for r in conn.execute(
                "SELECT submission_id, phash FROM image_hashes WHERE platform = '__mp__'"):
            d = image_hash.hamming(row["phash"], r["phash"])
            if d <= image_hash.HAMMING_THRESHOLD and d < best_d:
                best, best_d = r["submission_id"], d
        if not best:
            return {"match": None}
        try:
            art = artwork_reader.load_artwork(best)
            title = art.title or best
        except FileNotFoundError:
            title = best
        return {"match": {"name": best, "title": title,
                          "similarity": round(1.0 - best_d / 64.0, 3)}}
    finally:
        conn.close()


@masterpieces_router.post("/not-duplicate")
def not_duplicate_ep(body: dict):
    """Remember that these Masterpieces are NOT the same image, so the finder stops
    grouping them. Body: {names: [name, name, ...]} (2+)."""
    names = [str(n) for n in (body.get("names") or []) if n]
    if len(names) < 2:
        raise HTTPException(400, detail="names must list at least two Masterpieces")
    conn = get_connection()
    try:
        added = mq.add_not_duplicate(conn, names)
    finally:
        conn.close()
    return {"status": "remembered", "pairs_added": added}


@masterpieces_router.post("/merge")
def merge_masterpieces_ep(body: dict):
    """Merge two Masterpieces of the same image: fold ``drop``'s site-links into
    ``keep`` and delete ``drop`` (its image is identical). Body: {keep, drop}."""
    keep = (body.get("keep") or "").strip()
    drop = (body.get("drop") or "").strip()
    if not keep or not drop or keep == drop:
        raise HTTPException(400, detail="keep and drop (distinct) are required")
    conn = get_connection()
    try:
        artwork_reader.load_artwork(keep)          # 404 if either is missing
        art_drop = artwork_reader.load_artwork(drop)
        moved = mq.merge_masterpieces(conn, keep, drop)
        # Drop the now-redundant folder (identical image) + its cached hero hash.
        conn.execute("DELETE FROM image_hashes WHERE platform = '__mp__' AND submission_id = ?", (drop,))
        conn.commit()
    except FileNotFoundError:
        raise HTTPException(404, detail="Masterpiece not found")
    finally:
        conn.close()
    import shutil
    try:
        shutil.rmtree(art_drop.path)
    except OSError:
        logger.warning("merge: could not remove folder for %s", drop)
    return {"status": "merged", "keep": keep, "dropped": drop, "members_moved": moved}


# ── Variants (2.158.0, spec docs/specs/masterpiece_variants.md) ──────────────
# One piece of art, several renders (SFW/NSFW, censored/clean, dedication...).
# Definitions live in masterpiece.json "variants"; site-uploads carry
# masterpiece_members.variant_key so each variant's stats track separately while
# the cohort total stays the plain all-members rollup.

_VARIANT_KEY_RE = re.compile(r"^[a-z0-9_\-]{1,32}$")


def _raw_variants(name: str) -> list[dict]:
    try:
        raw = artwork_reader.read_raw_metadata(name) or {}
    except FileNotFoundError:
        return []
    out = []
    for v in raw.get("variants") or []:
        if isinstance(v, dict) and v.get("key") is not None and v.get("image"):
            out.append({"key": str(v["key"]), "label": v.get("label") or str(v["key"]),
                        "image": v["image"], "rating": v.get("rating") or ""})
    return out


def _write_variants(name: str, variants: list[dict]) -> None:
    artwork_reader.save_artwork_metadata(name, {"variants": variants})


@masterpieces_router.post("/merge-as-variant")
def merge_as_variant_ep(body: dict):
    """Fold ``absorb`` into ``keep`` as a labeled VARIANT of the same piece:
    absorb's image is copied into keep's folder, a variants entry is appended,
    and absorb's members move over re-keyed (their stats stay attributed).
    Body: {keep, absorb, key, label?, rating?}. The dup-finder's third option —
    for different RENDERS of one piece, where /merge (identical image) is wrong."""
    keep = (body.get("keep") or "").strip()
    absorb = (body.get("absorb") or "").strip()
    key = (body.get("key") or "").strip().lower()
    if not keep or not absorb or keep == absorb:
        raise HTTPException(400, detail="keep and absorb (distinct) are required")
    if not _VARIANT_KEY_RE.match(key):
        raise HTTPException(400, detail="key must be a short slug (a-z0-9_-)")
    try:
        art_keep = artwork_reader.load_artwork(keep)
        art_absorb = artwork_reader.load_artwork(absorb)
    except FileNotFoundError:
        raise HTTPException(404, detail="Masterpiece not found")
    variants = _raw_variants(keep)
    if any(v["key"] == key for v in variants):
        raise HTTPException(409, detail=f"variant key '{key}' already exists on {keep}")

    # Copy absorb's hero image in as the variant image.
    from pathlib import Path
    import shutil
    src = Path(art_absorb.path) / art_absorb.image
    if not src.is_file():
        raise HTTPException(422, detail=f"{absorb} has no hero image to absorb")
    i = 2
    while (Path(art_keep.path) / f"image_{i}{src.suffix.lower()}").exists():
        i += 1
    dst = Path(art_keep.path) / f"image_{i}{src.suffix.lower()}"
    shutil.copy2(src, dst)

    # Seed keep's own primary as an explicit variant on first use, so the set is
    # self-describing (primary '' + the new one).
    if not variants:
        variants = [{"key": "", "label": body.get("primary_label") or "Primary",
                     "image": art_keep.image, "rating": ""}]
    variants.append({"key": key, "label": (body.get("label") or key).strip(),
                     "image": dst.name, "rating": (body.get("rating") or "").strip().lower()})
    _write_variants(keep, variants)

    conn = get_connection()
    try:
        moved = mq.merge_as_variant(conn, keep, absorb, key)
        conn.execute("DELETE FROM image_hashes WHERE platform = '__mp__' AND submission_id = ?", (absorb,))
        conn.commit()
    finally:
        conn.close()
    try:
        shutil.rmtree(art_absorb.path)
    except OSError:
        logger.warning("merge-as-variant: could not remove folder for %s", absorb)
    return {"status": "merged-as-variant", "keep": keep, "absorbed": absorb,
            "key": key, "members_moved": moved, "variant_image": dst.name}


@masterpieces_router.post("/{name}/variants")
def declare_variant(name: str, body: dict):
    """Declare an EXISTING folder image as a labeled variant.
    Body: {key, image, label?, rating?}. Upgrades a 2.152 unlabeled alt in place."""
    key = (body.get("key") or "").strip().lower()
    image = (body.get("image") or "").strip()
    if not _VARIANT_KEY_RE.match(key):
        raise HTTPException(400, detail="key must be a short slug (a-z0-9_-)")
    try:
        art = artwork_reader.load_artwork(name)
    except FileNotFoundError:
        raise HTTPException(404, detail="Masterpiece not found")
    from pathlib import Path
    target = (Path(art.path) / image)
    if not image or not target.is_file() or \
            target.suffix.lower() not in artwork_reader.IMAGE_EXTENSIONS:
        raise HTTPException(422, detail="image must be an existing image file in this folder")
    variants = _raw_variants(name)
    if any(v["key"] == key for v in variants):
        raise HTTPException(409, detail=f"variant key '{key}' already exists")
    if not variants:
        variants = [{"key": "", "label": "Primary", "image": art.image, "rating": ""}]
    variants.append({"key": key, "label": (body.get("label") or key).strip(),
                     "image": image, "rating": (body.get("rating") or "").strip().lower()})
    _write_variants(name, variants)
    return {"status": "declared", "key": key}


@masterpieces_router.delete("/{name}/variants/{key}")
def delete_variant(name: str, key: str):
    """Demote a variant back to a plain alt image (file stays; members re-key
    to primary '')."""
    variants = _raw_variants(name)
    if not any(v["key"] == key for v in variants):
        raise HTTPException(404, detail="variant not found")
    _write_variants(name, [v for v in variants if v["key"] != key])
    conn = get_connection()
    try:
        mq.clear_variant_members(conn, name, key)
        conn.commit()
    finally:
        conn.close()
    return {"status": "removed", "key": key}


@masterpieces_router.patch("/{name}/members/variant")
def set_member_variant_ep(name: str, body: dict):
    """Attribute a linked site-upload to a variant.
    Body: {platform, submission_id, variant_key} (''=primary)."""
    platform = (body.get("platform") or "").strip()
    sid = str(body.get("submission_id") or "").strip()
    if not platform or not sid:
        raise HTTPException(400, detail="platform and submission_id are required")
    vkey = str(body.get("variant_key") or "")
    if vkey and not any(v["key"] == vkey for v in _raw_variants(name)):
        raise HTTPException(422, detail=f"no such variant '{vkey}' on {name}")
    conn = get_connection()
    try:
        mq.set_member_variant(conn, name, platform, sid, vkey)
        conn.commit()
    finally:
        conn.close()
    return {"status": "attributed", "variant_key": vkey}


# ── Replace the canonical image (2.153.0) ────────────────────────────────────
# "The artist sent the full-res / a fixed version" — swap the image a Masterpiece
# points at WITHOUT losing the record: masterpiece.json (title/desc/rating/tags)
# and every masterpiece_members site-link survive untouched, so pooled stats and
# links carry straight over. Previously the only route was delete + re-import,
# which threw all of that away.
#
# Deliberately NON-DESTRUCTIVE: the old file stays in the folder, so it drops into
# the 2.152 gallery strip as an alternate rather than being overwritten. This only
# ever moves the *hero* pointer (`image`) — it never touches the other images.

@masterpieces_router.post("/{name}/image")
async def replace_masterpiece_image(name: str, file: UploadFile = File(...)):
    """Replace the canonical (hero) image. Keeps metadata, members and the old file."""
    from pathlib import Path

    ext = Path(file.filename or "").suffix.lower()
    if ext not in artwork_reader.IMAGE_EXTENSIONS:
        raise HTTPException(415, detail=(
            f"Unsupported image type: {ext or '(none)'}. "
            f"Allowed: {', '.join(artwork_reader.IMAGE_EXTENSIONS)}"))
    data = await file.read()
    if not data:
        raise HTTPException(400, detail="Empty image upload")
    if len(data) > _MAX_IMAGE_BYTES:
        raise HTTPException(413, detail="Image exceeds the 50 MB archive cap")

    try:
        art = artwork_reader.load_artwork(name)
    except FileNotFoundError:
        raise HTTPException(404, detail="Masterpiece not found")

    folder = Path(art.path)
    # Never clobber an existing file (least of all the current hero) — the old
    # version must survive as a gallery alternate.
    stem = re.sub(r"[^\w.\-]", "_", Path(file.filename or "image").stem) or "image"
    target = folder / f"{stem}{ext}"
    n = 1
    while target.exists():
        target = folder / f"{stem}_v{n}{ext}"
        n += 1
    target.write_bytes(data)

    previous = art.image
    artwork_reader.save_artwork_metadata(name, {"image": target.name})

    # The hero changed, so the cached perceptual hash is stale — drop it and let
    # hash_masterpieces() recompute, or the de-dup finder would compare the OLD
    # pixels forever.
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM image_hashes WHERE platform = '__mp__' AND submission_id = ?",
            (name,))
        conn.commit()
    finally:
        conn.close()

    images = sorted(f.name for f in folder.iterdir()
                    if f.suffix.lower() in artwork_reader.IMAGE_EXTENSIONS)
    logger.info("Masterpiece %s: hero image %s -> %s", name, previous, target.name)
    return {"status": "replaced", "name": name, "image": target.name,
            "previous": previous, "images": images}


# ── Junk status (2.149.0) ─────────────────────────────────────────────────────
# 'junk' = kept-but-hidden: for pulled art that isn't wanted in the grid (memes,
# other people's ads, retired pieces) without deleting the record/folder.
# Reversible — restore sets status back to ''. Softer than /merge (which deletes).

_MP_STATUSES = {"", "junk"}


@masterpieces_router.post("/{name}/status")
def set_masterpiece_status(name: str, body: dict):
    """Set the Masterpiece's junk status. Body: {status: 'junk' | ''}.

    Accepts index-only names (Masterpieces with no folder — e.g. swept-in tweets)
    as well as real folders, since junking is exactly what those need.
    """
    status = str((body or {}).get("status", "")).strip().lower()
    if status not in _MP_STATUSES:
        raise HTTPException(400, detail="status must be 'junk' or '' (restore)")
    conn = get_connection()
    try:
        has_folder = True
        try:
            artwork_reader.load_artwork(name)
        except FileNotFoundError:
            has_folder = False
        if not has_folder and not conn.execute(
                "SELECT 1 FROM masterpieces WHERE name = ?", (name,)).fetchone():
            raise HTTPException(404, detail="Masterpiece not found")
        mq.set_status(conn, name, status)
        conn.commit()
        return {"status": "updated", "name": name, "junk": status == "junk"}
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
    # Every image file in the folder, hero first (2.152.0) — multi-image tweet
    # sets and preserved SFW/NSFW variants live beside the hero as image_N.*;
    # the detail view renders them as a gallery strip via /api/artwork/image.
    from pathlib import Path
    images = sorted(f.name for f in Path(art.path).iterdir()
                    if f.suffix.lower() in artwork_reader.IMAGE_EXTENSIONS)
    if art.image in images:
        images.remove(art.image)
        images.insert(0, art.image)
    conn = get_connection()
    try:
        mq.ensure_indexed(conn, name)
        conn.commit()
        roll = mq.rollup_members(conn, name)
        # Per-variant stats (2.158.0): each declared variant's members rolled up
        # alone; the cohort totals below stay the all-members rollup.
        variants = []
        for v in _raw_variants(name):
            vroll = mq.rollup_members(conn, name, v["key"])
            variants.append({**v, "totals": vroll["totals"],
                             "member_count": len(vroll["members"])})
        return {
            "name": art.name,
            "status": mq.get_status(conn, name),
            "images": images,
            "variants": variants,
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
