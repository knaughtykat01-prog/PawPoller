"""Archive of Our Own (AO3) platform poster.

Uses the existing AO3Client (ao3_client/client.py) with Rails CSRF auth.
Same OTW Archive software as SquidgeWorld — identical form structure.

Post flow:
  1. Login + CSRF token
  2. POST /works with form data (title, fandom, tags, content)

Edit flow:
  1. PATCH /works/{id} for metadata
  2. PATCH /works/{id}/chapters/{ch_id} for chapter content

Rate limiting: 3 seconds between requests (AO3 is volunteer-run).

Rating mapping:
  General → "General Audiences"
  Mature → "Mature"
  Adult → "Explicit"
"""

from __future__ import annotations

import logging

import config
from ao3_client.client import AO3Client
from posting.platforms.base import PlatformPoster, PostResult, StoryUploadPackage
from posting import story_reader

logger = logging.getLogger(__name__)


class AO3Poster(PlatformPoster):

    platform_id = "ao3"
    platform_name = "AO3"
    supports_edit = True
    supports_file_replace = True  # Can edit chapter content
    min_post_interval = 5
    max_file_size = 0  # No file upload — content is pasted as HTML
    accepted_file_types = ["html"]

    def __init__(self):
        self._client: AO3Client | None = None

    async def _ensure_client(self) -> AO3Client:
        if self._client and self._client._logged_in:
            return self._client

        settings = config.get_settings()
        username = settings.get("ao3_username", "")
        password = settings.get("ao3_password", "")
        target_user = settings.get("ao3_target_user", "")
        if not username or not password:
            raise RuntimeError("AO3 credentials not configured")

        self._client = AO3Client(username, password, target_user)
        if not await self._client.ensure_logged_in():
            raise RuntimeError("AO3 login failed")
        return self._client

    async def post(self, package: StoryUploadPackage) -> PostResult:
        """Create a new work on AO3."""
        _t = self._start_timer()
        try:
            client = await self._ensure_client()

            content = ""
            if package.file_path:
                with open(package.file_path, "r", encoding="utf-8") as f:
                    content = f.read()

            if not content:
                return PostResult(
                    success=False, error="No content for AO3 post",
                    duration_seconds=self._elapsed(_t),
                )

            rating = _rating_to_ao3(package.rating)
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
            logger.error("AO3 post failed: %s", e, exc_info=True)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))

    async def edit(self, external_id: str, package: StoryUploadPackage) -> PostResult:
        """Edit metadata AND chapter content on an existing AO3 work."""
        _t = self._start_timer()
        try:
            client = await self._ensure_client()
            tags = ", ".join(package.tags)

            # Step 1: Update work metadata
            await client.edit_work(
                external_id,
                title=package.title,
                summary=package.description[:1250],
                additional_tags=tags,
            )
            logger.info("AO3: Updated work %s metadata", external_id)

            # Step 2: Update chapter content
            try:
                story = story_reader.load_story(package.story_name)
                ao3_chapters = await client.get_chapter_ids(external_id)

                if ao3_chapters and story.chapters:
                    for ao3_ch in ao3_chapters:
                        ch_idx = ao3_ch["index"]
                        ch_id = ao3_ch["chapter_id"]

                        file_path, _ = story_reader._resolve_format_file(story, ch_idx, "ao3")
                        if file_path:
                            with open(file_path, "r", encoding="utf-8") as f:
                                content = f.read()
                            await client.edit_chapter(external_id, ch_id, content=content)
                            logger.info("AO3: Updated chapter %d (id=%s)", ch_idx, ch_id)
                        else:
                            logger.warning("AO3: No file for chapter %d of %s", ch_idx, package.story_name)
            except Exception as ch_err:
                logger.warning("AO3: Chapter content update failed (metadata still updated): %s", ch_err)

            return PostResult(
                success=True,
                external_id=external_id,
                external_url=f"https://archiveofourown.org/works/{external_id}",
                duration_seconds=self._elapsed(_t),
            )
        except Exception as e:
            logger.error("AO3 edit failed for %s: %s", external_id, e, exc_info=True)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))

    async def replace_file(self, external_id: str, file_path: str) -> PostResult:
        """Replace chapter content on AO3."""
        _t = self._start_timer()
        try:
            client = await self._ensure_client()

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            chapters = await client.get_chapter_ids(external_id)
            if not chapters:
                return PostResult(
                    success=False, error="No chapters found",
                    duration_seconds=self._elapsed(_t),
                )

            ch = chapters[0]
            await client.edit_chapter(external_id, ch["chapter_id"], content=content)

            return PostResult(
                success=True,
                external_id=external_id,
                external_url=f"https://archiveofourown.org/works/{external_id}",
                duration_seconds=self._elapsed(_t),
            )
        except Exception as e:
            logger.error("AO3 file replace failed for %s: %s", external_id, e)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))


def _rating_to_ao3(rating: str) -> str:
    r = rating.lower()
    if r in ("adult", "explicit", "nsfw"):
        return "Explicit"
    elif r in ("mature", "questionable"):
        return "Mature"
    elif r in ("teen",):
        return "Teen And Up Audiences"
    return "General Audiences"
