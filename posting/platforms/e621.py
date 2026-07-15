"""e621 platform poster.

e621 is an art gallery. We upload a single image plus a tag set and rating via
the official REST API (``POST /uploads.json``), authenticated with the same
HTTP Basic **username + API key** used for polling — no browser session.

Caveats that make e621 stricter than the other galleries:
  - Uploads hit a **moderation queue** and must be approved by janitors.
  - e621 demands an **accurate, real tag set** (not one keyword) and a valid
    rating; badly-tagged posts get flagged. We enforce a small tag floor.
  - **Duplicates are rejected** (by file hash); the client surfaces the
    existing post's URL in the error.
  - A **source** is strongly encouraged — pass one via the artwork's
    per-platform ``source`` override (package.extra["source"]).

Rating mapping (PawPoller rating -> e621 s/q/e):
  general / safe / sfw       -> s
  mature / questionable      -> q
  adult / explicit / nsfw    -> e   (also the fallback for anything unknown,
                                     since under-rating adult content violates
                                     e621 policy)
"""

from __future__ import annotations

import logging

import config
from clients.e621.client import E621Client
from posting.platforms.base import PlatformPoster, PostResult, StoryUploadPackage

logger = logging.getLogger(__name__)

# e621 wants a genuine tag set, not a single keyword. A modest floor protects
# the user's standing without blocking legitimate posts.
_MIN_TAGS = 4


class E621Poster(PlatformPoster):

    platform_id = "e621"
    platform_name = "e621"
    supports_edit = False
    supports_file_replace = False
    min_post_interval = 5
    max_file_size = 100 * 1024 * 1024  # e621 accepts large files (100 MB)
    accepted_file_types = ["png", "jpg", "jpeg", "gif", "webp", "webm"]
    requires_mode = "any"              # official API works from the server

    def __init__(self):
        self._client: E621Client | None = None

    async def _ensure_client(self) -> E621Client:
        settings = config.get_settings()
        creds = self._resolve_creds("e621", settings)
        username = creds.get("e621_username", "")
        api_key = creds.get("e621_api_key", "")
        if not (username and api_key):
            raise RuntimeError("e621 credentials not configured "
                               "(e621_username + e621_api_key)")
        if self._client is None:
            from polling.cf_proxy import proxy_kwargs
            self._client = E621Client(username=username, api_key=api_key,
                                      **proxy_kwargs(settings, "e621"))
        else:
            self._client.update_credentials(username, api_key)
        return self._client

    async def post(self, package: StoryUploadPackage) -> PostResult:
        """Upload one image to e621."""
        _t = self._start_timer()
        try:
            client = await self._ensure_client()
            rating = _rating_to_e621(package.rating)
            tag_string = " ".join(package.tags)
            source = str(package.extra.get("source", "") or "")

            result = await client.upload_post(
                tag_string=tag_string,
                rating=rating,
                file_path=package.file_path or "",
                source=source,
                description=package.description or "",
            )
            return PostResult(
                success=True,
                external_id=result.get("post_id", ""),
                external_url=result.get("url", ""),
                duration_seconds=self._elapsed(_t),
            )
        except Exception as e:
            logger.error("e621 post failed: %s", e, exc_info=True)
            return PostResult(success=False, error=str(e),
                              duration_seconds=self._elapsed(_t))

    async def edit(self, external_id: str, package: StoryUploadPackage) -> PostResult:
        return PostResult(success=False, error="e621 does not support editing via API")

    async def replace_file(self, external_id: str, file_path: str) -> PostResult:
        return PostResult(success=False, error="e621 does not support file replacement")

    def validate(self, package: StoryUploadPackage) -> list[str]:
        errors: list[str] = []
        if not package.file_path:
            errors.append("e621 requires an image file")
        if len(package.tags) < _MIN_TAGS:
            errors.append(f"e621 expects a real tag set - add at least "
                          f"{_MIN_TAGS} tags (got {len(package.tags)})")
        if package.file_path:
            import os
            if os.path.isfile(package.file_path):
                size = os.path.getsize(package.file_path)
                if size > self.max_file_size:
                    errors.append(f"File too large: {size / 1024 / 1024:.1f}MB "
                                  f"(max {self.max_file_size / 1024 / 1024:.0f}MB)")
        return errors


def _rating_to_e621(rating: str) -> str:
    r = (rating or "").strip().lower()
    if r in ("s", "safe", "general", "sfw", "g"):
        return "s"
    if r in ("q", "questionable", "mature", "m"):
        return "q"
    # explicit / adult / nsfw and any unknown value -> explicit (under-rating
    # adult content on e621 is a policy violation; over-rating is harmless).
    return "e"
