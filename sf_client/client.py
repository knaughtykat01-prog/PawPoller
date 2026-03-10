"""SoFurry client using web scraping for gallery and submission data.

SoFurry's new platform ("SoFurry Next") does not offer API key generation,
despite having had a public API in the past.  This client authenticates via
email/password to obtain session cookies, then scrapes the web interface for
submission data.

Authentication flow:
  1. GET /login to extract CSRF _token
  2. POST /login with _token, email, password
  3. On success, SoFurry sets session cookies in the response
  4. All subsequent requests use those cookies automatically (httpx cookie jar)

Data collection:
  - Gallery listing: scrape /u/{display_name}/gallery for submission IDs
  - Submission metadata: GET /ui/submission/{id} (JSON API)
  - Submission stats (views/likes): scrape /s/{id} web page
  - No individual comment text available (count only, like Weasyl)
  - No faving-user lists available (count only)

Important: SoFurry defaults to showing NSFW content after login.
Do NOT call GET /sfw — that toggles SFW mode ON, hiding Adult submissions.
"""

from __future__ import annotations
import asyncio
import logging
import re
from typing import Any

import httpx

import config

logger = logging.getLogger(__name__)

SOFURRY_BASE = "https://sofurry.com"

# SoFurry rating codes (from /ui/submission JSON)
_RATING_MAP = {10: "Clean", 20: "Adult"}


class SoFurryClient:
    """SoFurry web scraping client using session cookie authentication."""

    def __init__(self, username: str = "", password: str = "", totp_code: str = "",
                 display_name: str = "", proxy_url: str = "", proxy_key: str = ""):
        self.username = username          # email address used for login
        self.password = password
        self.totp_code = totp_code
        self.display_name = display_name  # SF profile handle (e.g. "KnaughtyKat")

        # Use Cloudflare Worker proxy if configured (bypasses datacenter IP blocks)
        if proxy_url and proxy_key:
            from polling.cf_proxy import CloudflareProxyTransport
            transport = CloudflareProxyTransport(proxy_url, proxy_key)
            logger.info("SoFurry client using CF proxy: %s", proxy_url)
        else:
            transport = httpx.AsyncHTTPTransport(retries=2)

        self._http = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Referer": "https://sofurry.com/",
            },
            transport=transport,
        )
        self._logged_in = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    # -- Authentication ------------------------------------------------

    async def login(self) -> bool:
        """Authenticate via email/password (+ optional TOTP 2FA).

        SoFurry uses Laravel with CSRF protection.  Login flow:
          1. GET /login to obtain the CSRF _token from a hidden form field
          2. POST /login with _token, email, password
          3. If 2FA is enabled the server redirects to /auth/2fa — we then
             submit the TOTP code from ``self.totp_code`` (set by caller)
          4. On success the server redirects to / (home)

        Note: when using the CF Worker proxy, use ``login_and_fetch_gallery``
        instead — it does GET/POST/gallery in one Worker invocation to avoid
        IP rotation breaking the session.
        """
        if not self.username or not self.password:
            return False
        try:
            # Step 1: Fetch CSRF token from the login page
            login_page = await self._http.get(f"{SOFURRY_BASE}/login")
            csrf_match = re.search(
                r'name="_token"\s*value="([^"]+)"', login_page.text
            )
            if not csrf_match:
                logger.error("SoFurry: Could not find CSRF token on login page")
                return False
            csrf_token = csrf_match.group(1)

            # Step 2: POST credentials with CSRF token
            resp = await self._http.post(
                f"{SOFURRY_BASE}/login",
                data={
                    "_token": csrf_token,
                    "email": self.username,
                    "password": self.password,
                    "remember": "on",
                },
            )
            final_url = resp.headers.get("x-final-url", str(resp.url))
            page_text = resp.text
            final_path = final_url.split("sofurry.com")[-1] if "sofurry.com" in final_url else final_url

            logger.info("SoFurry login — final URL: %s (status %s)", final_url, resp.status_code)

            # Step 3: Handle 2FA if redirected to /auth/2fa
            if "/auth/2fa" in final_path or "2fa" in final_path:
                if not self.totp_code:
                    logger.warning("SoFurry 2FA required but no TOTP code provided")
                    return False
                return await self._submit_2fa(page_text)

            # Success: ended up anywhere other than /login
            if "/login" not in final_path:
                self._logged_in = True
                logger.info("SoFurry login successful for %s", self.username)
                return True

            # Landed on /login — login failed
            if "credentials" in page_text.lower() or "invalid" in page_text.lower():
                logger.warning("SoFurry login failed — invalid credentials")
            else:
                logger.warning("SoFurry login failed — redirected back to login page")
            return False
        except Exception as e:
            logger.warning("SoFurry login failed: %s", e)
            return False

    async def login_and_fetch_gallery(self) -> str | None:
        """Login + fetch gallery in a single CF Worker invocation.

        Uses the Worker's x-proxy-login mode which does GET /login →
        extract CSRF → POST /login → GET gallery all in one execution
        (same egress IP).  This is required because SoFurry pins
        sessions to IPs, and CF Workers rotate IPs between invocations.

        Returns the gallery HTML on success, None on failure.
        """
        if not self.username or not self.password or not self.display_name:
            return None

        transport = self._http._transport
        if not hasattr(transport, 'login_and_fetch'):
            logger.error("SoFurry: login_and_fetch_gallery requires CF proxy transport")
            return None

        try:
            gallery_url = f"{SOFURRY_BASE}/u/{self.display_name}/gallery"
            logger.info("SoFurry: login_and_fetch_gallery → %s", gallery_url)

            resp = await transport.login_and_fetch(
                login_url=f"{SOFURRY_BASE}/login",
                email=self.username,
                password=self.password,
                then_url=gallery_url,
            )

            # Read response
            raw_bytes = b""
            async for chunk in resp.stream:
                raw_bytes += chunk
            html = raw_bytes.decode("utf-8", errors="replace")

            final_url = resp.headers.get("x-final-url", "")
            logger.info("SoFurry login_and_fetch — status=%d final=%s size=%d",
                        resp.status_code, final_url, len(html))

            # Check if login succeeded (page has logout link = authenticated)
            has_logout = bool(re.search(r'logout|sign.?out', html, re.IGNORECASE))
            has_subs = bool(re.search(r'/s/[A-Za-z0-9]+', html))

            if has_logout or has_subs:
                self._logged_in = True
                logger.info("SoFurry login_and_fetch OK — authenticated=%s, has_subs=%s",
                            has_logout, has_subs)
                return html

            # Login may have failed
            if "/login" in final_url:
                logger.warning("SoFurry login_and_fetch failed — still on login page")
            else:
                logger.warning("SoFurry login_and_fetch — no auth indicators (size=%d)", len(html))
            return None

        except Exception as e:
            logger.warning("SoFurry login_and_fetch failed: %s", e)
            return None

    async def _submit_2fa(self, page_text: str) -> bool:
        """Submit a TOTP 2FA code to complete authentication."""
        try:
            # Extract form action URL
            form_action = f"{SOFURRY_BASE}/auth/2fa"
            action_match = re.search(
                r'<form[^>]*action="([^"]*)"[^>]*>',
                page_text, re.IGNORECASE
            )
            if action_match:
                action_url = action_match.group(1)
                if action_url.startswith("/"):
                    form_action = f"{SOFURRY_BASE}{action_url}"
                elif action_url.startswith("http"):
                    form_action = action_url

            csrf_match = re.search(r'name="_token"\s*value="([^"]+)"', page_text)
            if not csrf_match:
                logger.error("SoFurry: Could not find CSRF token on 2FA page")
                return False
            csrf_token = csrf_match.group(1)

            code_field = "one_time_password"
            field_match = re.search(
                r'name="((?:code|one_time_password|totp|otp|2fa_code)[^"]*)"',
                page_text, re.IGNORECASE
            )
            if field_match:
                code_field = field_match.group(1)

            resp = await self._http.post(
                form_action,
                data={"_token": csrf_token, code_field: self.totp_code},
            )
            final_url = str(resp.url)
            final_path = final_url.split("sofurry.com")[-1] if "sofurry.com" in final_url else final_url

            if "/login" not in final_path and "/2fa" not in final_path:
                self._logged_in = True
                logger.info("SoFurry 2FA successful for %s", self.username)
                return True

            logger.warning("SoFurry 2FA failed — still on auth page")
            return False
        except Exception as e:
            logger.warning("SoFurry 2FA submission failed: %s", e)
            return False

    async def check_session(self) -> bool:
        """Lightweight check: are we still authenticated?

        Fetches the user's profile page and checks for a redirect to /login
        (which SoFurry does when the session has expired).  Returns True if
        the session cookies are still valid, False otherwise.
        """
        if not self._logged_in:
            return False
        try:
            resp = await self._http.get(
                f"{SOFURRY_BASE}/u/{self.display_name}",
                follow_redirects=False,
            )
            # A 302 to /login means the session expired
            if resp.status_code in (301, 302):
                location = resp.headers.get("location", "")
                if "/login" in location:
                    logger.info("SoFurry session expired (redirected to login)")
                    self._logged_in = False
                    return False
            # 200 with gallery content = still logged in
            return resp.status_code == 200
        except Exception as e:
            logger.debug("SoFurry session check failed: %s", e)
            return False

    async def ensure_logged_in(self) -> bool:
        """Re-use existing session if valid, otherwise log in fresh.

        Returns True if we end up authenticated, False on failure.
        Handles restored cookies: if cookies exist in the jar but
        _logged_in is False, temporarily enables the flag so
        check_session() can test the restored cookies.
        """
        # If cookies were restored but _logged_in is False, try them
        if not self._logged_in and self._http.cookies:
            self._logged_in = True  # Temporarily enable so check_session() proceeds
            if await self.check_session():
                logger.info("SoFurry restored session is valid -- skipping login")
                return True
            self._logged_in = False  # Restored cookies were invalid
        elif await self.check_session():
            logger.info("SoFurry session still valid — skipping login")
            return True
        # Session expired or never established — do a full login
        self._logged_in = False
        return await self.login()

    def update_credentials(self, username: str, password: str,
                           display_name: str, totp_code: str = "") -> bool:
        """Update stored credentials.  Returns True if they changed."""
        changed = (self.username != username or self.password != password
                   or self.display_name != display_name)
        self.username = username
        self.password = password
        self.display_name = display_name
        self.totp_code = totp_code
        if changed:
            self._logged_in = False  # Force re-login on next poll
        return changed

    def export_cookies(self) -> dict | None:
        """Serialize the httpx cookie jar for persistence across restarts.

        Returns a dict suitable for JSON storage in settings.json, or None
        if the cookie jar is empty (no session to save).
        """
        from datetime import datetime, timezone
        jar = self._http.cookies
        if not jar:
            return None
        cookies = {}
        for cookie in jar.jar:
            cookies[cookie.name] = {
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
            }
        if not cookies:
            return None
        return {
            "cookies": cookies,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "saved_for_user": self.username,
        }

    def import_cookies(self, data: dict) -> bool:
        """Restore cookies from a previously exported dict.

        Validates structure and checks that ``saved_for_user`` matches
        the current username (stale cookies from a different account are
        rejected).  Returns True if cookies were successfully restored.
        """
        if not isinstance(data, dict):
            return False
        if data.get("saved_for_user") != self.username:
            logger.info("Saved SF cookies are for %s, current user is %s -- ignoring",
                        data.get("saved_for_user"), self.username)
            return False
        cookies = data.get("cookies")
        if not isinstance(cookies, dict) or not cookies:
            return False
        try:
            for name, info in cookies.items():
                if not isinstance(info, dict) or "value" not in info:
                    continue
                self._http.cookies.set(
                    name,
                    info["value"],
                    domain=info.get("domain", ".sofurry.com"),
                    path=info.get("path", "/"),
                )
            logger.info("Restored %d SF session cookies from settings", len(cookies))
            return True
        except Exception as e:
            logger.warning("Failed to restore SF cookies: %s", e)
            return False

    async def validate_session(self) -> str | None:
        """Login and verify the display name works.

        Returns the display name on success, None on failure.
        """
        if not await self.ensure_logged_in():
            return None

        try:
            if self.display_name:
                resp = await self._http.get(f"{SOFURRY_BASE}/u/{self.display_name}")
                if resp.status_code == 200 and "/gallery" in resp.text:
                    return self.display_name

            # Try to discover display name from window.handle in gallery JS
            resp = await self._http.get(f"{SOFURRY_BASE}/u/{self.display_name}/gallery")
            handle_match = re.search(r'window\.handle\s*=\s*"([^"]+)"', resp.text)
            if handle_match:
                self.display_name = handle_match.group(1)
                return self.display_name

            logger.warning("Could not verify SF display name")
            return None
        except Exception as e:
            logger.warning("SoFurry session validation failed: %s", e)
            return None

    # -- Gallery Listing -----------------------------------------------

    async def get_all_gallery_ids(self) -> list[dict]:
        """Scrape all gallery submissions from the server-rendered gallery HTML.

        SoFurry's gallery pages are server-side rendered.  Each submission
        appears as a ``<div class="submission ..." id="{sid}">`` block with
        an ``<a href="/s/{sid}?ref=glr">`` link and a ``<div class="title">``
        inside it.  We extract IDs and titles directly from the HTML.

        When using the CF Worker proxy, the first page is fetched via
        ``login_and_fetch_gallery`` which does GET /login → POST /login →
        GET gallery all in one Worker invocation (same egress IP).  This
        is required because SoFurry pins sessions to IPs.
        """
        transport = self._http._transport
        uses_proxy = hasattr(transport, 'login_and_fetch')

        # Why proxy mode always does a fresh login rather than reusing sessions:
        # CF Workers rotate egress IPs between invocations, and SoFurry pins
        # sessions to the IP that performed login.  A session cookie obtained
        # in one Worker invocation becomes invalid in the next (different IP),
        # so session caching is useless through the proxy — we must re-login
        # every poll cycle.
        proxy_gallery_html: str | None = None
        if uses_proxy:
            proxy_gallery_html = await self.login_and_fetch_gallery()
            if not proxy_gallery_html:
                logger.warning("SF: login_and_fetch_gallery failed")
                return []
        elif not self._logged_in:
            await self.login()

        all_subs: list[dict] = []
        seen: set[str] = set()
        page = 1

        for _page_safety in range(100):
            try:
                # Use proxy gallery HTML for page 1 if available
                if page == 1 and proxy_gallery_html:
                    html = proxy_gallery_html
                    logger.info("SF gallery: using login_and_fetch HTML (%d chars)", len(html))
                else:
                    resp = await self._http.get(
                        f"{SOFURRY_BASE}/u/{self.display_name}/gallery",
                        params={"page": str(page)} if page > 1 else {},
                    )
                    resp.raise_for_status()
                    html = resp.text

                # Extract submission IDs from href="/s/{id}?ref=glr" links
                ids_on_page = re.findall(
                    r'href="(?:https://sofurry\.com)?/s/([A-Za-z0-9]+)\?ref=glr"',
                    html,
                )

                if not ids_on_page:
                    # Broader fallback: any /s/{id} link
                    ids_on_page = re.findall(
                        r'href="(?:https://sofurry\.com)?/s/([A-Za-z0-9]+)',
                        html,
                    )

                if not ids_on_page:
                    if page == 1:
                        # Check for authentication indicators
                        has_logout = 'logout' in html.lower()
                        has_username = self.display_name.lower() in html.lower()
                        has_login_link = 'href="/login"' in html or "href='/login'" in html
                        # Search for SFW/NSFW toggle
                        sfw_match = re.search(r'(?i)(sfw|nsfw)[^<]{0,100}', html)
                        sfw_context = sfw_match.group(0)[:80] if sfw_match else "not found"

                        logger.warning(
                            "SF gallery page has no /s/ links (%d chars). "
                            "Auth indicators: logout=%s, username=%s, login_link=%s, sfw_context=%s",
                            len(html), has_logout, has_username, has_login_link, sfw_context,
                        )
                        # Log more of the page — look for nav bar / header area
                        logger.warning("SF gallery first 1500 chars: %s", html[:1500])
                    break

                # Build a map of ID → title from the HTML.
                # Each submission block: <div ... id={sid}> ... <div class="title">Title</div>
                title_map: dict[str, str] = {}
                for match in re.finditer(
                    r'id=([A-Za-z0-9]+)>.*?<div\s+class="title">([^<]+)</div>',
                    html,
                    re.DOTALL,
                ):
                    title_map[match.group(1)] = match.group(2).strip()

                new_this_page = 0
                for sid in ids_on_page:
                    if sid not in seen:
                        seen.add(sid)
                        all_subs.append({
                            "submission_id": sid,
                            "title": title_map.get(sid, ""),
                            "thumbnail_url": "",
                        })
                        new_this_page += 1

                if new_this_page == 0:
                    break

                # Check for next page link
                has_next = re.search(
                    rf'/gallery\?page={page + 1}',
                    html,
                )
                if not has_next:
                    break

                page += 1
                await asyncio.sleep(config.SF_REQUEST_DELAY_SECONDS)

            except Exception as e:
                logger.warning("Failed to fetch SF gallery page %d: %s", page, e)
                break

        logger.info("SF: Found %d submissions from gallery HTML", len(all_subs))
        return all_subs

    # -- Submission Detail ---------------------------------------------

    async def get_submission_detail(self, submission_id: str) -> dict:
        """Fetch submission details using both the JSON API and web page.

        Uses /ui/submission/{id} for metadata (title, author, rating,
        publishedAt, thumbnail, description) and /s/{id} web page for
        stats (views, likes, comments) which aren't in the API response.
        """
        detail = {
            "submission_id": submission_id,
            "title": "",
            "username": self.display_name,
            "posted_at": "",
            "content_type": "",
            "rating": "",
            "thumbnail_url": "",
            "description": "",
            "keywords": [],
            "link": f"{SOFURRY_BASE}/s/{submission_id}",
            "views": 0,
            "favorites_count": 0,
            "comments_count": 0,
        }

        # Step 1: Get metadata from JSON API
        try:
            resp = await self._http.get(
                f"{SOFURRY_BASE}/ui/submission/{submission_id}",
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                detail["title"] = data.get("title", "")
                detail["username"] = data.get("author", self.display_name)
                detail["description"] = data.get("description", "")
                detail["thumbnail_url"] = data.get("thumbUrl", "") or data.get("coverUrl", "")
                detail["rating"] = _RATING_MAP.get(data.get("rating", 0), "Clean")
                detail["posted_at"] = data.get("publishedAt", "")
                detail["keywords"] = data.get("artistTags", []) or []
                # Content type based on category
                cat = data.get("category", 0)
                if cat == 20:
                    detail["content_type"] = "story"
                elif cat == 30:
                    detail["content_type"] = "art"
                elif cat == 40:
                    detail["content_type"] = "music"
                elif cat == 50:
                    detail["content_type"] = "photo"
        except Exception as e:
            logger.debug("Failed to fetch SF API metadata for %s: %s", submission_id, e)

        # Step 2: Get stats from the web page
        try:
            await asyncio.sleep(0.5)  # Small delay between API and web requests
            resp = await self._http.get(f"{SOFURRY_BASE}/s/{submission_id}")
            if resp.status_code == 200:
                html = resp.text
                # Extract title from page if not from API
                if not detail["title"]:
                    title_match = re.search(r'<title>([^<]+)</title>', html)
                    if title_match:
                        title = title_match.group(1).strip()
                        detail["title"] = re.sub(r'\s*[-|]\s*SoFurry.*$', '', title).strip()
                        # Also strip "by Author" suffix
                        detail["title"] = re.sub(r'\s+by\s+\S+$', '', detail["title"]).strip()

                # Views: "X Views" or "X views"
                views_match = re.search(r'(\d[\d,]*)\s*[Vv]iews?\b', html)
                if views_match:
                    detail["views"] = _safe_int(views_match.group(1))

                # Likes/Favorites: "X Likes"
                likes_match = re.search(r'(\d[\d,]*)\s*[Ll]ikes?\b', html)
                if likes_match:
                    detail["favorites_count"] = _safe_int(likes_match.group(1))

                # Comments: "X Comments"
                comments_match = re.search(r'(\d[\d,]*)\s*[Cc]omments?\b', html)
                if comments_match:
                    detail["comments_count"] = _safe_int(comments_match.group(1))

                # Thumbnail fallback: og:image
                if not detail["thumbnail_url"]:
                    og_match = re.search(
                        r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html
                    )
                    if og_match:
                        detail["thumbnail_url"] = og_match.group(1)
        except Exception as e:
            logger.debug("Failed to fetch SF web page for %s: %s", submission_id, e)

        return detail

    async def get_submission_details_batch(self, submission_ids: list[str]) -> list[dict]:
        """Fetch details for multiple submissions sequentially with rate limiting."""
        details: list[dict] = []
        for i, sid in enumerate(submission_ids):
            try:
                detail = await self.get_submission_detail(sid)
                details.append(detail)
            except Exception as e:
                logger.warning("Failed to fetch SF submission %s: %s", sid, e)
            if i < len(submission_ids) - 1:
                await asyncio.sleep(config.SF_REQUEST_DELAY_SECONDS)
        return details

    # -- Followers/Watchers --------------------------------------------

    async def get_follower_count(self) -> int:
        """Scrape the follower count from the user's profile page."""
        try:
            resp = await self._http.get(f"{SOFURRY_BASE}/u/{self.display_name}")
            resp.raise_for_status()
            match = re.search(r'(\d[\d,]*)\s*Followers?\b', resp.text, re.IGNORECASE)
            if match:
                return _safe_int(match.group(1))
        except Exception as e:
            logger.warning("Failed to get SF follower count: %s", e)
        return 0

    async def scrape_followers(self) -> list[str]:
        """Scrape the follower list from /u/{display_name}/followers.

        The followers page is public (no login required) and renders each
        follower as:
            <a href="https://sofurry.com/u/Username">
                <h5>Display Name</h5>
                <h6>@username</h6>
            </a>

        Returns a list of follower usernames.
        """
        all_followers: list[str] = []
        seen: set[str] = set()
        page = 1

        for _page_safety in range(1000):
            try:
                resp = await self._http.get(
                    f"{SOFURRY_BASE}/u/{self.display_name}/followers",
                    params={"page": str(page)} if page > 1 else {},
                )
                resp.raise_for_status()
                html = resp.text

                # Extract usernames from user-card follower entries.
                # Each follower is rendered as:
                #   <div class="... user-card ...">
                #     <a href="https://sofurry.com/u/Username" class="card ...">
                # We match the href inside user-card blocks to avoid picking up
                # navigation or header links.
                usernames = re.findall(
                    r'user-card[^>]*>\s*<a\s+href="(?:https://sofurry\.com)?/u/([A-Za-z0-9_\-]+)"',
                    html,
                )

                page_new = []
                for u in usernames:
                    if u not in seen:
                        seen.add(u)
                        page_new.append(u)

                if not page_new:
                    if page == 1:
                        logger.info("No SF followers found for %s", self.display_name)
                    break

                all_followers.extend(page_new)
                logger.info("Scraped SF follower page %d — found %d users", page, len(page_new))

                # Check for pagination — look for a next page link
                has_next = re.search(
                    rf'followers\?page={page + 1}',
                    html,
                )
                if not has_next:
                    break

                page += 1
                await asyncio.sleep(config.SF_REQUEST_DELAY_SECONDS)

            except Exception as e:
                logger.warning("Error scraping SF follower page %d: %s", page, e)
                break

        logger.info("Total SF followers scraped: %d", len(all_followers))
        return all_followers


def _safe_int(val: Any) -> int:
    """Safely convert a value to int, handling None, comma-formatted strings, etc."""
    if val is None:
        return 0
    try:
        if isinstance(val, str):
            val = val.replace(",", "").strip()
        return int(val)
    except (ValueError, TypeError):
        return 0
