"""Itaku platform poster.

Itaku is primarily an art gallery — stories are posted as text "posts"
(max ~5000 chars) or images are uploaded to the gallery. No chapter
system, no rich formatting for literature.

Auth: requires a Django REST Framework token extracted from the user's
browser session. No OAuth, no API keys. Token stored as ik_auth_token
in settings.

Image upload: POST /api/galleries/images/ (multipart)
Text post: POST /api/posts/ (JSON)

Rating mapping:
  General → "SFW"
  Mature → "Questionable"
  Adult → "NSFW"
"""

from __future__ import annotations

import logging

import config
from clients.ik.client import IKClient
from posting.platforms.base import PlatformPoster, PostResult, StoryUploadPackage

logger = logging.getLogger(__name__)


class ItakuPoster(PlatformPoster):

    platform_id = "ik"
    platform_name = "Itaku"
    supports_edit = False
    supports_file_replace = False
    min_post_interval = 5
    max_file_size = 10 * 1024 * 1024  # 10 MB for images
    accepted_file_types = ["png", "jpg", "jpeg", "gif", "webp", "mp4", "webm", "mov"]

    def __init__(self):
        self._client: IKClient | None = None

    async def _ensure_client(self) -> tuple[IKClient, str]:
        """Get client and auth token."""
        settings = config.get_settings()
        target_user = settings.get("ik_target_user", "")
        token = settings.get("ik_auth_token", "")
        if not token:
            raise RuntimeError("Itaku auth token not configured (ik_auth_token)")

        if not self._client:
            self._client = IKClient(target_user)
        return self._client, token

    async def post(self, package: StoryUploadPackage) -> PostResult:
        """Upload image or create text post on Itaku."""
        _t = self._start_timer()
        try:
            client, token = await self._ensure_client()

            rating = _rating_to_ik(package.rating)

            # If file is an image, upload to gallery
            if package.file_path and package.file_type in ("png", "jpg", "jpeg", "gif", "webp"):
                result = await client.upload_image(
                    package.file_path,
                    title=package.title,
                    description=package.description[:5000],
                    tags=package.tags[:59],  # Max 59 chars per tag
                    maturity_rating=rating,
                    token=token,
                )
                return PostResult(
                    success=True,
                    external_id=result.get("id", ""),
                    external_url=result.get("url", ""),
                    duration_seconds=self._elapsed(_t),
                )

            # Otherwise create a text post
            result = await client.create_post(
                title=package.title,
                content=package.description[:5000],
                tags=package.tags[:59],
                maturity_rating=rating,
                token=token,
            )
            return PostResult(
                success=True,
                external_id=result.get("id", ""),
                external_url=result.get("url", ""),
                duration_seconds=self._elapsed(_t),
            )

        except Exception as e:
            logger.error("IK post failed: %s", e, exc_info=True)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))

    async def edit(self, external_id: str, package: StoryUploadPackage) -> PostResult:
        """Itaku doesn't support editing via API."""
        return PostResult(success=False, error="Itaku does not support editing via API")

    async def replace_file(self, external_id: str, file_path: str) -> PostResult:
        """Itaku doesn't support file replacement."""
        return PostResult(success=False, error="Itaku does not support file replacement")

    def validate(self, package: StoryUploadPackage) -> list[str]:
        errors = []
        if len(package.tags) < 5:
            errors.append(f"Itaku requires at least 5 tags (got {len(package.tags)})")
        if package.file_path:
            import os
            if os.path.isfile(package.file_path):
                size = os.path.getsize(package.file_path)
                if size > self.max_file_size:
                    errors.append(f"File too large: {size / 1024 / 1024:.1f}MB (max 10MB)")
        return errors


def _rating_to_ik(rating: str) -> str:
    r = rating.lower()
    if r in ("adult", "explicit", "nsfw"):
        return "NSFW"
    elif r in ("mature", "questionable"):
        return "Questionable"
    return "SFW"
