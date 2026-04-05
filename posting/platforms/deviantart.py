"""DeviantArt platform poster via official OAuth2 API.

Uses the DeviantArt OAuth2 literature endpoints (not the undocumented
_napi/_puppy endpoints). This is stable and works from any IP.

Setup required:
  1. Register a DA app at the developer portal → get client_id + client_secret
  2. Do one-time Authorization Code flow in browser → get refresh_token
  3. Store da_client_id, da_client_secret, da_refresh_token in settings
  4. Access tokens auto-refresh (1-hour expiry, 3-month refresh token)

Post flow:
  POST /api/v1/oauth2/deviation/literature/create

Edit flow:
  POST /api/v1/oauth2/deviation/literature/update/{id}

Rating mapping:
  General → is_mature=false
  Mature → is_mature=true, mature_level="moderate"
  Adult → is_mature=true, mature_level="strict", mature_classification=["sexual"]
"""

from __future__ import annotations

import logging
import time

import config
from da_client.client import DAClient
from posting.platforms.base import PlatformPoster, PostResult, StoryUploadPackage

logger = logging.getLogger(__name__)


class DeviantArtPoster(PlatformPoster):

    platform_id = "da"
    platform_name = "DeviantArt"
    supports_edit = True
    supports_file_replace = False  # Update endpoint replaces body content
    min_post_interval = 5
    max_file_size = 0  # No file upload — body text
    accepted_file_types = ["txt", "md"]

    def __init__(self):
        self._client: DAClient | None = None
        self._access_token: str = ""
        self._token_expires_at: float = 0.0

    async def _ensure_client(self) -> tuple[DAClient, str]:
        """Get client and a valid access token."""
        settings = config.get_settings()

        client_id = settings.get("da_client_id", "")
        client_secret = settings.get("da_client_secret", "")
        refresh_token = settings.get("da_refresh_token", "")

        if not client_id or not client_secret or not refresh_token:
            raise RuntimeError(
                "DeviantArt OAuth not configured. Set da_client_id, "
                "da_client_secret, and da_refresh_token in settings."
            )

        if not self._client:
            self._client = DAClient(
                cookie=settings.get("da_cookie", ""),
                target_user=settings.get("da_target_user", ""),
            )

        # Refresh access token if expired or missing
        if not self._access_token or time.time() >= self._token_expires_at:
            data = await self._client.oauth_refresh_token(
                client_id, client_secret, refresh_token,
            )
            self._access_token = data.get("access_token", "")
            expires_in = data.get("expires_in", 3600)
            self._token_expires_at = time.time() + expires_in - 60  # 1-min buffer

            # Update refresh token if a new one was issued
            new_refresh = data.get("refresh_token", "")
            if new_refresh and new_refresh != refresh_token:
                config.save_settings({"da_refresh_token": new_refresh})
                logger.info("DA: Stored new refresh token")

        return self._client, self._access_token

    async def post(self, package: StoryUploadPackage) -> PostResult:
        """Create a literature deviation on DeviantArt."""
        _t = self._start_timer()
        try:
            client, token = await self._ensure_client()

            # Read story content
            body = ""
            if package.file_path:
                with open(package.file_path, "r", encoding="utf-8") as f:
                    body = f.read()
            if not body:
                body = package.description

            is_mature, mature_level, mature_class = _rating_to_da(package.rating)

            result = await client.oauth_create_literature(
                title=package.title[:50],
                body=body,
                tags=package.tags[:30],
                is_mature=is_mature,
                mature_level=mature_level,
                mature_classification=mature_class,
                access_token=token,
            )

            dev_id = result.get("deviationid", "")
            url = result.get("url", "")
            return PostResult(
                success=True,
                external_id=dev_id,
                external_url=url,
                duration_seconds=self._elapsed(_t),
            )
        except Exception as e:
            logger.error("DA post failed: %s", e, exc_info=True)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))

    async def edit(self, external_id: str, package: StoryUploadPackage) -> PostResult:
        """Update a literature deviation on DeviantArt."""
        _t = self._start_timer()
        try:
            client, token = await self._ensure_client()

            body = None
            if package.file_path:
                with open(package.file_path, "r", encoding="utf-8") as f:
                    body = f.read()

            is_mature, _, _ = _rating_to_da(package.rating)

            await client.oauth_update_literature(
                external_id,
                title=package.title[:50],
                body=body,
                tags=package.tags[:30],
                is_mature=is_mature,
                access_token=token,
            )

            return PostResult(
                success=True,
                external_id=external_id,
                external_url=f"https://www.deviantart.com/knaughtykat/art/{external_id}",
                duration_seconds=self._elapsed(_t),
            )
        except Exception as e:
            logger.error("DA edit failed for %s: %s", external_id, e, exc_info=True)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))

    async def replace_file(self, external_id: str, file_path: str) -> PostResult:
        """Replace body content via the update endpoint."""
        _t = self._start_timer()
        try:
            client, token = await self._ensure_client()

            with open(file_path, "r", encoding="utf-8") as f:
                body = f.read()

            await client.oauth_update_literature(
                external_id,
                body=body,
                access_token=token,
            )

            return PostResult(
                success=True,
                external_id=external_id,
                external_url=f"https://www.deviantart.com/knaughtykat/art/{external_id}",
                duration_seconds=self._elapsed(_t),
            )
        except Exception as e:
            logger.error("DA file replace failed for %s: %s", external_id, e)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))

    def validate(self, package: StoryUploadPackage) -> list[str]:
        errors = []
        if len(package.title) > 50:
            errors.append(f"DA title max 50 chars (got {len(package.title)})")
        if len(package.tags) > 30:
            errors.append(f"DA max 30 tags (got {len(package.tags)})")
        return errors


def _rating_to_da(rating: str) -> tuple[bool, str, list[str]]:
    """Convert rating to DA's mature settings.

    Returns (is_mature, mature_level, mature_classification).
    """
    r = rating.lower()
    if r in ("adult", "explicit", "nsfw"):
        return True, "strict", ["sexual"]
    elif r in ("mature", "questionable"):
        return True, "moderate", []
    return False, "", []
