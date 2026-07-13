"""e621 (E621) official REST API client.

e621 exposes a first-class JSON API (https://e621.net/help/api). Auth is HTTP
Basic with your **username + API key** (Account → Manage API Access — NOT your
password). Poll-only: we track the connected user's own uploads via the
`user:<username>` tag search and snapshot each post's engagement.

Policy compliance (https://e621.net/help/api):
  - A descriptive, non-empty **User-Agent is mandatory**, and it MUST NOT
    impersonate a browser — doing so gets the client blocked. We send
    ``PawPoller/<version> (e621 analytics; user <name>)``.
  - Hard rate limit is 2 req/s; the docs ask for ~1 req/s best-effort. We sleep
    ``config.E621_REQUEST_DELAY_SECONDS`` (1.0s) between paged requests.

Metric shape:
  - score  = score.total  (can be NEGATIVE — down-votes)
  - favorites_count = fav_count
  - comments_count  = comment_count
Post IDs are integers; we store them as TEXT strings.
"""

from __future__ import annotations
import asyncio
import logging
from typing import Any

import httpx

import config

logger = logging.getLogger(__name__)

_API_BASE = "https://e621.net"

_RATING_MAP = {"s": "Safe", "q": "Questionable", "e": "Explicit"}

# file extension → coarse content type (drives the type badge in the UI)
_EXT_TYPE = {
    "png": "image", "jpg": "image", "jpeg": "image", "webp": "image",
    "gif": "animation",
    "webm": "video", "mp4": "video",
    "swf": "flash",
}


def _safe_int(val: Any) -> int:
    if val is None:
        return 0
    try:
        if isinstance(val, str):
            val = val.replace(",", "").strip()
        return int(val)
    except (ValueError, TypeError):
        return 0


class E621Client:
    """Async client for the official e621 REST API."""

    def __init__(self, username: str = "", api_key: str = "",
                 proxy_url: str = "", proxy_key: str = ""):
        self.username = str(username or "").strip()
        self.api_key = str(api_key or "").strip()
        self._logged_in = False

        if proxy_url and proxy_key:
            from polling.cf_proxy import CloudflareProxyTransport
            transport = CloudflareProxyTransport(proxy_url, proxy_key)
            logger.info("e621 client using CF proxy: %s", proxy_url)
        else:
            transport = httpx.AsyncHTTPTransport(retries=2)
        self._http = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            transport=transport,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    def update_credentials(self, username: str, api_key: str) -> None:
        new_user = str(username or "").strip()
        new_key = str(api_key or "").strip()
        changed = (self.username != new_user or self.api_key != new_key)
        self.username = new_user
        self.api_key = new_key
        if changed:
            self._logged_in = False

    # -- HTTP -----------------------------------------------------------------

    def _headers(self) -> dict:
        # Descriptive, non-browser User-Agent (mandatory; impersonating a
        # browser is an explicit policy violation that gets the client blocked).
        who = self.username or "anonymous"
        return {
            "User-Agent": f"PawPoller/{config.APP_VERSION} (e621 self-analytics; user {who})",
            "Accept": "application/json",
        }

    def _auth(self):
        if self.username and self.api_key:
            return (self.username, self.api_key)
        return None

    async def _get_json(self, path: str, params: dict | None = None) -> Any:
        url = path if path.startswith("http") else f"{_API_BASE}{path}"
        try:
            resp = await self._http.get(url, params=params, headers=self._headers(), auth=self._auth())
            if resp.status_code in (401, 403):
                logger.warning("e621: auth rejected (%s) for %s", resp.status_code, path)
                return None
            if resp.status_code == 429:
                logger.warning("e621: rate limited (429), waiting 10s...")
                await asyncio.sleep(10)
                resp = await self._http.get(url, params=params, headers=self._headers(), auth=self._auth())
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            logger.error("e621: failed to fetch %s: %s", path, e)
            return None
        except Exception as e:
            logger.error("e621: JSON parse error for %s: %s", path, e)
            return None

    # -- Auth -----------------------------------------------------------------

    async def validate_session(self) -> str | None:
        """Confirm the username + API key work. Returns the username on success.

        Hits `/favorites.json` (an authenticated-only endpoint) — a wrong API
        key returns 401/403 there, whereas public post endpoints would 200
        regardless, so this actually verifies the key rather than the username.
        """
        if not self.username or not self.api_key:
            return None
        data = await self._get_json("/favorites.json", {"limit": 1})
        if data is None:
            return None
        self._logged_in = True
        return self.username

    async def ensure_logged_in(self) -> bool:
        if self._logged_in:
            return True
        return bool(await self.validate_session())

    # -- Post discovery -------------------------------------------------------

    async def get_all_post_uris(self) -> list[dict]:
        """Page through the connected user's own uploads (tags=user:<username>).

        e621 returns posts newest-first; deep pagination uses the `page=b<id>`
        (before-id) cursor rather than page numbers (which cap at 750). Each
        listing carries full engagement data, so no per-post fetch is needed —
        the raw post is stashed for get_post_details_batch() to parse.
        """
        if not self.username:
            return []
        items: list[dict] = []
        seen: set[int] = set()
        before_id: int | None = None

        for _page_safety in range(500):  # 500 * 320 = 160k posts hard ceiling
            params: dict[str, Any] = {"tags": f"user:{self.username}", "limit": 320}
            if before_id is not None:
                params["page"] = f"b{before_id}"
            data = await self._get_json("/posts.json", params)
            if not data or not isinstance(data, dict):
                break
            page_posts = data.get("posts") or []
            if not page_posts:
                break
            page_ids = []
            for p in page_posts:
                pid = _safe_int(p.get("id"))
                page_ids.append(pid)
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                items.append({"post_uri": str(pid), "raw": p})
            before_id = min(page_ids) if page_ids else None
            if len(page_posts) < 320 or before_id is None:
                break
            await asyncio.sleep(config.E621_REQUEST_DELAY_SECONDS)

        logger.info("e621: found %d posts for user %s", len(items), self.username)
        return items

    async def get_post_details_batch(self, items: list[dict]) -> list[dict]:
        """Parse the raw posts gathered in discovery — no extra API calls."""
        details: list[dict] = []
        for item in items:
            raw = item.get("raw")
            detail = (self._parse_post(raw)
                      if raw else self._empty_detail(item.get("post_uri", "")))
            details.append(detail)
        return details

    # -- Parsing --------------------------------------------------------------

    def _parse_post(self, p: dict) -> dict:
        pid = str(_safe_int(p.get("id")))
        file_obj = p.get("file", {}) or {}
        preview = p.get("preview", {}) or {}
        sample = p.get("sample", {}) or {}
        score = p.get("score", {}) or {}

        ext = (file_obj.get("ext") or "").lower()
        content_type = _EXT_TYPE.get(ext, "image")

        # Flatten every tag category into one keyword list.
        keywords: list[str] = []
        tags = p.get("tags", {}) or {}
        if isinstance(tags, dict):
            for cat_tags in tags.values():
                if isinstance(cat_tags, list):
                    keywords.extend(str(t) for t in cat_tags)

        description = p.get("description", "") or ""
        # e621 posts have no title; derive a readable one from the description
        # first line, falling back to the post number.
        first_line = description.strip().splitlines()[0].strip() if description.strip() else ""
        title = (first_line[:80] if first_line else f"#{pid}")

        thumb = preview.get("url") or sample.get("url") or file_obj.get("url") or ""
        file_url = file_obj.get("url") or ""

        return {
            "post_uri": pid,
            "title": title,
            "full_text": description,
            "username": self.username,
            "posted_at": p.get("created_at", "") or "",
            "content_type": content_type,
            "rating": _RATING_MAP.get((p.get("rating") or "").lower(), ""),
            "description": description,
            "keywords": keywords,
            "link": f"{_API_BASE}/posts/{pid}",
            "thumbnail_url": thumb,
            "file_url": file_url,
            "score": _safe_int(score.get("total")),
            "up_score": _safe_int(score.get("up")),
            "down_score": _safe_int(score.get("down")),
            "favorites_count": _safe_int(p.get("fav_count")),
            "comments_count": _safe_int(p.get("comment_count")),
            "has_media": 1 if file_url else 0,
        }

    def _empty_detail(self, uri: str) -> dict:
        return {
            "post_uri": uri,
            "title": f"#{uri}" if uri else "",
            "full_text": "",
            "username": self.username,
            "posted_at": "",
            "content_type": "image",
            "rating": "",
            "description": "",
            "keywords": [],
            "link": f"{_API_BASE}/posts/{uri}" if uri else "",
            "thumbnail_url": "",
            "file_url": "",
            "score": 0,
            "up_score": 0,
            "down_score": 0,
            "favorites_count": 0,
            "comments_count": 0,
            "has_media": 0,
        }
