"""REST API endpoints for the posting module.

Provides endpoints for uploading stories to platforms, managing the posting
queue, viewing publication history, and browsing the story archive.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import tarfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, UploadFile, File

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
        from posting.manager import get_platform_requires
        queue_ids = []
        for platform in platforms:
            requires = get_platform_requires(platform)
            for ch_idx in chapters:
                qid = posting_queries.add_to_queue(
                    conn, story_name, ch_idx, platform, action,
                    scheduled_at=scheduled_at,
                    requires=requires,
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
        "posting_server_url", "posting_server_api_key",
    }
    filtered = {k: v for k, v in body.items() if k in allowed_keys}
    config.save_settings(filtered)
    return {"status": "saved"}


# ── Claim: Retroactive sync ───────────────────────────────────

@posting_router.post("/claim")
def claim_submissions(body: dict = {}):
    """Claim existing platform submissions into the publications registry.

    Scans platform submission tables, matches to archive stories, and creates
    publication records so /update can push revisions to them.

    Body (all optional): {
        "platforms": ["ib", "fa"],  // null = all with data
        "dry_run": false            // true = preview matches without writing
    }
    """
    from posting.sync import claim_existing_submissions

    platforms = body.get("platforms")
    dry_run = body.get("dry_run", False)

    try:
        results = claim_existing_submissions(platforms=platforms, dry_run=dry_run)
        claimed = [r for r in results if r["status"] == "claimed"]
        already = [r for r in results if r["status"] == "already_claimed"]
        unmatched = [r for r in results if r["status"] == "unmatched"]

        return {
            "status": "dry_run" if dry_run else "synced",
            "claimed": len(claimed),
            "already_claimed": len(already),
            "unmatched": len(unmatched),
            "results": results,
        }
    except Exception as e:
        logger.error("Claim failed: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


# ── Sync: Server receives archive uploads ─────────────────────

@posting_router.post("/sync/upload")
async def sync_upload(file: UploadFile = File(...)):
    """Receive a .tar.gz archive and extract to the story archive directory.

    Called by the desktop instance to push updated story files to the server.
    The archive is extracted in-place, overwriting existing files.
    """
    from posting.story_reader import get_archive_path

    archive_path = get_archive_path()
    if not archive_path.is_dir():
        try:
            archive_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise HTTPException(500, detail=f"Cannot create archive directory: {e}")

    try:
        contents = await file.read()
        buf = io.BytesIO(contents)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            # Security: reject paths that escape the archive directory
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in member.name:
                    raise HTTPException(400, detail=f"Unsafe path in archive: {member.name}")
            tar.extractall(path=str(archive_path))

        # Count what was extracted
        story_dirs = [d for d in archive_path.iterdir() if d.is_dir() and not d.name.startswith(".")]
        return {
            "status": "synced",
            "archive_path": str(archive_path),
            "stories": len(story_dirs),
            "bytes_received": len(contents),
        }
    except tarfile.TarError as e:
        raise HTTPException(400, detail=f"Invalid tar.gz archive: {e}")
    except Exception as e:
        logger.error("Sync upload failed: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


@posting_router.post("/sync/push")
async def sync_push(body: dict):
    """Push the local story archive to a remote PawPoller server.

    Called from the desktop instance. Tars the local archive and POSTs it
    to the remote server's /api/posting/sync/upload endpoint.

    Body: {
        "server_url": "http://34.xx.xx.xx:8420",  // optional, uses setting if omitted
        "api_key": "pp_xxxx",                      // optional, uses setting if omitted
        "story_name": "Extra_Credit"               // optional, sync one story only
    }
    """
    import httpx as _httpx
    from posting.story_reader import get_archive_path

    settings = config.get_settings()
    server_url = body.get("server_url") or settings.get("posting_server_url", "")
    api_key = body.get("api_key") or settings.get("posting_server_api_key", "")

    if not server_url:
        raise HTTPException(400, detail="No server URL configured. Set posting_server_url in settings.")

    archive_path = get_archive_path()
    if not archive_path.is_dir():
        raise HTTPException(404, detail=f"Local archive not found at {archive_path}")

    story_filter = body.get("story_name")

    try:
        # Create tarball in memory
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            if story_filter:
                story_path = archive_path / story_filter
                if not story_path.is_dir():
                    raise HTTPException(404, detail=f"Story not found: {story_filter}")
                tar.add(str(story_path), arcname=story_filter)
            else:
                for entry in sorted(archive_path.iterdir()):
                    if entry.is_dir() and not entry.name.startswith("."):
                        tar.add(str(entry), arcname=entry.name)
        buf.seek(0)
        tar_bytes = buf.getvalue()

        # POST to remote server
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with _httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{server_url.rstrip('/')}/api/posting/sync/upload",
                files={"file": ("story-archive.tar.gz", tar_bytes, "application/gzip")},
                headers=headers,
            )

        if resp.status_code != 200:
            raise HTTPException(502, detail=f"Remote server returned {resp.status_code}: {resp.text[:200]}")

        result = resp.json()
        result["bytes_sent"] = len(tar_bytes)
        result["synced_from"] = str(archive_path)
        if story_filter:
            result["story_filter"] = story_filter
        return result

    except _httpx.HTTPError as e:
        raise HTTPException(502, detail=f"Failed to reach remote server: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Sync push failed: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


# ── Change Detection ──────────────────────────────────────────

def _hash_file(path: str) -> str:
    """SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]  # Short hash for display


def _hash_story(story_path: Path) -> dict:
    """Hash all posting-relevant files in a story folder."""
    hashes = {}
    for pattern in ["Markdown/MASTER.md", "Tags/tags_upload.txt", "Chapters/split_manifest.json"]:
        f = story_path / pattern
        if f.is_file():
            hashes[pattern] = _hash_file(str(f))
    # Hash chapter format files
    for subdir in ["Chapters/BBCode", "Chapters/SoFurry_HTML", "BBCode", "PDF"]:
        d = story_path / subdir
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.is_file():
                    rel = f"{subdir}/{f.name}"
                    hashes[rel] = _hash_file(str(f))
    return hashes


@posting_router.get("/sync/status")
def get_sync_status():
    """Check which stories have changed since they were last posted.

    Compares current file hashes against the format_file hash stored
    in publications when the story was last posted/updated.
    """
    from posting.story_reader import get_archive_path

    archive_path = get_archive_path()
    if not archive_path.is_dir():
        return {"stories": [], "archive_path": str(archive_path), "error": "Archive not found"}

    conn = get_connection()
    try:
        pubs = posting_queries.get_publications(conn, status="posted")
    finally:
        conn.close()

    # Group publications by story
    pub_by_story: dict[str, list] = {}
    for p in pubs:
        pub_by_story.setdefault(p["story_name"], []).append(p)

    stories = []
    for entry in sorted(archive_path.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name == "Reference_Guides":
            continue

        story_name = entry.name
        current_hashes = _hash_story(entry)
        master_hash = current_hashes.get("Markdown/MASTER.md", "")

        story_pubs = pub_by_story.get(story_name, [])
        published_platforms = [p["platform"] for p in story_pubs]
        last_posted = max((p["first_posted_at"] or "" for p in story_pubs), default="")
        last_updated = max((p["last_updated_at"] or "" for p in story_pubs), default="")

        # Detect changes: compare current MASTER hash against what was last posted
        # We store the hash of the format file used, but MASTER.md is the source of truth
        changed = False
        if story_pubs:
            # Check if any posted format file has changed
            for p in story_pubs:
                fmt_file = p.get("format_file", "")
                if fmt_file:
                    # Get relative path within story folder
                    try:
                        full_path = entry / fmt_file if not os.path.isabs(fmt_file) else Path(fmt_file)
                        if full_path.is_file():
                            current = _hash_file(str(full_path))
                            # We don't have the old hash stored yet, so compare against pub timestamp
                            # If the file's mtime is newer than last_updated, it's changed
                            import datetime
                            mtime = datetime.datetime.fromtimestamp(full_path.stat().st_mtime)
                            if last_updated:
                                try:
                                    posted_dt = datetime.datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                                    if mtime.replace(tzinfo=None) > posted_dt.replace(tzinfo=None):
                                        changed = True
                                except (ValueError, TypeError):
                                    pass
                    except (OSError, ValueError):
                        pass

        stories.append({
            "name": story_name,
            "master_hash": master_hash,
            "file_count": len(current_hashes),
            "published_to": published_platforms,
            "last_posted": last_posted,
            "last_updated": last_updated,
            "changed": changed,
            "status": "changed" if changed else ("published" if story_pubs else "not published"),
        })

    return {"stories": stories, "archive_path": str(archive_path)}
