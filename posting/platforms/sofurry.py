"""SoFurry platform poster.

Uses the existing SoFurryClient (sf_client/client.py) with session cookie +
CSRF token auth. Supports post + edit + file replace.

Post flow (3-step REST):
  1. PUT /ui/submission → create empty submission
  2. POST /ui/submission/{id}/content → upload file
  3. POST /ui/submission/{id} → set metadata + privacy

Edit flow:
  POST /ui/submission/{id} → update metadata

Rating mapping:
  General → 0 (Clean), Mature → 10, Adult → 20

Privacy mapping (SF supports a real draft state):
  privacy=1  Private    (owner-only — used by extra["draft"] = True)
  privacy=2  Unlisted   (accessible by direct link, not in feeds/search)
  privacy=3  Public     (default — listed in feeds/search)

Draft mode:
  Set ``package.extra["draft"] = True`` to create the submission as
  Private (privacy=1). The submission is uploaded with full content and
  metadata but ONLY the owner (logged in) can see it. Switch to public
  later via the SF UI or by calling ``edit_submission(privacy=3)``.

Visibility override:
  Set ``package.extra["privacy"] = 1|2|3`` (or "private"/"unlisted"/"public")
  to explicitly choose. Wins over the draft default.
"""

from __future__ import annotations

import logging

import config
from posting import story_reader
from posting.platforms.base import PlatformPoster, PostResult, StoryUploadPackage
from sf_client.client import SoFurryClient

logger = logging.getLogger(__name__)


_PRIVACY_PUBLIC = 3
_PRIVACY_UNLISTED = 2
_PRIVACY_PRIVATE = 1


def _normalize_privacy(value) -> int | None:
    """Convert a privacy override (int 1-3 or string) to the SF numeric code."""
    if value is None:
        return None
    if isinstance(value, int):
        return value if value in (1, 2, 3) else None
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("private", "1", "draft"):
            return _PRIVACY_PRIVATE
        if v in ("unlisted", "2"):
            return _PRIVACY_UNLISTED
        if v in ("public", "3"):
            return _PRIVACY_PUBLIC
    return None


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

    def _read_sf_chapter_content(self, story: story_reader.StoryInfo, ch_idx: int) -> str | None:
        """Read a single chapter's SoFurry HTML file path for upload."""
        ch = next((c for c in story.chapters if c.index == ch_idx), None)
        if not ch:
            return None

        sf_html = story.path / "Chapters" / "SoFurry_HTML"
        if sf_html.is_dir():
            base = ch.filename.replace(".md", "") if ch.filename else f"Chapter_{ch_idx}"
            exact = sf_html / f"{base}.html"
            if exact.is_file():
                return str(exact)
            for candidate in sorted(
                sf_html.glob(f"Chapter_{ch_idx}_*.html"),
                key=lambda c: len(c.name),
            ):
                return str(candidate)
        return None

    async def post(self, package: StoryUploadPackage) -> PostResult:
        """Create a new SoFurry submission, with chaptered support.

        For multi-chapter stories: creates the submission with chapter 1,
        then appends chapters 2..N via POST to /ui/submission/{id}/content
        (SF's content endpoint APPENDS chapters, it doesn't replace).

        Visibility behaviour:
          - Default: privacy=3 (Public) — listed in feeds and search
          - ``extra["draft"] = True`` → privacy=1 (Private) — owner-only
          - ``extra["privacy"] = 1|2|3`` → explicit override (wins over draft)

        Returns the submission ID and URL on success.
        """
        _t = self._start_timer()
        try:
            client = await self._ensure_client()

            # Resolve chapter 1 file (if chaptered) or full-story file
            story = story_reader.load_story(package.story_name)
            has_chapters = bool(story.chapters) and story.total_chapters > 1

            ch1_file = package.file_path
            if has_chapters:
                ch1_path = self._read_sf_chapter_content(story, 1)
                if ch1_path:
                    ch1_file = ch1_path

            if not ch1_file:
                return PostResult(
                    success=False, error="No file for SoFurry upload",
                    duration_seconds=self._elapsed(_t),
                )

            rating = _rating_to_sf(package.rating)

            # Determine privacy. extra["privacy"] wins over draft default.
            draft_mode = bool(package.extra.get("draft", False))
            explicit_privacy = _normalize_privacy(package.extra.get("privacy"))
            if explicit_privacy is not None:
                privacy = explicit_privacy
            elif draft_mode:
                privacy = _PRIVACY_PRIVATE
            else:
                privacy = _PRIVACY_PUBLIC

            privacy_label = {1: "Private", 2: "Unlisted", 3: "Public"}.get(privacy, str(privacy))
            logger.info(
                "SF: Posting %r as %s (draft=%s, privacy=%d, chapters=%d)",
                package.title, privacy_label, draft_mode, privacy,
                story.total_chapters if has_chapters else 1,
            )

            result = await client.create_submission(
                ch1_file,
                title=package.title,
                description=package.description,
                tags=package.tags,
                category=20,  # Writing
                sub_type=21,  # Short story
                rating=rating,
                privacy=privacy,
                thumbnail_path=package.thumbnail_path,
            )

            submission_id = result.get("submission_id", "")
            url = result.get("url", "")

            # Add remaining chapters (2..N) by POSTing each file to
            # /ui/submission/{id}/content — SF appends chapters on POST.
            if has_chapters and submission_id:
                csrf = await client._get_csrf_meta()
                remaining = [c for c in story.chapters if c.index > 1]
                for ch in sorted(remaining, key=lambda c: c.index):
                    ch_path = self._read_sf_chapter_content(story, ch.index)
                    if not ch_path:
                        logger.warning(
                            "SF: Skipping chapter %d for %s (no SoFurry HTML)",
                            ch.index, story.name,
                        )
                        continue
                    import os
                    with open(ch_path, "rb") as f:
                        file_data = f.read()
                    ch_resp = await client._http.post(
                        f"https://sofurry.com/ui/submission/{submission_id}/content",
                        headers={
                            "X-CSRF-TOKEN": csrf,
                            "Origin": "https://sofurry.com",
                            "Referer": "https://sofurry.com/",
                        },
                        files={"file": (os.path.basename(ch_path), file_data)},
                        timeout=60.0,
                    )
                    if ch_resp.status_code in (200, 201):
                        logger.info(
                            "SF: Added chapter %d to submission %s",
                            ch.index, submission_id,
                        )
                    else:
                        logger.warning(
                            "SF: Chapter %d upload returned %d for %s",
                            ch.index, ch_resp.status_code, submission_id,
                        )

            # SAFETY: when posting as draft/private, verify the submission
            # actually landed Private. The existing get_submission_detail
            # helper strips the privacy field, so we hit /ui/submission/{id}
            # raw and look for it ourselves.
            if privacy == _PRIVACY_PRIVATE and submission_id:
                try:
                    raw_resp = await client._http.get(
                        f"https://sofurry.com/ui/submission/{submission_id}",
                        headers={"Accept": "application/json"},
                    )
                    if raw_resp.status_code == 200:
                        raw = raw_resp.json()
                        server_privacy = raw.get("privacy")
                        if server_privacy is not None and int(server_privacy) != _PRIVACY_PRIVATE:
                            logger.warning(
                                "SF: SAFETY WARN — submission %s posted with privacy=%s "
                                "(expected 1/Private). Inspect at %s",
                                submission_id, server_privacy, url,
                            )
                        elif server_privacy is None:
                            logger.info(
                                "SF: post-flight check found no privacy field for %s "
                                "(API may not expose it); trusting create flow",
                                submission_id,
                            )
                        else:
                            logger.info(
                                "SF: verified submission %s is Private (privacy=1)",
                                submission_id,
                            )
                    else:
                        logger.warning(
                            "SF: post-flight verify status %d for %s — trusting create flow",
                            raw_resp.status_code, submission_id,
                        )
                except Exception as verify_err:
                    logger.warning(
                        "SF: post-flight privacy verification failed for %s: %s",
                        submission_id, verify_err,
                    )

            return PostResult(
                success=True,
                external_id=submission_id,
                external_url=url,
                duration_seconds=self._elapsed(_t),
            )
        except Exception as e:
            logger.error("SF post failed: %s", e, exc_info=True)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))

    async def edit(self, external_id: str, package: StoryUploadPackage) -> PostResult:
        """Edit metadata AND refresh content on an existing SoFurry submission.

        SF's edit_submission() only touches metadata (title/desc/tags/rating/
        privacy) — it does NOT replace the story content. To keep drifted
        local files in sync with what's on the platform, we also call
        replace_file() when a file is attached to the package. If the caller
        only wants a metadata refresh, they can set
        ``package.extra["skip_content_refresh"] = True``.

        By default this PRESERVES the existing privacy state (whatever the
        submission is currently set to on the server). To change privacy
        explicitly, set ``package.extra["privacy"]`` (1=Private, 2=Unlisted,
        3=Public) or use ``package.extra["draft"] = True`` for Private.
        """
        _t = self._start_timer()
        try:
            client = await self._ensure_client()
            rating = _rating_to_sf(package.rating)

            # Optional privacy override on edit (defaults: preserve current state)
            draft_mode = bool(package.extra.get("draft", False))
            explicit_privacy = _normalize_privacy(package.extra.get("privacy"))
            privacy: int | None
            if explicit_privacy is not None:
                privacy = explicit_privacy
            elif draft_mode:
                privacy = _PRIVACY_PRIVATE
            else:
                privacy = None  # None = preserve existing state on the server

            result = await client.edit_submission(
                external_id,
                title=package.title,
                description=package.description,
                tags=package.tags,
                rating=rating,
                privacy=privacy,
            )

            # Refresh the file on SF to match what we have locally. Skipped
            # when there's no file (shouldn't happen for SF normally) or
            # when the caller asks for a metadata-only edit.
            skip_content = bool(package.extra.get("skip_content_refresh", False))
            if package.file_path and not skip_content:
                file_result = await self.replace_file(external_id, package.file_path)
                if not file_result.success:
                    logger.warning(
                        "SF edit: metadata updated but content replace failed for %s: %s",
                        external_id, file_result.error,
                    )
                    return PostResult(
                        success=False,
                        external_id=external_id,
                        external_url=result.get("url", ""),
                        error=f"Metadata updated but content refresh failed: {file_result.error}",
                        duration_seconds=self._elapsed(_t),
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

    async def probe_exists(self, external_id: str) -> bool | None:
        """Check whether an SF submission still exists.

        Uses the authenticated client so drafts (privacy=1) are visible too.
        Returns False only when the server actively says the submission is
        gone (404 / deleted). Network errors return None so the caller
        doesn't incorrectly mark a still-live submission as deleted.
        """
        try:
            client = await self._ensure_client()
            if not client._logged_in:
                if not await client.ensure_logged_in():
                    return None
            resp = await client._http.get(
                f"https://sofurry.com/ui/submission/{external_id}",
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 404:
                return False
            if resp.status_code == 200:
                # Some platforms return a generic 200 with an error body when
                # the submission is gone. SF returns a JSON payload with
                # submission fields when it exists. If we get JSON with no
                # submissionId/title, treat it as missing.
                try:
                    data = resp.json()
                    if isinstance(data, dict) and not (data.get("id") or data.get("title")):
                        return False
                except Exception:
                    pass
                return True
            return None
        except Exception as e:
            logger.warning("SF probe_exists(%s) failed: %s", external_id, e)
            return None

    async def replace_file(self, external_id: str, file_path: str) -> PostResult:
        """Replace content on an existing SF submission.

        SF's POST /ui/submission/{id}/content APPENDS a new chapter —
        it does not replace. To update content we must:
          1. Fetch the submission to get existing content item IDs
          2. DELETE all existing content items
          3. POST the new content as a fresh upload

        This ensures the submission always has exactly one content item
        with the latest file.
        """
        _t = self._start_timer()
        try:
            client = await self._ensure_client()
            csrf = await client._get_csrf_meta()
            if not csrf:
                return PostResult(success=False, error="Could not get CSRF token", duration_seconds=self._elapsed(_t))

            api_headers = {
                "X-CSRF-TOKEN": csrf,
                "Origin": "https://sofurry.com",
                "Referer": "https://sofurry.com/",
                "Accept": "application/json",
            }

            # Step 1: Fetch current content items (to get old IDs for deletion)
            resp = await client._http.get(
                f"https://sofurry.com/ui/submission/{external_id}",
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                return PostResult(success=False, error=f"Could not fetch submission (status {resp.status_code})", duration_seconds=self._elapsed(_t))

            data = resp.json()
            old_content_ids = [c["contentId"] for c in data.get("content", []) if c.get("contentId")]
            title = data.get("title", "")

            # Step 2: Upload NEW content FIRST
            # SF won't allow deleting the last content item (returns 400).
            # By uploading first, we ensure there's always at least 1 item
            # remaining when we delete the old ones.
            import os
            with open(file_path, "rb") as f:
                file_data = f.read()

            upload_resp = await client._http.post(
                f"https://sofurry.com/ui/submission/{external_id}/content",
                headers={
                    "X-CSRF-TOKEN": csrf,
                    "Origin": "https://sofurry.com",
                    "Referer": "https://sofurry.com/",
                },
                files={"file": (os.path.basename(file_path), file_data)},
                timeout=60.0,
            )

            if upload_resp.status_code not in (200, 201):
                return PostResult(
                    success=False,
                    error=f"Content upload returned status {upload_resp.status_code}",
                    duration_seconds=self._elapsed(_t),
                )

            # Step 3: Delete OLD content items (the new one is safe)
            # Re-fetch CSRF in case the upload consumed it
            csrf2 = await client._get_csrf_meta()
            del_headers = {
                "X-CSRF-TOKEN": csrf2 or csrf,
                "Origin": "https://sofurry.com",
                "Referer": "https://sofurry.com/",
                "Accept": "application/json",
            }
            deleted = 0
            for cid in old_content_ids:
                del_resp = await client._http.request(
                    "DELETE",
                    f"https://sofurry.com/ui/submission/{external_id}/content/{cid}",
                    headers=del_headers,
                )
                if del_resp.status_code == 204:
                    deleted += 1
                    logger.info("SF: Deleted old content %s from %s", cid, external_id)
                else:
                    logger.warning("SF: Failed to delete old content %s (status %d)", cid, del_resp.status_code)

            # Step 4: Set chapter title on the new content item
            try:
                resp2 = await client._http.get(
                    f"https://sofurry.com/ui/submission/{external_id}",
                    headers={"Accept": "application/json"},
                )
                new_content = resp2.json().get("content", [])
                if new_content:
                    new_cid = new_content[-1]["contentId"]  # newest = last
                    if not new_content[-1].get("title") or new_content[-1].get("title") != title:
                        await client._http.post(
                            f"https://sofurry.com/ui/submission/{external_id}/content/{new_cid}",
                            headers=del_headers,
                            json={"title": title},
                            timeout=15.0,
                        )
                        logger.info("SF: Set chapter title '%s' on new content %s", title, new_cid)
            except Exception as title_err:
                logger.warning("SF: Could not set chapter title: %s", title_err)

            logger.info("SF: Replaced content on submission %s (uploaded new, deleted %d old)", external_id, deleted)
            return PostResult(
                success=True,
                external_id=external_id,
                external_url=f"https://sofurry.com/s/{external_id}",
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
