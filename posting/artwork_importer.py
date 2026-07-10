"""Artwork importer — create a local artwork from a platform submission the
pollers already discovered (Phase 3 of docs/specs/submissions-hub.md).

Unlike the story importer (`posting/importer.py`, which calls each platform's API
live), this reuses the metadata the pollers already stored in the per-platform
submission tables (title / description / keywords / rating + an image URL), so a
single generic path works across platforms. It downloads the image from the
stored URL (full-res where the platform records one — FA `download_url`, Weasyl
`media_url`; thumbnail fallback otherwise), creates the artwork, and links it
(writes a publication) so it folds into the Submissions hub and leaves the
discovered bucket.

Note: FA's full-res CDN may refuse datacenter IPs — run FA imports from the
desktop (residential IP), same as AO3 imports.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx

import config
from database.db import get_connection
from database import posting_queries
from posting import artwork_reader
from posting.sync import PLATFORM_TABLES

logger = logging.getLogger(__name__)

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")

# Per-platform rating text → the artwork archive's general/mature/adult scale.
_RATING_MAP = {
    "general": "general", "clean": "general", "tame": "general", "safe": "general",
    "mature": "mature", "questionable": "mature",
    "adult": "adult", "explicit": "adult", "extreme": "adult",
}


def norm_rating(val) -> str:
    return _RATING_MAP.get(str(val or "").strip().lower(), "")


def image_url(row: dict) -> str:
    """Best available image URL: full-res where stored, else the thumbnail.

    Deliberately does NOT fall back to a generic ``url`` column — on some
    platforms (Inkbunny) that holds the submission *page* URL, not an image, so
    using it would download HTML. ``thumb_url`` (Inkbunny's thumbnail) is safe.
    """
    return (row.get("download_url") or row.get("media_url") or row.get("file_url")
            or row.get("thumbnail_url") or row.get("thumb_url") or "")


# Magic-byte signatures so we can reject non-images even when a server lies about
# (or omits) the Content-Type header.
_MAGIC = [(b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"), (b"GIF87a", ".gif"),
          (b"GIF89a", ".gif")]
_CT_EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
           "image/gif": ".gif", "image/webp": ".webp"}


def magic_ext(data: bytes) -> str:
    for sig, ext in _MAGIC:
        if data[:len(sig)] == sig:
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ""


def is_image(content_type: str, data: bytes) -> bool:
    """True if the payload looks like an image (by header OR magic bytes)."""
    return (content_type or "").lower().startswith("image/") or bool(magic_ext(data))


def pick_ext(url: str, content_type: str, data: bytes) -> str:
    """Choose a file extension from the URL, then magic bytes, then Content-Type."""
    path = urlparse(url).path.lower()
    for e in IMAGE_EXTS:
        if path.endswith(e):
            return e
    return magic_ext(data) or _CT_EXT.get((content_type or "").lower(), ".png")


def parse_tags(raw) -> list[str]:
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


def find_existing(platform: str, submission_id: str) -> str | None:
    """Name of an artwork already imported from this submission, if any."""
    for a in artwork_reader.list_artworks():
        try:
            data = json.loads((Path(a["path"]) / "artwork.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        src = data.get("import_source") or {}
        if src.get("platform") == platform and str(src.get("submission_id", "")) == str(submission_id):
            return a["name"]
    return None


async def _resolve_ib_full_url(submission_id: str) -> str:
    """Fetch Inkbunny's full-resolution file URL via the API.

    The poller only stores a thumbnail for IB; the original file lives in the
    API's ``files[].file_url_full``. Reuses the cached session SID the poller
    persists (so no re-login), mirroring the story importer's IB path.
    """
    from clients.ib.client import InkbunnyClient
    from database import queries, accounts as _accts

    settings = config.get_settings()
    conn = get_connection()
    try:
        acct = _accts.get_default_account_id(conn, "ib", create=True)
        cached = queries.get_cached_session(conn, acct)
    finally:
        conn.close()
    cached_sid = cached["sid"] if cached else None

    client = InkbunnyClient(username=settings.get("username", ""),
                            password=settings.get("password", ""))
    if cached and cached.get("user_id"):
        client.user_id = cached["user_id"]
    try:
        await client.ensure_session(cached_sid)
        resp = await client._http.post(
            f"{config.INKBUNNY_API_BASE}/api_submissions.php",
            data={"sid": client.sid, "submission_ids": str(submission_id)},
        )
        resp.raise_for_status()
        subs = resp.json().get("submissions", [])
        if subs:
            files = subs[0].get("files", [])
            if files:
                return files[0].get("file_url_full", "") or files[0].get("file_url_screen", "")
    finally:
        await client.close()
    return ""


def import_artwork(platform: str, submission_id: str) -> dict:
    """Import one discovered submission as a local artwork + link it.

    Returns {status: imported|already_imported, name, ...}.
    """
    cfg = PLATFORM_TABLES.get(platform)
    if not cfg:
        raise ValueError(f"Unknown platform: {platform}")

    existing = find_existing(platform, submission_id)
    if existing:
        return {"status": "already_imported", "name": existing}

    conn = get_connection()
    try:
        row = conn.execute(
            f"SELECT * FROM {cfg['table']} WHERE {cfg['id_col']} = ?",
            (submission_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise ValueError(f"Submission {submission_id} not found for {platform}")

    d = dict(row)
    url = image_url(d)
    # Upgrade to full resolution where a per-platform re-fetch is available.
    # FA/Weasyl already store a full-res URL; Inkbunny stores only a thumbnail,
    # so re-fetch the original file from its API.
    if platform == "ib":
        try:
            full = asyncio.run(_resolve_ib_full_url(submission_id))
            if full:
                url = full
        except Exception as e:
            logger.warning("IB full-res resolve failed for %s (%s); using stored image",
                           submission_id, e)
    if not url:
        raise ValueError("No image URL stored for this submission")

    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        image_bytes = resp.content
        content_type = resp.headers.get("content-type", "").split(";")[0].strip()

    # Guard: only create an artwork from an actual image. Some platforms store a
    # page URL instead of a file (Inkbunny), which would otherwise download HTML.
    if not is_image(content_type, image_bytes):
        raise ValueError(
            f"Stored URL did not return an image (content-type: {content_type or 'unknown'}). "
            f"{platform.upper()} may not expose a direct image URL — full import for it is pending."
        )

    title = d.get(cfg["title_col"]) or f"{platform}_{submission_id}"
    tags = parse_tags(d.get("keywords"))
    rating = norm_rating(d.get("rating") or d.get("rating_name"))
    # Prefer the poller-stored permalink; url_template is a fallback (and can't
    # be right for instance-scoped mast/tum URLs built from the id alone).
    external_url = d.get("link") or cfg["url_template"].format(id=submission_id)

    name = artwork_reader.create_artwork(
        title=title,
        image_filename=f"image{pick_ext(url, content_type, image_bytes)}",
        image_bytes=image_bytes,
        description=d.get("description", "") or "",
        rating=rating,
        tags={"default": tags} if tags else {},
        platforms=[platform],
        source={"platform": platform, "submission_id": str(submission_id), "url": external_url},
    )

    # Link it (write a publication) so it folds into the hub + leaves the
    # discovered bucket — same external_id matching as a normal publication.
    conn = get_connection()
    try:
        posting_queries.upsert_publication(
            conn,
            story_name=name,
            chapter_index=0,
            platform=platform,
            content_type="artwork",
            external_id=str(submission_id),
            external_url=external_url,
            title_used=title,
            status="posted",
        )
    finally:
        conn.close()

    logger.info("Imported artwork %s from %s/%s", name, platform, submission_id)
    return {"status": "imported", "name": name, "platform": platform}
