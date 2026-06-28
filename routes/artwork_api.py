"""Artwork hub API — PostyBirb-style image posting.

Mirrors routes/posting_api.py but for single-image artwork submissions. The
heavy lifting (posting, registry, polling) is reused: publishing calls
``manager.post_artwork`` (same posters/registry as stories, tagged
content_type='artwork'); analytics are free because pollers auto-discover the
posted art. This module only adds the artwork-specific surface: list/detail,
image upload (browser) + create-from-local-path (desktop), publish, settings,
artwork-scoped publications/log, image serving, and desktop⇄server media sync.
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import tarfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse

import config
from database.db import get_connection
from database import posting_queries
from posting import artwork_reader

logger = logging.getLogger(__name__)

artwork_router = APIRouter(prefix="/api/artwork")

# Generous archive cap — the per-platform posters enforce each site's real
# limit; this just stops a runaway upload filling the disk.
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

_IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _parse_metadata(raw: str) -> dict:
    """Parse the JSON metadata blob sent alongside an upload."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        raise HTTPException(400, detail="metadata must be a JSON object")


def _validate_image_name(filename: str) -> None:
    ext = Path(filename or "").suffix.lower()
    if ext not in artwork_reader.IMAGE_EXTENSIONS:
        raise HTTPException(
            415, detail=f"Unsupported image type: {ext or '(none)'}. "
            f"Allowed: {', '.join(artwork_reader.IMAGE_EXTENSIONS)}")


# ── Listing + detail ──────────────────────────────────────────

@artwork_router.get("/images")
def list_artworks():
    """List all artworks in the archive (card grid source)."""
    return {"artworks": artwork_reader.list_artworks()}


@artwork_router.get("/images/{name:path}")
def get_artwork_detail(name: str):
    """One artwork's metadata + its publications enriched with live stats."""
    try:
        artwork = artwork_reader.load_artwork(name)
    except FileNotFoundError:
        raise HTTPException(404, detail=f"Artwork not found: {name}")

    conn = get_connection()
    try:
        pubs = posting_queries.get_publications_with_stats(
            conn, story_name=name, content_type="artwork")
    finally:
        conn.close()

    return {
        "name": artwork.name,
        "title": artwork.title,
        "description": artwork.description,
        "author": artwork.author,
        "rating": artwork.rating,
        "image": artwork.image,
        "thumbnail": artwork.thumbnail or "",
        "tags": artwork.tags_by_platform,
        "titles": artwork.titles_by_platform,
        "descriptions": artwork.descriptions_by_platform,
        "categories": artwork.categories_by_platform,
        "platforms": artwork.platforms,
        "created_at": artwork.created_at,
        "publications": pubs,
    }


@artwork_router.delete("/images/{name:path}")
def delete_artwork(name: str):
    """Delete the local artwork folder. Leaves any upstream posts + their
    publication rows intact (the art still exists on each platform)."""
    try:
        artwork = artwork_reader.load_artwork(name)
    except FileNotFoundError:
        raise HTTPException(404, detail=f"Artwork not found: {name}")
    shutil.rmtree(artwork.path)
    return {"status": "deleted", "name": name}


# ── Creation: browser upload + desktop local-path ─────────────

@artwork_router.post("/upload")
async def upload_artwork(
    file: UploadFile = File(...),
    metadata: str = Form("{}"),
    thumbnail: UploadFile | None = File(None),
):
    """Create an artwork from a browser upload (works on desktop + server).

    The image bytes are written into a new archive folder along with an
    artwork.json built from the metadata blob. Returns the new artwork name.
    """
    _validate_image_name(file.filename or "")
    image_bytes = await file.read()
    if len(image_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, detail="Image exceeds the 50 MB archive cap")
    if not image_bytes:
        raise HTTPException(400, detail="Empty image upload")

    thumb_bytes = None
    thumb_name = None
    if thumbnail is not None and thumbnail.filename:
        _validate_image_name(thumbnail.filename)
        thumb_bytes = await thumbnail.read()
        if len(thumb_bytes) > _MAX_UPLOAD_BYTES:
            raise HTTPException(413, detail="Thumbnail exceeds the 50 MB archive cap")
        thumb_name = thumbnail.filename

    meta = _parse_metadata(metadata)
    name = artwork_reader.create_artwork(
        title=meta.get("title", ""),
        image_filename=file.filename or "image.png",
        image_bytes=image_bytes,
        description=meta.get("description", ""),
        author=meta.get("author", ""),
        rating=meta.get("rating", ""),
        tags=meta.get("tags"),
        titles=meta.get("titles"),
        descriptions=meta.get("descriptions"),
        categories=meta.get("categories"),
        platforms=meta.get("platforms"),
        thumbnail_filename=thumb_name,
        thumbnail_bytes=thumb_bytes,
    )
    return {"status": "created", "name": name}


@artwork_router.post("/create-from-path")
def create_artwork_from_path(body: dict):
    """Create an artwork from a local filesystem path (desktop native picker).

    The desktop app's native file dialog returns a real path; rather than
    round-tripping the bytes through the browser, copy the file straight into
    the archive. Server instances have no such path, so they use /upload.

    Body: { "path": "C:/.../art.png", "metadata": {...} }
    """
    # Desktop-only: this reads an arbitrary server-side path, which on a server
    # instance would be a local-file-read gadget. The server uses /upload.
    from posting.scheduler import detect_runtime_mode
    if detect_runtime_mode() != "desktop":
        raise HTTPException(403, detail="create-from-path is desktop-only; use /upload")
    path = (body.get("path") or "").strip()
    if not path:
        raise HTTPException(400, detail="path is required")
    src = Path(path)
    if not src.is_file():
        raise HTTPException(404, detail=f"File not found: {path}")
    _validate_image_name(src.name)
    try:
        image_bytes = src.read_bytes()
    except OSError as e:
        raise HTTPException(500, detail=f"Cannot read file: {e}")
    if len(image_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, detail="Image exceeds the 50 MB archive cap")

    meta = body.get("metadata") or {}
    if not isinstance(meta, dict):
        raise HTTPException(400, detail="metadata must be an object")

    thumb_path = (body.get("thumbnail_path") or "").strip()
    thumb_bytes = None
    thumb_name = None
    if thumb_path and Path(thumb_path).is_file():
        _validate_image_name(Path(thumb_path).name)
        thumb_bytes = Path(thumb_path).read_bytes()
        if len(thumb_bytes) > _MAX_UPLOAD_BYTES:
            raise HTTPException(413, detail="Thumbnail exceeds the 50 MB archive cap")
        thumb_name = Path(thumb_path).name

    name = artwork_reader.create_artwork(
        title=meta.get("title", "") or src.stem.replace("_", " "),
        image_filename=src.name,
        image_bytes=image_bytes,
        description=meta.get("description", ""),
        author=meta.get("author", ""),
        rating=meta.get("rating", ""),
        tags=meta.get("tags"),
        titles=meta.get("titles"),
        descriptions=meta.get("descriptions"),
        categories=meta.get("categories"),
        platforms=meta.get("platforms"),
        thumbnail_filename=thumb_name,
        thumbnail_bytes=thumb_bytes,
    )
    return {"status": "created", "name": name}


@artwork_router.patch("/images/{name:path}")
def update_artwork(name: str, body: dict):
    """Merge metadata updates into an existing artwork.json (edit flow)."""
    allowed = {"title", "description", "author", "rating", "tags",
               "titles", "descriptions", "categories", "platforms"}
    updates = {k: v for k, v in (body or {}).items() if k in allowed}
    try:
        artwork_reader.save_artwork_metadata(name, updates)
    except FileNotFoundError:
        raise HTTPException(404, detail=f"Artwork not found: {name}")
    return {"status": "saved", "name": name}


# ── Import (gallery → local artwork; Phase 3) ─────────────────

@artwork_router.post("/import/{platform}/{submission_id}")
def import_artwork_from_platform(platform: str, submission_id: str):
    """Import a discovered platform submission as a local artwork and link it.

    Reuses the metadata the pollers already stored (title/description/keywords/
    rating + image URL), downloads the image, creates the artwork, and writes a
    publication so it folds into the Submissions hub.
    """
    from posting import artwork_importer
    try:
        return artwork_importer.import_artwork(platform, submission_id)
    except Exception as e:
        logger.error("Artwork import failed for %s/%s: %s", platform, submission_id, e)
        raise HTTPException(400, detail=str(e))


@artwork_router.post("/import/bulk/{platform}")
def import_all_for_platform(platform: str):
    """Import every discovered (unlinked) submission for one platform.

    Per-item failures (e.g. a row with no direct image URL) are collected, not
    fatal — so one bad submission doesn't abort the batch.
    """
    from posting import artwork_importer
    from routes.submissions_api import get_discovered_unlinked

    conn = get_connection()
    try:
        items = get_discovered_unlinked(conn, platform_filter=platform)
    finally:
        conn.close()

    imported, skipped, failed = [], [], []
    for it in items:
        sid = it["submission_id"]
        try:
            res = artwork_importer.import_artwork(platform, sid)
            (imported if res.get("status") == "imported" else skipped).append(
                {"submission_id": sid, "name": res.get("name"), "status": res.get("status")})
        except Exception as e:
            failed.append({"submission_id": sid, "title": it.get("title"), "error": str(e)[:160]})

    return {
        "platform": platform,
        "imported": len(imported),
        "skipped": len(skipped),
        "failed": len(failed),
        "results": {"imported": imported, "skipped": skipped, "failed": failed},
    }


# ── Publish ───────────────────────────────────────────────────

@artwork_router.post("/publish")
async def publish_artwork(body: dict):
    """Publish an artwork to one or more platforms immediately.

    Body: {
        "artwork_name": "Autumn_Study",
        "platforms": ["ib", "fa", "bsky"],
        "account_ids": {"fa": 5}   // optional, {platform: account_id}
    }
    """
    from posting import manager

    artwork_name = body.get("artwork_name")
    platforms = body.get("platforms", [])
    account_ids = body.get("account_ids")

    if not artwork_name:
        raise HTTPException(400, detail="artwork_name is required")
    if not platforms:
        raise HTTPException(400, detail="platforms list is required")

    try:
        results = await manager.post_artwork(
            artwork_name, platforms, account_ids=account_ids)
        successes = sum(1 for r in results if r.get("success"))
        return {
            "status": "completed",
            "total": len(results),
            "successes": successes,
            "failures": len(results) - successes,
            "results": results,
        }
    except FileNotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.error("Artwork publish failed: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


# ── Publications + log (artwork-scoped) ───────────────────────

@artwork_router.get("/publications")
def get_artwork_publications():
    """All artwork publications, enriched with live stats from polling."""
    conn = get_connection()
    try:
        pubs = posting_queries.get_publications_with_stats(
            conn, content_type="artwork")
        return {"publications": pubs}
    finally:
        conn.close()


@artwork_router.get("/log")
def get_artwork_log(limit: int = Query(50)):
    """Artwork posting-log entries, newest first."""
    conn = get_connection()
    try:
        return {"log": posting_queries.get_posting_log(
            conn, limit=limit, content_type="artwork")}
    finally:
        conn.close()


# ── Image serving ─────────────────────────────────────────────

@artwork_router.get("/image")
def get_artwork_image(name: str = Query(...), file: str = Query(...)):
    """Serve an image from an artwork folder.

    Query params (not path segments) so names + nested files round-trip through
    ``encodeURIComponent``. Path-traversal guarded; only image extensions served.
    """
    if not name or not file:
        raise HTTPException(400, detail="name and file query params are required")
    try:
        artwork = artwork_reader.load_artwork(name)
    except FileNotFoundError:
        raise HTTPException(404, detail=f"Artwork not found: {name}")

    root = artwork.path.resolve()
    requested = (root / file).resolve()
    try:
        requested.relative_to(root)
    except ValueError:
        raise HTTPException(403, detail="Path escapes artwork directory")
    if not requested.is_file():
        raise HTTPException(404, detail="Image not found")
    if requested.suffix.lower() not in artwork_reader.IMAGE_EXTENSIONS:
        raise HTTPException(415, detail="Unsupported image type")

    return FileResponse(
        path=str(requested),
        media_type=_IMAGE_MEDIA_TYPES.get(requested.suffix.lower(), "application/octet-stream"),
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ── Settings ──────────────────────────────────────────────────

@artwork_router.get("/settings")
def get_artwork_settings():
    """Get artwork-related settings."""
    s = config.get_settings()
    return {
        "artwork_enabled": s.get("artwork_enabled", False),
        "artwork_archive_path": s.get("artwork_archive_path", ""),
        "artwork_default_platforms": s.get("artwork_default_platforms", []),
        "artwork_default_rating": s.get(
            "artwork_default_rating", s.get("posting_default_rating", "adult")),
        "artwork_fa_category": s.get("artwork_fa_category", ""),
        "artwork_fa_species": s.get("artwork_fa_species", ""),
        "artwork_fa_gender": s.get("artwork_fa_gender", ""),
        "artwork_ws_subtype": s.get("artwork_ws_subtype", ""),
        "artwork_sf_sub_type": s.get("artwork_sf_sub_type", ""),
    }


@artwork_router.post("/settings")
def save_artwork_settings(body: dict):
    """Save artwork-related settings."""
    allowed_keys = {
        "artwork_enabled", "artwork_archive_path", "artwork_default_platforms",
        "artwork_default_rating", "artwork_fa_category", "artwork_fa_species",
        "artwork_fa_gender", "artwork_ws_subtype", "artwork_sf_sub_type",
    }
    config.save_settings({k: v for k, v in body.items() if k in allowed_keys})
    return {"status": "saved"}


# ── Desktop ⇄ server media sync (tar.gz) ──────────────────────

@artwork_router.post("/sync/upload")
async def artwork_sync_upload(file: UploadFile = File(...)):
    """Receive a .tar.gz of the artwork archive and extract it in place.

    Called by the desktop instance to push artwork (image + artwork.json) to
    the server so the server's Artwork hub stays consistent and can publish the
    server-capable platforms.
    """
    archive_path = artwork_reader.get_artwork_archive_path()
    try:
        archive_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(500, detail=f"Cannot create archive directory: {e}")

    try:
        contents = await file.read()
        buf = io.BytesIO(contents)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in member.name:
                    raise HTTPException(400, detail=f"Unsafe path in archive: {member.name}")
                # Block symlink/hardlink members — a link whose name passes the
                # check above could still redirect a later write outside the dir.
                if member.issym() or member.islnk():
                    raise HTTPException(400, detail=f"Unsafe link member in archive: {member.name}")
            tar.extractall(path=str(archive_path))
        art_dirs = [d for d in archive_path.iterdir()
                    if d.is_dir() and not d.name.startswith(".")]
        return {
            "status": "synced",
            "archive_path": str(archive_path),
            "artworks": len(art_dirs),
            "bytes_received": len(contents),
        }
    except tarfile.TarError as e:
        raise HTTPException(400, detail=f"Invalid tar.gz archive: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Artwork sync upload failed: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


@artwork_router.post("/sync/push")
async def artwork_sync_push(body: dict):
    """Push the local artwork archive to a remote PawPoller server.

    Body: {
        "server_url": "http://34.xx.xx.xx:8420",  // optional, uses setting
        "api_key": "pp_xxxx",                      // optional, uses setting
        "artwork_name": "Autumn_Study"             // optional, one artwork only
    }
    """
    import httpx as _httpx

    settings = config.get_settings()
    server_url = body.get("server_url") or settings.get("posting_server_url", "")
    api_key = body.get("api_key") or settings.get("posting_server_api_key", "")
    if not server_url:
        raise HTTPException(400, detail="No server URL configured (posting_server_url).")

    archive_path = artwork_reader.get_artwork_archive_path()
    if not archive_path.is_dir():
        raise HTTPException(404, detail=f"Local artwork archive not found at {archive_path}")

    art_filter = body.get("artwork_name")
    try:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            if art_filter:
                art_path = archive_path / art_filter
                if not art_path.is_dir():
                    raise HTTPException(404, detail=f"Artwork not found: {art_filter}")
                tar.add(str(art_path), arcname=art_filter)
            else:
                for entry in sorted(archive_path.iterdir()):
                    if entry.is_dir() and not entry.name.startswith("."):
                        tar.add(str(entry), arcname=entry.name)
        buf.seek(0)
        tar_bytes = buf.getvalue()

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with _httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{server_url.rstrip('/')}/api/artwork/sync/upload",
                files={"file": ("artwork-archive.tar.gz", tar_bytes, "application/gzip")},
                headers=headers,
            )
        if resp.status_code != 200:
            raise HTTPException(502, detail=f"Remote server returned {resp.status_code}: {resp.text[:200]}")
        result = resp.json()
        result["bytes_sent"] = len(tar_bytes)
        result["synced_from"] = str(archive_path)
        if art_filter:
            result["artwork_filter"] = art_filter
        return result
    except _httpx.HTTPError as e:
        raise HTTPException(502, detail=f"Failed to reach remote server: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Artwork sync push failed: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
