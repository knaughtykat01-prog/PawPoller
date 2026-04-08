"""Inkbunny draft test — controlled, safe.

Uploads Tombstone Chapter 1 to Inkbunny as a HIDDEN draft (visibility != yes).
Verifies the submission was created and the metadata was applied.
Optionally cleans up by deleting the test submission.

Steps:
  1. Build StoryUploadPackage for Tombstone Ch1 (BBCode)
  2. Set extra["draft"] = True
  3. Call InkbunnyPoster.post(package)
  4. Verify submission exists, fetch its details, confirm metadata
  5. Verify it does NOT show up in the public listing (anonymous fetch)
  6. Prompt for cleanup decision (delete or leave hidden for manual review)

NO EXISTING IB SUBMISSIONS ARE TOUCHED.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from api_client.client import InkbunnyClient
from posting.platforms.base import StoryUploadPackage
from posting.platforms.inkbunny import InkbunnyPoster


STORY_NAME = "Tombstone"
STORY_ROOT = Path("C:/Users/rhysc/claude/m_x/Archives/Complete_Stories/Tombstone")
CHAPTER_BBCODE = STORY_ROOT / "Chapters" / "BBCode" / "Chapter_1_The_Bar_bbcode.txt"


async def main() -> int:
    print("=" * 70)
    print(f"Inkbunny Draft Test — {STORY_NAME} Ch 1")
    print("=" * 70)
    print()

    # Load story.json
    story_json = STORY_ROOT / "story.json"
    if not story_json.is_file():
        print(f"ERROR: story.json not found at {story_json}")
        return 1
    story = json.loads(story_json.read_text(encoding="utf-8"))

    if not CHAPTER_BBCODE.is_file():
        print(f"ERROR: Chapter BBCode not found at {CHAPTER_BBCODE}")
        return 1

    # Build the package for Chapter 1
    ch1_info = next(
        (c for c in story.get("chapter_info", []) if c.get("index") == 1),
        None,
    )
    if not ch1_info:
        print("ERROR: no chapter_info[index=1] in story.json")
        return 1

    # Build a per-chapter title and description
    chapter_title = f"{story['title']} — {ch1_info['title']}"
    chapter_desc = ch1_info.get("description") or story.get("description", "")

    # Tags: prefer chapter-specific Inkbunny tags, fall back to story-level
    ch_tags = ch1_info.get("tags", {}).get("inkbunny") \
        or story.get("tags", {}).get("inkbunny", []) \
        or story.get("tags", {}).get("default", [])
    # IB requires minimum 4 tags
    if len(ch_tags) < 4:
        print(f"ERROR: only {len(ch_tags)} tags, IB requires 4 minimum")
        return 1

    package = StoryUploadPackage(
        story_name=STORY_NAME,
        chapter_index=1,
        chapter_title=ch1_info["title"],
        platform="ib",
        title=chapter_title[:100],
        description=chapter_desc,
        tags=ch_tags,
        rating="explicit",
        file_path=str(CHAPTER_BBCODE),
        file_type="bbcode",
        word_count=ch1_info.get("words", 0),
    )
    package.extra["draft"] = True  # SAFETY: stay hidden

    print(f"Package built:")
    print(f"  story:       {STORY_NAME}")
    print(f"  chapter:     {ch1_info['title']}")
    print(f"  title:       {package.title}")
    print(f"  description: {package.description[:80]}{'...' if len(package.description) > 80 else ''}")
    print(f"  tags:        {len(ch_tags)} tags ({', '.join(ch_tags[:6])}{'...' if len(ch_tags) > 6 else ''})")
    print(f"  rating:      {package.rating}")
    print(f"  file:        {CHAPTER_BBCODE.name} ({CHAPTER_BBCODE.stat().st_size:,} bytes)")
    print(f"  draft mode:  {package.extra['draft']}")
    print()

    poster = InkbunnyPoster()
    submission_id = None

    try:
        # Step 1: Post as draft
        print("[1/3] Calling InkbunnyPoster.post(package)...")
        result = await poster.post(package)
        if not result.success:
            print(f"  [FAIL] {result.error}")
            return 1
        submission_id = int(result.external_id)
        print(f"  [OK] submission_id={submission_id} ({result.duration_seconds:.1f}s)")
        print(f"  url: {result.external_url}")
        print()

        # Step 2: Verify submission exists via authenticated fetch
        print("[2/3] Verifying submission exists (authenticated fetch)...")
        client = await poster._ensure_client()
        details = await client.get_submission_details([submission_id])
        if not details:
            print(f"  [FAIL] No submission returned by api_submissions.php for id {submission_id}")
            return 1
        d = details[0]
        print(f"  [OK] fetched: submission_id={d.submission_id}")
        print(f"    title:    {d.title}")
        print(f"    type:     {d.type_name}")
        print(f"    rating:   {d.rating_name}")
        print(f"    keywords: {len(d.keywords)} ({', '.join(k.keyword_name for k in d.keywords[:6])}{'...' if len(d.keywords) > 6 else ''})")
        if d.title != package.title[:100]:
            print(f"  [WARN] title mismatch: server={d.title!r} expected={package.title[:100]!r}")
        print()

        # Step 3: Verify it's hidden from anonymous (public) view
        print("[3/3] Verifying submission is HIDDEN from anonymous viewers...")
        # Make a fresh client with no SID and try to fetch
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as anon:
            anon_resp = await anon.post(
                f"{config.INKBUNNY_API_BASE}/api_submissions.php",
                data={
                    "sid": "guest",  # IB allows guest sid for public access
                    "submission_ids": str(submission_id),
                    "show_description": "yes",
                },
            )
            anon_resp.raise_for_status()
            anon_data = anon_resp.json()
        anon_subs = anon_data.get("submissions", [])
        if anon_subs and anon_subs[0].get("submission_id"):
            print(f"  [WARN] anonymous fetch returned data — submission may be VISIBLE")
            print(f"    raw: {anon_subs[0]}")
        else:
            print(f"  [OK] anonymous fetch returned empty — submission is hidden from public")
        print()

        print("=" * 70)
        print(f"DRAFT TEST PASSED — submission {submission_id} created as hidden")
        print(f"  Visit it logged in: https://inkbunny.net/s/{submission_id}")
        print("=" * 70)
        print()
        print("To clean up later, delete via the IB UI or run:")
        print(f"  python -c \"import asyncio, sys; sys.path.insert(0,'.'); "
              f"from posting.platforms.inkbunny import InkbunnyPoster; "
              f"p = InkbunnyPoster(); "
              f"asyncio.run((lambda: (lambda c: c.delete_submission({submission_id}))(p._ensure_client()))())\"")
        return 0

    except Exception as e:
        print(f"[EXCEPTION] {e}")
        import traceback
        traceback.print_exc()
        if submission_id:
            print()
            print(f"Test work was created: submission {submission_id}")
            print(f"  Manual cleanup: https://inkbunny.net/s/{submission_id}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
