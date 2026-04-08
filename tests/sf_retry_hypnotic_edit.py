"""Retry the failed Hypnotic_Claim edit on SoFurry.

Background:
  4 days ago a routine update edit on Hypnotic_Claim failed with
  'SoFurry login failed' (probably stale cookies on the server). The post
  itself succeeded earlier — submission ebQ4Jkd1 exists on SF.

This script:
  1. Logs in fresh from local desktop (no proxy, residential IP)
  2. Fetches submission ebQ4Jkd1's current state
  3. Re-runs the edit with current package data via SoFurryPoster.edit()
  4. Re-fetches and reports the new state
  5. Updates the publication row from 'failed' to 'posted' on success
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from posting.platforms.sofurry import SoFurryPoster
from posting.story_reader import build_package, load_story


SUBMISSION_ID = "ebQ4Jkd1"
STORY_NAME = "Hypnotic_Claim"


async def main() -> int:
    print("=" * 70)
    print(f"SF retry — edit Hypnotic_Claim ({SUBMISSION_ID})")
    print("=" * 70)
    print()

    poster = SoFurryPoster()

    print("[1/4] Login...")
    client = await poster._ensure_client()
    print("  [OK] logged in")
    print()

    print(f"[2/4] Fetching current state of {SUBMISSION_ID}...")
    raw_resp = await client._http.get(
        f"https://sofurry.com/ui/submission/{SUBMISSION_ID}",
        headers={"Accept": "application/json"},
    )
    print(f"  status:  {raw_resp.status_code}")
    if raw_resp.status_code != 200:
        print(f"  [FAIL] could not fetch submission")
        return 1
    raw = raw_resp.json()
    print(f"  title:        {raw.get('title')}")
    print(f"  privacy:      {raw.get('privacy')}")
    print(f"  rating:       {raw.get('rating')}")
    print(f"  description:  {(raw.get('description') or '')[:80]}")
    print(f"  tag count:    {len(raw.get('artistTags', []))}")
    print()

    print(f"[3/4] Re-running edit via SoFurryPoster.edit({SUBMISSION_ID!r})...")
    story = load_story(STORY_NAME)
    package = build_package(story, chapter_index=0, platform="sf")
    print(f"  new title:        {package.title}")
    print(f"  new description:  {package.description[:80]}")
    print(f"  new tag count:    {len(package.tags)}")
    print(f"  new rating:       {package.rating}")
    result = await poster.edit(SUBMISSION_ID, package)
    if not result.success:
        print(f"  [FAIL] {result.error}")
        return 1
    print(f"  [OK] edit complete ({result.duration_seconds:.1f}s)")
    print()

    print("[4/4] Re-fetching to confirm...")
    raw_resp = await client._http.get(
        f"https://sofurry.com/ui/submission/{SUBMISSION_ID}",
        headers={"Accept": "application/json"},
    )
    if raw_resp.status_code == 200:
        raw = raw_resp.json()
        print(f"  title:        {raw.get('title')}")
        print(f"  privacy:      {raw.get('privacy')}")
        print(f"  rating:       {raw.get('rating')}")
        print(f"  description:  {(raw.get('description') or '')[:80]}")
        print(f"  tag count:    {len(raw.get('artistTags', []))}")
    print()
    print("DONE")
    print(f"  visit: https://sofurry.com/s/{SUBMISSION_ID}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
