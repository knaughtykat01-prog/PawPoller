"""FurAffinity client using FAExport API for data and direct cookies for validation.

This client uses a DUAL HTTP CLIENT PATTERN, similar to the Inkbunny client but for
different reasons:

  _http      -- Talks to FAExport (https://faexport.spangle.org.uk), a third-party
                REST API that wraps FurAffinity's data into clean JSON endpoints.
                No authentication needed -- FAExport is a public proxy.

  _fa_http   -- Talks directly to furaffinity.net with the user's session cookies
                (cookie 'a' and cookie 'b'). Used ONLY for cookie validation, not
                for data retrieval.

WHY FAEXPORT INSTEAD OF DIRECT SCRAPING?
FurAffinity does not have an official API. The only way to get structured data is to
scrape the HTML pages directly. FAExport handles this scraping server-side and exposes
the data as JSON, which is far more reliable and maintainable than parsing FA's HTML
ourselves. FAExport provides endpoints for gallery listings, submission details, and
comments -- covering all our data needs.

The direct FA client (_fa_http) exists solely to validate that the user's cookies are
still active, since FAExport doesn't support authenticated requests and we need valid
cookies for other parts of the system.
"""

from __future__ import annotations
import asyncio
import json
import logging
import re
from typing import Any

import httpx

import config

logger = logging.getLogger(__name__)


class FAClient:
    """FurAffinity data client -- FAExport for gallery/submission data, cookies for validation.

    Two independent HTTP transports:
      _http      -- unauthenticated client for FAExport JSON API (public proxy)
      _fa_http   -- authenticated client for direct FA access (cookies, lazy-init)
    """

    def __init__(self, username: str = "", cookie_a: str = "", cookie_b: str = ""):
        self.username = username or config.FA_USERNAME
        # FA uses two cookies ('a' and 'b') together as the session token.
        # Both must be present and valid for an authenticated session.
        self.cookie_a = cookie_a or config.FA_COOKIE_A
        self.cookie_b = cookie_b or config.FA_COOKIE_B
        # Primary client: talks to FAExport (no auth needed)
        self._http = httpx.AsyncClient(timeout=30.0)
        # Secondary client: direct FA with cookies (lazy-initialised)
        self._fa_http: httpx.AsyncClient | None = None

    async def close(self) -> None:
        """Shut down both HTTP clients and release their connection pools."""
        await self._http.aclose()
        if self._fa_http:
            await self._fa_http.aclose()

    def _fa_cookies(self) -> dict[str, str]:
        """Return the FA session cookies as a dict for httpx cookie injection."""
        return {"a": self.cookie_a, "b": self.cookie_b}

    async def _get_fa_http(self) -> httpx.AsyncClient:
        """Lazy-init the direct FA client with session cookies.

        Created on first use rather than in __init__ because most operations only
        need FAExport (_http). The direct FA client is only needed for cookie
        validation, so we avoid the overhead of creating it unless actually needed.
        """
        if self._fa_http is None:
            self._fa_http = httpx.AsyncClient(
                timeout=30.0,
                cookies=self._fa_cookies(),
                follow_redirects=True,
                # Custom UA to identify our traffic to FA's servers
                headers={"User-Agent": "PawPoller/1.0"},
            )
        return self._fa_http

    # ── Cookie Validation ─────────────────────────────────────

    async def validate_cookies(self) -> bool:
        """Test cookies by fetching the user's gallery page on FA directly.

        Validation approach:
        We request the user's gallery page and check for <figure> elements in the
        HTML. On FurAffinity, each submission thumbnail is wrapped in a <figure> tag.
        If the page contains <figure> elements, the cookies are valid and we're seeing
        real gallery content.

        If cookies are expired or invalid, FA either:
          - Redirects to the login page (no <figure> elements)
          - Returns a 200 with a "please log in" message (no <figure> elements)

        As a secondary check, we verify the final URL still contains our username's
        gallery path (in case of a redirect that kept status 200).
        """
        if not self.cookie_a or not self.cookie_b or not self.username:
            return False
        try:
            client = await self._get_fa_http()
            resp = await client.get(f"{config.FA_BASE}/gallery/{self.username}/")
            if resp.status_code != 200:
                return False
            # <figure> elements = gallery thumbnails are present = valid session
            return "<figure" in resp.text or f"gallery/{self.username}" in str(resp.url)
        except Exception as e:
            logger.warning("FA cookie validation failed: %s", e)
            return False

    # ── FAExport Gallery Listing ──────────────────────────────

    async def get_gallery_page(self, page: int = 1) -> list[dict]:
        """Fetch one page of gallery via FAExport.

        The `full=1` parameter tells FAExport to return expanded submission data
        (title, thumbnail, etc.) rather than just bare submission IDs.
        FAExport returns an empty list when the page is beyond the last page.
        """
        resp = await self._http.get(
            f"{config.FAEXPORT_BASE}/user/{self.username}/gallery.json",
            params={"page": str(page), "full": "1"},
        )
        resp.raise_for_status()
        items = resp.json()
        # FAExport should return a list; if it returns something else
        # (e.g. an error object), treat it as empty.
        if not isinstance(items, list):
            return []
        return items

    async def get_all_gallery_ids(self) -> list[dict]:
        """Paginate through all gallery pages and return submission stubs.

        Walks pages sequentially until FAExport returns an empty list (indicating
        we've gone past the last page). Rate-limited between pages to be polite
        to the FAExport server.

        Returns minimal stubs {submission_id, title, thumbnail_url} -- enough for
        the caller to decide which submissions need full detail fetching.
        """
        all_subs: list[dict] = []
        page = 1
        while True:
            items = await self.get_gallery_page(page)
            # Empty list = no more pages
            if not items:
                break
            for item in items:
                sub_id = item.get("id")
                if sub_id:
                    all_subs.append({
                        "submission_id": int(sub_id),
                        "title": item.get("title", ""),
                        "thumbnail_url": item.get("thumbnail", ""),
                    })
            page += 1
            # Rate-limit between pages to avoid overloading FAExport
            await asyncio.sleep(config.FA_REQUEST_DELAY_SECONDS)
        return all_subs

    # ── FAExport Submission Detail ────────────────────────────

    async def get_submission_detail(self, submission_id: int) -> dict:
        """Fetch full submission details from FAExport and normalize.

        FAExport returns the raw scraped data in its own JSON schema. We normalise
        it into our internal DB format via _normalize_submission() so the rest of
        the application works with a consistent structure regardless of platform.
        """
        resp = await self._http.get(
            f"{config.FAEXPORT_BASE}/submission/{submission_id}.json",
        )
        resp.raise_for_status()
        raw = resp.json()
        return self._normalize_submission(raw, submission_id)

    async def get_submission_details_batch(self, submission_ids: list[int]) -> list[dict]:
        """Fetch details for multiple submissions one-by-one with rate limiting.

        Unlike the Inkbunny API which supports batch fetching (multiple IDs in one
        request), FAExport only serves one submission at a time. We therefore loop
        through IDs sequentially with a rate-limiting delay between each request.

        Individual failures are logged and skipped so one bad submission doesn't
        abort the entire batch.
        """
        details: list[dict] = []
        for i, sid in enumerate(submission_ids):
            try:
                detail = await self.get_submission_detail(sid)
                details.append(detail)
            except Exception as e:
                logger.warning("Failed to fetch FA submission %d: %s", sid, e)
            # Rate-limit between requests, but not after the final one
            if i < len(submission_ids) - 1:
                await asyncio.sleep(config.FA_REQUEST_DELAY_SECONDS)
        return details

    # ── FAExport Comments ─────────────────────────────────────

    async def get_submission_comments(self, submission_id: int) -> list[dict]:
        """Fetch comments for a submission from FAExport.

        Unlike Inkbunny (where we must scrape comments from HTML because the API
        doesn't expose comment text), FAExport provides a dedicated comments endpoint
        that returns structured JSON with full comment text, threading info, and
        timestamps. Each comment is normalised to our internal format.
        """
        resp = await self._http.get(
            f"{config.FAEXPORT_BASE}/submission/{submission_id}/comments.json",
        )
        resp.raise_for_status()
        raw_comments = resp.json()
        # Guard against unexpected response shapes (e.g. error objects)
        if not isinstance(raw_comments, list):
            return []
        return [self._normalize_comment(c, submission_id) for c in raw_comments]

    # ── Watcher Tracking ──────────────────────────────────────

    async def get_watchers_page(self, page: int = 1) -> list[str]:
        """Fetch one page of watcher usernames via FAExport.

        FAExport returns a plain JSON array of username strings for the watchers
        endpoint. Returns an empty list when the page is beyond the last page.
        """
        resp = await self._http.get(
            f"{config.FAEXPORT_BASE}/user/{self.username}/watchers.json",
            params={"page": str(page)},
        )
        resp.raise_for_status()
        items = resp.json()
        # FAExport should return a list; if it returns something else
        # (e.g. an error object), treat it as empty.
        if not isinstance(items, list):
            return []
        return items

    async def get_all_watchers(self) -> list[str]:
        """Paginate through all watcher pages and return the complete list.

        Walks pages sequentially until FAExport returns an empty list (indicating
        we've gone past the last page). Rate-limited between pages to be polite
        to the FAExport server.

        Returns a flat list of all watcher usernames.
        """
        all_watchers: list[str] = []
        page = 1
        while True:
            items = await self.get_watchers_page(page)
            # Empty list = no more pages
            if not items:
                break
            all_watchers.extend(items)
            page += 1
            # Rate-limit between pages to avoid overloading FAExport
            await asyncio.sleep(config.FA_REQUEST_DELAY_SECONDS)
        logger.info("Fetched %d total watchers for %s", len(all_watchers), self.username)
        return all_watchers

    # ── Normalization ─────────────────────────────────────────
    #
    # FAExport's JSON schema doesn't match our internal DB format. These methods
    # translate FAExport field names/types into the consistent structure used by
    # the rest of the application (same shape as Inkbunny's to_db_dict output).
    #

    @staticmethod
    def _normalize_submission(raw: dict, submission_id: int) -> dict:
        """Normalize FAExport submission JSON to our DB dict format.

        Handles several inconsistencies in FAExport's response:
        - Tags may be under "tags" or "keywords" (varies by FAExport version)
        - Tags may be a list of strings OR a single comma-separated string
        - Numeric stats (views, favorites) may be strings or ints
        - Some metadata lives in a nested "info" dict, some at top level
        - The "comments" field can be either a count (int/str) or a full list
          of comment objects -- we just need the count here
        """
        # Tags: FAExport returns these under different keys depending on endpoint.
        # May be a list ["tag1", "tag2"] or a comma-separated string "tag1, tag2".
        tags = raw.get("tags") or raw.get("keywords") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        # Numeric stats need _safe_int because FAExport may return them as
        # strings (e.g. "1,234"), ints, or None depending on the submission.
        views = _safe_int(raw.get("views", 0))
        favorites = _safe_int(raw.get("favorites", 0))

        # The "comments" field is polymorphic in FAExport:
        #   - On the submission detail endpoint: usually an integer count
        #   - On the full endpoint with comments included: a list of comment objects
        # We need just the count, so if it's a list, we take its length.
        comments_raw = raw.get("comments", 0)
        if isinstance(comments_raw, list):
            comments_count = len(comments_raw)
        else:
            comments_count = _safe_int(comments_raw)

        # FAExport nests some metadata (category, species, etc.) under an "info" dict
        # on certain endpoints, but puts them at the top level on others.
        # We check "info" first, then fall back to top-level keys.
        info = raw.get("info", {}) if isinstance(raw.get("info"), dict) else {}

        return {
            "submission_id": submission_id,
            "title": raw.get("title", ""),
            # Author name: FAExport uses "name" or "profile_name" inconsistently
            "username": raw.get("name", raw.get("profile_name", "")),
            # Posted date: may be "posted_at" or just "posted"
            "posted_at": raw.get("posted_at", raw.get("posted", "")),
            # Metadata with info-dict fallback
            "category": info.get("category", raw.get("category", "")),
            "theme": info.get("theme", raw.get("theme", "")),
            "species": info.get("species", raw.get("species", "")),
            "gender": info.get("gender", raw.get("gender", "")),
            "rating": raw.get("rating", ""),
            "thumbnail_url": raw.get("thumbnail", ""),
            "download_url": raw.get("download", ""),
            "description": raw.get("description", ""),
            "keywords": tags,
            # Construct canonical FA URL as fallback if "link" is missing
            "link": raw.get("link", f"https://www.furaffinity.net/view/{submission_id}/"),
            "views": views,
            "favorites_count": favorites,
            "comments_count": comments_count,
        }

    @staticmethod
    def _normalize_comment(raw: dict, submission_id: int) -> dict:
        """Normalize FAExport comment JSON to our DB comment dict format.

        FAExport provides structured comment data including threading info
        (reply_to parent ID and reply_level nesting depth) and deletion status.
        """
        return {
            "comment_id": str(raw.get("id", "")),
            "submission_id": submission_id,
            # Author: same inconsistent naming as submissions
            "username": raw.get("name", raw.get("profile_name", "")),
            "comment_text": raw.get("text", ""),
            # Timestamp: same dual-key pattern as submissions
            "commented_at": raw.get("posted_at", raw.get("posted", "")),
            # reply_to: parent comment ID (None for top-level comments)
            "reply_to": str(raw["reply_to"]) if raw.get("reply_to") else None,
            # reply_level: nesting depth (0 = top-level, 1 = direct reply, etc.)
            "reply_level": _safe_int(raw.get("reply_level", 0)),
            # FAExport includes a flag for comments that were deleted by the author/mod
            "is_deleted": raw.get("is_deleted", False),
        }


def _safe_int(val: Any) -> int:
    """Safely convert a value to int, handling None, comma-formatted strings, and type errors.

    FA and FAExport return numeric values in inconsistent formats:
      - Integers: 42
      - Plain strings: "42"
      - Comma-formatted strings: "1,234" (common for view/fav counts on FA pages)
      - None: when the field is missing entirely

    This helper normalises all of these to a plain int, returning 0 on any failure.
    """
    if val is None:
        return 0
    try:
        # Strip commas from formatted numbers like "1,234" before int conversion
        if isinstance(val, str):
            val = val.replace(",", "").strip()
        return int(val)
    except (ValueError, TypeError):
        return 0
