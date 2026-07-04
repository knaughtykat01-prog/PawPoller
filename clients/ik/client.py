"""Itaku (IK) API client.

Itaku provides a public REST API at itaku.ee/api/. No authentication
is required — only the target username is needed. Content is split into
two types: images (gallery_images) and posts (posts).

Key details:
  - Content IDs are integers
  - Stats: likes (num_likes), comments (num_comments), reshares (num_reshares)
  - NO views metric available
  - Auth: none required (public API)
  - Pagination: cursor-based (next URL in response)
  - Content types: images and posts
"""

from __future__ import annotations
import asyncio
import logging

import httpx

import config

logger = logging.getLogger(__name__)
_API_BASE = "https://itaku.ee/api"
_WEB_BASE = "https://itaku.ee"

_HEADERS = {
    "User-Agent": "PawPoller/1.0",
    "Accept": "application/json",
}


class IKClient:
    """Async HTTP client for Itaku's public API."""

    def __init__(self, target_user: str, proxy_url: str = "", proxy_key: str = ""):
        self.target_user = target_user
        self._user_id: int | None = None
        if proxy_url and proxy_key:
            from polling.cf_proxy import CloudflareProxyTransport
            transport = CloudflareProxyTransport(proxy_url, proxy_key)
            logger.info("IK client using CF proxy: %s", proxy_url)
        else:
            transport = httpx.AsyncHTTPTransport(retries=2)
        self._http = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=_HEADERS,
            transport=transport,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    def update_credentials(self, target_user: str) -> None:
        self.target_user = target_user
        self._user_id = None  # Reset cached user ID

    async def close(self) -> None:
        await self._http.aclose()

    async def _get_json(self, url: str, params: dict | None = None) -> dict | list | None:
        """Fetch a JSON endpoint with error handling."""
        try:
            resp = await self._http.get(url, params=params)
            if resp.status_code == 404:
                logger.warning("IK: Not found (404) for %s", url)
                return None
            if resp.status_code == 429:
                logger.warning("IK: Rate limited (429), waiting 30s...")
                await asyncio.sleep(30)
                resp = await self._http.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            logger.error("IK: Failed to fetch %s: %s", url, e)
            return None
        except Exception as e:
            logger.error("IK: JSON parse error for %s: %s", url, e)
            return None

    # ── User Resolution ───────────────────────────────────────

    async def _resolve_user_id(self) -> int | None:
        """Resolve username to user ID via the profile endpoint."""
        if self._user_id is not None:
            return self._user_id

        data = await self._get_json(f"{_API_BASE}/user_profiles/{self.target_user}/")
        if data and isinstance(data, dict):
            self._user_id = data.get("owner")
            return self._user_id
        return None

    async def validate_user(self) -> str | None:
        """Check if the target user exists on Itaku. Returns username if valid."""
        if not self.target_user:
            return None
        data = await self._get_json(f"{_API_BASE}/user_profiles/{self.target_user}/")
        if data and isinstance(data, dict) and data.get("owner"):
            self._user_id = data["owner"]
            return self.target_user
        return None

    async def get_follower_count(self) -> int | None:
        """Best-effort follower count from the Itaku user profile.

        Itaku's /user_profiles/{name}/ payload is the only profile source the
        client already uses; the follower field name isn't formally documented,
        so try the plausible keys and return None if none are present (the
        follower series simply won't populate for Itaku rather than storing junk).
        """
        if not self.target_user:
            return None
        data = await self._get_json(f"{_API_BASE}/user_profiles/{self.target_user}/")
        if not data or not isinstance(data, dict):
            return None
        for key in ("num_followers", "followers_count", "follower_count", "num_follower"):
            val = data.get(key)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    return None
        return None

    # ── Content Discovery ─────────────────────────────────────

    async def get_all_content_ids(self) -> list[dict]:
        """Fetch all images and posts for the target user."""
        user_id = await self._resolve_user_id()
        if not user_id:
            logger.error("IK: Could not resolve user ID for %s", self.target_user)
            return []

        all_content: list[dict] = []

        # Fetch images
        images = await self._paginate_content("gallery_images", user_id)
        all_content.extend(images)

        # Fetch posts
        posts = await self._paginate_content("posts", user_id)
        all_content.extend(posts)

        logger.info("IK: Found %d content items (%d images, %d posts) for %s",
                     len(all_content), len(images), len(posts), self.target_user)
        return all_content

    async def _paginate_content(self, content_type: str, user_id: int) -> list[dict]:
        """Paginate through a content type using cursor-based pagination."""
        items: list[dict] = []
        url = f"{_API_BASE}/{content_type}/"
        params = {"owner": str(user_id), "page_size": "30", "ordering": "-date_added"}

        for _page_safety in range(1000):
            if not url:
                break
            data = await self._get_json(url, params=params)
            if not data or not isinstance(data, dict):
                break

            results = data.get("results", [])
            if not results:
                break

            for item in results:
                item_id = item.get("id")
                if item_id:
                    items.append({
                        "content_id": int(item_id),
                        "title": item.get("title", ""),
                        "content_type": "image" if content_type == "gallery_images" else "post",
                    })

            # Cursor pagination: use the "next" URL from the response
            next_url = data.get("next")
            if next_url:
                url = next_url
                params = None  # params are already in the next URL
            else:
                break

            await asyncio.sleep(config.IK_REQUEST_DELAY_SECONDS)

        return items

    # ── Content Details ───────────────────────────────────────

    async def get_content_detail(self, content_id: int, content_type: str = "image") -> dict:
        """Fetch stats and metadata for a single content item."""
        endpoint = "gallery_images" if content_type == "image" else "posts"
        data = await self._get_json(f"{_API_BASE}/{endpoint}/{content_id}/")

        if not data or not isinstance(data, dict):
            return {
                "content_id": content_id, "title": "", "username": self.target_user,
                "likes": 0, "comments_count": 0, "reshares": 0,
                "keywords": [], "link": f"{_WEB_BASE}/{self.target_user}/gallery/{content_id}",
                "description": "", "content_type": content_type, "posted_at": "",
            }

        detail = {
            "content_id": int(data.get("id", content_id)),
            "title": data.get("title", ""),
            "username": self.target_user,
            "description": data.get("description", "") or "",
            "content_type": content_type,
            "likes": data.get("num_likes", 0),
            "comments_count": data.get("num_comments", 0),
            "reshares": data.get("num_reshares", 0),
            "posted_at": data.get("date_added", ""),
            "link": f"{_WEB_BASE}/{self.target_user}/gallery/{content_id}" if content_type == "image" else f"{_WEB_BASE}/{self.target_user}/posts/{content_id}",
            "maturity_rating": data.get("maturity_rating", ""),
        }

        # Tags/keywords
        tags = data.get("tags", [])
        if isinstance(tags, list):
            detail["keywords"] = [t.get("name", str(t)) if isinstance(t, dict) else str(t) for t in tags]
        else:
            detail["keywords"] = []

        # Thumbnail
        if content_type == "image":
            detail["thumbnail_url"] = data.get("image_sm", data.get("image", ""))
        else:
            detail["thumbnail_url"] = ""

        # Rating mapping
        mr = data.get("maturity_rating", "")
        if mr == "SFW" or mr == "0" or mr == 0:
            detail["rating"] = "General"
        elif mr == "Questionable" or mr == "1" or mr == 1:
            detail["rating"] = "Mature"
        elif mr == "NSFW" or mr == "2" or mr == 2:
            detail["rating"] = "Adult"
        else:
            detail["rating"] = str(mr) if mr else "General"

        return detail

    async def get_content_details_batch(self, content_items: list[dict]) -> list[dict]:
        """Fetch details for multiple content items with rate limiting."""
        details = []
        for i, item in enumerate(content_items):
            if i > 0:
                await asyncio.sleep(config.IK_REQUEST_DELAY_SECONDS)
            try:
                detail = await self.get_content_detail(
                    item["content_id"],
                    item.get("content_type", "image"),
                )
                details.append(detail)
            except Exception as e:
                logger.warning("IK: Failed to fetch content %s: %s", item.get("content_id"), e)
        return details

    # ── Posting / Upload ────────────────────────────────────────

    async def upload_image(
        self,
        file_path: str,
        *,
        title: str = "",
        description: str = "",
        tags: list[str] | None = None,
        maturity_rating: str = "SFW",
        visibility: str = "PUBLIC",
        sections: list[int] | None = None,
        share_on_feed: bool = True,
        token: str = "",
    ) -> dict:
        """Upload an image to Itaku gallery.

        Args:
            file_path: Path to image file (PNG, JPG, GIF, WEBP).
            title: Image title.
            description: Plaintext description (max 5000 chars).
            tags: List of tag names (min 5 tags).
            maturity_rating: "SFW", "Questionable", or "NSFW".
            visibility: "PUBLIC", "FOLLOWERS_ONLY", or "PRIVATE".
            sections: Gallery folder IDs (optional).
            share_on_feed: Post to activity feed.
            token: Auth token (from browser session).

        Returns:
            Dict with 'id' and 'url'.
        """
        import os

        if not token:
            raise RuntimeError("Itaku auth token required for uploads")

        with open(file_path, "rb") as f:
            file_data = f.read()

        filename = os.path.basename(file_path)
        tag_json = [{"name": t} for t in (tags or [])]

        # Build multipart form
        import json
        files = {"image": (filename, file_data)}
        data = {
            "title": title,
            "description": description[:5000],
            "tags": json.dumps(tag_json),
            "maturity_rating": maturity_rating,
            "visibility": visibility,
            "share_on_feed": "true" if share_on_feed else "false",
        }
        if sections:
            data["sections"] = json.dumps(sections)

        resp = await self._http.post(
            f"{_API_BASE}/galleries/images/",
            data=data,
            files=files,
            headers={"Authorization": f"Token {token}"},
            timeout=60.0,
        )

        if resp.status_code == 429:
            logger.warning("IK: Rate limited on upload, waiting 30s...")
            await asyncio.sleep(30)
            resp = await self._http.post(
                f"{_API_BASE}/galleries/images/",
                data=data,
                files=files,
                headers={"Authorization": f"Token {token}"},
                timeout=60.0,
            )

        if resp.status_code not in (200, 201):
            raise RuntimeError(f"IK: Upload failed — status {resp.status_code}: {resp.text[:200]}")

        result = resp.json()
        image_id = result.get("id", "")
        logger.info("IK: Uploaded image %s — %s", image_id, title[:40])
        return {"id": str(image_id), "url": f"{_WEB_BASE}/image/{image_id}"}

    async def create_post(
        self,
        *,
        title: str = "",
        content: str = "",
        tags: list[str] | None = None,
        maturity_rating: str = "SFW",
        visibility: str = "PUBLIC",
        gallery_images: list[int] | None = None,
        token: str = "",
    ) -> dict:
        """Create a text post on Itaku.

        Posts are text/blog-style content. Can optionally reference gallery images.
        Content is plaintext, max ~5000 chars.

        Args:
            title: Post title.
            content: Post body text (plaintext).
            tags: List of tag names.
            maturity_rating: "SFW", "Questionable", or "NSFW".
            visibility: "PUBLIC", "FOLLOWERS_ONLY", or "PRIVATE".
            gallery_images: List of gallery image IDs to attach.
            token: Auth token.

        Returns:
            Dict with 'id' and 'url'.
        """
        if not token:
            raise RuntimeError("Itaku auth token required for posting")

        import json
        tag_json = [{"name": t} for t in (tags or [])]
        payload = {
            "title": title,
            "content": content[:5000],
            "tags": tag_json,
            "maturity_rating": maturity_rating,
            "visibility": visibility,
            "gallery_images": gallery_images or [],
        }

        resp = await self._http.post(
            f"{_API_BASE}/posts/",
            json=payload,
            headers={"Authorization": f"Token {token}"},
            timeout=30.0,
        )

        if resp.status_code not in (200, 201):
            raise RuntimeError(f"IK: Post creation failed — status {resp.status_code}: {resp.text[:200]}")

        result = resp.json()
        post_id = result.get("id", "")
        logger.info("IK: Created post %s — %s", post_id, title[:40])
        return {"id": str(post_id), "url": f"{_WEB_BASE}/post/{post_id}"}
