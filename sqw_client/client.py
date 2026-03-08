"""SquidgeWorld (SqW) HTTP client.

SquidgeWorld runs the OTW Archive software (same as AO3).  Authentication
is via standard Rails form login with CSRF token.  Data is collected by
scraping the web UI since there is no public API.

Key details:
  - Work IDs are integers (e.g. 88335)
  - Stats: hits, kudos, comments, bookmarks
  - Auth: username/password login (separate from the user being tracked)
  - Anti-bot measures may require realistic headers and rate limiting
"""

from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import re
from html import unescape

import httpx

import config

logger = logging.getLogger(__name__)

# Rate limit between requests (seconds)
SQW_REQUEST_DELAY = 2.0

_BASE = "https://squidgeworld.org"

# Realistic browser headers to avoid bot detection
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


class SquidgeWorldClient:
    """Async HTTP client for SquidgeWorld (OTW Archive)."""

    def __init__(self, username: str, password: str, target_user: str):
        """
        Args:
            username: Login account username (e.g. PawPoller)
            password: Login account password
            target_user: User whose works to track (e.g. KnaughtyKat)
        """
        self.username = username
        self.password = password
        self.target_user = target_user
        self._http = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=_HEADERS,
        )
        self._logged_in = False

    def update_credentials(self, username: str, password: str, target_user: str) -> None:
        """Update credentials, invalidating cached session if changed."""
        if username != self.username or password != self.password:
            self._logged_in = False
        self.username = username
        self.password = password
        self.target_user = target_user

    async def close(self) -> None:
        await self._http.aclose()

    # ── Anubis Bot Challenge ─────────────────────────────────────

    async def _solve_anubis(self, html: str) -> bool:
        """Solve the Anubis proof-of-work bot challenge.

        Anubis (by Xe Iaso / Techaro) protects SquidgeWorld with a SHA-256
        challenge.  The "preact" algorithm:
          1. Extract the challenge string from the page's preact_info JSON
          2. Compute SHA-256 of the challenge string
          3. GET the pass-challenge endpoint with result=<sha256hex>
          4. Receive an auth cookie for subsequent requests
        """
        # Extract preact_info JSON from the challenge page
        m = re.search(
            r'id="preact_info"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        if not m:
            logger.error("SqW: Could not find preact_info in Anubis challenge page")
            return False

        try:
            info = json.loads(m.group(1).strip())
        except json.JSONDecodeError as e:
            logger.error("SqW: Failed to parse preact_info JSON: %s", e)
            return False

        challenge = info.get("challenge", "")
        redir = info.get("redir", "")
        difficulty = info.get("difficulty", 1)

        if not challenge or not redir:
            logger.error("SqW: preact_info missing challenge or redir")
            return False

        # Compute SHA-256 of the challenge string
        result = hashlib.sha256(challenge.encode("utf-8")).hexdigest()
        logger.info("SqW: Solved Anubis challenge (difficulty=%d)", difficulty)

        # Wait the required delay (difficulty * 100ms)
        await asyncio.sleep(difficulty * 0.1)

        # Submit the solution
        pass_url = f"{_BASE}{redir}"
        # Add result as query parameter
        separator = "&" if "?" in pass_url else "?"
        pass_url = f"{pass_url}{separator}result={result}"

        try:
            resp = await self._http.get(pass_url)
            logger.info("SqW: Anubis challenge response: %d -> %s", resp.status_code, resp.url)
            return True
        except httpx.HTTPError as e:
            logger.error("SqW: Failed to submit Anubis solution: %s", e)
            return False

    async def _get_page(self, url: str) -> str | None:
        """Fetch a page, solving Anubis challenges if encountered."""
        try:
            resp = await self._http.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error("SqW: Failed to fetch %s: %s", url, e)
            return None

        html = resp.text

        # Check if we got an Anubis challenge instead of the actual page
        if "Making sure you" in html and "anubis" in html.lower():
            logger.info("SqW: Anubis challenge detected, solving...")
            if await self._solve_anubis(html):
                # Retry the original request
                try:
                    resp = await self._http.get(url)
                    resp.raise_for_status()
                    return resp.text
                except httpx.HTTPError as e:
                    logger.error("SqW: Retry after Anubis failed: %s", e)
                    return None
            else:
                return None

        return html

    # ── Authentication ──────────────────────────────────────────

    async def login(self) -> bool:
        """Authenticate via OTW Archive Rails login form.

        Steps:
          1. GET /users/login → extract authenticity_token from form
          2. POST /users/login with credentials + token
          3. Verify login succeeded by checking for redirect or user menu
        """
        logger.info("SqW: Logging in as %s...", self.username)

        # Step 1: Get login page (may trigger Anubis challenge)
        html = await self._get_page(f"{_BASE}/users/login")
        if not html:
            logger.error("SqW: Failed to fetch login page")
            return False

        # Extract authenticity_token from the login form
        token_match = re.search(
            r'<input[^>]*name="authenticity_token"[^>]*value="([^"]+)"',
            html,
        )
        if not token_match:
            # Try alternate pattern (value before name)
            token_match = re.search(
                r'<input[^>]*value="([^"]+)"[^>]*name="authenticity_token"',
                html,
            )
        if not token_match:
            logger.error("SqW: Could not find authenticity_token on login page")
            return False

        token = token_match.group(1)

        # Step 2: POST login
        login_data = {
            "authenticity_token": token,
            "user[login]": self.username,
            "user[password]": self.password,
            "user[remember_me]": "1",
            "commit": "Log In",
        }

        try:
            resp = await self._http.post(
                f"{_BASE}/users/login",
                data=login_data,
                headers={
                    **_HEADERS,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": f"{_BASE}/users/login",
                },
            )
        except httpx.HTTPError as e:
            logger.error("SqW: Login POST failed: %s", e)
            return False

        # Step 3: Verify login — check for greeting or logged-in indicators
        page = resp.text
        if "greeting" in page.lower() or f"Hi, {self.username}" in page or "Log Out" in page:
            self._logged_in = True
            logger.info("SqW: Successfully logged in as %s", self.username)
            return True

        # Check if we landed on the dashboard (successful login redirects)
        if resp.url and "/users/" in str(resp.url):
            self._logged_in = True
            logger.info("SqW: Login redirect successful for %s", self.username)
            return True

        logger.error("SqW: Login appears to have failed (no logged-in indicators)")
        return False

    async def ensure_logged_in(self) -> bool:
        """Login if not already authenticated."""
        if self._logged_in:
            # Quick session check
            html = await self._get_page(f"{_BASE}/users/{self.username}")
            if html and "Log Out" in html:
                return True
            self._logged_in = False

        return await self.login()

    async def validate_session(self) -> str | None:
        """Login and return the target username if successful, else None."""
        if await self.ensure_logged_in():
            return self.target_user
        return None

    # ── Works Discovery ─────────────────────────────────────────

    async def get_all_work_ids(self) -> list[dict]:
        """Scrape the target user's works page to discover all work IDs.

        Returns list of dicts with 'work_id' (int) and 'title' (str).
        """
        if not await self.ensure_logged_in():
            raise ValueError("SqW: Not authenticated")

        all_works: list[dict] = []
        page = 1
        seen_ids: set[int] = set()

        while True:
            url = f"{_BASE}/users/{self.target_user}/works?page={page}"
            logger.info("SqW: Fetching works page %d for %s", page, self.target_user)

            html = await self._get_page(url)
            if not html:
                logger.error("SqW: Failed to fetch works page %d", page)
                break

            # Extract work IDs and titles from the listing
            # OTW Archive pattern: <h4 class="heading"><a href="/works/88335">Title</a>
            works = re.findall(
                r'<a\s+href="/works/(\d+)"[^>]*>([^<]+)</a>',
                html,
            )

            if not works:
                break

            new_this_page = 0
            for work_id_str, title in works:
                work_id = int(work_id_str)
                if work_id not in seen_ids:
                    seen_ids.add(work_id)
                    all_works.append({
                        "work_id": work_id,
                        "title": unescape(title.strip()),
                    })
                    new_this_page += 1

            if new_this_page == 0:
                break

            # Check for next page link
            if f'page={page + 1}' not in html and 'rel="next"' not in html:
                break

            page += 1
            await asyncio.sleep(SQW_REQUEST_DELAY)

        logger.info("SqW: Found %d works for %s", len(all_works), self.target_user)
        return all_works

    # ── Work Details ────────────────────────────────────────────

    async def get_work_detail(self, work_id: int) -> dict:
        """Fetch stats and metadata for a single work.

        Parses the work page for:
          - Title, author, fandom, rating, warnings, tags
          - Stats: hits, kudos, comments, bookmarks, word_count, chapters
          - Posted date, updated date
        """
        url = f"{_BASE}/works/{work_id}?view_adult=true"

        html = await self._get_page(url)
        if not html:
            logger.error("SqW: Failed to fetch work %d", work_id)
            return {"work_id": work_id, "title": "", "hits": 0, "kudos_count": 0,
                    "comments_count": 0, "bookmarks_count": 0}

        detail: dict = {"work_id": work_id}

        # Title — <h2 class="title heading">Title</h2>
        # Restricted works have an <img> tag inside, so capture full h2 content
        m = re.search(r'<h2\s+class="title[^"]*heading"[^>]*>(.*?)</h2>', html, re.DOTALL)
        if m:
            title_html = m.group(1)
            detail["title"] = unescape(re.sub(r'<[^>]+>', '', title_html).strip())
        else:
            detail["title"] = ""

        # Author
        m = re.search(r'<a\s+rel="author"[^>]*>([^<]+)</a>', html)
        detail["username"] = unescape(m.group(1).strip()) if m else self.target_user

        # Fandom
        m = re.search(r'class="fandom[^"]*"[^>]*>.*?<a[^>]*>([^<]+)</a>', html, re.DOTALL)
        detail["fandom"] = unescape(m.group(1).strip()) if m else ""

        # Rating
        m = re.search(r'class="rating[^"]*"[^>]*>.*?<a[^>]*>([^<]+)</a>', html, re.DOTALL)
        detail["rating"] = unescape(m.group(1).strip()) if m else ""

        # Summary — may have an <h3>Summary:</h3> before the blockquote
        m = re.search(
            r'class="summary[^"]*"[^>]*>.*?<blockquote[^>]*>(.*?)</blockquote>',
            html, re.DOTALL,
        )
        if m:
            summary_html = m.group(1).strip()
            detail["description"] = re.sub(r'<[^>]+>', '', summary_html).strip()
        else:
            detail["description"] = ""

        # Tags/keywords — collect all freeform and other tags
        tags = re.findall(r'class="tag"[^>]*>([^<]+)</a>', html)
        detail["keywords"] = [unescape(t.strip()) for t in tags]

        # ── Stats extraction ────────────────────────────────
        # OTW Archive uses <dl class="stats"> with <dd class="metric">value</dd>

        def _extract_stat(stat_class: str) -> int:
            """Extract an integer stat from the stats dl."""
            pattern = rf'<dd\s+class="{stat_class}"[^>]*>\s*(\d[\d,]*)\s*</dd>'
            m = re.search(pattern, html)
            if m:
                return int(m.group(1).replace(",", ""))
            # Fallback: stat might be wrapped in an <a> tag (bookmarks)
            pattern2 = rf'<dd\s+class="{stat_class}"[^>]*>\s*<a[^>]*>\s*(\d[\d,]*)\s*</a>'
            m = re.search(pattern2, html)
            if m:
                return int(m.group(1).replace(",", ""))
            return 0

        detail["hits"] = _extract_stat("hits")
        detail["kudos_count"] = _extract_stat("kudos")
        detail["comments_count"] = _extract_stat("comments")
        detail["bookmarks_count"] = _extract_stat("bookmarks")

        # Word count and chapters
        detail["word_count"] = _extract_stat("words")
        m = re.search(r'<dd\s+class="chapters"[^>]*>(\d+)/(\d+|\?)', html)
        if m:
            detail["chapters_current"] = int(m.group(1))
            detail["chapters_total"] = m.group(2)
            detail["chapters"] = f"{m.group(1)}/{m.group(2)}"
        else:
            detail["chapters_current"] = 1
            detail["chapters_total"] = "1"
            detail["chapters"] = "1/1"

        # Posted date
        m = re.search(r'class="published"[^>]*>(\d{4}-\d{2}-\d{2})</dd>', html)
        detail["posted_at"] = m.group(1) if m else None

        # Updated date
        m = re.search(r'class="status"[^>]*>(\d{4}-\d{2}-\d{2})</dd>', html)
        detail["updated_date"] = m.group(1) if m else detail.get("posted_at")

        # Link
        detail["link"] = f"{_BASE}/works/{work_id}"

        # Map to consistent schema column names
        detail["views"] = detail["hits"]
        detail["favorites_count"] = detail["kudos_count"]

        return detail

    async def get_work_details_batch(self, work_ids: list[int]) -> list[dict]:
        """Fetch details for multiple works with rate limiting."""
        details = []
        for i, work_id in enumerate(work_ids):
            if i > 0:
                await asyncio.sleep(SQW_REQUEST_DELAY)
            detail = await self.get_work_detail(work_id)
            details.append(detail)
        return details

    # ── Kudos Users ─────────────────────────────────────────────

    async def get_kudos_users(self, work_id: int) -> list[str]:
        """Extract the list of users who left kudos on a work.

        OTW Archive shows kudos users at the bottom of the work page
        in a <p class="kudos"> section.
        """
        url = f"{_BASE}/works/{work_id}?view_adult=true"
        html = await self._get_page(url)
        if not html:
            return []

        # Find kudos section: <p class="kudos">...<a href="/users/name">name</a>...
        kudos_section = re.search(
            r'id="kudos"[^>]*>(.*?)</p>', html, re.DOTALL,
        )
        if not kudos_section:
            kudos_section = re.search(
                r'class="kudos"[^>]*>(.*?)</p>', html, re.DOTALL,
            )
        if not kudos_section:
            return []

        # Extract usernames from links
        users = re.findall(
            r'<a\s+href="/users/([^"]+)"', kudos_section.group(1),
        )
        # Also count guest kudos
        guest_match = re.search(r'(\d+)\s+guest', kudos_section.group(1))
        # Return just registered user names
        return [unescape(u) for u in users]
