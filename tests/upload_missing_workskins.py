"""Create work skins for the 3 stories that didn't have one,
then push the skins to their existing SquidgeWorld drafts.

The new skins are picked up by SquidgeWorldPoster.edit() because
story_reader.load_story() now auto-detects Work_Skin.css and the
poster's _ensure_work_skin() will create-or-find based on title.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from posting.platforms.base import StoryUploadPackage
from posting.platforms.squidgeworld import SquidgeWorldPoster


# Stories needing skins → their work IDs on SQW
STORIES = [
    ("Drumheller_Detour", "91391"),
    ("The_Haunting_Desires", "91396"),
    ("Velvet_And_Vice", "91397"),
]


async def main() -> int:
    print("=" * 70)
    print("Upload missing Work Skins + re-edit drafts to apply them")
    print("=" * 70)
    print()

    poster = SquidgeWorldPoster()

    successes = 0
    failures = []

    for story_name, work_id in STORIES:
        print(f"--- {story_name} (work {work_id}) ---")
        package = StoryUploadPackage(
            story_name=story_name,
            chapter_index=0,
            chapter_title="",
            platform="sqw",
            title="",
            description="",
            tags=[],
            rating="explicit",
        )
        try:
            result = await poster.edit(work_id, package)
            if result.success:
                print(f"  [OK] {result.duration_seconds:.1f}s")
                successes += 1
            else:
                print(f"  [FAIL] {result.error}")
                failures.append((story_name, result.error))
        except Exception as e:
            print(f"  [EXCEPTION] {e}")
            failures.append((story_name, str(e)))
        print()
        await asyncio.sleep(3)

    print("=" * 70)
    print(f"Done: {successes} succeeded, {len(failures)} failed")
    if failures:
        for n, e in failures:
            print(f"  - {n}: {e}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
