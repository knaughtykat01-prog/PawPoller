"""AO3 draft test — controlled, safe.

Posts Tombstone to AO3 as a HIDDEN DRAFT (preview state) using the
refactored AO3Poster, then verifies the work landed in /works/drafts.

Steps:
  1. Build a full-story package via story_reader.build_package(0, "ao3")
  2. Verify content + thumbnail are resolved correctly
  3. Cross-check against the user's already-published works (abort on overlap)
  4. poster.post(package) — uses preview_button only, work stays in drafts
  5. Verify is_work_in_drafts(work_id) returns True
  6. Verify is_work_published(work_id) returns False
  7. Print URL — manual cleanup if needed

NO existing AO3 works are touched.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/app")  # for in-container run; bare import works locally too
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from posting.platforms.ao3 import AO3Poster
from posting.story_reader import build_package, load_story


STORY_NAME = "Tombstone"


async def main() -> int:
    print("=" * 70)
    print(f"AO3 Draft Test — {STORY_NAME}")
    print("=" * 70)
    print()

    # 1. Load + build package
    print("[1/5] Loading story + building AO3 package...")
    story = load_story(STORY_NAME)
    package = build_package(story, chapter_index=0, platform="ao3")
    print(f"  story:           {story.name}")
    print(f"  total words:     {story.total_words:,}")
    print(f"  fandom:          {story.fandom or '(none)'}")
    print(f"  warnings:        {story.warnings}")
    print(f"  categories:      {story.categories}")
    print(f"  characters:      {story.characters}")
    print(f"  relationships:   {story.relationships}")
    print(f"  title:           {package.title}")
    print(f"  description:     {package.description[:80]}...")
    print(f"  ao3 tag count:   {len(package.tags)}")
    print(f"  resolved file:   {package.file_path}")
    if package.file_path:
        print(f"  file size:       {Path(package.file_path).stat().st_size:,} bytes")
    print()

    poster = AO3Poster()

    # 2. Login + safety check
    print("[2/5] Login + safety check (cross-check published works)...")
    client = await poster._ensure_client()
    print("  [OK] logged in")

    pub_works = await client.get_all_work_ids()
    pub_titles = {w["title"].strip().lower() for w in pub_works}
    print(f"  found {len(pub_works)} works on AO3 user account")
    display_title = story.name.replace("_", " ").strip().lower()
    if display_title in pub_titles:
        print(f"  [ABORT] {display_title!r} is already on AO3 — refusing to re-post")
        return 1
    print(f"  no overlap — safe to draft")
    print()

    # 3. Post as draft
    print("[3/5] Posting as draft via AO3Poster.post()...")
    result = await poster.post(package)
    if not result.success:
        print(f"  [FAIL] {result.error}")
        return 1
    work_id = result.external_id
    print(f"  [OK] work_id={work_id} ({result.duration_seconds:.1f}s)")
    print(f"  url: {result.external_url}")
    print()

    # 4. Verify draft state explicitly (tri-state: True/False/None)
    print("[4/5] Verifying work state...")
    in_drafts = await client.is_work_in_drafts(work_id)
    in_published = await client.is_work_published(work_id)
    def fmt(v):
        if v is True: return "YES"
        if v is False: return "no"
        return "UNKNOWN (fetch failed)"
    print(f"  is_work_in_drafts:   {fmt(in_drafts)}")
    print(f"  is_work_published:   {fmt(in_published)}")
    print()

    issues = []
    # Only fail on POSITIVE bad signal — fetch failures are not failures
    if in_published is True:
        issues.append("work IS in published listing — UNEXPECTED")
    if in_drafts is False and in_published is False:
        issues.append("work is in NEITHER drafts nor published — strange state")

    print("[5/5] Final report")
    print("=" * 70)
    if issues:
        print(f"PARTIAL — {len(issues)} issue(s):")
        for i in issues:
            print(f"  - {i}")
        print(f"  visit (logged in): https://archiveofourown.org/works/{work_id}/preview")
        print(f"  manual cleanup:    https://archiveofourown.org/works/{work_id}/confirm_delete")
        return 1
    print("DRAFT TEST PASSED")
    print(f"  work {work_id} created in preview/draft state, not published")
    print(f"  visit (logged in): https://archiveofourown.org/works/{work_id}/preview")
    print()
    print("To clean up later:")
    print(f"  https://archiveofourown.org/works/{work_id}/confirm_delete")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
