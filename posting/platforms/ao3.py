"""Archive of Our Own (AO3) platform poster.

Wraps the AO3Client to upload, edit, and manage works on AO3.

Pulls full metadata from story.json via posting.story_reader, including
fandom, category, characters, relationships, warnings.

Posting flow (single-bulk-file convention, mirrors the IB convention):
  1. Read StoryInfo from the archive (story.json)
  2. Trim freeform tags to fit OTW's 75-tag total limit
     (fandom + relationship + character + freeform <= 75)
  3. Read full-story body-only HTML (HTML/<story>_Clean.html)
  4. create_work via preview_button — work lands in /works/{id}/preview
     (AO3's draft equivalent), NOT published
  5. SAFETY: verify the new work is in /users/{user}/works/drafts.
     If it ever lands in published, the work is DELETED and the call fails.

Edit flow:
  1. Read StoryInfo
  2. Detect current state (draft vs published)
  3. Edit metadata via edit_work
  4. Iterate AO3's chapter list and update each chapter's content via
     edit_chapter

Rating mapping:
  explicit -> "Explicit"
  mature   -> "Mature"
  teen     -> "Teen And Up Audiences"
  general  -> "General Audiences"

Notes for the AO3-vs-SQW differences:
  - AO3 client does NOT yet support multi-chapter create_chapter or Work
    Skins. For chaptered prose we use the IB-style single bulk file
    (HTML/<story>_Clean.html) which contains all chapters as <p> elements
    in one big body.
  - AO3 has no "preview" → "publish" automated flow here. Work stays in
    preview/draft until you manually click Post on AO3.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import config
from posting import story_reader
from posting.platforms.base import PlatformPoster, PostResult, StoryUploadPackage
from ao3_client.client import AO3Client

logger = logging.getLogger(__name__)


# OTW Archive total-tag limit (fandom + relationship + character + freeform).
# Rating, warnings, categories do NOT count toward this.
OTW_TAG_LIMIT = 75


class AO3Poster(PlatformPoster):

    platform_id = "ao3"
    platform_name = "AO3"
    supports_edit = True
    supports_file_replace = True
    min_post_interval = 5
    max_file_size = 0  # Content pasted as HTML, no file upload
    accepted_file_types = ["html"]

    def __init__(self):
        self._client: AO3Client | None = None

    async def _ensure_client(self) -> AO3Client:
        if self._client and self._client._logged_in:
            return self._client

        settings = config.get_settings()
        username = settings.get("ao3_username", "")
        password = settings.get("ao3_password", "")
        target_user = settings.get("ao3_target_user", "") or username
        if not username or not password:
            raise RuntimeError("AO3 credentials not configured")

        self._client = AO3Client(username, password, target_user)
        if not await self._client.ensure_logged_in():
            raise RuntimeError("AO3 login failed")
        return self._client

    # ─── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _rating_to_ao3(rating: str) -> str:
        r = (rating or "").lower()
        if r in ("adult", "explicit", "nsfw"):
            return "Explicit"
        if r in ("mature", "questionable"):
            return "Mature"
        if r == "teen":
            return "Teen And Up Audiences"
        return "General Audiences"

    @staticmethod
    def _trim_freeform_tags(
        tags: list[str],
        characters: list[str],
        relationships: list[str],
        fandom: str,
    ) -> list[str]:
        """Trim freeform tags so the total fits OTW's 75-tag limit."""
        used = 0
        if fandom:
            used += 1
        used += len(characters)
        used += len(relationships)
        budget = OTW_TAG_LIMIT - used
        if budget <= 0:
            return []
        if len(tags) <= budget:
            return tags
        return tags[:budget]

    async def _ensure_work_skin(
        self,
        client: AO3Client,
        story: story_reader.StoryInfo,
    ) -> str:
        """Find or create the Work Skin for this story and sync the CSS.

        Ports the SquidgeWorld poster's behaviour — both platforms run the
        OTW Archive software, so the endpoints and skin conventions are
        identical. Returns the skin_id, or '' if the story doesn't have a
        Work_Skin.css file (in which case no skin gets applied).

        Behavior:
          1. No Work_Skin.css → return '' (no skin applied)
          2. Skin doesn't exist by title → create new with current CSS
          3. Skin exists → push current CSS + description via edit_work_skin
             so local edits propagate on every post/edit. Best-effort —
             if the refresh fails, log and return the existing skin_id.
        """
        if not story.work_skin_path or not story.work_skin_path.is_file():
            return ""

        skin_title = f"{story.name.replace('_', ' ')} Skin"
        skin_description = (
            f"Custom Work Skin for '{story.name.replace('_', ' ')}' by {story.author}."
        )

        try:
            css = story.work_skin_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(
                "AO3: Could not read Work_Skin.css for %s: %s", story.name, e,
            )
            return ""

        try:
            existing = await client.find_work_skin_by_title(skin_title)
        except Exception as e:
            logger.warning(
                "AO3: Could not search for existing Work Skin for %s: %s",
                story.name, e,
            )
            existing = None

        if existing:
            skin_id = existing
            try:
                await client.edit_work_skin(
                    skin_id,
                    title=skin_title,
                    description=skin_description,
                    css=css,
                )
                logger.info(
                    "AO3: Refreshed Work Skin %s (%s) with current CSS",
                    skin_id, skin_title,
                )
            except Exception as e:
                logger.warning(
                    "AO3: Could not refresh Work Skin %s for %s: %s "
                    "(using existing CSS on AO3)",
                    skin_id, story.name, e,
                )
            return skin_id

        try:
            result = await client.create_work_skin(
                title=skin_title, css=css, description=skin_description,
            )
            return result["skin_id"]
        except Exception as e:
            logger.warning("AO3: Work skin creation failed for %s: %s", story.name, e)
            return ""

    async def probe_exists(self, external_id: str) -> bool | None:
        """Check whether an AO3 work still exists.

        Uses the authenticated client so drafts are visible. Hits the
        work's edit page — AO3 returns 404 for deleted works and 200 (or
        a redirect to the work) for live ones. Returns None on transient
        errors (Cloudflare hiccups, timeouts) so we don't falsely mark
        still-alive works as deleted.
        """
        try:
            client = await self._ensure_client()
            if not client._logged_in:
                if not await client.ensure_logged_in():
                    return None
            resp = await client._http.get(
                f"https://archiveofourown.org/works/{external_id}/edit",
                follow_redirects=False,
            )
            if resp.status_code == 404:
                return False
            if 200 <= resp.status_code < 400:
                return True
            return None
        except Exception as e:
            logger.warning("AO3 probe_exists(%s) failed: %s", external_id, e)
            return None

    @staticmethod
    def _read_chapter_content(story: story_reader.StoryInfo, ch_idx: int) -> str | None:
        """Resolve a single chapter's body HTML for AO3.

        Uses the SquidgeWorld/ per-chapter files (same OTW Archive format),
        falling back to Chapters/SoFurry_HTML/ as a last resort.
        """
        ch = next((c for c in story.chapters if c.index == ch_idx), None)
        if not ch:
            return None

        sqw_dir = story.path / "SquidgeWorld"
        if sqw_dir.is_dir():
            base = ch.filename.replace(".md", "") if ch.filename else f"Chapter_{ch_idx}"
            for candidate in sqw_dir.glob(f"{base}*"):
                if candidate.suffix == ".html":
                    try:
                        return candidate.read_text(encoding="utf-8")
                    except Exception:
                        pass
            for candidate in sorted(sqw_dir.glob(f"Chapter_{ch_idx}_*.html")):
                try:
                    return candidate.read_text(encoding="utf-8")
                except Exception:
                    pass

        sf_html = story.path / "Chapters" / "SoFurry_HTML"
        if sf_html.is_dir():
            for candidate in sorted(sf_html.glob(f"Chapter_{ch_idx}_*.html")):
                try:
                    return candidate.read_text(encoding="utf-8")
                except Exception:
                    pass

        return None

    @staticmethod
    def _read_full_story_html(story: story_reader.StoryInfo) -> str | None:
        """Read the body-only full-story HTML for AO3.

        Order of preference:
          1. HTML/<Story>_Clean.html (single bulk file, body-only paragraphs)
          2. Concatenate SquidgeWorld/Chapter_*.html files (body-only)
        """
        html_dir = story.path / "HTML"
        if html_dir.is_dir():
            for f in sorted(html_dir.glob("*_Clean.html")):
                try:
                    return f.read_text(encoding="utf-8")
                except Exception:
                    pass

        # Fallback: concatenate SquidgeWorld chapter files
        sqw_dir = story.path / "SquidgeWorld"
        if sqw_dir.is_dir():
            chapters: list[str] = []
            for ch in sorted(story.chapters, key=lambda c: c.index):
                # Match Chapter_<idx>_*.html
                matches = sorted(sqw_dir.glob(f"Chapter_{ch.index}_*.html"))
                if not matches:
                    continue
                try:
                    body = matches[0].read_text(encoding="utf-8")
                    chapters.append(body)
                except Exception:
                    pass
            if chapters:
                return "\n<hr />\n".join(chapters)

        return None

    def _build_freeform_tags(
        self,
        story: story_reader.StoryInfo,
        package: StoryUploadPackage,
    ) -> list[str]:
        """Choose the freeform tag list — prefer package.tags, then story tags."""
        if package.tags:
            return list(package.tags)
        ao3_tags = story.tags_by_platform.get("ao3")
        if ao3_tags:
            return list(ao3_tags)
        sqw_tags = story.tags_by_platform.get("sqw")
        if sqw_tags:
            return list(sqw_tags)
        return list(story.tags_by_platform.get("default", []))

    # ─── Posting / Editing ────────────────────────────────────────────

    async def post(self, package: StoryUploadPackage) -> PostResult:
        """Create a new work on AO3 with full metadata, single bulk content.

        SAFETY: AO3's create_work uses preview_button so the work lands in
        /works/{id}/preview (drafts) by default. After creation, this method
        verifies the work is in the user's drafts listing. If it has been
        published unexpectedly, the work is DELETED and the call fails.
        Set ``package.extra["allow_publish"] = True`` to skip the safety
        check (e.g. for re-publishing already-live works).
        """
        _t = self._start_timer()
        allow_publish = bool(package.extra.get("allow_publish", False))

        async def _verify_still_draft(client_inst, work_id_inner: str, step: str) -> None:
            """Best-effort verification that the work is in draft state.

            create_work uses preview_button which AO3 guarantees creates a
            preview/draft. The check below is a defensive net for the
            impossible case of accidental publish — it ONLY aborts on
            POSITIVE confirmation the work is published.

            States from is_work_published:
              True  -> definitely published    -> abort + delete
              False -> definitely not          -> safe, return
              None  -> fetch failed (timeout)  -> warn but trust preview_button
            """
            if allow_publish:
                return
            await asyncio.sleep(2)  # let AO3 catch up
            in_published = await client_inst.is_work_published(work_id_inner)
            if in_published is True:
                # Confirmed published — try to delete
                try:
                    await client_inst.delete_work(work_id_inner)
                    msg = (
                        f"AO3: SAFETY ABORT after {step} — work {work_id_inner} "
                        f"is published. Work has been DELETED."
                    )
                except Exception as del_err:
                    msg = (
                        f"AO3: SAFETY ABORT after {step} — work {work_id_inner} "
                        f"is published and DELETE FAILED: {del_err}. "
                        f"MANUAL DELETE: https://archiveofourown.org/works/{work_id_inner}/confirm_delete"
                    )
                raise RuntimeError(msg)
            elif in_published is None:
                # Fetch failed — trust preview_button, log a warning
                logger.warning(
                    "AO3: post-flight is_work_published check failed for %s after %s. "
                    "create_work used preview_button so the work is in draft state by "
                    "construction; trusting that. Verify manually if concerned.",
                    work_id_inner, step,
                )
            # in_published is False -> definitely not published, safe

        try:
            client = await self._ensure_client()
            story = story_reader.load_story(package.story_name)

            # 1. Build metadata
            rating = self._rating_to_ao3(story.rating or package.rating)
            categories = story.categories or ([story.category] if story.category else [])
            warnings = story.warnings or ["No Archive Warnings Apply"]
            characters_str = ", ".join(story.characters)
            relationships_str = ", ".join(story.relationships)
            fandom = story.fandom or "Original Work"

            # 2. Trim freeform tags to fit OTW's 75-tag limit
            freeform_tags = self._build_freeform_tags(story, package)
            freeform_tags = self._trim_freeform_tags(
                freeform_tags, story.characters, story.relationships, fandom,
            )
            additional_tags = ", ".join(freeform_tags)

            # 3. Decide content strategy.
            # Multi-chapter story → create work with Ch1, then create_chapter
            # for Ch2..N (mirrors the SQW flow so AO3 works match the source
            # chapter structure).
            # Single-chapter story / no chapter_info → use the full-story
            # Clean HTML as one chapter.
            has_chapters = bool(story.chapters) and story.total_chapters > 1

            if has_chapters:
                chapter_1 = next((c for c in story.chapters if c.index == 1), None)
                chapter_1_title = chapter_1.title if chapter_1 else "Chapter 1"
                content = self._read_chapter_content(story, 1)
                if not content:
                    return PostResult(
                        success=False,
                        error=f"No AO3 content for {story.name} chapter 1",
                        duration_seconds=self._elapsed(_t),
                    )
            else:
                chapter_1_title = ""
                content = self._read_full_story_html(story)
                if not content and package.file_path:
                    with open(package.file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                if not content:
                    return PostResult(
                        success=False,
                        error=f"No AO3 content for {story.name} (no HTML/<story>_Clean.html and no fallback)",
                        duration_seconds=self._elapsed(_t),
                    )

            # 4. Title + summary
            work_title = package.title or story.name.replace("_", " ")
            summary = (story.description or package.description or "")[:1250]

            # 4b. Ensure the Work Skin exists and is up-to-date (no-op if
            # the story has no Work_Skin.css). Done BEFORE create_work so
            # the skin_id can be passed through.
            skin_id = await self._ensure_work_skin(client, story)

            # 5. Create the work in preview/draft state (with ch1 content)
            create_kwargs: dict = dict(
                title=work_title,
                content=content,
                fandom=fandom,
                rating=rating,
                warnings=warnings,
                categories=categories,
                relationship=relationships_str,
                characters=characters_str,
                additional_tags=additional_tags,
                summary=summary,
                language_id="1",  # AO3 English (numeric, like SQW's "15")
                work_skin_id=skin_id,
            )
            if chapter_1_title:
                create_kwargs["chapter_title"] = chapter_1_title
            create_result = await client.create_work(**create_kwargs)
            work_id = create_result["work_id"]
            url = create_result.get("url", f"https://archiveofourown.org/works/{work_id}")
            logger.info("AO3: Created work %s for %s — %s", work_id, story.name, url)

            # SAFETY: verify the new work is in drafts
            await _verify_still_draft(client, work_id, "create_work")

            # 6. Add remaining chapters (Ch2..N) as drafts.
            # publish=False keeps the work in its current (draft) state —
            # the OTW preview_button flow adds the chapter without flipping
            # the work to published, verified by SQW's test suite.
            if has_chapters:
                remaining = [c for c in story.chapters if c.index > 1]
                for ch in sorted(remaining, key=lambda c: c.index):
                    ch_content = self._read_chapter_content(story, ch.index)
                    if not ch_content:
                        logger.warning(
                            "AO3: Skipping chapter %d for %s (no content found)",
                            ch.index, story.name,
                        )
                        continue
                    await client.create_chapter(
                        work_id,
                        title=ch.title,
                        content=ch_content,
                        position=ch.index,
                        publish=False,
                    )
                    logger.info(
                        "AO3: Added chapter %d to %s (work_id=%s)",
                        ch.index, story.name, work_id,
                    )
                    # SAFETY: verify still draft after each chapter
                    await _verify_still_draft(
                        client, work_id, f"create_chapter ch{ch.index}",
                    )

            return PostResult(
                success=True,
                external_id=work_id,
                external_url=url,
                duration_seconds=self._elapsed(_t),
            )
        except Exception as e:
            logger.error("AO3 post failed: %s", e, exc_info=True)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))

    async def edit(self, external_id: str, package: StoryUploadPackage) -> PostResult:
        """Edit an existing AO3 work — metadata + per-chapter content refresh.

        For multi-chapter stories, iterates AO3's chapters in order and
        updates each one's content from the matching SquidgeWorld HTML
        file. Chapters present on AO3 beyond the local story length are
        left alone; chapters present locally but missing on AO3 are
        appended via create_chapter. Chapter count/order should match
        the local source after this call.
        """
        _t = self._start_timer()
        try:
            client = await self._ensure_client()
            story = story_reader.load_story(package.story_name)

            freeform_tags = self._build_freeform_tags(story, package)
            freeform_tags = self._trim_freeform_tags(
                freeform_tags, story.characters, story.relationships,
                story.fandom or "Original Work",
            )
            additional_tags = ", ".join(freeform_tags)

            # Ensure work skin is synced — reuses existing skin by title,
            # pushes the current CSS, then assigns it to the work.
            skin_id = await self._ensure_work_skin(client, story)

            await client.edit_work(
                external_id,
                title=package.title or story.name.replace("_", " "),
                summary=(story.description or package.description or "")[:1250],
                additional_tags=additional_tags,
                work_skin_id=skin_id if skin_id else None,
            )
            logger.info("AO3: Updated work %s metadata", external_id)

            # Update chapter content. Multi-chapter: edit each existing
            # chapter from local source; append any extras. Single-chapter:
            # fall back to the full-story Clean HTML blob (unchanged behaviour).
            try:
                ao3_chapters = await client.get_chapter_ids(external_id)
                has_chapters = bool(story.chapters) and story.total_chapters > 1

                if has_chapters:
                    local_chapters = sorted(story.chapters, key=lambda c: c.index)
                    for ao3_ch, local_ch in zip(ao3_chapters, local_chapters):
                        ch_content = self._read_chapter_content(story, local_ch.index)
                        if not ch_content:
                            logger.warning(
                                "AO3: Skipping ch%d edit for %s (no content)",
                                local_ch.index, story.name,
                            )
                            continue
                        await client.edit_chapter(
                            external_id, ao3_ch["chapter_id"],
                            title=local_ch.title, content=ch_content,
                        )
                        logger.info(
                            "AO3: Updated chapter %s (local idx %d) of work %s",
                            ao3_ch["chapter_id"], local_ch.index, external_id,
                        )

                    # Append any local chapters that aren't on AO3 yet
                    if len(local_chapters) > len(ao3_chapters):
                        for local_ch in local_chapters[len(ao3_chapters):]:
                            ch_content = self._read_chapter_content(story, local_ch.index)
                            if not ch_content:
                                continue
                            await client.create_chapter(
                                external_id,
                                title=local_ch.title,
                                content=ch_content,
                                position=local_ch.index,
                                publish=False,
                            )
                            logger.info(
                                "AO3: Appended missing ch%d to work %s",
                                local_ch.index, external_id,
                            )
                elif ao3_chapters:
                    # Single-chapter work: push the full-story HTML blob
                    content = self._read_full_story_html(story)
                    if content:
                        await client.edit_chapter(
                            external_id, ao3_chapters[0]["chapter_id"], content=content,
                        )
                        logger.info(
                            "AO3: Updated chapter %s content of work %s",
                            ao3_chapters[0]["chapter_id"], external_id,
                        )
            except Exception as ch_err:
                logger.warning("AO3: Chapter content update failed: %s", ch_err)

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
        """Replace chapter 1 content on AO3."""
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

            await client.edit_chapter(
                external_id, chapters[0]["chapter_id"], content=content,
            )

            return PostResult(
                success=True,
                external_id=external_id,
                external_url=f"https://archiveofourown.org/works/{external_id}",
                duration_seconds=self._elapsed(_t),
            )
        except Exception as e:
            logger.error("AO3 file replace failed for %s: %s", external_id, e)
            return PostResult(success=False, error=str(e), duration_seconds=self._elapsed(_t))
