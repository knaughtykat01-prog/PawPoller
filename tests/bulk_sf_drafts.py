"""Bulk-draft missing stories to SoFurry as Private (privacy=1).

For every local story not yet on SoFurry, post via SoFurryPoster with
extra["draft"]=True. Tombstone is already drafted as nLrR4PBe; recorded
in the publications table during setup.

SAFETY:
  - Every package gets extra["draft"]=True → privacy=1 (Private, owner-only)
  - Cross-check against client.get_all_gallery_ids() to skip existing works
  - Server-side privacy verification on every successful post
  - Per-story try/except so a single failure doesn't abort the run
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import get_connection, init_db
from database.posting_queries import upsert_publication
from posting.platforms.sofurry import SoFurryPoster
from posting.story_reader import build_package, load_story


# Stories I want on SF as Private drafts. The 5 not yet posted at all,
# plus Tombstone (already drafted as nLrR4PBe — registered in setup).
MISSING_FROM_SF = [
    "Chosen",
    "Not_So_Efficient_Studying",
    "Overtime",
    "Ruins_of_Breeding",
    "The_Haunting_Desires",
]

EXISTING_DRAFTS = {
    "Tombstone": "nLrR4PBe",
}

INTER_POST_DELAY = 5  # SF is faster than AO3 — short pause is enough


async def register_existing(client, conn) -> None:
    print("[setup] Registering existing SF drafts in publications table...")
    for story_name, sub_id in EXISTING_DRAFTS.items():
        try:
            story = load_story(story_name)
        except Exception as e:
            print(f"  [WARN] {story_name}: {e}")
            continue
        upsert_publication(
            conn,
            story_name=story_name,
            chapter_index=0,
            platform="sf",
            external_id=sub_id,
            external_url=f"https://sofurry.com/s/{sub_id}",
            title_used=story.name.replace("_", " "),
            description_used=story.description,
            tags_used=story.tags_by_platform.get("sofurry", story.tags_by_platform.get("default", [])),
            rating_used="adult",
            format_file=str(story.path / "HTML" / f"{story_name}_Clean.html"),
            word_count=story.total_words,
            status="draft",
        )
        print(f"  [OK] {story_name} -> submission {sub_id} recorded")
    print()


async def main() -> int:
    print("=" * 70)
    print("SoFurry: bulk-draft missing stories as Private")
    print("=" * 70)
    print()

    init_db()
    conn = get_connection()
    poster = SoFurryPoster()

    print("[1/4] Login...")
    client = await poster._ensure_client()
    print("  [OK] logged in")
    print()

    print("[2/4] Pulling SF gallery for safety check...")
    try:
        gallery = await client.get_all_gallery_ids()
        gallery_titles = {g.get("title", "").strip().lower() for g in gallery}
        print(f"  found {len(gallery)} existing submissions")
    except Exception as e:
        print(f"  [WARN] gallery scrape failed: {e}")
        gallery_titles = set()
    print()

    # Determine targets
    targets = []
    for story_name in MISSING_FROM_SF:
        if story_name in EXISTING_DRAFTS:
            print(f"[skip] {story_name} — already drafted as {EXISTING_DRAFTS[story_name]}")
            continue
        try:
            story = load_story(story_name)
        except Exception as e:
            print(f"[skip] {story_name} — load failed: {e}")
            continue
        display_title = story.name.replace("_", " ").strip().lower()
        if display_title in gallery_titles:
            print(f"[skip] {story_name} — title already in SF gallery ({display_title!r})")
            continue
        targets.append(story_name)
    print()
    print(f"[3/4] Drafting {len(targets)} stories as Private...")
    print()

    await register_existing(client, conn)

    results = []
    for i, story_name in enumerate(targets, start=1):
        print(f"[{i}/{len(targets)}] {story_name}")
        try:
            story = load_story(story_name)
            package = build_package(story, chapter_index=0, platform="sf")
            package.extra["draft"] = True

            print(f"  title:        {package.title}")
            print(f"  description:  {package.description[:80]}{'...' if len(package.description) > 80 else ''}")
            print(f"  tags:         {len(package.tags)}")
            print(f"  word count:   {package.word_count:,}")
            print(f"  file:         {Path(package.file_path).name if package.file_path else '(none)'}")
            if package.file_path:
                size_kb = Path(package.file_path).stat().st_size / 1024
                print(f"  file size:    {size_kb:.0f} KB (limit: 512 KB)")
            print(f"  thumbnail:    {Path(package.thumbnail_path).name if package.thumbnail_path else '(none)'}")

            result = await poster.post(package)
            if not result.success:
                print(f"  [FAIL] {result.error}")
                results.append((story_name, None, result.error))
                continue

            sub_id = result.external_id
            print(f"  [OK] submission_id={sub_id} ({result.duration_seconds:.1f}s)")
            print(f"  url: {result.external_url}")

            try:
                upsert_publication(
                    conn,
                    story_name=story_name,
                    chapter_index=0,
                    platform="sf",
                    external_id=sub_id,
                    external_url=result.external_url,
                    title_used=package.title,
                    description_used=package.description,
                    tags_used=package.tags,
                    rating_used=package.rating,
                    format_file=package.file_path or "",
                    word_count=package.word_count,
                    status="draft",
                )
            except Exception as db_err:
                print(f"  [WARN] publications upsert failed: {db_err}")

            results.append((story_name, sub_id, None))
        except Exception as e:
            print(f"  [EXCEPTION] {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            results.append((story_name, None, str(e)))
        print()

        if i < len(targets):
            print(f"  ... sleeping {INTER_POST_DELAY}s before next post ...")
            await asyncio.sleep(INTER_POST_DELAY)
            print()

    conn.close()

    print("=" * 70)
    print("[4/4] BULK DRAFT SUMMARY")
    print("=" * 70)
    ok = [r for r in results if r[1]]
    fail = [r for r in results if not r[1]]
    print(f"  succeeded: {len(ok)} / {len(results)}")
    for name, sub_id, _ in ok:
        print(f"    {name:30s} -> https://sofurry.com/s/{sub_id}")
    if fail:
        print(f"  failed: {len(fail)}")
        for name, _, err in fail:
            print(f"    {name:30s}: {(err or '')[:200]}")
    print()
    print("Plus pre-existing drafts:")
    for name, sub_id in EXISTING_DRAFTS.items():
        print(f"    {name:30s} -> https://sofurry.com/s/{sub_id}")
    print()
    print("All new submissions are PRIVATE (owner-only). Visit while logged in")
    print("to review and switch to Public when ready.")
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
