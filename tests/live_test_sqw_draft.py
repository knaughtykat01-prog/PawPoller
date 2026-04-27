"""Live test: create a DRAFT on SquidgeWorld for Chosen Chapter 1.

Confirms the SquidgeWorld posting pipeline end-to-end:
  1. Author credentials login
  2. CSRF token retrieval
  3. /works POST with preview_button (= draft mode)
  4. Response URL contains /preview (= draft state confirmed)
  5. Work appears in KnaughtyKat's drafts on SquidgeWorld

DOES NOT click "Post" on the preview page. The work stays in drafts
until manually published or deleted via the SquidgeWorld dashboard.

Usage:
  cd C:/Users/rhysc/claude/PawPoller
  python tests/live_test_sqw_draft.py

Output:
  - work_id of the created draft
  - direct URL to the preview/edit page
  - instructions for cleanup
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Make PawPoller modules importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from posting.platforms.base import StoryUploadPackage
from posting.platforms.squidgeworld import SquidgeWorldPoster


CHOSEN_ROOT = Path("C:/Users/rhysc/claude/m_x/Archives/Complete_Stories/Chosen")
CHAPTER_1_HTML = CHOSEN_ROOT / "SquidgeWorld" / "Chapter_1_The_Heat.html"
STORY_JSON = CHOSEN_ROOT / "story.json"


def build_package() -> StoryUploadPackage:
    """Build a StoryUploadPackage for Chosen Chapter 1 (draft test)."""
    if not STORY_JSON.is_file():
        raise FileNotFoundError(f"story.json not found: {STORY_JSON}")
    if not CHAPTER_1_HTML.is_file():
        raise FileNotFoundError(f"Chapter 1 SQW HTML not found: {CHAPTER_1_HTML}")

    story = json.loads(STORY_JSON.read_text(encoding="utf-8"))

    # Mark the title clearly as a draft test so it's easy to identify and clean up
    test_title = f"Chosen [DRAFT TEST 2026-04-07]"

    # Pull tags from chapter 1's tag set if available, fall back to story default
    chapter_tags = []
    for ch in story.get("chapter_info", []):
        if ch.get("index") == 1:
            chapter_tags = ch.get("tags", {}).get("default", [])
            break
    if not chapter_tags:
        chapter_tags = story.get("tags", {}).get("default", [])

    return StoryUploadPackage(
        story_name="Chosen",
        chapter_index=1,
        chapter_title="Chapter 1: The Heat",
        platform="sqw",
        title=test_title,
        description=story.get("description", "")[:1200],
        tags=chapter_tags,
        rating="explicit",
        file_path=str(CHAPTER_1_HTML),
        file_type="html",
        word_count=2542,
    )


async def main() -> int:
    print("=" * 70)
    print("SquidgeWorld Draft Test — Chosen Chapter 1")
    print("=" * 70)
    print()

    print(f"Source HTML: {CHAPTER_1_HTML}")
    if CHAPTER_1_HTML.is_file():
        size_kb = CHAPTER_1_HTML.stat().st_size / 1024
        print(f"  size: {size_kb:.1f} KB")
    else:
        print("  ERROR: file not found")
        return 1
    print()

    package = build_package()
    print(f"Package built:")
    print(f"  story_name: {package.story_name}")
    print(f"  test title: {package.title}")
    print(f"  rating:     {package.rating}")
    print(f"  tags:       {len(package.tags)} tags")
    print(f"  description: {len(package.description)} chars")
    print()

    print("Initialising SquidgeWorldPoster (will log in as author)...")
    poster = SquidgeWorldPoster()

    errors = poster.validate(package)
    if errors:
        print(f"Validation errors: {errors}")
        return 1

    print("Calling poster.post() — this uses preview_button (draft mode)...")
    print()
    result = await poster.post(package)

    print("=" * 70)
    print("Result")
    print("=" * 70)
    print(f"  success:  {result.success}")
    print(f"  duration: {result.duration_seconds:.1f}s")

    if result.success:
        work_id = result.external_id
        url = result.external_url
        print(f"  work_id:  {work_id}")
        print(f"  URL:      {url}")
        print()
        print("DRAFT CREATED. Verify by visiting:")
        print(f"  https://squidgeworld.org/works/{work_id}/preview")
        print()
        print("Or in your KnaughtyKat dashboard:")
        print("  https://squidgeworld.org/users/KnaughtyKat/drafts")
        print()
        print("To clean up later, delete the draft from the SquidgeWorld dashboard,")
        print("OR call this with the work_id to delete:")
        print(f"  (manual deletion required - no auto-delete in this test script)")
        return 0
    else:
        print(f"  error:    {result.error}")
        print()
        print("DRAFT NOT CREATED. Check the error above.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
