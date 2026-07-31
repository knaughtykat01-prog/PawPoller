"""FurryNetwork platform poster.

FurryNetwork is an art gallery where work lives under a **character**. We upload
one image (chunked/resumable) under a character, then PATCH the metadata
(title/description/tags/rating/status) via the OAuth2 API — the same email+password
token used for polling. Server-side posting works (the API host isn't datacenter-
blocked, unlike FurAffinity).

The character is chosen from ``package.extra["fn_character"]`` if set, else the
account's default/first character. Rating maps general/mature/adult → FN 0/1/2
inside the client.
"""
from __future__ import annotations

import logging

import config
from clients.fn.client import FnClient
from posting.platforms.base import PlatformPoster, PostResult, StoryUploadPackage

logger = logging.getLogger(__name__)


class FurryNetworkPoster(PlatformPoster):

    platform_id = "fn"
    platform_name = "FurryNetwork"
    supports_edit = False
    supports_file_replace = False
    min_post_interval = 5
    max_file_size = 50 * 1024 * 1024
    accepted_file_types = ["png", "jpg", "jpeg", "gif", "webp"]
    requires_mode = "any"              # OAuth API works from the server

    def __init__(self):
        self._client: FnClient | None = None

    async def _ensure_client(self) -> FnClient:
        settings = config.get_settings()
        creds = self._resolve_creds("fn", settings)
        if not (creds.get("fn_username") and
                (creds.get("fn_password") or creds.get("fn_refresh_token"))):
            raise RuntimeError("FurryNetwork credentials not configured "
                               "(connect in Settings → Platforms → FurryNetwork)")
        if self._client is None:
            self._client = FnClient(
                username=creds.get("fn_username", ""), password=creds.get("fn_password", ""),
                access_token=creds.get("fn_access_token", ""),
                refresh_token=creds.get("fn_refresh_token", ""))
        else:
            self._client.username = creds.get("fn_username", "")
            self._client.password = creds.get("fn_password", "")
            if creds.get("fn_refresh_token"):
                self._client.refresh_token = creds["fn_refresh_token"]
        return self._client

    async def _resolve_character(self, client: FnClient, package: StoryUploadPackage) -> str:
        override = str((package.extra or {}).get("fn_character", "") or "").strip()
        if override:
            return override
        chars = await client.get_characters()
        if not chars:
            raise RuntimeError("No FurryNetwork character found on this account")
        # Prefer the account's default character if flagged, else the first.
        default = next((c for c in chars if c.get("default")), None)
        return (default or chars[0]).get("name", "")

    async def post(self, package: StoryUploadPackage) -> PostResult:
        """Upload one image to FurryNetwork under a character."""
        _t = self._start_timer()
        try:
            client = await self._ensure_client()
            await client.login()
            character = await self._resolve_character(client, package)
            if not character:
                raise RuntimeError("Could not resolve a FurryNetwork character to post under")
            result = await client.upload_artwork(
                character=character,
                file_path=package.file_path or "",
                title=package.title or "",
                description=package.description or "",
                tags=list(package.tags or []),
                rating=package.rating or "general",
                status="public",
            )
            if not result.get("success"):
                return PostResult(success=False, error=result.get("error", "upload failed"),
                                  duration_seconds=self._elapsed(_t))
            return PostResult(success=True, external_id=result.get("id", ""),
                              external_url=result.get("url", ""),
                              duration_seconds=self._elapsed(_t))
        except Exception as e:
            logger.error("FurryNetwork post failed: %s", e, exc_info=True)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))

    async def edit(self, external_id: str, package: StoryUploadPackage) -> PostResult:
        return PostResult(success=False, error="FurryNetwork editing not supported yet")

    async def replace_file(self, external_id: str, file_path: str) -> PostResult:
        return PostResult(success=False, error="FurryNetwork does not support file replacement")

    def validate(self, package: StoryUploadPackage) -> list[str]:
        errors: list[str] = []
        if not package.file_path:
            errors.append("FurryNetwork requires an image file")
        if not package.title:
            errors.append("Title is required")
        if package.file_path:
            import os
            if os.path.isfile(package.file_path):
                size = os.path.getsize(package.file_path)
                if size > self.max_file_size:
                    errors.append(f"File too large: {size / 1024 / 1024:.1f}MB "
                                  f"(max {self.max_file_size / 1024 / 1024:.0f}MB)")
        return errors
