"""Push regenerated Clean HTML to existing AO3 draft works.

After the converter rewrite (2026-04-09), all Clean HTML files have been
regenerated with proper italic/bold parsing. This script updates each
AO3 draft's chapter 1 content with the clean HTML.

Usage:
  cd C:/Users/rhysc/claude/PawPoller
  python tests/edit_ao3_after_converter_rewrite.py            # dry run
  python tests/edit_ao3_after_converter_rewrite.py --apply    # push
  python tests/edit_ao3_after_converter_rewrite.py --apply --story Tombstone
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from posting.platforms.base import StoryUploadPackage
from posting.platforms.ao3 import AO3Poster
from ao3_client.client import AO3Client
import config


# All stories with AO3 drafts (from the publications table / previous bulk post)
# Format: (folder_name, canonical_title, ao3_work_id)
STORIES = [
    ("Chosen", "Chosen", "82712456"),
    ("Drumheller_Detour", "Drumheller Detour", "82712566"),
    ("Extra_Credit", "Extra Credit", "82713211"),
    ("Hypnotic_Claim", "Hypnotic Claim", "82712801"),
    ("Not_So_Efficient_Studying", "Not So Efficient Studying", "82712821"),
    ("Overtime", "Overtime", "82712896"),
    ("Ruins_of_Breeding", "Ruins of Breeding", "82712911"),
    ("The_Abstinent_Bet/Naughty_Version", "The Abstinent Bet (Naughty Version)", "82713271"),
    ("The_Abstinent_Bet/Nice_Version", "The Abstinent Bet (Nice Version)", "82713236"),
    ("The_Haunting_Desires", "The Haunting Desires", "82713001"),
    ("The_Silk_Threaded_Bonds", "The Silk-Threaded Bonds", "82713066"),
    ("Tombstone", "Tombstone", "82711601"),
    ("Velvet_And_Vice", "Velvet And Vice", "82713131"),
]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--story", help="only this story folder")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    print("=" * 70)
    print("AO3 bulk edit — push regenerated Clean HTML")
    print("=" * 70)
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print()

    targets = STORIES
    if args.story:
        targets = [(f, t, w) for f, t, w in STORIES if f == args.story]
        if not targets:
            print(f"Story not found: {args.story}")
            return 1

    print(f"Stories to edit: {len(targets)}")
    for folder, title, wid in targets:
        print(f"  {folder}: work_id={wid}")
    print()

    if not args.apply:
        print("DRY RUN — re-run with --apply to push.")
        return 0

    # Verify AO3 credentials
    settings = config.get_settings()
    if not settings.get("ao3_username") or not settings.get("ao3_password"):
        print("ERROR: ao3_username/ao3_password not in settings")
        return 1

    poster = AO3Poster()
    successes, failures = [], []

    for folder, title, wid in targets:
        print(f"\n--- {folder} (work_id={wid}) ---")
        package = StoryUploadPackage(
            story_name=folder,
            chapter_index=0,
            chapter_title=title,
            platform="ao3",
            title=title,
            description="",
            tags=[],
            rating="explicit",
        )
        try:
            result = await poster.edit(wid, package)
            if result.success:
                print(f"  [OK] {result.duration_seconds:.1f}s")
                successes.append(folder)
            else:
                print(f"  [FAIL] {result.error}")
                failures.append((folder, result.error))
        except Exception as e:
            print(f"  [EXCEPTION] {e}")
            failures.append((folder, str(e)))

        await asyncio.sleep(3)  # polite delay

    print(f"\n{'='*70}")
    print(f"Done. {len(successes)} OK, {len(failures)} failed.")
    for f, err in failures:
        print(f"  FAIL: {f} — {err}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
