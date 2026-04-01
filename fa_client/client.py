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
import os
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
        transport = httpx.AsyncHTTPTransport(retries=2)
        self._http = httpx.AsyncClient(timeout=30.0, transport=transport)
        # Secondary client: direct FA with cookies (lazy-initialised)
        self._fa_http: httpx.AsyncClient | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

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
            fa_transport = httpx.AsyncHTTPTransport(retries=2)
            self._fa_http = httpx.AsyncClient(
                timeout=30.0,
                cookies=self._fa_cookies(),
                follow_redirects=True,
                # Custom UA to identify our traffic to FA's servers
                headers={"User-Agent": "PawPoller/1.0"},
                transport=fa_transport,
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
        for _page_safety in range(1000):
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

    # ── Profile Sniff (Spam Detection) ──────────────────────

    async def get_user_profile(self, username: str) -> dict | None:
        """Fetch a user's profile summary from FAExport.

        Returns a dict with profile data (name, profile, submissions count, etc.)
        or None if the user doesn't exist or the request fails. Used to sniff
        new watchers for bot characteristics (zero submissions, zero favorites).
        """
        try:
            resp = await self._http.get(
                f"{config.FAEXPORT_BASE}/user/{username}.json",
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data if isinstance(data, dict) else None
        except Exception as e:
            logger.debug("Failed to fetch profile for %s: %s", username, e)
            return None

    async def sniff_watcher_profiles(self, usernames: list[str]) -> dict[str, bool]:
        """Check a batch of watcher usernames for bot characteristics.

        For each username, fetches their FAExport profile and checks:
        - Zero submissions + zero favorites + zero watches = likely bot
        - Profile doesn't exist (banned already) = definitely bot

        Returns a dict of {username: is_spam} for each checked user.
        Rate-limited to avoid hammering FAExport.
        """
        results: dict[str, bool] = {}
        for username in usernames:
            await asyncio.sleep(config.FA_REQUEST_DELAY_SECONDS)
            profile = await self.get_user_profile(username)
            if profile is None:
                # Profile doesn't exist = already banned = spam
                results[username] = True
                continue
            # Check activity indicators
            stats = profile.get("stats", {})
            submissions = _safe_int(stats.get("submissions", 0))
            favorites = _safe_int(stats.get("favorites", 0))
            watches = _safe_int(stats.get("watches", 0))
            # Zero activity across the board = almost certainly a bot
            if submissions == 0 and favorites == 0 and watches == 0:
                results[username] = True
            else:
                results[username] = False
            logger.debug("Profile sniff %s: subs=%d fav=%d watches=%d -> spam=%s",
                         username, submissions, favorites, watches, results[username])
        return results

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

        Walks pages sequentially until FAExport returns an empty list or
        repeats the previous page (FAExport returns the last page's data
        indefinitely instead of an empty list for some accounts).
        Rate-limited between pages to be polite to the FAExport server.

        Returns a deduplicated list of all watcher usernames.
        """
        all_watchers: list[str] = []
        seen: set[str] = set()
        page = 1
        for _page_safety in range(1000):
            items = await self.get_watchers_page(page)
            # Empty list = no more pages
            if not items:
                break
            # FAExport repeats the last page forever instead of returning
            # empty — stop when we see no new usernames
            new_items = [u for u in items if u not in seen]
            if not new_items:
                break
            seen.update(new_items)
            all_watchers.extend(new_items)
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


    # ── Posting / Upload ────────────────────────────────────────

    async def submit_story(
        self,
        file_path: str,
        *,
        title: str = "",
        description: str = "",
        keywords: str = "",
        rating: str = "1",
        cat: str = "13",
        atype: str = "1",
        species: str = "1",
        gender: str = "0",
        scrap: bool = False,
        thumbnail_path: str | None = None,
    ) -> dict:
        """Upload a story submission to FurAffinity.

        Three-step form scraping flow (same as PostyBirb):
          1. GET /submit/ → scrape hidden 'key' input
          2. POST /submit/upload → multipart with key + file + submission_type
          3. POST /submit/finalize → urlencoded with new key + all metadata

        Args:
            file_path: Path to PDF/TXT/DOC file.
            title: Title (max 60 chars).
            description: BBCode description.
            keywords: Space-separated tags (underscores for multi-word).
            rating: "0"=General, "2"=Mature, "1"=Adult.
            cat: Category ("13"=Story).
            atype: Theme ("1"=All).
            species: Species code ("1"=Unspecified).
            gender: Gender code ("0"=Any).
            scrap: Post to scraps if True.
            thumbnail_path: Optional cover image path.

        Returns:
            Dict with 'submission_id' and 'url'.
        """
        client = await self._get_fa_http()

        # Step 1: GET /submit/ and scrape the key
        resp = await client.get(f"{config.FA_BASE}/submit/")
        if resp.status_code != 200:
            raise RuntimeError(f"FA: GET /submit/ failed — status {resp.status_code}")

        # Extract the key from the upload form specifically (not the logout form)
        upload_form = re.search(
            r'<form[^>]*action="/submit/upload/"[^>]*>(.*?)</form>', resp.text, re.DOTALL
        )
        if upload_form:
            key_match = re.search(r'name="key"\s*value="([^"]+)"', upload_form.group(1))
        else:
            # Fallback: try id="myform"
            myform = re.search(r'id="myform"(.*?)</form>', resp.text, re.DOTALL)
            key_match = re.search(r'name="key"\s*value="([^"]+)"', myform.group(1)) if myform else None

        if not key_match:
            if "captcha" in resp.text.lower():
                raise RuntimeError("FA: CAPTCHA required — account needs 11+ posts")
            raise RuntimeError("FA: Could not find form key on /submit/")
        key1 = key_match.group(1)
        logger.info("FA: Got upload form key")

        # Step 2: POST /submit/upload with file
        with open(file_path, "rb") as f:
            file_data = f.read()
        filename = os.path.basename(file_path)

        upload_files = {"submission": (filename, file_data)}
        if thumbnail_path and os.path.isfile(thumbnail_path):
            with open(thumbnail_path, "rb") as tf:
                upload_files["thumbnail"] = (os.path.basename(thumbnail_path), tf.read())

        upload_data = {
            "key": key1,
            "submission_type": "story",
        }

        resp = await client.post(
            f"{config.FA_BASE}/submit/upload/",
            data=upload_data,
            files=upload_files,
            headers={"Referer": f"{config.FA_BASE}/submit/"},
            timeout=120.0,
        )

        # Scrape the new key from the finalize form
        # Look for the form that posts to /submit/finalize/
        finalize_form = re.search(
            r'<form[^>]*action="/submit/finalize/"[^>]*>(.*?)</form>', resp.text, re.DOTALL
        )
        if finalize_form:
            key2_match = re.search(r'name="key"\s*value="([^"]+)"', finalize_form.group(1))
        else:
            # Fallback: last key on the page (skip the logout form key)
            all_keys = re.findall(r'name="key"\s*value="([^"]+)"', resp.text)
            key2_match = None
            if all_keys:
                # The finalize key is typically the last one on the page
                class _M:
                    def group(self, n): return all_keys[-1]
                key2_match = _M()
        if not key2_match:
            errors = re.findall(r'(?:error|Error)[^>]*>([^<]+)', resp.text)
            raise RuntimeError(f"FA: Could not find finalize key — upload may have failed. Errors: {errors[:2]}")
        key2 = key2_match.group(1)
        logger.info("FA: File uploaded, got finalize key")

        # Step 3: POST /submit/finalize with metadata
        finalize_data = {
            "key": key2,
            "title": title[:60],
            "message": description,
            "keywords": keywords,
            "rating": rating,
            "cat": cat,
            "atype": atype,
            "species": species,
            "gender": gender,
        }
        if scrap:
            finalize_data["scrap"] = "1"

        resp = await client.post(
            f"{config.FA_BASE}/submit/finalize/",
            data=finalize_data,
            headers={
                "Referer": f"{config.FA_BASE}/submit/upload/",
            },
            timeout=30.0,
        )

        final_url = str(resp.url)
        if "upload-successful" not in final_url and "/view/" not in final_url:
            raise RuntimeError(f"FA: Finalize may have failed — final URL: {final_url}")

        # Extract submission ID from URL
        clean_url = final_url.split("?")[0]
        sid_match = re.search(r'/view/(\d+)', clean_url)
        submission_id = sid_match.group(1) if sid_match else ""

        logger.info("FA: Story submitted — %s (id=%s)", clean_url, submission_id)
        return {"submission_id": submission_id, "url": clean_url}

    async def edit_submission(
        self,
        submission_id: str,
        *,
        title: str = "",
        description: str = "",
        keywords: str = "",
        rating: str | None = None,
    ) -> dict:
        """Edit an existing FurAffinity submission.

        Scrapes the edit form at /controls/submissions/changeinfo/{id}/
        to get the key and existing field values, merges in the caller's changes,
        and posts the complete form back. This avoids blanking fields that the
        caller didn't provide.

        FA has separate edit pages:
          changeinfo/{id}/   — title, description, keywords, rating, category
          changethumbnail/   — thumbnail image
          changesubmission/  — replace the source file
          changestory/       — story text content
        """
        client = await self._get_fa_http()
        edit_url = f"{config.FA_BASE}/controls/submissions/changeinfo/{submission_id}/"

        # GET the edit page
        resp = await client.get(edit_url)
        if resp.status_code != 200:
            raise RuntimeError(f"FA: GET edit page failed — status {resp.status_code}")
        page = resp.text

        # Extract the changeinfo form and its key (not the logout form key)
        changeinfo_form = re.search(
            r'<form[^>]*action="/controls/submissions/changeinfo/[^"]*"[^>]*>(.*?)</form>',
            page, re.DOTALL,
        )
        if not changeinfo_form:
            raise RuntimeError("FA: Could not find changeinfo form on edit page")
        form_html = changeinfo_form.group(1)

        key_match = re.search(r'name="key"\s*value="([^"]+)"', form_html)
        if not key_match:
            raise RuntimeError("FA: Could not find key in changeinfo form")
        key = key_match.group(1)

        # Scrape existing values from the form to preserve fields the caller didn't provide
        def _scrape_input(name: str) -> str:
            m = re.search(rf'name="{name}"[^>]*value="([^"]*)"', form_html)
            return m.group(1) if m else ""

        def _scrape_textarea(name: str) -> str:
            m = re.search(rf'name="{name}"[^>]*>(.*?)</textarea>', form_html, re.DOTALL)
            return m.group(1).strip() if m else ""

        def _scrape_select(name: str) -> str:
            m = re.search(rf'name="{name}".*?<option[^>]*selected[^>]*value="([^"]*)"', form_html, re.DOTALL)
            return m.group(1) if m else ""

        # Build complete form data: current values as base, overlay caller's changes
        form_data: dict[str, str] = {
            "key": key,
            "update": "yes",
            "title": title[:60] if title else _scrape_input("title"),
            "message": description if description else _scrape_textarea("message"),
            "keywords": keywords if keywords else _scrape_textarea("keywords"),
            "rating": rating if rating is not None else _scrape_select("rating"),
            "cat": _scrape_input("cat") or "13",
            "atype": _scrape_select("atype") or "1",
            "species": _scrape_select("species") or "1",
        }

        resp = await client.post(
            edit_url,
            data=form_data,
            headers={"Referer": edit_url},
            timeout=30.0,
        )

        # Check for success
        final_url = str(resp.url)
        if resp.status_code >= 400:
            raise RuntimeError(f"FA: Edit POST failed — status {resp.status_code}")

        url = f"{config.FA_BASE}/view/{submission_id}/"
        logger.info("FA: Edited submission %s — title=%r", submission_id, title[:40] if title else "(unchanged)")
        return {"submission_id": submission_id, "url": url}


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
