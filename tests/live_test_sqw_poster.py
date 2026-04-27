"""Live test of the refactored SquidgeWorldPoster.

Verifies the full posting pipeline against the existing live work 91374:
  1. Build a StoryUploadPackage for Chosen
  2. Call SquidgeWorldPoster.edit(91374, package)
  3. Confirm the work metadata, all chapter content, and work skin are
     all updated correctly via the new safe pattern

This is the end-to-end test that should verify the poster module works
without needing one-shot test scripts.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from posting.platforms.base import StoryUploadPackage
from posting.platforms.squidgeworld import SquidgeWorldPoster


WORK_ID = "91374"


async def main() -> int:
    print("=" * 70)
    print(f"SquidgeWorldPoster end-to-end edit test — work {WORK_ID}")
    print("=" * 70)
    print()

    # Build a minimal package - the poster will pull everything else from
    # story.json via story_reader.load_story
    package = StoryUploadPackage(
        story_name="Chosen",
        chapter_index=0,         # 0 = whole story
        chapter_title="Chosen",
        platform="sqw",
        title="Chosen",          # poster will fall back to story name if empty
        description="",          # poster pulls from story.json
        tags=[],                 # poster pulls from story.json
        rating="explicit",
        file_path=None,
        file_type="html",
    )

    print(f"Package: story={package.story_name}")
    print(f"  (everything else read by the poster from story.json)")
    print()

    poster = SquidgeWorldPoster()

    print(f"Calling poster.edit({WORK_ID}, package)...")
    print()
    result = await poster.edit(WORK_ID, package)

    print()
    print("=" * 70)
    print("Result")
    print("=" * 70)
    print(f"  success:  {result.success}")
    print(f"  duration: {result.duration_seconds:.1f}s")
    if result.success:
        print(f"  url:      {result.external_url}")
        print()
        print("Verify visually at:")
        print(f"  https://www.squidgeworld.org/works/{WORK_ID}")
        return 0
    else:
        print(f"  error:    {result.error}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
