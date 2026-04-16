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
