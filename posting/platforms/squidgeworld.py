"""SquidgeWorld platform poster.

Uses the existing SquidgeWorldClient (sqw_client/client.py) with Rails CSRF auth.
OTW Archive platform — same software as AO3.

Post flow:
  1. Login + CSRF token
  2. POST /works with form data (title, fandom, tags, content)
  3. For multi-chapter: POST additional chapters

Edit flow:
  1. PATCH /works/{id} for metadata
  2. PATCH /works/{id}/chapters/{ch_id} for chapter content

Rating mapping:
  General → "General Audiences"
  Mature → "Mature"
  Adult → "Explicit"
"""

from __future__ import annotations

import logging

import config
from posting.platforms.base import PlatformPoster, PostResult, StoryUploadPackage
from sqw_client.client import SquidgeWorldClient

logger = logging.getLogger(__name__)


class SquidgeWorldPoster(PlatformPoster):

    platform_id = "sqw"
    platform_name = "SquidgeWorld"
    supports_edit = True
    supports_file_replace = True  # Can edit chapter content
    min_post_interval = 5
    max_file_size = 0  # No file upload — content is pasted as HTML
    accepted_file_types = ["html"]

    def __init__(self):
        self._client: SquidgeWorldClient | None = None

    async def _ensure_client(self) -> SquidgeWorldClient:
        if self._client and self._client._logged_in:
            return self._client

        settings = config.get_settings()
        username = settings.get("sqw_username", "")
        password = settings.get("sqw_password", "")
        target_user = settings.get("sqw_target_user", "")
        if not username or not password:
            raise RuntimeError("SquidgeWorld credentials not configured")

        self._client = SquidgeWorldClient(username, password, target_user)
        if not await self._client.ensure_logged_in():
            raise RuntimeError("SquidgeWorld login failed")
        return self._client

    async def post(self, package: StoryUploadPackage) -> PostResult:
        """Create a new work on SquidgeWorld."""
        _t = self._start_timer()
        try:
            client = await self._ensure_client()

            # Read content from the SoFurry HTML or Markdown file
            content = ""
            if package.file_path:
                with open(package.file_path, "r", encoding="utf-8") as f:
                    content = f.read()

            if not content:
                return PostResult(
                    success=False, error="No content for SquidgeWorld post",
                    duration_seconds=self._elapsed(_t),
                )

            rating = _rating_to_sqw(package.rating)
            tags = ", ".join(package.tags)

            result = await client.create_work(
                title=package.title,
                content=content,
                rating=rating,
                additional_tags=tags,
                summary=package.description[:1250],
            )

            return PostResult(
                success=True,
                external_id=result.get("work_id", ""),
                external_url=result.get("url", ""),
                duration_seconds=self._elapsed(_t),
            )
        except Exception as e:
            logger.error("SqW post failed: %s", e, exc_info=True)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))

    async def edit(self, external_id: str, package: StoryUploadPackage) -> PostResult:
        """Edit metadata on an existing SquidgeWorld work."""
        _t = self._start_timer()
        try:
            client = await self._ensure_client()
            tags = ", ".join(package.tags)

            result = await client.edit_work(
                external_id,
                title=package.title,
                summary=package.description[:1250],
                additional_tags=tags,
            )

            return PostResult(
                success=True,
                external_id=external_id,
                external_url=result.get("url", ""),
                duration_seconds=self._elapsed(_t),
            )
        except Exception as e:
            logger.error("SqW edit failed for %s: %s", external_id, e, exc_info=True)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))

    async def replace_file(self, external_id: str, file_path: str) -> PostResult:
        """Replace chapter content on SquidgeWorld."""
        _t = self._start_timer()
        try:
            client = await self._ensure_client()

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Get chapter IDs for this work
            chapters = await client.get_chapter_ids(external_id)
            if not chapters:
                return PostResult(
                    success=False, error="No chapters found for this work",
                    duration_seconds=self._elapsed(_t),
                )

            # Update the first chapter (or single-chapter work)
            ch = chapters[0]
            await client.edit_chapter(external_id, ch["chapter_id"], content=content)

            return PostResult(
                success=True,
                external_id=external_id,
                external_url=f"https://squidgeworld.org/works/{external_id}",
                duration_seconds=self._elapsed(_t),
            )
        except Exception as e:
            logger.error("SqW file replace failed for %s: %s", external_id, e)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))


def _rating_to_sqw(rating: str) -> str:
    r = rating.lower()
    if r in ("adult", "explicit", "nsfw"):
        return "Explicit"
    elif r in ("mature", "questionable"):
        return "Mature"
    elif r in ("teen",):
        return "Teen And Up Audiences"
    return "General Audiences"
