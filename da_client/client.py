"""DeviantArt (DA) HTTP client.

DeviantArt uses the Eclipse frontend which provides internal `_napi` JSON
endpoints. Authentication is via browser cookies. Data collection uses these
internal endpoints since there is no public gallery stats API.

Key details:
  - Deviation IDs are integers
  - Stats: views, favourites, comments, downloads
  - Auth: cookie-based (auth_token cookie from browser)
  - DA has aggressive rate limiting; respectful delays required
"""

from __future__ import annotations
import asyncio
import logging
import re
from html import unescape
from typing import Any

import httpx

import config

logger = logging.getLogger(__name__)

_BASE = "https://www.deviantart.com"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.deviantart.com/",
}


class DAClient:
    """Async HTTP client for DeviantArt using Eclipse _napi endpoints."""

    def __init__(self, cookie_value: str, target_user: str,
                 proxy_url: str = "", proxy_key: str = ""):
        self.cookie_value = cookie_value  # Full cookie string from browser
        self.target_user = target_user

        # Use Cloudflare Worker proxy if configured (bypasses datacenter IP blocks)
        if proxy_url and proxy_key:
            from polling.cf_proxy import CloudflareProxyTransport
            transport = CloudflareProxyTransport(proxy_url, proxy_key)
            logger.info("DA client using CF proxy: %s", proxy_url)
        else:
            transport = httpx.AsyncHTTPTransport(retries=2)

        self._http = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=_HEADERS,
            transport=transport,
        )
        self._update_cookies()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    def _update_cookies(self) -> None:
        """Parse and set cookies on the HTTP client."""
        # Cookie value is the raw cookie string from browser
        # Parse individual cookies from the string
        cookies = {}
        if self.cookie_value:
            for part in self.cookie_value.split(";"):
                part = part.strip()
                if "=" in part:
                    key, val = part.split("=", 1)
                    cookies[key.strip()] = val.strip()
        self._http.cookies.update(cookies)

    def update_credentials(self, cookie_value: str, target_user: str) -> None:
        self.cookie_value = cookie_value
        self.target_user = target_user
        self._update_cookies()

    async def close(self) -> None:
        await self._http.aclose()

    # ── Page/API Fetching ─────────────────────────────────────

    async def _get_json(self, url: str, params: dict | None = None) -> dict | None:
        """Fetch a JSON endpoint, handling errors gracefully."""
        try:
            resp = await self._http.get(url, params=params)
            if resp.status_code == 403:
                logger.error("DA: Access denied (403) for %s", url)
                return None
            if resp.status_code == 429:
                logger.warning("DA: Rate limited (429), waiting 30s...")
                await asyncio.sleep(30)
                resp = await self._http.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            logger.error("DA: Failed to fetch %s: %s", url, e)
            return None
        except Exception as e:
            logger.error("DA: JSON parse error for %s: %s", url, e)
            return None

    async def _get_page(self, url: str) -> str | None:
        """Fetch an HTML page."""
        try:
            resp = await self._http.get(url)
            if resp.status_code in (403, 429):
                if resp.status_code == 429:
                    await asyncio.sleep(30)
                    resp = await self._http.get(url)
                else:
                    return None
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as e:
            logger.error("DA: Failed to fetch %s: %s", url, e)
            return None

    # ── Authentication ────────────────────────────────────────

    async def validate_cookies(self) -> bool:
        """Test cookies by accessing the user's gallery page."""
        if not self.cookie_value or not self.target_user:
            return False
        try:
            html = await self._get_page(f"{_BASE}/{self.target_user}/gallery")
            if not html:
                return False
            # Check for authenticated-user indicators (present only when logged in)
            return "data-userid" in html or "deviantart.com/notifications" in html
        except Exception as e:
            logger.warning("DA: Cookie validation failed: %s", e)
            return False

    # ── Gallery Discovery ─────────────────────────────────────

    async def get_all_deviation_ids(self) -> list[dict]:
        """Fetch all deviation IDs for the target user using the _napi endpoint."""
        all_deviations: list[dict] = []
        offset = 0
        limit = 24
        seen_ids: set[int] = set()

        for _page_safety in range(1000):
            url = f"{_BASE}/_napi/da-user-profile/api/gallery/contents"
            params = {
                "username": self.target_user,
                "offset": str(offset),
                "limit": str(limit),
                "all_folder": "true",
                "mode": "newest",
            }

            logger.info("DA: Fetching gallery page offset=%d for %s", offset, self.target_user)
            data = await self._get_json(url, params=params)

            if not data:
                # Fallback: try scraping the gallery page HTML
                logger.info("DA: _napi failed, trying HTML scrape fallback")
                return await self._scrape_gallery_ids()

            results = data.get("results", [])
            if not results:
                break

            new_this_page = 0
            for item in results:
                deviation = item.get("deviation", item)
                dev_id = deviation.get("deviationId")
                if dev_id and dev_id not in seen_ids:
                    seen_ids.add(dev_id)
                    all_deviations.append({
                        "deviation_id": dev_id,
                        "title": deviation.get("title", ""),
                    })
                    new_this_page += 1

            if new_this_page == 0:
                break

            has_more = data.get("hasMore", False)
            next_offset = data.get("nextOffset")

            if not has_more:
                break

            offset = next_offset if next_offset is not None else offset + limit
            await asyncio.sleep(config.DA_REQUEST_DELAY_SECONDS)

        logger.info("DA: Found %d deviations for %s", len(all_deviations), self.target_user)
        return all_deviations

    async def _scrape_gallery_ids(self) -> list[dict]:
        """Fallback: scrape deviation IDs from gallery HTML pages."""
        all_deviations: list[dict] = []
        seen_ids: set[int] = set()
        page = 0

        for _page_safety in range(1000):
            url = f"{_BASE}/{self.target_user}/gallery?offset={page * 24}"
            html = await self._get_page(url)
            if not html:
                break

            # Find deviation links in gallery HTML
            matches = re.findall(
                r'data-deviationid="(\d+)"[^>]*>.*?class="[^"]*title[^"]*"[^>]*>([^<]*)<',
                html, re.DOTALL,
            )
            if not matches:
                # Alternative pattern
                matches = re.findall(
                    r'/art/[^"]*-(\d+)"[^>]*title="([^"]*)"',
                    html,
                )

            if not matches:
                break

            new_this_page = 0
            for dev_id_str, title in matches:
                dev_id = int(dev_id_str)
                if dev_id not in seen_ids:
                    seen_ids.add(dev_id)
                    all_deviations.append({
                        "deviation_id": dev_id,
                        "title": unescape(title.strip()),
                    })
                    new_this_page += 1

            if new_this_page == 0:
                break

            page += 1
            await asyncio.sleep(config.DA_REQUEST_DELAY_SECONDS)

        logger.info("DA: Scraped %d deviations for %s", len(all_deviations), self.target_user)
        return all_deviations

    # ── Deviation Details ─────────────────────────────────────

    async def get_deviation_detail(self, deviation_id: int) -> dict:
        """Fetch stats and metadata for a single deviation."""
        detail: dict = {"deviation_id": deviation_id}

        # Try the _napi extended fetch endpoint
        url = f"{_BASE}/_napi/shared_api/deviation/extended_fetch"
        params = {
            "deviationid": str(deviation_id),
            "username": self.target_user,
            "type": "art",
            "include_session": "false",
        }
        data = await self._get_json(url, params=params)

        if data and "deviation" in data:
            dev = data["deviation"]
            detail["title"] = dev.get("title", "")
            detail["username"] = dev.get("author", {}).get("username", self.target_user)
            detail["description"] = dev.get("textContent", {}).get("excerpt", "")

            # Category from media info
            detail["category"] = dev.get("categoryPath", "")
            detail["rating"] = "Mature" if dev.get("isMature") else "General"

            # Stats
            stats = dev.get("stats", {})
            detail["views"] = stats.get("views", 0)
            detail["favorites_count"] = stats.get("favourites", 0)
            detail["comments_count"] = stats.get("comments", 0)
            detail["downloads"] = stats.get("downloads", 0)

            # Tags/keywords
            tags = data.get("tags", [])
            detail["keywords"] = [t.get("name", "") for t in tags if isinstance(t, dict)]

            # URL and thumbnail
            detail["link"] = dev.get("url", f"{_BASE}/art/-{deviation_id}")
            media = dev.get("media", {})
            if media and "baseUri" in media:
                detail["thumbnail_url"] = media["baseUri"]
            else:
                detail["thumbnail_url"] = ""

            # Dates
            detail["posted_at"] = dev.get("publishedTime", "")

        else:
            # Fallback: scrape the deviation page HTML
            detail = await self._scrape_deviation_detail(deviation_id)

        return detail

    async def _scrape_deviation_detail(self, deviation_id: int) -> dict:
        """Fallback: scrape deviation details from the HTML page."""
        detail: dict = {"deviation_id": deviation_id}

        # Try to find the deviation URL
        url = f"{_BASE}/art/-{deviation_id}"
        html = await self._get_page(url)

        if not html:
            detail.update({
                "title": "", "username": self.target_user, "views": 0,
                "favorites_count": 0, "comments_count": 0, "downloads": 0,
                "keywords": [], "link": url, "description": "",
                "category": "", "rating": "", "thumbnail_url": "",
                "posted_at": "",
            })
            return detail

        # Title
        m = re.search(r'<title>([^<]+)</title>', html)
        if m:
            title = m.group(1).split(" by ")[0].strip()
            detail["title"] = unescape(title)
        else:
            detail["title"] = ""

        detail["username"] = self.target_user
        detail["link"] = url
        detail["description"] = ""
        detail["category"] = ""
        detail["rating"] = ""
        detail["thumbnail_url"] = ""
        detail["posted_at"] = ""
        detail["keywords"] = []

        # Try to extract stats from page JSON data
        stats_match = re.search(r'"stats"\s*:\s*\{([^}]+)\}', html)
        if stats_match:
            stats_text = stats_match.group(1)
            detail["views"] = _extract_stat_int(stats_text, "views")
            detail["favorites_count"] = _extract_stat_int(stats_text, "favourites")
            detail["comments_count"] = _extract_stat_int(stats_text, "comments")
            detail["downloads"] = _extract_stat_int(stats_text, "downloads")
        else:
            detail["views"] = 0
            detail["favorites_count"] = 0
            detail["comments_count"] = 0
            detail["downloads"] = 0

        return detail

    async def get_deviation_details_batch(self, deviation_ids: list[int]) -> list[dict]:
        """Fetch details for multiple deviations sequentially with rate limiting."""
        details = []
        for i, dev_id in enumerate(deviation_ids):
            if i > 0:
                await asyncio.sleep(config.DA_REQUEST_DELAY_SECONDS)
            detail = await self.get_deviation_detail(dev_id)
            details.append(detail)
        return details


def _extract_stat_int(text: str, key: str) -> int:
    """Extract an integer stat value from a JSON-like string."""
    m = re.search(rf'"{key}"\s*:\s*(\d+)', text)
    return int(m.group(1)) if m else 0
