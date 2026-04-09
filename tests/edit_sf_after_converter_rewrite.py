"""Push regenerated Clean HTML to existing SoFurry submissions.

Uses SoFurryPoster.replace_file() to update the content body without
touching metadata or privacy state.

Usage:
  cd C:/Users/rhysc/claude/PawPoller
  python tests/edit_sf_after_converter_rewrite.py            # dry run
  python tests/edit_sf_after_converter_rewrite.py --apply    # push
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from posting.platforms.sofurry import SoFurryPoster

ARCHIVE = Path("C:/Users/rhysc/claude/m_x/Archives/Complete_Stories")

# From server publications table
STORIES = [
    ("Chosen", "m0KjxlKe"),
    ("Drumheller_Detour", "mXB3AJz1"),
    ("Extra_Credit", "e3Qxq0En"),
    ("Hypnotic_Claim", "ebQ4Jkd1"),
    ("Not_So_Efficient_Studying", "ePdyAZ5e"),
    ("Overtime", "1xJGPWZm"),
    ("Ruins_of_Breeding", "nd4Pol7n"),
    ("The_Abstinent_Bet/Naughty_Version", "mW3Kv5Qm"),
    ("The_Abstinent_Bet/Nice_Version", "mywPXpP1"),
    ("The_Haunting_Desires", "mXB73JG1"),
    ("The_Silk_Threaded_Bonds", "noX5xXp1"),
    ("Tombstone", "nLrR4PBe"),
    ("Velvet_And_Vice", "ejYYA8G1"),
]


def find_clean_html(folder: str) -> Path | None:
    html_dir = ARCHIVE / folder / "HTML"
    if not html_dir.is_dir():
        return None
    for f in html_dir.glob("*_Clean.html"):
        return f
    for f in html_dir.glob("*_sofurry.html"):
        return f
    return None


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--story", help="only this story")
    args = parser.parse_args()

    print("=" * 70)
    print("SoFurry bulk content update — push regenerated Clean HTML")
    print("=" * 70)
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print()

    targets = STORIES
    if args.story:
        targets = [(f, s) for f, s in STORIES if f == args.story or f.split("/")[-1] == args.story]

    for folder, sf_id in targets:
        html_path = find_clean_html(folder)
        status = "OK" if html_path else "NO FILE"
        print(f"  {folder}: sf_id={sf_id} file={html_path.name if html_path else 'MISSING'} [{status}]")
    print()

    if not args.apply:
        print("DRY RUN — re-run with --apply to push.")
        return 0

    poster = SoFurryPoster()
    successes, failures = [], []

    for folder, sf_id in targets:
        html_path = find_clean_html(folder)
        if not html_path:
            failures.append((folder, "no Clean HTML file"))
            continue
        print(f"  {folder}...", end=" ", flush=True)
        try:
            result = await poster.replace_file(sf_id, str(html_path))
            if result.success:
                print(f"OK ({result.duration_seconds:.1f}s)")
                successes.append(folder)
            else:
                print(f"FAIL: {result.error}")
                failures.append((folder, result.error))
        except Exception as e:
            print(f"EXCEPTION: {e}")
            failures.append((folder, str(e)))
        await asyncio.sleep(2)

    print(f"\n{'='*70}")
    print(f"Done. {len(successes)} OK, {len(failures)} failed.")
    for f, err in failures:
        print(f"  FAIL: {f} — {err}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
