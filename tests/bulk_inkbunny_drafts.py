"""Bulk-draft missing stories to Inkbunny.

For every local story not yet on KnaughtyKat's IB account, build a
full-story IB package via story_reader.build_package() and post it as
a HIDDEN DRAFT. Records each result in the publications table.

SAFETY:
  - Every package gets extra["draft"] = True (visibility omitted ⇒ hidden).
  - The script first lists currently published submissions on IB and
    refuses to touch any story whose title is already live.
  - Tombstone (already drafted as 3847083) is also recorded into
    publications so the registry stays accurate.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import get_connection, init_db
from database.posting_queries import upsert_publication
from posting.platforms.inkbunny import InkbunnyPoster
from posting.story_reader import build_package, load_story


# Local stories that need IB drafts (verified not yet on IB account)
DRAFT_TARGETS = [
    "Chosen",
    "Not_So_Efficient_Studying",
    "Overtime",
    "Ruins_of_Breeding",
    "The_Haunting_Desires",
]

# Tombstone is already a draft on IB — register it.
EXISTING_DRAFTS = {
    "Tombstone": 3847083,
}


async def register_existing(client, conn) -> None:
    """Pull metadata for already-known drafts and write to publications."""
    print("[setup] Registering existing IB drafts in publications table...")
    for story_name, sub_id in EXISTING_DRAFTS.items():
        details = await client.get_submission_details([sub_id])
        if not details:
            print(f"  [WARN] {story_name} ({sub_id}): not found on IB")
            continue
        d = details[0]
        story = load_story(story_name)
        upsert_publication(
            conn,
            story_name=story_name,
            chapter_index=0,
            platform="ib",
            external_id=str(sub_id),
            external_url=f"https://inkbunny.net/s/{sub_id}",
            title_used=d.title,
            description_used=story.description,
            tags_used=story.tags_by_platform.get("ib", []),
            rating_used="adult",
            format_file=str(Path(load_story(story_name).path) / "BBCode" / f"{story_name}_bbcode.txt"),
            word_count=story.total_words,
            status="draft",
        )
        print(f"  [OK] {story_name} -> submission {sub_id} recorded")
    print()


async def main() -> int:
    print("=" * 70)
    print("Inkbunny: bulk-draft missing stories")
    print("=" * 70)
    print()

    # 1. Sanity check: verify each target loads + has BBCode
    for s in DRAFT_TARGETS:
        try:
            story = load_story(s)
            pkg = build_package(story, chapter_index=0, platform="ib")
            if not pkg.file_path or not Path(pkg.file_path).is_file():
                print(f"[FAIL] {s}: no BBCode file resolved")
                return 1
            ib_tags = story.tags_by_platform.get("ib", [])
            if len(ib_tags) < 4:
                print(f"[FAIL] {s}: only {len(ib_tags)} IB tags (need ≥4)")
                return 1
        except Exception as e:
            print(f"[FAIL] {s}: {e}")
            return 1

    init_db()
    conn = get_connection()
    poster = InkbunnyPoster()
    client = await poster._ensure_client()

    # 2. Cross-check against published IB to avoid clobbering anything live
    print("[guard] Pulling published IB submissions for safety check...")
    pub_subs = await client.search_user_submissions()
    pub_titles = {s["title"].strip().lower() for s in pub_subs}
    print(f"  found {len(pub_subs)} published submissions")
    for target in DRAFT_TARGETS:
        try:
            story = load_story(target)
        except Exception:
            continue
        display_title = story.name.replace("_", " ").strip().lower()
        if display_title in pub_titles:
            print(f"[ABORT] {target} ({display_title!r}) is already published on IB")
            return 1
    print("  no overlap with published works — safe to proceed")
    print()

    # 3. Register existing drafts
    await register_existing(client, conn)

    # 4. Draft each missing story
    results = []
    for i, story_name in enumerate(DRAFT_TARGETS, start=1):
        print(f"[{i}/{len(DRAFT_TARGETS)}] {story_name}")
        try:
            story = load_story(story_name)
            package = build_package(story, chapter_index=0, platform="ib")
            package.extra["draft"] = True

            print(f"  title:        {package.title}")
            print(f"  description:  {package.description[:80]}{'...' if len(package.description) > 80 else ''}")
            print(f"  tags:         {len(package.tags)}")
            print(f"  word count:   {package.word_count:,}")
            print(f"  file:         {Path(package.file_path).name} ({Path(package.file_path).stat().st_size:,} bytes)")
            print(f"  thumbnail:    {package.thumbnail_path or '(none — add via UI later)'}")

            result = await poster.post(package)
            if not result.success:
                print(f"  [FAIL] {result.error}")
                results.append((story_name, None, result.error))
                continue

            sub_id = int(result.external_id)
            print(f"  [OK] submission_id={sub_id} ({result.duration_seconds:.1f}s)")
            print(f"  url: {result.external_url}")

            # Verify draft state via api_submissions
            await asyncio.sleep(2)
            details = await client.get_submission_details([sub_id])
            if details:
                d = details[0]
                print(f"  verified: title={d.title!r} pages={d.pagecount} keywords={len(d.keywords)}")

            # Record in publications table
            upsert_publication(
                conn,
                story_name=story_name,
                chapter_index=0,
                platform="ib",
                external_id=str(sub_id),
                external_url=result.external_url,
                title_used=package.title,
                description_used=package.description,
                tags_used=package.tags,
                rating_used=package.rating,
                format_file=package.file_path,
                word_count=package.word_count,
                status="draft",
            )
            results.append((story_name, sub_id, None))
        except Exception as e:
            print(f"  [EXCEPTION] {e}")
            import traceback
            traceback.print_exc()
            results.append((story_name, None, str(e)))
        print()

        # Polite pause between IB uploads
        if i < len(DRAFT_TARGETS):
            await asyncio.sleep(5)

    conn.close()

    # 5. Summary
    print("=" * 70)
    print("BULK DRAFT SUMMARY")
    print("=" * 70)
    ok = [r for r in results if r[1]]
    fail = [r for r in results if not r[1]]
    print(f"  succeeded: {len(ok)} / {len(results)}")
    for name, sub_id, _ in ok:
        print(f"    {name:30s} -> https://inkbunny.net/s/{sub_id}")
    if fail:
        print(f"  failed: {len(fail)}")
        for name, _, err in fail:
            print(f"    {name:30s}: {err}")
    print()
    print("All new submissions are HIDDEN drafts. Visit each (logged in) to add")
    print("thumbnails and review before publishing.")
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
