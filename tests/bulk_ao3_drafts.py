"""Bulk-draft missing stories to AO3.

Posts every local story not yet on AO3 as a HIDDEN PREVIEW (AO3's draft
state) using AO3Poster. Records each in the publications table.

Tombstone is already drafted (work 82711601) and is recorded into
publications during the setup phase.

SAFETY:
  - create_work uses preview_button → AO3 guarantees draft state.
  - The poster's post-flight check only aborts on POSITIVE confirmation
    of publication (handles AO3's drafts-page flakiness gracefully).
  - Cross-checks against client.get_all_work_ids() to skip stories that
    are already PUBLISHED on AO3.
  - Each story is independent: a single failure does not abort the run.
  - Generous sleep between posts (10s) — AO3 is volunteer-run.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# In-container path first (for docker exec runs), local path second
sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import get_connection, init_db
from database.posting_queries import upsert_publication
from posting.platforms.ao3 import AO3Poster
from posting.story_reader import build_package, load_story


# All local stories. Tombstone is already drafted, recorded separately.
ALL_STORIES = [
    "Tombstone",                  # already drafted (82711601)
    "Chosen",
    "Drumheller_Detour",
    "Extra_Credit",
    "Hypnotic_Claim",
    "Not_So_Efficient_Studying",
    "Overtime",
    "Ruins_of_Breeding",
    "The_Abstinent_Bet",
    "The_Haunting_Desires",
    "The_Silk_Threaded_Bonds",
    "Velvet_And_Vice",
]

EXISTING_DRAFTS = {
    "Tombstone": "82711601",
}

INTER_POST_DELAY = 10  # seconds


def _safety_check_published(pub_titles: set, target: str) -> tuple[bool, str]:
    """Compare local story name (and natural title) against published list."""
    try:
        story = load_story(target)
    except Exception:
        return False, ""
    display = story.name.replace("_", " ").strip().lower()
    if display in pub_titles:
        return True, display
    return False, display


async def register_existing(client, conn) -> None:
    print("[setup] Registering existing AO3 drafts in publications table...")
    for story_name, work_id in EXISTING_DRAFTS.items():
        try:
            story = load_story(story_name)
        except Exception as e:
            print(f"  [WARN] {story_name}: {e}")
            continue
        upsert_publication(
            conn,
            story_name=story_name,
            chapter_index=0,
            platform="ao3",
            external_id=work_id,
            external_url=f"https://archiveofourown.org/works/{work_id}",
            title_used=story.name.replace("_", " "),
            description_used=story.description,
            tags_used=story.tags_by_platform.get("default", []),
            rating_used="adult",
            format_file=str(story.path / "HTML" / f"{story_name}_Clean.html"),
            word_count=story.total_words,
            status="draft",
        )
        print(f"  [OK] {story_name} -> work {work_id} recorded")
    print()


async def main() -> int:
    print("=" * 70)
    print("AO3: bulk-draft missing stories")
    print("=" * 70)
    print()

    init_db()
    conn = get_connection()
    poster = AO3Poster()

    print("[1/4] Login...")
    client = await poster._ensure_client()
    print("  [OK] logged in")
    print()

    # 2. Pull published works for safety
    print("[2/4] Pulling published AO3 works for safety check...")
    pub_works = await client.get_all_work_ids()
    pub_titles = {w["title"].strip().lower() for w in pub_works}
    print(f"  found {len(pub_works)} published works")
    for w in pub_works[:10]:
        print(f"    {w['work_id']}  {w['title']}")
    if len(pub_works) > 10:
        print(f"    ... and {len(pub_works) - 10} more")
    print()

    # 3. Determine targets (skip already-drafted, skip published)
    targets = []
    for story_name in ALL_STORIES:
        if story_name in EXISTING_DRAFTS:
            print(f"[skip] {story_name} — already drafted as {EXISTING_DRAFTS[story_name]}")
            continue
        clash, display = _safety_check_published(pub_titles, story_name)
        if clash:
            print(f"[skip] {story_name} — already published on AO3 ({display!r})")
            continue
        targets.append(story_name)
    print()
    print(f"[3/4] Drafting {len(targets)} stories...")
    print()

    # 4. Register existing
    await register_existing(client, conn)

    # 5. Draft each
    results = []
    for i, story_name in enumerate(targets, start=1):
        print(f"[{i}/{len(targets)}] {story_name}")
        try:
            story = load_story(story_name)
            package = build_package(story, chapter_index=0, platform="ao3")
            print(f"  title:        {package.title}")
            print(f"  description:  {package.description[:80]}{'...' if len(package.description) > 80 else ''}")
            print(f"  fandom:       {story.fandom or 'Original Work'}")
            print(f"  warnings:     {story.warnings}")
            print(f"  categories:   {story.categories}")
            print(f"  characters:   {len(story.characters)} character(s)")
            print(f"  relationships:{len(story.relationships)} relationship(s)")
            print(f"  word count:   {package.word_count:,}")
            print(f"  content file: {Path(package.file_path).name if package.file_path else '(none)'}")

            result = await poster.post(package)
            if not result.success:
                print(f"  [FAIL] {result.error}")
                results.append((story_name, None, result.error))
                continue

            work_id = result.external_id
            print(f"  [OK] work_id={work_id} ({result.duration_seconds:.1f}s)")
            print(f"  url: {result.external_url}")

            # Record in publications
            try:
                upsert_publication(
                    conn,
                    story_name=story_name,
                    chapter_index=0,
                    platform="ao3",
                    external_id=work_id,
                    external_url=result.external_url,
                    title_used=package.title,
                    description_used=package.description,
                    tags_used=package.tags or story.tags_by_platform.get("default", []),
                    rating_used=package.rating,
                    format_file=package.file_path or "",
                    word_count=package.word_count,
                    status="draft",
                )
            except Exception as db_err:
                print(f"  [WARN] publications upsert failed: {db_err}")

            results.append((story_name, work_id, None))
        except Exception as e:
            print(f"  [EXCEPTION] {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            results.append((story_name, None, str(e)))
        print()

        # Polite pause between AO3 posts (volunteer-run server)
        if i < len(targets):
            print(f"  ... sleeping {INTER_POST_DELAY}s before next post ...")
            await asyncio.sleep(INTER_POST_DELAY)
            print()

    conn.close()

    # 6. Summary
    print("=" * 70)
    print("[4/4] BULK DRAFT SUMMARY")
    print("=" * 70)
    ok = [r for r in results if r[1]]
    fail = [r for r in results if not r[1]]
    print(f"  succeeded: {len(ok)} / {len(results)}")
    for name, work_id, _ in ok:
        print(f"    {name:30s} -> https://archiveofourown.org/works/{work_id}/preview")
    if fail:
        print(f"  failed: {len(fail)}")
        for name, _, err in fail:
            err_short = (err or "")[:200]
            print(f"    {name:30s}: {err_short}")
    print()
    print("Plus pre-existing drafts:")
    for name, work_id in EXISTING_DRAFTS.items():
        print(f"    {name:30s} -> https://archiveofourown.org/works/{work_id}/preview")
    print()
    print("All new works are PREVIEW/DRAFT state. Visit each (logged in) to")
    print("review and click 'Post Without Preview' when ready to publish.")
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
