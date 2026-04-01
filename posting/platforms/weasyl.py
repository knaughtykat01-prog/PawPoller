"""Weasyl platform poster.

Uses the existing WeasylClient (weasyl_client/client.py) with API key auth.
The API key is sent on every request as X-Weasyl-API-Key header.

Post flow:
  1. POST /submit/literary — multipart with file + metadata

Edit flow:
  1. GET /edit/submission/{id} — scrape form
  2. POST /edit/submission/{id} — update fields

Rating mapping:
  General → 10, Mature → 30, Adult → 40
"""

from __future__ import annotations

import logging

import config
from posting.platforms.base import PlatformPoster, PostResult, StoryUploadPackage
from weasyl_client.client import WeasylClient

logger = logging.getLogger(__name__)


class WeasylPoster(PlatformPoster):

    platform_id = "ws"
    platform_name = "Weasyl"
    supports_edit = True
    supports_file_replace = False
    min_post_interval = 5
    max_file_size = 10 * 1024 * 1024  # 10 MB for text
    accepted_file_types = ["pdf", "txt", "md", "png", "jpg", "gif"]

    def __init__(self):
        self._client: WeasylClient | None = None

    async def _ensure_client(self) -> WeasylClient:
        if self._client:
            return self._client
        settings = config.get_settings()
        api_key = settings.get("ws_api_key", "")
        if not api_key:
            raise RuntimeError("Weasyl API key not configured")
        self._client = WeasylClient(api_key=api_key)
        return self._client

    async def post(self, package: StoryUploadPackage) -> PostResult:
        _t = self._start_timer()
        try:
            client = await self._ensure_client()
            if not package.file_path:
                return PostResult(success=False, error="No file for Weasyl upload", duration_seconds=self._elapsed(_t))

            rating = _rating_to_ws(package.rating)
            tags_str = " ".join(package.tags)

            result = await client.submit_literary(
                package.file_path,
                title=package.title,
                description=package.description,
                tags=tags_str,
                rating=rating,
            )

            return PostResult(
                success=True,
                external_id=result.get("submission_id", ""),
                external_url=result.get("url", ""),
                duration_seconds=self._elapsed(_t),
            )
        except Exception as e:
            logger.error("WS post failed: %s", e, exc_info=True)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))

    async def edit(self, external_id: str, package: StoryUploadPackage) -> PostResult:
        _t = self._start_timer()
        try:
            client = await self._ensure_client()
            rating = _rating_to_ws(package.rating)
            tags_str = " ".join(package.tags)

            result = await client.edit_submission(
                external_id,
                title=package.title,
                description=package.description,
                tags=tags_str,
                rating=rating,
            )

            return PostResult(
                success=True,
                external_id=external_id,
                external_url=result.get("url", ""),
                duration_seconds=self._elapsed(_t),
            )
        except Exception as e:
            logger.error("WS edit failed for %s: %s", external_id, e, exc_info=True)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))

    async def replace_file(self, external_id: str, file_path: str) -> PostResult:
        return PostResult(success=False, error="Weasyl does not support file replacement")

    def validate(self, package: StoryUploadPackage) -> list[str]:
        errors = super().validate(package)
        if len(package.tags) < 2:
            errors.append(f"Weasyl requires at least 2 tags (got {len(package.tags)})")
        return errors


def _rating_to_ws(rating: str) -> int:
    r = rating.lower()
    if r in ("adult", "explicit", "nsfw"):
        return 40
    elif r in ("mature", "questionable"):
        return 30
    return 10
