"""Inkbunny: rebuild submission 3847063 as a single bulk-file draft.

Replaces the experimental two-page submission with a clean single-file
submission containing the FULL Tombstone BBCode + one auto-detected
thumbnail. Stays HIDDEN — no publish.

Steps:
  1. Load Tombstone via story_reader (triggers auto thumbnail detection)
  2. Build a full-story IB package via build_package(chapter_index=0)
  3. Delete the existing test submission 3847063
  4. Repost as draft via InkbunnyPoster.post(package, extra={draft: True})
  5. Verify: title, page_count==1, thumbnail populated
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from posting.platforms.inkbunny import InkbunnyPoster
from posting.story_reader import build_package, load_story


OLD_SUBMISSION_ID = 3847080
STORY_NAME = "Tombstone"


async def main() -> int:
    print("=" * 70)
    print(f"Inkbunny: rebuild submission {OLD_SUBMISSION_ID} as single bulk file")
    print("=" * 70)
    print()

    # 1. Load story + build full-story IB package
    print("[1/5] Loading story metadata...")
    story = load_story(STORY_NAME)
    print(f"  story:           {story.name}")
    print(f"  total words:     {story.total_words:,}")
    print(f"  chapters:        {len(story.chapters)}")
    print(f"  thumbnail_path:  {story.thumbnail_path}")
    if not story.thumbnail_path or not Path(story.thumbnail_path).is_file():
        print("  [FAIL] thumbnail auto-detect did not find a file")
        return 1
    print()

    print("[2/5] Building full-story IB package (chapter_index=0)...")
    package = build_package(story, chapter_index=0, platform="ib")
    package.extra["draft"] = True  # SAFETY: stay hidden
    print(f"  title:           {package.title}")
    print(f"  description:     {package.description[:80]}{'...' if len(package.description) > 80 else ''}")
    print(f"  tags:            {len(package.tags)} (first 6: {', '.join(package.tags[:6])}...)")
    print(f"  rating:          {package.rating}")
    print(f"  file_path:       {package.file_path}")
    print(f"  file_type:       {package.file_type}")
    print(f"  thumbnail_path:  {package.thumbnail_path}")
    print(f"  draft mode:      {package.extra['draft']}")
    if not package.file_path or not Path(package.file_path).is_file():
        print("  [FAIL] file_path missing or does not exist")
        return 1
    print(f"  file size:       {Path(package.file_path).stat().st_size:,} bytes")
    print()

    poster = InkbunnyPoster()

    # 3. Delete the old test submission
    print(f"[3/5] Deleting old submission {OLD_SUBMISSION_ID}...")
    client = await poster._ensure_client()
    try:
        del_result = await client.delete_submission(OLD_SUBMISSION_ID)
        print(f"  [OK] response: {del_result}")
    except Exception as e:
        print(f"  [WARN] delete failed (may already be gone): {e}")
    print()

    # 4. Post fresh as draft
    print("[4/5] Posting fresh draft via InkbunnyPoster.post()...")
    result = await poster.post(package)
    if not result.success:
        print(f"  [FAIL] {result.error}")
        return 1
    new_id = int(result.external_id)
    print(f"  [OK] new submission_id={new_id} ({result.duration_seconds:.1f}s)")
    print(f"  url: {result.external_url}")
    print()

    # 5. Verify final state
    print("[5/5] Verifying final state via api_submissions.php...")
    await asyncio.sleep(2)  # let IB catch up
    details = await client.get_submission_details([new_id])
    if not details:
        print(f"  [FAIL] no details returned for {new_id}")
        return 1
    d = details[0]
    print(f"  title:       {d.title}")
    print(f"  type:        {d.type_name}")
    print(f"  rating:      {d.rating_name}")
    print(f"  page_count:  {d.pagecount}")
    print(f"  keywords:    {len(d.keywords)}")
    thumb_now = bool(
        d.thumbnail_url_huge
        or d.thumbnail_url_large
        or d.thumbnail_url_medium
        or d.thumbnail_url_medium_noncustom
    )
    print(f"  thumbnail:   {'populated' if thumb_now else '(empty)'}")
    if d.thumbnail_url_huge:
        print(f"    huge:    {d.thumbnail_url_huge[:80]}")
    print()

    issues = []
    if d.title != "Tombstone":
        issues.append(f"title is {d.title!r}, expected 'Tombstone'")
    try:
        if int(d.pagecount) != 1:
            issues.append(f"page_count is {d.pagecount}, expected 1")
    except Exception:
        pass
    if not thumb_now:
        issues.append("thumbnail not populated")

    print("=" * 70)
    if issues:
        print(f"PARTIAL — {len(issues)} issue(s):")
        for i in issues:
            print(f"  - {i}")
        print(f"  visit: https://inkbunny.net/s/{new_id}")
        return 1
    print("REBUILD SUCCEEDED")
    print(f"  one bulk file + thumbnail, hidden draft, ready for live submission")
    print(f"  visit (logged in): https://inkbunny.net/s/{new_id}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
