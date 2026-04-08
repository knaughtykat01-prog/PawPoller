"""Inkbunny: add thumbnail + additional file/page to existing draft.

Uses the new InkbunnyClient.add_files_to_submission() method to:
  1. Attach the Tombstone series thumbnail to draft submission 3847063
  2. Add Tombstone Chapter 2 BBCode as a second page in the same submission
  3. Verify both via api_submissions.php (page count should jump 1 -> 2,
     thumbnail URLs should populate)

The submission stays HIDDEN throughout — we don't touch visibility.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from posting.platforms.inkbunny import InkbunnyPoster


SUBMISSION_ID = 3847063
TOMBSTONE_ROOT = Path("C:/Users/rhysc/claude/m_x/Archives/Complete_Stories/Tombstone")
THUMBNAIL = TOMBSTONE_ROOT / "tombstone_thumbnail_full_series.png"
CHAPTER_2_BBCODE = TOMBSTONE_ROOT / "Chapters" / "BBCode" / "Chapter_2_The_Graveyard_bbcode.txt"


async def main() -> int:
    print("=" * 70)
    print(f"Inkbunny: add thumbnail + page to existing submission {SUBMISSION_ID}")
    print("=" * 70)
    print()

    if not THUMBNAIL.is_file():
        print(f"ERROR: thumbnail not found at {THUMBNAIL}")
        return 1
    if not CHAPTER_2_BBCODE.is_file():
        print(f"ERROR: chapter 2 BBCode not found at {CHAPTER_2_BBCODE}")
        return 1

    print(f"Thumbnail: {THUMBNAIL.name} ({THUMBNAIL.stat().st_size:,} bytes)")
    print(f"Chapter 2: {CHAPTER_2_BBCODE.name} ({CHAPTER_2_BBCODE.stat().st_size:,} bytes)")
    print()

    poster = InkbunnyPoster()
    client = await poster._ensure_client()

    # 1. Baseline: fetch current state
    print("[1/4] Baseline — current submission state...")
    before = await client.get_submission_details([SUBMISSION_ID])
    if not before:
        print(f"  [FAIL] Submission {SUBMISSION_ID} not found")
        return 1
    b = before[0]
    print(f"  title:      {b.title}")
    print(f"  page_count: {b.pagecount}")
    print(f"  thumb urls (any populated): {bool(b.thumbnail_url_huge or b.thumbnail_url_large or b.thumbnail_url_medium)}")
    print(f"    huge:    {b.thumbnail_url_huge[:70] if b.thumbnail_url_huge else '(empty)'}")
    print(f"    medium:  {b.thumbnail_url_medium[:70] if b.thumbnail_url_medium else '(empty)'}")
    print()

    # 2. Add thumbnail
    print("[2/4] Adding thumbnail via api_upload.php with submission_id...")
    try:
        result = await client.add_files_to_submission(
            SUBMISSION_ID,
            thumbnail_path=str(THUMBNAIL),
        )
        print(f"  [OK] response: {result}")
    except Exception as e:
        print(f"  [FAIL] {e}")
        return 1
    print()

    # 3. Add chapter 2 as a second page
    print("[3/4] Adding Chapter 2 as a second page...")
    try:
        result = await client.add_files_to_submission(
            SUBMISSION_ID,
            file_paths=[str(CHAPTER_2_BBCODE)],
        )
        print(f"  [OK] response: {result}")
    except Exception as e:
        print(f"  [FAIL] {e}")
        return 1
    print()

    # 4. Verify
    print("[4/4] Verifying — re-fetch submission state...")
    await asyncio.sleep(2)  # let IB catch up
    after = await client.get_submission_details([SUBMISSION_ID])
    if not after:
        print(f"  [FAIL] Submission {SUBMISSION_ID} not found after edits")
        return 1
    a = after[0]
    print(f"  page_count: {b.pagecount} -> {a.pagecount}")
    thumb_now = bool(a.thumbnail_url_huge or a.thumbnail_url_large or a.thumbnail_url_medium or a.thumbnail_url_medium_noncustom)
    print(f"  thumb populated: {thumb_now}")
    print(f"    huge:    {a.thumbnail_url_huge[:70] if a.thumbnail_url_huge else '(empty)'}")
    print(f"    medium:  {a.thumbnail_url_medium[:70] if a.thumbnail_url_medium else '(empty)'}")
    print(f"    noncustom: {a.thumbnail_url_medium_noncustom[:70] if a.thumbnail_url_medium_noncustom else '(empty)'}")
    print()

    issues = []
    try:
        if int(a.pagecount) <= int(b.pagecount):
            issues.append(f"page_count did not increase ({b.pagecount} -> {a.pagecount})")
    except Exception:
        pass
    if not thumb_now:
        issues.append("thumbnail still not populated")

    print("=" * 70)
    if issues:
        print(f"PARTIAL — {len(issues)} issue(s):")
        for i in issues:
            print(f"  - {i}")
        print()
        print("Visit: https://inkbunny.net/s/{0}".format(SUBMISSION_ID))
        return 1
    else:
        print("BOTH OPERATIONS SUCCEEDED")
        print(f"  thumbnail attached + chapter 2 added")
        print(f"  visit: https://inkbunny.net/s/{SUBMISSION_ID}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
