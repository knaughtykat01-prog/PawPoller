"""SoFurry platform poster.

Uses the existing SoFurryClient (sf_client/client.py) with session cookie +
CSRF token auth. Supports post + edit + file replace.

Post flow (3-step REST):
  1. PUT /ui/submission → create empty submission
  2. POST /ui/submission/{id}/content → upload file
  3. POST /ui/submission/{id} → set metadata + publish

Edit flow:
  POST /ui/submission/{id} → update metadata

Rating mapping:
  General → 0 (Clean), Mature → 10, Adult → 20
"""

from __future__ import annotations

import logging

import config
from posting.platforms.base import PlatformPoster, PostResult, StoryUploadPackage
from sf_client.client import SoFurryClient

logger = logging.getLogger(__name__)


class SoFurryPoster(PlatformPoster):

    platform_id = "sf"
    platform_name = "SoFurry"
    supports_edit = True
    supports_file_replace = True
    min_post_interval = 5
    max_file_size = 512 * 1024  # 512 KB
    accepted_file_types = ["txt", "html", "png", "jpg", "gif", "mp3"]

    def __init__(self):
        self._client: SoFurryClient | None = None

    async def _ensure_client(self) -> SoFurryClient:
        if self._client and self._client._logged_in:
            return self._client

        settings = config.get_settings()
        username = settings.get("sf_username", "")
        password = settings.get("sf_password", "")
        display_name = settings.get("sf_display_name", "")
        if not username or not password:
            raise RuntimeError("SoFurry credentials not configured")

        proxy_url = settings.get("cf_worker_url", "")
        proxy_key = settings.get("cf_worker_key", "")

        self._client = SoFurryClient(
            username=username,
            password=password,
            display_name=display_name,
            proxy_url=proxy_url,
            proxy_key=proxy_key,
        )

        # Restore cookies if available
        saved_cookies = settings.get("sf_session_cookies")
        if saved_cookies:
            self._client.import_cookies(saved_cookies)

        if not await self._client.ensure_logged_in():
            raise RuntimeError("SoFurry login failed")
        return self._client

    async def post(self, package: StoryUploadPackage) -> PostResult:
        _t = self._start_timer()
        try:
            client = await self._ensure_client()
            if not package.file_path:
                return PostResult(success=False, error="No file for SoFurry upload", duration_seconds=self._elapsed(_t))

            rating = _rating_to_sf(package.rating)
            result = await client.create_submission(
                package.file_path,
                title=package.title,
                description=package.description,
                tags=package.tags,
                category=20,  # Writing
                sub_type=21,  # Short story
                rating=rating,
            )

            return PostResult(
                success=True,
                external_id=result.get("submission_id", ""),
                external_url=result.get("url", ""),
                duration_seconds=self._elapsed(_t),
            )
        except Exception as e:
            logger.error("SF post failed: %s", e, exc_info=True)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))

    async def edit(self, external_id: str, package: StoryUploadPackage) -> PostResult:
        _t = self._start_timer()
        try:
            client = await self._ensure_client()
            rating = _rating_to_sf(package.rating)

            result = await client.edit_submission(
                external_id,
                title=package.title,
                description=package.description,
                tags=package.tags,
                rating=rating,
            )

            return PostResult(
                success=True,
                external_id=external_id,
                external_url=result.get("url", ""),
                duration_seconds=self._elapsed(_t),
            )
        except Exception as e:
            logger.error("SF edit failed for %s: %s", external_id, e, exc_info=True)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))

    async def replace_file(self, external_id: str, file_path: str) -> PostResult:
        """Replace content file on an existing SF submission."""
        _t = self._start_timer()
        try:
            client = await self._ensure_client()
            csrf = await client._get_csrf_meta()
            if not csrf:
                return PostResult(success=False, error="Could not get CSRF token", duration_seconds=self._elapsed(_t))

            import os
            with open(file_path, "rb") as f:
                file_data = f.read()

            resp = await client._http.post(
                f"https://sofurry.com/ui/submission/{external_id}/content",
                headers={
                    "X-CSRF-TOKEN": csrf,
                    "Origin": "https://sofurry.com",
                    "Referer": "https://sofurry.com/",
                },
                files={"file": (os.path.basename(file_path), file_data)},
                timeout=60.0,
            )

            if resp.status_code in (200, 201):
                logger.info("SF: Replaced content on submission %s", external_id)
                return PostResult(
                    success=True,
                    external_id=external_id,
                    external_url=f"https://sofurry.com/s/{external_id}",
                    duration_seconds=self._elapsed(_t),
                )
            return PostResult(
                success=False,
                error=f"File replace returned status {resp.status_code}",
                duration_seconds=self._elapsed(_t),
            )
        except Exception as e:
            logger.error("SF file replace failed for %s: %s", external_id, e)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))

    def validate(self, package: StoryUploadPackage) -> list[str]:
        errors = super().validate(package)
        if len(package.tags) < 2:
            errors.append(f"SoFurry requires at least 2 tags (got {len(package.tags)})")
        if package.file_path:
            import os
            size = os.path.getsize(package.file_path) if os.path.isfile(package.file_path) else 0
            if size > self.max_file_size:
                errors.append(f"SoFurry max file size is 512KB (got {size / 1024:.0f}KB)")
        return errors


def _rating_to_sf(rating: str) -> int:
    r = rating.lower()
    if r in ("adult", "explicit", "nsfw"):
        return 20
    elif r in ("mature", "questionable"):
        return 10
    return 0
