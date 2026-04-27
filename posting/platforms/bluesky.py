"""Bluesky platform poster.

Uses the existing BskyClient (clients/bsky/client.py) with the new
create_post(), upload_blob(), and delete_post() methods.

Bluesky is used for announcement posts (not full story uploads). Posts are
limited to 300 graphemes and can include up to 4 images.

Post flow:
  1. ensure_logged_in()
  2. (optional) upload_blob(cover_image)
  3. create_post(text, embed=image, labels=nsfw)

Edit flow:
  Bluesky does not support in-place editing. The only option is delete + repost,
  which loses engagement. For announcements this is acceptable.
"""

from __future__ import annotations

import logging

import config
from clients.bsky.client import BskyClient
from posting.platforms.base import PlatformPoster, PostResult, StoryUploadPackage

logger = logging.getLogger(__name__)


class BlueskyPoster(PlatformPoster):

    platform_id = "bsky"
    platform_name = "Bluesky"
    supports_edit = False        # Delete+repost only
    supports_file_replace = False
    min_post_interval = 3
    max_file_size = 1 * 1024 * 1024  # 1 MB for images
    accepted_file_types = ["png", "jpg", "jpeg", "gif"]

    def __init__(self):
        self._client: BskyClient | None = None

    async def _ensure_client(self) -> BskyClient:
        """Get or create an authenticated Bluesky client."""
        if self._client and self._client._logged_in:
            return self._client

        settings = config.get_settings()
        identifier = settings.get("bsky_identifier", "")
        app_password = settings.get("bsky_app_password", "")
        if not identifier or not app_password:
            raise RuntimeError("Bluesky credentials not configured")

        self._client = BskyClient(identifier=identifier, app_password=app_password)
        if not await self._client.ensure_logged_in():
            raise RuntimeError("Bluesky login failed")
        return self._client

    async def post(self, package: StoryUploadPackage) -> PostResult:
        """Create a Bluesky announcement post for a story."""
        _t = self._start_timer()
        try:
            client = await self._ensure_client()

            # Build post text — announcement style
            text = package.description
            if len(text) > 295:
                text = text[:292] + "..."

            # Determine NSFW labels
            labels = None
            if package.rating.lower() in ("adult", "explicit", "nsfw"):
                labels = ["sexual"]
            elif package.rating.lower() in ("mature", "questionable"):
                labels = ["nudity"]

            result = await client.create_post(
                text=text,
                image_path=package.thumbnail_path,
                image_alt=package.title,
                labels=labels,
            )

            if result and "uri" in result:
                return PostResult(
                    success=True,
                    external_id=result["uri"],
                    external_url=result.get("url", ""),
                    duration_seconds=self._elapsed(_t),
                )

            return PostResult(
                success=False,
                error="Post creation returned no URI",
                duration_seconds=self._elapsed(_t),
            )

        except Exception as e:
            logger.error("BSKY post failed: %s", e, exc_info=True)
            return PostResult(
                success=False,
                error=str(e),
                duration_seconds=self._elapsed(_t),
            )

    async def edit(self, external_id: str, package: StoryUploadPackage) -> PostResult:
        """Bluesky doesn't support editing — delete and repost."""
        _t = self._start_timer()
        try:
            client = await self._ensure_client()

            # Delete old post
            await client.delete_post(external_id)

            # Create new post
            result = await self.post(package)
            result.duration_seconds = self._elapsed(_t)
            return result

        except Exception as e:
            logger.error("BSKY edit (delete+repost) failed: %s", e, exc_info=True)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))

    async def replace_file(self, external_id: str, file_path: str) -> PostResult:
        """Not supported — Bluesky posts don't have replaceable files."""
        return PostResult(success=False, error="Bluesky does not support file replacement")

    def validate(self, package: StoryUploadPackage) -> list[str]:
        errors = []
        if not package.description:
            errors.append("Bluesky post requires text (description)")
        if len(package.description.encode("utf-8")) > 900:
            errors.append("Bluesky text too long (max ~300 graphemes)")
        return errors
