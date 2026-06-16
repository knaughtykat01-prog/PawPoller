"""Abstract base class for platform posting implementations.

Each platform poster wraps the existing PawPoller client (e.g. InkbunnyClient,
BskyClient) and adds upload/edit/replace methods. The base class enforces a
consistent interface so the PostingManager can treat all platforms the same.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class PostResult:
    """Result of a posting operation (upload, edit, or file replace)."""
    success: bool
    external_id: str = ""
    external_url: str = ""
    error: str | None = None
    duration_seconds: float = 0.0


@dataclass
class StoryUploadPackage:
    """Everything needed to post one chapter/story to one platform."""
    story_name: str
    chapter_index: int              # 0 = full story, 1+ = chapter number
    chapter_title: str
    platform: str                   # 'ib', 'fa', 'ws', 'sf', 'bsky'
    title: str
    description: str
    tags: list[str] = field(default_factory=list)
    rating: str = ""                # Platform-specific rating value
    file_path: str | None = None    # Absolute path to format file
    file_type: str = ""             # 'bbcode', 'pdf', 'html', 'text'
    word_count: int = 0
    thumbnail_path: str | None = None
    extra: dict = field(default_factory=dict)


class PlatformPoster(ABC):
    """Base class for all platform posting implementations."""

    platform_id: str = ""
    platform_name: str = ""
    supports_edit: bool = False
    supports_file_replace: bool = False
    min_post_interval: int = 5      # Seconds between consecutive posts
    max_file_size: int = 0          # Bytes (0 = no limit)
    accepted_file_types: list[str] = []
    requires_mode: str = "any"      # "any", "desktop", or "server"
    # Which account to post as. Set by manager._get_poster; None = the
    # platform's default account. Account-aware posters (IB, FA) read it in
    # _ensure_client to authenticate as the right account.
    account_id: int | None = None

    def _resolve_creds(self, platform: str, settings: dict | None = None) -> dict:
        """Return this poster's account's credentials, keyed by canonical field.

        Resolves ``self.account_id`` (set by manager._get_poster; None → the
        platform's default account) to its credential set via
        ``config.resolve_account_credentials``. Posters call this in
        ``_ensure_client`` instead of reading flat ``settings.get(...)`` so they
        authenticate as the selected account.
        """
        import config
        from database.db import get_connection
        from database import accounts as _accts
        conn = get_connection()
        try:
            acct_id = self.account_id
            if acct_id is None:
                acct_id = _accts.get_default_account_id(conn, platform, create=True)
                self.account_id = acct_id
            acct = _accts.get_account(conn, acct_id)
            is_default = bool(acct["is_default"]) if acct else True
        finally:
            conn.close()
        return config.resolve_account_credentials(platform, acct_id, is_default, settings)

    @abstractmethod
    async def post(self, package: StoryUploadPackage) -> PostResult:
        """Upload a new submission to the platform."""
        ...

    @abstractmethod
    async def edit(self, external_id: str, package: StoryUploadPackage) -> PostResult:
        """Edit metadata on an existing submission."""
        ...

    @abstractmethod
    async def replace_file(self, external_id: str, file_path: str) -> PostResult:
        """Replace the file on an existing submission."""
        ...

    async def probe_exists(self, external_id: str) -> bool | None:
        """Check whether a previously-posted submission still exists on the platform.

        Returns:
            True  — confirmed still present
            False — confirmed deleted / missing
            None  — probe not implemented for this platform, caller should
                    not draw conclusions from the result
        """
        return None

    async def probe_draft_state(self, external_id: str) -> bool | None:
        """Check whether a previously-posted submission is sitting as a draft.

        "Draft" semantics vary by platform: FA has no real drafts, so its
        implementation reads the Scraps flag (hidden from gallery/browse/
        search but still on the profile + visible to watchers). IB exposes
        an explicit visibility/hold state. SF flags works as published or
        unpublished. AO3/SQW have a `posted: false` state.

        Returns:
            True  — confirmed draft / not publicly listed
            False — confirmed live / publicly listed
            None  — probe not implemented for this platform
        """
        return None

    def validate(self, package: StoryUploadPackage) -> list[str]:
        """Validate a package before posting. Returns list of errors (empty = OK)."""
        errors = []
        if not package.title:
            errors.append("Title is required")
        if not package.tags:
            errors.append("At least one tag is required")
        if package.file_path:
            import os
            if not os.path.isfile(package.file_path):
                errors.append(f"File not found: {package.file_path}")
            elif self.max_file_size > 0:
                size = os.path.getsize(package.file_path)
                if size > self.max_file_size:
                    errors.append(
                        f"File too large: {size / 1024 / 1024:.1f}MB "
                        f"(max {self.max_file_size / 1024 / 1024:.1f}MB)"
                    )
        return errors

    async def _rate_limit(self) -> None:
        """Sleep for the platform's minimum post interval."""
        import asyncio
        await asyncio.sleep(self.min_post_interval)

    @staticmethod
    def _start_timer() -> float:
        """Start a timer. Call _elapsed(start) to get seconds elapsed."""
        return time.monotonic()

    @staticmethod
    def _elapsed(start: float) -> float:
        """Return seconds elapsed since _start_timer()."""
        return time.monotonic() - start
