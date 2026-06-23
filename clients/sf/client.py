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
import json
import logging
import os
import re
from typing import Any

import httpx

import config

logger = logging.getLogger(__name__)

SOFURRY_BASE = "https://sofurry.com"
SOFURRY_API = f"{SOFURRY_BASE}/api"

# SoFurry rating codes (from the submission JSON)
_RATING_MAP = {10: "Clean", 20: "Adult"}
_RATING_REVERSE = {"clean": 0, "mature": 10, "adult": 20}

# SoFurry "beta" write-encoding: the create/editor API wants INT category/type
# codes, while the read API (/api/submission/{id}) echoes display strings. These
# map the read strings back to the int codes for round-tripping on edit.
# (PawPoller only ever posts Writing; the rest are here for completeness.)
_SF_CATEGORY_STR_TO_INT = {
    "writing": 20, "artwork": 10, "photography": 30,
    "music": 40, "video": 50, "3d": 60, "game": 70,
}
_SF_TYPE_STR_TO_INT = {
    "shortstory": 21, "book": 29, "drawing": 11, "comic": 12,
    "animation": 13, "photograph": 31, "track": 42, "album": 49,
}


def _normalize_rating(val) -> int:
    """Convert a rating value (int, str, or label) to SF's numeric code."""
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        return _RATING_REVERSE.get(val.lower().strip(), 0)
    return 0


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
        """Best-effort discovery of gallery submission IDs on the SoFurry beta.

        The 2026-06 "SoFurry beta" rewrite replaced the server-rendered gallery
        (``<div id={sid}>`` blocks + ``/s/{sid}?ref=glr`` links) with a React
        Router SPA whose gallery loader data lives at
        ``/u/{handle}/gallery.data`` (a turbo-stream payload). Crucially, an
        UNAUTHENTICATED request to that endpoint is SFW-filtered, so a user
        whose works are Adult sees NO submissions — auto-discovery of new works
        therefore needs a working authenticated session, which the CF-Worker
        login path no longer provides on the new site.

        The poll cycle does not depend on this: per-submission stats are now
        fetched login-free from ``/s/{id}.data`` (see get_submission_detail),
        and the poller polls the submission IDs it already knows from the DB.
        This method returns whatever the gallery loader exposes (work IDs that
        appear immediately before a ``"title"`` key in the turbo-stream) so that
        once an authenticated session is restored, discovery resumes with no
        further changes. Returns [] when nothing is visible.
        """
        try:
            resp = await self._http.get(
                f"{SOFURRY_BASE}/u/{self.display_name}/gallery.data",
                headers={"Accept": "*/*"},
            )
            if resp.status_code != 200:
                logger.warning("SF: gallery.data returned HTTP %d", resp.status_code)
                return []
            # In the turbo-stream serialisation each work appears as
            # ``"<id>","title","<Title>"``; the profile's own id is followed by
            # "handle", not "title", so this pattern won't pick it up.
            # Submission ids appear two ways in the turbo-stream depending on
            # serialisation: `"<id>","title"` (recommended/inline works) and
            # `"id","<id>","name"` (gallery list items). NOTE: React-Router
            # turbo-stream de-duplicates repeated strings, so a long gallery may
            # only surface a subset here — the poller also always polls DB-known
            # ids, and works posted via PawPoller are recorded at post time, so
            # discovery is a best-effort top-up, not the source of truth.
            ids = list(dict.fromkeys(
                re.findall(r'"([A-Za-z0-9]{8})","title"', resp.text)
                + re.findall(r'"id","([A-Za-z0-9]{8})","name"', resp.text)
            ))
            if not ids:
                logger.warning(
                    "SF: gallery.data exposed no submissions for %s — the beta "
                    "hides adult galleries from unauthenticated requests, so "
                    "new-work discovery needs a rebuilt authenticated session. "
                    "Known works are still polled login-free from /s/{id}.data.",
                    self.display_name,
                )
            else:
                logger.info("SF: discovered %d submissions from gallery.data", len(ids))
            return [{"submission_id": sid, "title": "", "thumbnail_url": ""} for sid in ids]
        except Exception as e:
            logger.warning("SF: gallery.data discovery failed: %s", e)
            return []

    # -- Submission Detail ---------------------------------------------

    async def get_submission_detail(self, submission_id: str) -> dict:
        """Fetch submission stats from the SoFurry beta (React Router) site.

        The 2026-06 "SoFurry beta" rewrite retired the server-rendered pages and
        the old ``/ui/submission/{id}`` JSON API (now 404). The per-submission
        loader data is exposed at ``/s/{id}.data`` as a turbo-stream payload that
        carries title/views/likes/comments inline — and it is served WITHOUT
        login for published works, so polling no longer needs an authenticated
        session. We parse the stats out of that payload.

        On any fetch/parse failure the stat fields stay 0; the poller's
        zero-view guard then skips the work for the cycle rather than persisting
        a bogus 0 snapshot (which would corrupt the baseline — see the AO3/SqW/FA
        zero-snapshot fix).
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

        try:
            resp = await self._http.get(
                f"{SOFURRY_BASE}/s/{submission_id}.data",
                headers={"Accept": "*/*"},
            )
            if resp.status_code != 200:
                logger.warning("SF: /s/%s.data returned HTTP %d", submission_id, resp.status_code)
                return detail
            text = resp.text
            detail["title"] = _rr_str(text, "title")
            detail["description"] = _rr_str(text, "description")
            detail["posted_at"] = _rr_str(text, "publishedAt")
            detail["content_type"] = _rr_str(text, "category")
            detail["views"] = _rr_int(text, "views")
            detail["favorites_count"] = _rr_int(text, "likes")
            # commentsMeta carries the real comment count:
            #   ...,"perPage",20,"total",N,"hasMore",false,...
            cm = re.search(r'"total",(\d+),"hasMore"', text)
            if cm:
                detail["comments_count"] = int(cm.group(1))
        except Exception as e:
            logger.warning("Failed to fetch SF submission %s via .data: %s", submission_id, e)

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
        """Follower count from the beta profile API (login-free).

        ``GET /api/profile?handle={handle}`` → ``user.followerCount``. The old
        ``/u/{handle}`` HTML scrape is dead (the profile is an SPA now). Returns
        0 on failure.
        """
        try:
            resp = await self._http.get(
                f"{SOFURRY_API}/profile",
                params={"handle": self.display_name},
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 200:
                user = (resp.json() or {}).get("user", {})
                return _safe_int(user.get("followerCount"))
            logger.warning("SF: /api/profile returned HTTP %d for follower count", resp.status_code)
        except Exception as e:
            logger.warning("Failed to get SF follower count: %s", e)
        return 0

    async def scrape_followers(self) -> list[str]:
        """Follower usernames via the beta API (login-free).

        ``GET /api/followers?handle={handle}&mode=followers&page={0-based}`` →
        ``{"users":[{"handle","username","avatarUrl","headline","followerCount"}],
        "page","hasNextPage"}`` (20 per page). Pages through ``hasNextPage`` and
        collects handles. Returns [] on failure — the poller's prune is guarded on
        a non-empty result, so an empty/failed fetch never wipes the watcher list.
        """
        followers: list[str] = []
        seen: set[str] = set()
        page = 0

        for _page_safety in range(500):  # hard cap: 500 pages * 20 = 10k followers
            try:
                resp = await self._http.get(
                    f"{SOFURRY_API}/followers",
                    params={"handle": self.display_name, "mode": "followers", "page": str(page)},
                    headers={"Accept": "application/json"},
                )
                if resp.status_code != 200:
                    logger.warning("SF: /api/followers page %d returned HTTP %d", page, resp.status_code)
                    break
                data = resp.json() or {}
            except Exception as e:
                logger.warning("SF: follower fetch failed on page %d: %s", page, e)
                break

            users = data.get("users") or []
            for u in users:
                handle = u.get("handle") or u.get("username")
                if handle and handle not in seen:
                    seen.add(handle)
                    followers.append(handle)

            if not data.get("hasNextPage") or not users:
                break
            page += 1
            await asyncio.sleep(config.SF_REQUEST_DELAY_SECONDS)

        logger.info("SF: scraped %d followers via /api/followers", len(followers))
        return followers


    # ── Posting / Upload ────────────────────────────────────────

    async def _get_csrf_meta(self) -> str | None:
        """Extract the CSRF token from <meta name="csrf-token"> on a page.

        Post-auth-bridge, the homepage is a Remix page whose meta tag carries the
        token the beta /api/* write endpoints require in an X-CSRF-Token header.
        """
        try:
            resp = await self._http.get(f"{SOFURRY_BASE}/")
            match = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', resp.text)
            if match:
                return match.group(1)
            # Fallback: try the _token hidden input pattern
            match = re.search(r'name="_token"\s*value="([^"]+)"', resp.text)
            if match:
                return match.group(1)
        except Exception as e:
            logger.warning("SF: CSRF token extraction failed: %s", e)
        return None

    def _api_headers(self, csrf: str) -> dict:
        """Standard headers for an authed write to the beta /api/* endpoints."""
        return {
            "X-CSRF-Token": csrf,
            "Accept": "application/json",
            "Origin": SOFURRY_BASE,
            "Referer": f"{SOFURRY_BASE}/",
        }

    async def _api_authed(self) -> bool:
        """Cheap check: does the current Remix session authorise /api/* writes?"""
        try:
            r = await self._http.get(
                f"{SOFURRY_API}/upload-quota", headers={"Accept": "application/json"}
            )
            return r.status_code == 200
        except Exception:
            return False

    async def _bridge_session(self) -> None:
        """Exchange the authed Laravel session for an authed Remix session.

        SoFurry's "beta" is a hybrid: Laravel still serves /login, but the new
        /api/* endpoints are React-Router (Remix) and authenticate via a separate
        Remix session cookie. GET /fe/auth/sofurry runs an OAuth2-PKCE flow that
        auto-approves off the live Laravel session (→ /oauth/authorize →
        /fe/auth/callback) and sets an authenticated Remix `_session`. Idempotent;
        re-running it refreshes the Remix session.
        """
        try:
            await self._http.get(f"{SOFURRY_BASE}/fe/auth/sofurry")
        except Exception as e:
            logger.warning("SF: auth bridge (/fe/auth/sofurry) failed: %s", e)

    async def _ensure_api_session(self) -> str:
        """Ensure an authenticated Remix /api session, returning the CSRF token.

        Laravel login (or restored cookies) → OAuth bridge → verify the API is
        actually authed (a restored session can pass check_session but still be
        stale for /api/*), retrying with a fresh login once if needed.
        """
        if not await self.ensure_logged_in():
            raise RuntimeError("SoFurry: Not logged in")
        await self._bridge_session()
        if not await self._api_authed():
            logger.info("SF: API not authed after bridge — forcing a fresh login")
            self._logged_in = False
            if not await self.login():
                raise RuntimeError("SoFurry: login failed")
            await self._bridge_session()
            if not await self._api_authed():
                raise RuntimeError(
                    "SoFurry: API session not authenticated after login + bridge"
                )
        csrf = await self._get_csrf_meta()
        if not csrf:
            raise RuntimeError("SoFurry: could not obtain CSRF token")
        return csrf

    async def _editor_dispatch(
        self, endpoint: str, csrf: str, *,
        method: str | None = None,
        fields: list[tuple[str, str]] | None = None,
    ) -> dict:
        """Low-level POST to /api/submission-editor (the beta's generic write hub).

        The editor tunnels every submission/content write through one endpoint:
        `_endpoint` selects the target (e.g. ``submission/{id}``,
        ``submission/{id}/content/{cid}``, ``upload/{id}/content/{cid}``) and the
        optional ``_method`` overrides the verb (PUT/DELETE). Sent as multipart so
        repeated keys (e.g. ``artistTags[]``) work like the browser's FormData.
        """
        parts: list[tuple[str, str]] = [("_endpoint", endpoint)]
        if method:
            parts.append(("_method", method))
        parts.extend(fields or [])
        files = [(k, (None, v)) for k, v in parts]
        resp = await self._http.post(
            f"{SOFURRY_API}/submission-editor",
            headers=self._api_headers(csrf), files=files, timeout=30.0,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"SF: submission-editor ({endpoint}) failed — "
                f"status {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except Exception:
            return {}

    async def _submission_editor(
        self, submission_id: str, csrf: str, *,
        title: str, description: str, tags: list[str] | None,
        category: int, sub_type: int, rating: int, privacy: int,
        allow_comments: bool = True, allow_downloads: bool = True,
        is_wip: bool = False, optimize: bool = True,
        pixel_perfect: bool = False, is_advert: bool = False,
        content_order: list[str] | None = None,
    ) -> dict:
        """Set a submission's metadata (title/desc/tags/rating/privacy/flags).

        Tags go as repeated ``artistTags[]`` (underscores → spaces); category/type
        are INT codes; ``content_order`` (a list of contentIds) sets chapter order.
        """
        b = lambda v: "true" if v else "false"
        fields = [
            ("title", title or ""),
            ("description", description or ""),
            ("category", str(category)),
            ("type", str(sub_type)),
            ("rating", str(rating)),
            ("privacy", str(privacy)),
            ("allowComments", b(allow_comments)),
            ("allowDownloads", b(allow_downloads)),
            ("isWip", b(is_wip)),
            ("optimize", b(optimize)),
            ("pixelPerfect", b(pixel_perfect)),
            ("isAdvert", b(is_advert)),
        ]
        for t in (tags or []):
            fields.append(("artistTags[]", t.replace("_", " ")))
        for cid in (content_order or []):
            fields.append(("contentOrder[]", str(cid)))
        return await self._editor_dispatch(
            f"submission/{submission_id}", csrf, method="POST", fields=fields,
        )

    async def set_content_title(self, submission_id: str, content_id: str,
                                title: str, csrf: str | None = None) -> None:
        """Set the chapter title on one content item of a submission."""
        if csrf is None:
            csrf = await self._ensure_api_session()
        await self._editor_dispatch(
            f"submission/{submission_id}/content/{content_id}", csrf,
            fields=[("title", title or "")],
        )

    async def delete_content(self, submission_id: str, content_id: str,
                             csrf: str | None = None) -> None:
        """Delete one content item (chapter) from a submission."""
        if csrf is None:
            csrf = await self._ensure_api_session()
        await self._editor_dispatch(
            f"upload/{submission_id}/content/{content_id}", csrf, method="DELETE",
        )

    async def get_content_ids(self, submission_id: str) -> list[str]:
        """Return the submission's content item ids, in their stored order."""
        resp = await self._http.get(
            f"{SOFURRY_API}/submission/{submission_id}",
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            return []
        try:
            sub = (resp.json() or {}).get("submission", {})
        except Exception:
            return []
        out = []
        for item in (sub.get("content") or []):
            cid = item.get("contentId") or item.get("id")
            if cid:
                out.append(str(cid))
        return out

    async def upload_content(self, submission_id: str, file_path: str,
                             csrf: str | None = None) -> str | None:
        """Upload a content file (a chapter) to an existing submission.

        Adds another item to the submission's `content[]` array. Returns the new
        contentId. The file must be ≥ 1 KB (SoFurry enforces a 1 KB floor).
        """
        if csrf is None:
            csrf = await self._ensure_api_session()
        with open(file_path, "rb") as f:
            file_data = f.read()
        filename = os.path.basename(file_path)
        resp = await self._http.post(
            f"{SOFURRY_API}/upload-content",
            headers=self._api_headers(csrf),
            data={"submissionId": str(submission_id)},
            files={"file": (filename, file_data, "text/html")},
            timeout=120.0,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"SF: upload-content failed — status {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return (resp.json() or {}).get("contentId")
        except Exception:
            return None

    async def delete_submission(self, submission_id: str,
                                csrf: str | None = None) -> bool:
        """Delete a submission via DELETE /api/submission/{id}."""
        if csrf is None:
            csrf = await self._ensure_api_session()
        resp = await self._http.request(
            "DELETE", f"{SOFURRY_API}/submission/{submission_id}",
            headers=self._api_headers(csrf), timeout=30.0,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"SF: delete failed — status {resp.status_code}: {resp.text[:200]}"
            )
        return True

    async def set_thumbnail(self, submission_id: str, image_path: str,
                            csrf: str | None = None) -> bool:
        """Upload a custom thumbnail (png/jpeg/webp) for a submission.

        Goes through the submission-editor dispatcher with
        ``_endpoint=submission/{id}/thumbnail`` + a multipart ``file`` part, the
        same call the beta editor makes. (Regenerate = the same endpoint with
        ``_method=DELETE``, which drops the custom thumbnail so SF re-derives one.)
        """
        if csrf is None:
            csrf = await self._ensure_api_session()
        with open(image_path, "rb") as f:
            data = f.read()
        name = os.path.basename(image_path)
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "webp": "image/webp"}.get(ext, "image/png")
        files = [
            ("_endpoint", (None, f"submission/{submission_id}/thumbnail")),
            ("file", (name, data, mime)),
        ]
        resp = await self._http.post(
            f"{SOFURRY_API}/submission-editor",
            headers=self._api_headers(csrf), files=files, timeout=60.0,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"SF: thumbnail upload failed — status {resp.status_code}: {resp.text[:200]}"
            )
        return True

    async def create_submission(
        self,
        file_path: str,
        *,
        title: str = "",
        description: str = "",
        tags: list[str] | None = None,
        category: int = 20,
        sub_type: int = 21,
        rating: int = 20,
        privacy: int = 3,
        thumbnail_path: str | None = None,
    ) -> dict:
        """Create and publish a new SoFurry submission (beta /api flow).

        Three steps against the React-Router API:
          1. POST /api/upload-create        → mint an empty submission, get its id
          2. POST /api/upload-content       → upload the story HTML file (>= 1 KB)
          3. POST /api/submission-editor    → set metadata + publish

        Args:
            file_path: Path to the HTML file to upload (>= 1 KB).
            title: Submission title.
            description: Plaintext description.
            tags: List of tags (underscores replaced with spaces).
            category: int code — 10=artwork, 20=writing, 30=photography, 40=music.
            sub_type: int code — 21=short story, 29=book, 11=drawing, etc.
            rating: 0=Clean, 10=Mature, 20=Adult.
            privacy: 1=Private, 2=Unlisted, 3=Public.

        Returns:
            Dict with 'submission_id' and 'url'.
        """
        csrf = await self._ensure_api_session()

        # 1. Mint an empty submission (no body, like the browser).
        resp = await self._http.post(
            f"{SOFURRY_API}/upload-create", headers=self._api_headers(csrf), timeout=30.0,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"SF: upload-create failed — status {resp.status_code}: {resp.text[:200]}"
            )
        submission_id = (resp.json() or {}).get("id")
        if not submission_id:
            raise RuntimeError(f"SF: upload-create response missing id: {resp.text[:200]}")
        logger.info("SF: created submission %s", submission_id)

        # 2. Upload the story HTML as the first content item.
        await self.upload_content(submission_id, file_path, csrf=csrf)
        logger.info("SF: uploaded content to submission %s", submission_id)

        # 3. Set metadata + publish.
        await self._submission_editor(
            submission_id, csrf,
            title=title, description=description, tags=tags,
            category=category, sub_type=sub_type, rating=rating, privacy=privacy,
        )

        if thumbnail_path and os.path.isfile(thumbnail_path):
            try:
                await self.set_thumbnail(submission_id, thumbnail_path, csrf=csrf)
                logger.info("SF: uploaded custom thumbnail for %s", submission_id)
            except Exception as thumb_err:
                # Non-fatal: text works auto-generate a thumbnail anyway.
                logger.warning("SF: thumbnail upload failed for %s: %s", submission_id, thumb_err)

        url = f"{SOFURRY_BASE}/s/{submission_id}"
        logger.info("SF: published submission %s — %s", submission_id, url)
        return {"submission_id": str(submission_id), "url": url}

    async def edit_submission(
        self,
        submission_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        rating: int | None = None,
        privacy: int | None = None,
    ) -> dict:
        """Edit metadata on an existing SoFurry submission (beta /api flow).

        Reads current state from GET /api/submission/{id} (the read API echoes
        category/type as display STRINGS), overlays the caller's changes, and
        POSTs the complete metadata back via /api/submission-editor (which wants
        INT category/type codes — mapped here). Every unspecified field mirrors
        the server's current value so an edit never clobbers state.

        Privacy preservation: privacy defaults to the server's reported value,
        keeping the old invariant that an edit must never silently downgrade a
        public work to Private.
        """
        csrf = await self._ensure_api_session()

        raw_resp = await self._http.get(
            f"{SOFURRY_API}/submission/{submission_id}",
            headers={"Accept": "application/json"},
        )
        if raw_resp.status_code != 200:
            raise RuntimeError(
                f"SF: could not fetch current submission {submission_id} for edit "
                f"(status {raw_resp.status_code})"
            )
        try:
            current = (raw_resp.json() or {}).get("submission", {})
        except Exception as e:
            raise RuntimeError(f"SF: edit fetch returned non-JSON: {e}")

        category = _SF_CATEGORY_STR_TO_INT.get(
            str(current.get("category", "")).lower().replace(" ", ""), 20
        )
        sub_type = _SF_TYPE_STR_TO_INT.get(
            str(current.get("type", "")).lower().replace(" ", ""), 21
        )
        cur_privacy = _safe_int(current.get("privacy")) or 3

        await self._submission_editor(
            submission_id, csrf,
            title=title if title is not None else current.get("title", ""),
            description=description if description is not None else current.get("description", ""),
            tags=tags if tags is not None else current.get("tags"),
            category=category, sub_type=sub_type,
            rating=rating if rating is not None else _safe_int(current.get("rating")),
            privacy=privacy if privacy is not None else cur_privacy,
            allow_comments=bool(current.get("allowComments", True)),
            allow_downloads=bool(current.get("allowDownloads", True)),
            is_wip=bool(current.get("isWip", False)),
            pixel_perfect=bool(current.get("pixelPerfect", False)),
        )

        url = f"{SOFURRY_BASE}/s/{submission_id}"
        logger.info(
            "SF: edited submission %s — title=%r privacy=%s",
            submission_id,
            (title if title is not None else current.get("title", ""))[:40],
            privacy if privacy is not None else cur_privacy,
        )
        return {"submission_id": submission_id, "url": url}


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


# ── React Router turbo-stream helpers (SoFurry beta /…​.data payloads) ──
# React Router serialises loader data as a flat array where object entries are
# laid out as ``"key",value`` pairs, so the value we want sits immediately after
# its key name (e.g. ``"views",1485`` or ``"title","Hypnotic Claim"``). These
# pull a single scalar by key — robust enough for stats without a full decoder.

def _rr_int(text: str, key: str) -> int:
    """Pull an int value that immediately follows a turbo-stream key."""
    m = re.search(rf'"{re.escape(key)}",(\d+)', text)
    return int(m.group(1)) if m else 0


def _rr_str(text: str, key: str) -> str:
    """Pull a JSON string value that immediately follows a turbo-stream key."""
    m = re.search(rf'"{re.escape(key)}",("(?:[^"\\]|\\.)*")', text)
    if not m:
        return ""
    try:
        return json.loads(m.group(1))
    except Exception:
        return ""
