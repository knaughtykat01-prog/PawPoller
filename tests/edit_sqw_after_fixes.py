"""Push the 2026-04-09 SquidgeWorld body fixes to existing draft works.

Affected stories:
  - Velvet and Vice    (CSS rule add + 9 chapter labels + ch1 warning rebuild)
  - Drumheller Detour  (ch1 warning rebuild + delete duplicate plain block)
  - Ruins of Breeding  (46 narrative bolding paragraphs + ch1 dup delete)
  - Overtime           (4 chapter print-container strip + class rename)
  - Tombstone          (3 chapter print-container strip + class rename)

For each, the script:
  1. Looks up the work_id by matching title against the user's draft + published lists
  2. Calls SquidgeWorldPoster.edit() which:
     a) Detects current state (draft vs published) and PRESERVES it
     b) Refreshes the Work Skin CSS
     c) Edits the work metadata (title, summary, tags)
     d) Iterates all chapters and updates each chapter body
     e) Verifies the state didn't accidentally flip

SAFETY: All affected works MUST be in draft state. The poster aborts if it
detects a state change. Skips any story whose title isn't found in the user's
work list.

Usage:
  cd C:/Users/rhysc/claude/PawPoller
  python tests/edit_sqw_after_fixes.py            # dry run
  python tests/edit_sqw_after_fixes.py --apply    # actual edits
  python tests/edit_sqw_after_fixes.py --apply --story Velvet_And_Vice
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from posting.platforms.base import StoryUploadPackage
from posting.platforms.squidgeworld import SquidgeWorldPoster
from sqw_client.client import SquidgeWorldClient


# Story folder name -> canonical title (from story.json)
STORIES = [
    ("Chosen", "Chosen"),
    ("Drumheller_Detour", "Drumheller Detour"),
    ("Extra_Credit", "Extra Credit"),
    ("Hypnotic_Claim", "Hypnotic Claim"),
    ("Not_So_Efficient_Studying", "Not So Efficient Studying"),
    ("Overtime", "Overtime"),
    ("Ruins_of_Breeding", "Ruins of Breeding"),
    ("The_Haunting_Desires", "The Haunting Desires"),
    ("The_Silk_Threaded_Bonds", "The Silk-Threaded Bonds"),
    ("Tombstone", "Tombstone"),
    ("Velvet_And_Vice", "Velvet and Vice"),
]


def _normalize_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


async def fetch_existing_works(client: SquidgeWorldClient) -> dict[str, tuple[str, str]]:
    """Returns {normalized_title: (work_id, display_title)}."""
    out: dict[str, tuple[str, str]] = {}
    for path in ["works/drafts", "works"]:
        url = f"https://www.squidgeworld.org/users/{client.username}/{path}"
        r = await client._http.get(url)
        if r.status_code != 200:
            continue
        # Match: <h4 class="heading"><a href="/works/12345">Title</a>
        for m in re.finditer(
            r'<h4[^>]*class="[^"]*heading[^"]*"[^>]*>\s*<a[^>]*href="/works/(\d+)"[^>]*>([^<]+)</a>',
            r.text,
        ):
            wid = m.group(1)
            title = m.group(2).strip()
            out[_normalize_title(title)] = (wid, title)
    return out


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="actually push edits (default: dry run)")
    parser.add_argument("--story", help="only edit this specific story (folder name)")
    parser.add_argument("--yes", action="store_true", help="skip per-story confirmation")
    args = parser.parse_args()

    print("=" * 70)
    print("SquidgeWorld bulk edit after 2026-04-09 body fixes")
    print("=" * 70)
    print()
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print()

    settings = config.get_settings()
    client = SquidgeWorldClient(
        settings.get("sqw_author_username") or settings.get("sqw_username"),
        settings.get("sqw_author_password") or settings.get("sqw_password"),
        settings.get("sqw_target_user", ""),
    )
    if not await client.ensure_logged_in():
        print("LOGIN FAILED")
        return 1
    print(f"Logged in as {client.username}")
    print()

    print("Fetching existing SquidgeWorld works...")
    existing = await fetch_existing_works(client)
    print(f"  Found {len(existing)} works")
    print()

    targets = STORIES
    if args.story:
        targets = [(name, title) for name, title in STORIES if name == args.story]
        if not targets:
            print(f"Story not found in target list: {args.story}")
            return 1

    print(f"Stories to edit: {len(targets)}")
    plan: list[tuple[str, str, str]] = []  # (folder, work_id, display)
    for folder, title in targets:
        norm = _normalize_title(title)
        match = existing.get(norm)
        if not match:
            print(f"  [MISSING] {folder}: '{title}' not found on SQW — skipping")
            continue
        wid, display = match
        print(f"  [OK]      {folder}: '{display}' -> work_id={wid}")
        plan.append((folder, wid, display))
    print()

    if not plan:
        print("Nothing to edit.")
        return 0

    if not args.apply:
        print("DRY RUN: nothing pushed. Re-run with --apply to push edits.")
        return 0

    if not args.yes:
        print(f"Proceed with editing {len(plan)} works on SquidgeWorld? Type 'yes' to continue: ", end="", flush=True)
        try:
            answer = input().strip().lower()
        except EOFError:
            answer = ""
        if answer != "yes":
            print("Aborted.")
            return 0

    poster = SquidgeWorldPoster()
    successes = []
    failures = []

    for folder, wid, display in plan:
        print()
        print("=" * 70)
        print(f"Editing {folder} (work_id={wid})")
        print("=" * 70)

        package = StoryUploadPackage(
            story_name=folder,
            chapter_index=0,
            chapter_title=display,
            platform="sqw",
            title=display,
            description="",  # poster will use story.json description
            tags=[],
            rating="explicit",
        )

        try:
            result = await poster.edit(wid, package)
            if result.success:
                print(f"  [OK] {folder} updated in {result.duration_seconds:.1f}s")
                print(f"  url: {result.external_url}")
                successes.append((folder, wid))
            else:
                print(f"  [FAIL] {folder}: {result.error}")
                failures.append((folder, result.error))
        except Exception as e:
            print(f"  [EXCEPTION] {folder}: {e}")
            failures.append((folder, str(e)))

        # Polite delay between stories
        await asyncio.sleep(5)

    print()
    print("=" * 70)
    print(f"Done. {len(successes)} successes, {len(failures)} failures")
    print("=" * 70)
    for folder, wid in successes:
        print(f"  OK   {folder} -> https://squidgeworld.org/works/{wid}")
    for folder, err in failures:
        print(f"  FAIL {folder} -> {err}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
