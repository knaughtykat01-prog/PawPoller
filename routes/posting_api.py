"""REST API endpoints for the posting module.

Provides endpoints for uploading stories to platforms, managing the posting
queue, viewing publication history, and browsing the story archive.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

import config
from database.db import get_connection
from database import posting_queries

logger = logging.getLogger(__name__)

posting_router = APIRouter(prefix="/api/posting")


# ── Story Archive ─────────────────────────────────────────────

@posting_router.get("/stories")
def list_stories():
    """List all available stories in the archive."""
    from posting import story_reader
    try:
        stories = story_reader.list_stories()
        return {"stories": stories}
    except Exception as e:
        logger.error("Error listing stories: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


@posting_router.get("/stories/{story_name}")
def get_story_detail(story_name: str):
    """Get detailed info for a story (manifest, tags, available formats)."""
    from posting import story_reader
    try:
        story = story_reader.load_story(story_name)
        return {
            "name": story.name,
            "path": str(story.path),
            "total_chapters": story.total_chapters,
            "total_words": story.total_words,
            "author": story.author,
            "description": story.description,
            "chapters": [
                {
                    "index": ch.index,
                    "title": ch.title,
                    "word_count": ch.word_count,
                    "files": ch.files,
                }
                for ch in story.chapters
            ],
            "tags_by_platform": story.tags_by_platform,
        }
    except FileNotFoundError:
        raise HTTPException(404, detail=f"Story not found: {story_name}")
    except Exception as e:
        logger.error("Error loading story %s: %s", story_name, e, exc_info=True)
        raise HTTPException(500, detail=str(e))


# ── Post / Upload ─────────────────────────────────────────────

@posting_router.post("/post")
async def post_story(body: dict):
    """Post a story to one or more platforms immediately.

    Body: {
        "story_name": "Extra_Credit",
        "platforms": ["ib", "bsky"],
        "chapters": [1, 2, 3]   // optional, null = all
    }
    """
    from posting import manager

    story_name = body.get("story_name")
    platforms = body.get("platforms", [])
    chapters = body.get("chapters")

    if not story_name:
        raise HTTPException(400, detail="story_name is required")
    if not platforms:
        raise HTTPException(400, detail="platforms list is required")

    try:
        results = await manager.post_story(story_name, platforms, chapters)
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
        logger.error("Post failed: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


@posting_router.post("/update")
async def update_story(body: dict):
    """Push updates to already-posted submissions.

    Body: {
        "story_name": "Extra_Credit",
        "platforms": ["ib"],        // optional, null = all
        "chapters": [3]            // optional, null = all
    }
    """
    from posting import manager

    story_name = body.get("story_name")
    platforms = body.get("platforms")
    chapters = body.get("chapters")

    if not story_name:
        raise HTTPException(400, detail="story_name is required")

    try:
        results = await manager.update_story(story_name, platforms, chapters)
        successes = sum(1 for r in results if r.get("success"))
        return {
            "status": "completed",
            "total": len(results),
            "successes": successes,
            "failures": len(results) - successes,
            "results": results,
        }
    except Exception as e:
        logger.error("Update failed: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


# ── Publications ──────────────────────────────────────────────

@posting_router.get("/publications")
def get_publications(
    story_name: str = Query(None),
    platform: str = Query(None),
):
    """List all publications (what's been posted where)."""
    conn = get_connection()
    try:
        pubs = posting_queries.get_publications(conn, story_name=story_name, platform=platform)
        return {"publications": pubs}
    finally:
        conn.close()


@posting_router.get("/publications/{pub_id}")
def get_publication(pub_id: int):
    """Get a single publication by ID."""
    conn = get_connection()
    try:
        pub = posting_queries.get_publication(conn, pub_id)
        if not pub:
            raise HTTPException(404, detail="Publication not found")
        return pub
    finally:
        conn.close()


# ── Queue ─────────────────────────────────────────────────────

@posting_router.post("/queue")
def add_to_queue(body: dict):
    """Add items to the posting queue.

    Body: {
        "story_name": "Extra_Credit",
        "platforms": ["ib", "sf"],
        "chapters": [1, 2],        // optional
        "action": "post",          // "post" or "update"
        "scheduled_at": null       // ISO datetime or null for immediate
    }
    """
    story_name = body.get("story_name")
    platforms = body.get("platforms", [])
    chapters = body.get("chapters", [0])
    action = body.get("action", "post")
    scheduled_at = body.get("scheduled_at")

    if not story_name:
        raise HTTPException(400, detail="story_name is required")
    if not platforms:
        raise HTTPException(400, detail="platforms list is required")

    conn = get_connection()
    try:
        queue_ids = []
        for platform in platforms:
            for ch_idx in chapters:
                qid = posting_queries.add_to_queue(
                    conn, story_name, ch_idx, platform, action,
                    scheduled_at=scheduled_at,
                )
                queue_ids.append(qid)
        return {"status": "queued", "queue_ids": queue_ids}
    except Exception as e:
        logger.error("Queue add failed: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@posting_router.get("/queue")
def get_queue(include_completed: bool = Query(False)):
    """List posting queue items."""
    conn = get_connection()
    try:
        items = posting_queries.get_queue(conn, include_completed=include_completed)
        return {"queue": items}
    finally:
        conn.close()


@posting_router.delete("/queue/{queue_id}")
def cancel_queue_item(queue_id: int):
    """Cancel a pending queue item."""
    conn = get_connection()
    try:
        if posting_queries.cancel_queue_item(conn, queue_id):
            return {"status": "cancelled", "queue_id": queue_id}
        raise HTTPException(404, detail="Queue item not found or not pending")
    finally:
        conn.close()


# ── Log ───────────────────────────────────────────────────────

@posting_router.get("/log")
def get_log(
    story_name: str = Query(None),
    limit: int = Query(50),
):
    """Get posting audit log."""
    conn = get_connection()
    try:
        entries = posting_queries.get_posting_log(conn, story_name=story_name, limit=limit)
        return {"log": entries}
    finally:
        conn.close()


# ── Settings ──────────────────────────────────────────────────

@posting_router.get("/settings")
def get_posting_settings():
    """Get posting-related settings."""
    settings = config.get_settings()
    return {
        "posting_enabled": settings.get("posting_enabled", False),
        "posting_story_archive_path": settings.get("posting_story_archive_path", ""),
        "posting_default_platforms": settings.get("posting_default_platforms", []),
        "posting_default_rating": settings.get("posting_default_rating", "adult"),
    }


@posting_router.post("/settings")
def save_posting_settings(body: dict):
    """Save posting-related settings."""
    allowed_keys = {
        "posting_enabled", "posting_story_archive_path",
        "posting_default_platforms", "posting_default_rating",
    }
    filtered = {k: v for k, v in body.items() if k in allowed_keys}
    config.save_settings(filtered)
    return {"status": "saved"}
