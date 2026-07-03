"""Posts module (microblog publishing) REST API — 2.49.0.

Compose short-form posts and publish them to microblog platforms (Bluesky +
Mastodon in Phase 2). Mirrors the shape of the Artwork hub API: a library list,
create (multipart so an optional image can ride along), publish, delete, and a
query-param image server.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse

import config
from database.db import get_connection
from database import posts_queries
from posting import post_publisher

logger = logging.getLogger(__name__)
posts_router = APIRouter(prefix="/api/posts")

_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_ALLOWED_RATINGS = {"general", "mature", "adult"}
_MAX_IMAGE_BYTES = 25 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _media_dir() -> Path:
    d = config.DATA_DIR / "posts_media"
    d.mkdir(parents=True, exist_ok=True)
    return d


@posts_router.get("")
def list_posts(limit: int = Query(100, ge=1, le=500)):
    """The Posts feed — every composed post, newest-first, with publications."""
    conn = get_connection()
    try:
        return {"posts": posts_queries.list_posts(conn, limit=limit)}
    finally:
        conn.close()


@posts_router.get("/image")
def get_post_image(post_id: int = Query(...)):
    """Serve a post's attached image (traversal-safe: path is derived from the id)."""
    conn = get_connection()
    try:
        post = posts_queries.get_post(conn, post_id)
    finally:
        conn.close()
    if not post or not post.get("image_path"):
        raise HTTPException(404, "No image for this post")
    p = Path(post["image_path"]).resolve()
    if _media_dir().resolve() not in p.parents or not p.is_file():
        raise HTTPException(404, "Image not found")
    return FileResponse(str(p))


@posts_router.get("/{post_id}")
def get_post(post_id: int):
    conn = get_connection()
    try:
        post = posts_queries.get_post(conn, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        post["publications"] = posts_queries.get_post_publications(conn, post_id)
        return post
    finally:
        conn.close()


@posts_router.post("")
async def create_post(
    body: str = Form(""),
    rating: str = Form("general"),
    image_alt: str = Form(""),
    file: UploadFile | None = File(None),
):
    """Create a draft post (optionally with a single image)."""
    body = (body or "").strip()
    rating = rating if rating in _ALLOWED_RATINGS else "general"
    if not body and not file:
        raise HTTPException(400, "A post needs text or an image")

    conn = get_connection()
    try:
        post_id = posts_queries.create_post(
            conn, body=body, rating=rating, image_alt=image_alt, now=_now())
    finally:
        conn.close()

    if file is not None:
        ext = Path(file.filename or "").suffix.lower()
        if ext not in _ALLOWED_EXT:
            _cleanup(post_id)
            raise HTTPException(400, "Image must be PNG, JPG, GIF or WebP")
        data = await file.read()
        if len(data) > _MAX_IMAGE_BYTES:
            _cleanup(post_id)
            raise HTTPException(400, "Image is too large (max 25 MB)")
        dest = _media_dir() / f"{post_id}{ext}"
        dest.write_bytes(data)
        conn = get_connection()
        try:
            posts_queries.update_post(conn, post_id, image_path=str(dest), now=_now())
        finally:
            conn.close()

    return {"post_id": post_id}


@posts_router.post("/{post_id}/publish")
async def publish_post(post_id: int, payload: dict):
    """Publish a composed post to the chosen platforms."""
    platforms = payload.get("platforms") or []
    account_ids = payload.get("account_ids") or {}
    if not platforms:
        raise HTTPException(400, "Pick at least one platform")
    try:
        results = await post_publisher.publish_post(post_id, platforms, account_ids)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error("publish_post failed: %s", e, exc_info=True)
        raise HTTPException(500, str(e))
    successes = sum(1 for r in results if r.get("success"))
    return {"results": results, "successes": successes, "failures": len(results) - successes}


@posts_router.delete("/{post_id}")
def delete_post(post_id: int):
    conn = get_connection()
    try:
        post = posts_queries.get_post(conn, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        posts_queries.delete_post(conn, post_id)
    finally:
        conn.close()
    # Best-effort media cleanup.
    img = post.get("image_path")
    if img:
        try:
            p = Path(img).resolve()
            if _media_dir().resolve() in p.parents and p.is_file():
                p.unlink()
        except OSError:
            pass
    return {"status": "deleted"}


def _cleanup(post_id: int) -> None:
    """Delete a just-created post row after an image-validation failure."""
    conn = get_connection()
    try:
        posts_queries.delete_post(conn, post_id)
    finally:
        conn.close()
