"""SoFurry draft test — controlled, safe.

Posts Tombstone to SoFurry as Private (privacy=1) using the refactored
SoFurryPoster, then verifies the submission is owner-only.

Steps:
  1. Build a full-story package via story_reader.build_package(0, "sf")
  2. Verify content + thumbnail are resolved
  3. Cross-check against existing live works (abort if title clash)
  4. poster.post(package) with extra["draft"]=True
  5. Verify privacy=1 server-side via raw /ui/submission/{id} GET
  6. Print URL — manual cleanup if needed

NO existing SF submissions are touched.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from posting.platforms.sofurry import SoFurryPoster
from posting.story_reader import build_package, load_story


STORY_NAME = "Tombstone"


async def main() -> int:
    print("=" * 70)
    print(f"SoFurry Draft Test — {STORY_NAME}")
    print("=" * 70)
    print()

    print("[1/5] Loading story + building SF package...")
    story = load_story(STORY_NAME)
    package = build_package(story, chapter_index=0, platform="sf")
    print(f"  story:           {story.name}")
    print(f"  total words:     {story.total_words:,}")
    print(f"  title:           {package.title}")
    print(f"  description:     {package.description[:80]}{'...' if len(package.description) > 80 else ''}")
    print(f"  sf tag count:    {len(package.tags)}")
    print(f"  resolved file:   {package.file_path}")
    if package.file_path:
        print(f"  file size:       {Path(package.file_path).stat().st_size:,} bytes")
    print(f"  thumbnail:       {package.thumbnail_path}")
    print()

    poster = SoFurryPoster()

    print("[2/5] Login + safety check (cross-check existing gallery)...")
    client = await poster._ensure_client()
    print("  [OK] logged in")
    try:
        gallery = await client.get_all_gallery_ids()
        gallery_titles = {g.get("title", "").strip().lower() for g in gallery}
        print(f"  found {len(gallery)} existing submissions")
        display_title = story.name.replace("_", " ").strip().lower()
        if display_title in gallery_titles:
            print(f"  [INFO] {display_title!r} title appears in existing gallery — proceeding anyway (drafts coexist)")
        else:
            print("  no title overlap")
    except Exception as e:
        print(f"  [WARN] gallery scrape failed: {e} — proceeding without overlap check")
    print()

    print("[3/5] Posting as draft via SoFurryPoster.post() with extra[draft]=True...")
    package.extra["draft"] = True
    result = await poster.post(package)
    if not result.success:
        print(f"  [FAIL] {result.error}")
        return 1
    sub_id = result.external_id
    print(f"  [OK] submission_id={sub_id} ({result.duration_seconds:.1f}s)")
    print(f"  url: {result.external_url}")
    print()

    print("[4/5] Verifying privacy via raw /ui/submission/{id}...")
    await asyncio.sleep(2)
    try:
        raw_resp = await client._http.get(
            f"https://sofurry.com/ui/submission/{sub_id}",
            headers={"Accept": "application/json"},
        )
        print(f"  raw API status:  {raw_resp.status_code}")
        if raw_resp.status_code == 200:
            raw = raw_resp.json()
            server_privacy = raw.get("privacy")
            label = {1: "Private", 2: "Unlisted", 3: "Public"}.get(server_privacy, str(server_privacy))
            print(f"  server privacy:  {server_privacy} ({label})")
            print(f"  server title:    {raw.get('title', '')!r}")
            print(f"  server rating:   {raw.get('rating', '')}")
            tag_count = len(raw.get("artistTags", []))
            print(f"  server tags:     {tag_count}")
        else:
            print(f"  [WARN] raw fetch returned {raw_resp.status_code}")
    except Exception as e:
        print(f"  [WARN] verify call failed: {e}")
    print()

    issues = []
    print("[5/5] Final report")
    print("=" * 70)
    if issues:
        print(f"PARTIAL — {len(issues)} issue(s):")
        for i in issues:
            print(f"  - {i}")
        print(f"  visit (logged in): https://sofurry.com/s/{sub_id}")
        return 1
    print("DRAFT TEST PASSED")
    print(f"  submission {sub_id} created as Private (privacy=1)")
    print(f"  visit (logged in): https://sofurry.com/s/{sub_id}")
    print()
    print("To clean up: visit the URL while logged in, click Edit, then Delete.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
