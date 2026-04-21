"""Story importer — downloads content from platforms and creates local archive folders.

Supports importing existing published submissions from Inkbunny and SoFurry into
the local story archive. The importer:
  1. Fetches full submission metadata from the platform client
  2. Downloads the story content (BBCode from IB, HTML from SF)
  3. Creates the standard folder structure with story.json + MASTER.md
  4. Optionally downloads the cover/thumbnail image

This is a first-version importer — stories are imported as single-chapter works
with whatever format the platform provides, plus a basic MASTER.md created by
stripping formatting from the source content.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import httpx

import config
from posting.story_reader import get_archive_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Folder name sanitisation
# ---------------------------------------------------------------------------

def _sanitize_folder_name(title: str) -> str:
    """Convert a submission title to a safe folder name.

    Strips non-alphanumeric characters (except underscores), collapses
    whitespace to single underscores, and truncates to 80 characters.
    """
    # Replace common separators with underscores
    name = re.sub(r'[\s\-–—]+', '_', title.strip())
    # Keep only letters, digits, underscores
    name = re.sub(r'[^A-Za-z0-9_]', '', name)
    # Collapse multiple underscores
    name = re.sub(r'_+', '_', name).strip('_')
    # Truncate
    if len(name) > 80:
        name = name[:80].rstrip('_')
    return name or 'Imported_Story'


# ---------------------------------------------------------------------------
# Content stripping — produce basic markdown from BBCode / HTML
# ---------------------------------------------------------------------------

def _bbcode_to_markdown(bbcode: str) -> str:
    """Convert BBCode to basic markdown for MASTER.md.

    Handles the most common BBCode tags used in Inkbunny stories. This is
    intentionally simple — the goal is a readable MASTER.md, not a perfect
    round-trip conversion.
    """
    text = bbcode

    # Bold: [b]...[/b] → **...**
    text = re.sub(r'\[b\](.*?)\[/b\]', r'**\1**', text, flags=re.IGNORECASE | re.DOTALL)
    # Italic: [i]...[/i] → *...*
    text = re.sub(r'\[i\](.*?)\[/i\]', r'*\1*', text, flags=re.IGNORECASE | re.DOTALL)
    # Underline: [u]...[/u] → just the text (no markdown equivalent)
    text = re.sub(r'\[u\](.*?)\[/u\]', r'\1', text, flags=re.IGNORECASE | re.DOTALL)
    # Strikethrough: [s]...[/s] → ~~...~~
    text = re.sub(r'\[s\](.*?)\[/s\]', r'~~\1~~', text, flags=re.IGNORECASE | re.DOTALL)
    # URLs: [url=X]text[/url] → [text](X)
    text = re.sub(r'\[url=(.*?)\](.*?)\[/url\]', r'[\2](\1)', text, flags=re.IGNORECASE | re.DOTALL)
    # Plain URLs: [url]X[/url] → X
    text = re.sub(r'\[url\](.*?)\[/url\]', r'\1', text, flags=re.IGNORECASE | re.DOTALL)
    # Horizontal rule: [hr] → ---
    text = re.sub(r'\[hr\]', '\n---\n', text, flags=re.IGNORECASE)
    # Center/left/right alignment — just strip the tags
    text = re.sub(r'\[/?(?:center|left|right)\]', '', text, flags=re.IGNORECASE)
    # Color/size/font tags — strip
    text = re.sub(r'\[(?:color|size|font)=[^\]]*\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[/(?:color|size|font)\]', '', text, flags=re.IGNORECASE)
    # Quote: [quote]...[/quote] → > blockquote
    def _quote_block(m):
        lines = m.group(1).strip().split('\n')
        return '\n'.join(f'> {line}' for line in lines)
    text = re.sub(r'\[quote(?:=[^\]]*)?\](.*?)\[/quote\]', _quote_block, text, flags=re.IGNORECASE | re.DOTALL)
    # Strip remaining BBCode tags
    text = re.sub(r'\[/?[a-z]+(?:=[^\]]*?)?\]', '', text, flags=re.IGNORECASE)

    # Normalise line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    return text.strip()


def _html_to_markdown(html_content: str) -> str:
    """Convert HTML to basic markdown for MASTER.md.

    Handles common HTML elements found in SoFurry story content. Like the
    BBCode converter, this is intentionally simple.
    """
    text = html_content

    # Remove script/style blocks
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.IGNORECASE | re.DOTALL)

    # Headings: <h1>-<h6> → # markers
    for i in range(1, 7):
        text = re.sub(rf'<h{i}[^>]*>(.*?)</h{i}>', rf'\n{"#" * i} \1\n', text, flags=re.IGNORECASE | re.DOTALL)

    # Bold: <b>, <strong> → **...**
    text = re.sub(r'<(?:b|strong)[^>]*>(.*?)</(?:b|strong)>', r'**\1**', text, flags=re.IGNORECASE | re.DOTALL)
    # Italic: <i>, <em> → *...*
    text = re.sub(r'<(?:i|em)[^>]*>(.*?)</(?:i|em)>', r'*\1*', text, flags=re.IGNORECASE | re.DOTALL)

    # Line breaks: <br> → newline
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    # Paragraphs: <p>...</p> → double newline
    text = re.sub(r'<p[^>]*>(.*?)</p>', r'\n\n\1\n\n', text, flags=re.IGNORECASE | re.DOTALL)
    # Horizontal rules: <hr> → ---
    text = re.sub(r'<hr[^>]*/?>', '\n---\n', text, flags=re.IGNORECASE)

    # Links: <a href="X">text</a> → [text](X)
    text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r'[\2](\1)', text, flags=re.IGNORECASE | re.DOTALL)

    # Strip all remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Decode HTML entities
    import html
    text = html.unescape(text)

    # Normalise whitespace
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Collapse excessive blank lines (3+ → 2)
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


# ---------------------------------------------------------------------------
# IB rating map
# ---------------------------------------------------------------------------

_IB_RATING_MAP = {
    "0": "general",
    "1": "mature",
    "2": "explicit",
}


# ---------------------------------------------------------------------------
# Story folder creation
# ---------------------------------------------------------------------------

def _create_story_folder(
    name: str,
    title: str,
    author: str,
    description: str,
    tags: list[str],
    rating: str,
    content: str,
    content_format: str,
    cover_url: str = "",
    platform: str = "",
    submission_id: str = "",
    source_url: str = "",
) -> str:
    """Create the full story folder structure and return the story name.

    Args:
        name: Sanitised folder name.
        title: Display title.
        author: Author name.
        description: Story description/summary.
        tags: List of tag strings.
        rating: Rating string (general, mature, explicit).
        content: The story content text.
        content_format: Format of content — "bbcode", "html", or "markdown".
        cover_url: URL to a cover image (optional, downloaded if provided).
        platform: Source platform code (e.g. "ib", "sf").
        submission_id: Original submission ID on the platform.
        source_url: Direct URL to the submission.

    Returns:
        The story folder name (same as `name`).
    """
    archive = get_archive_path()
    story_dir = archive / name

    if story_dir.exists():
        # Append a suffix to avoid collisions
        i = 2
        while (archive / f"{name}_{i}").exists():
            i += 1
        name = f"{name}_{i}"
        story_dir = archive / name

    # Create directory structure
    dirs = [
        story_dir / "Markdown",
        story_dir / "BBCode",
        story_dir / "HTML",
        story_dir / "Images",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # Save original format content
    if content_format == "bbcode":
        (story_dir / "BBCode" / f"{name}_bbcode.txt").write_text(content, encoding="utf-8")
    elif content_format == "html":
        (story_dir / "HTML" / f"{name}_SoFurry.html").write_text(content, encoding="utf-8")

    # Create MASTER.md from content
    if content_format == "bbcode":
        body = _bbcode_to_markdown(content)
    elif content_format == "html":
        body = _html_to_markdown(content)
    else:
        body = content

    # Count words in the converted body
    word_count = len(body.split())

    master_content = f"""<!-- @title -->
# {title}

<!-- @subtitle -->
*Imported from {platform.upper()}*

<!-- @byline -->
by {author or 'Unknown'}

<!-- @body -->

{body}

<!-- @story-end -->
"""
    (story_dir / "Markdown" / "MASTER.md").write_text(master_content, encoding="utf-8")

    # Generate story.json
    story_json = {
        "title": title,
        "author": author,
        "description": description,
        "summary": "",
        "rating": rating,
        "category": "",
        "fandom": "Original Work",
        "genre": "",
        "warnings": [],
        "characters": [],
        "relationships": [],
        "word_count": word_count,
        "chapters": 1,
        "tags": {"default": tags},
        "chapter_info": [],
        "formats": {"bbcode": True, "html": True, "markdown": True},
        "images": {"cover": ""},
        "import_source": {
            "platform": platform,
            "submission_id": submission_id,
            "url": source_url,
        },
    }
    (story_dir / "story.json").write_text(
        json.dumps(story_json, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    logger.info("Created imported story folder: %s (%d words from %s)", name, word_count, platform)
    return name


# ---------------------------------------------------------------------------
# Platform importers
# ---------------------------------------------------------------------------

async def import_from_inkbunny(submission_id: str) -> dict:
    """Download an IB submission and create a local story folder.

    Uses the Inkbunny API to fetch submission details with show_writing=yes
    to get the file URL, then downloads the BBCode content and creates the
    local folder structure.

    Returns:
        Dict with 'story_name' and 'title'.
    """
    from api_client.client import InkbunnyClient
    from database.db import get_connection
    from database import queries

    settings = config.get_settings()
    username = settings.get("username", "")
    password = settings.get("password", "")
    if not username or not password:
        raise RuntimeError("Inkbunny credentials not configured — set up in Settings")

    # Look up the submission in the local DB first for basic metadata
    conn = get_connection()
    try:
        db_sub = queries.get_submission(conn, int(submission_id))
    finally:
        conn.close()

    client = InkbunnyClient(username=username, password=password)
    try:
        # Login and fetch the full submission with file URLs
        await client.login()

        # Use the raw API with show_writing=yes to get the file URL
        resp = await client._http.post(
            f"{config.INKBUNNY_API_BASE}/api_submissions.php",
            data={
                "sid": client.sid,
                "submission_ids": str(submission_id),
                "show_description": "yes",
                "show_writing": "yes",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if "error_code" in data:
            raise RuntimeError(f"IB API error: {data.get('error_message', data)}")

        submissions = data.get("submissions", [])
        if not submissions:
            raise RuntimeError(f"Submission {submission_id} not found on Inkbunny")

        sub = submissions[0]
        title = sub.get("title", f"IB_{submission_id}")
        author = sub.get("username", "")
        description = sub.get("description", "")
        keywords = [k.get("keyword_name", "") for k in sub.get("keywords", []) if k.get("keyword_name")]
        rating = _IB_RATING_MAP.get(str(sub.get("rating_id", "0")), "general")
        url = f"https://inkbunny.net/s/{submission_id}"

        # Get the file URL — Inkbunny stores files in a "files" array
        # When show_writing=yes, writing submissions include file_url_full
        files = sub.get("files", [])
        content = ""
        cover_url = ""

        if files:
            file_info = files[0]
            file_url = file_info.get("file_url_full", "") or file_info.get("file_url_screen", "")
            # The thumbnail/preview for cover
            cover_url = (
                sub.get("thumbnail_url_huge", "")
                or sub.get("thumbnail_url_large", "")
                or sub.get("thumbnail_url_medium", "")
                or sub.get("thumbnail_url_medium_noncustom", "")
            )

            if file_url:
                async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as dl:
                    file_resp = await dl.get(file_url)
                    file_resp.raise_for_status()
                    content = file_resp.text
            else:
                # Fallback: use writing_text if available from the API
                content = file_info.get("writing_text", "")

        if not content:
            # Last resort: use description as content
            content = description or "(No content available)"
            logger.warning("IB import %s: no file content found, using description", submission_id)

    finally:
        await client.close()

    folder_name = _sanitize_folder_name(title)
    story_name = _create_story_folder(
        name=folder_name,
        title=title,
        author=author,
        description=description,
        tags=keywords,
        rating=rating,
        content=content,
        content_format="bbcode",
        cover_url=cover_url,
        platform="ib",
        submission_id=str(submission_id),
        source_url=url,
    )

    return {"story_name": story_name, "title": title}


async def import_from_sofurry(submission_id: str) -> dict:
    """Download an SF submission and create a local story folder.

    Fetches the submission metadata from the SF JSON API, then scrapes
    the submission page for the story content HTML.

    Returns:
        Dict with 'story_name' and 'title'.
    """
    from sf_client.client import SoFurryClient, SOFURRY_BASE

    settings = config.get_settings()
    sf_username = settings.get("sf_username", "")
    sf_password = settings.get("sf_password", "")
    sf_display = settings.get("sf_display_name", "")

    proxy_url = settings.get("cf_worker_url", "")
    proxy_key = settings.get("cf_worker_key", "")

    if not sf_username or not sf_password:
        raise RuntimeError("SoFurry credentials not configured — set up in Settings")

    client = SoFurryClient(
        username=sf_username,
        password=sf_password,
        display_name=sf_display,
        proxy_url=proxy_url,
        proxy_key=proxy_key,
    )

    try:
        logged_in = await client.ensure_logged_in()
        if not logged_in:
            raise RuntimeError("Could not log in to SoFurry")

        # Fetch metadata from JSON API
        resp = await client._http.get(
            f"{SOFURRY_BASE}/ui/submission/{submission_id}",
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"SF API returned {resp.status_code} for submission {submission_id}")

        data = resp.json()
        title = data.get("title", f"SF_{submission_id}")
        author = data.get("author", sf_display or "")
        description = data.get("description", "")
        tags = data.get("artistTags", []) or []
        sf_rating = data.get("rating", 0)
        if sf_rating >= 20:
            rating = "explicit"
        elif sf_rating >= 10:
            rating = "mature"
        else:
            rating = "general"

        cover_url = data.get("coverUrl", "") or data.get("thumbUrl", "")
        url = f"{SOFURRY_BASE}/s/{submission_id}"

        # Fetch the actual story content from the submission page
        # SoFurry renders story text in a specific div on the page
        import asyncio
        await asyncio.sleep(0.5)  # Rate limit

        page_resp = await client._http.get(f"{SOFURRY_BASE}/s/{submission_id}")
        if page_resp.status_code != 200:
            raise RuntimeError(f"Could not fetch SF submission page (status {page_resp.status_code})")

        page_html = page_resp.text
        content = ""

        # SoFurry renders story content in a div with id="sfContentBody"
        # or in a <div class="sf-story-content"> or similar container.
        # Try multiple patterns since the page structure may vary.
        patterns = [
            r'<div[^>]*id="sfContentBody"[^>]*>(.*?)</div>\s*(?:</div>|<div)',
            r'<div[^>]*class="[^"]*sfContentBody[^"]*"[^>]*>(.*?)</div>',
            r'<div[^>]*class="[^"]*story-content[^"]*"[^>]*>(.*?)</div>',
            r'<div[^>]*class="[^"]*submission-content[^"]*"[^>]*>(.*?)</div>',
            r'<div[^>]*id="sfTextBody"[^>]*>(.*?)</div>',
        ]

        for pattern in patterns:
            match = re.search(pattern, page_html, re.DOTALL | re.IGNORECASE)
            if match:
                content = match.group(1).strip()
                break

        if not content:
            # Broader fallback: look for the main content area between
            # known SF page landmarks
            body_match = re.search(
                r'<!-- content start -->(.*?)<!-- content end -->',
                page_html, re.DOTALL | re.IGNORECASE,
            )
            if body_match:
                content = body_match.group(1).strip()

        if not content:
            # Final fallback: use contentUrl from API if available
            content_url = data.get("contentUrl", "")
            if content_url:
                if not content_url.startswith("http"):
                    content_url = f"{SOFURRY_BASE}{content_url}"
                content_resp = await client._http.get(content_url)
                if content_resp.status_code == 200:
                    content = content_resp.text

        if not content:
            content = description or "(No content available — story text could not be extracted)"
            logger.warning("SF import %s: no story content found, using description", submission_id)

    finally:
        await client.close()

    folder_name = _sanitize_folder_name(title)
    story_name = _create_story_folder(
        name=folder_name,
        title=title,
        author=author,
        description=description,
        tags=tags,
        rating=rating,
        content=content,
        content_format="html",
        cover_url=cover_url,
        platform="sf",
        submission_id=str(submission_id),
        source_url=url,
    )

    return {"story_name": story_name, "title": title}
