"""Retry the AO3 stories that failed in the bulk run.

Retries:
  - Extra_Credit (network timeout in bulk run)
  - The_Abstinent_Bet/Nice_Version (subfolder, not loadable as bare 'The_Abstinent_Bet')
  - The_Abstinent_Bet/Naughty_Version
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import get_connection, init_db
from database.posting_queries import upsert_publication
from posting.platforms.ao3 import AO3Poster
from posting.story_reader import build_package, load_story


TARGETS = [
    "Extra_Credit",
    "The_Abstinent_Bet/Nice_Version",
    "The_Abstinent_Bet/Naughty_Version",
]


async def main() -> int:
    print("=" * 70)
    print("AO3 retry: Extra_Credit + Abstinent Bet (both versions)")
    print("=" * 70)
    print()

    init_db()
    conn = get_connection()
    poster = AO3Poster()

    print("[1/2] Login...")
    client = await poster._ensure_client()
    print("  [OK] logged in")
    print()

    results = []
    for i, story_name in enumerate(TARGETS, start=1):
        print(f"[{i}/{len(TARGETS)}] {story_name}")
        try:
            story = load_story(story_name)
            package = build_package(story, chapter_index=0, platform="ao3")

            # Some stories like Abstinent Bet have explicit titles in story.json
            # that need overriding (the build_package uses story.name which may
            # include the subfolder path). Use story.json title via story_reader's
            # logic — the title was set from story_path.name internally.
            print(f"  title:        {package.title}")
            print(f"  description:  {package.description[:80]}{'...' if len(package.description) > 80 else ''}")
            print(f"  fandom:       {story.fandom or 'Original Work'}")
            print(f"  word count:   {package.word_count:,}")
            print(f"  content file: {Path(package.file_path).name if package.file_path else '(none)'}")
            if not package.file_path:
                print(f"  [SKIP] no content file")
                results.append((story_name, None, "no content file"))
                continue

            result = await poster.post(package)
            if not result.success:
                print(f"  [FAIL] {result.error}")
                results.append((story_name, None, result.error))
                continue

            work_id = result.external_id
            print(f"  [OK] work_id={work_id} ({result.duration_seconds:.1f}s)")
            print(f"  url: {result.external_url}")

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

        if i < len(TARGETS):
            print(f"  ... sleeping 10s ...")
            await asyncio.sleep(10)
            print()

    conn.close()

    print("=" * 70)
    print("RETRY SUMMARY")
    print("=" * 70)
    ok = [r for r in results if r[1]]
    fail = [r for r in results if not r[1]]
    print(f"  succeeded: {len(ok)} / {len(results)}")
    for name, work_id, _ in ok:
        print(f"    {name:40s} -> https://archiveofourown.org/works/{work_id}/preview")
    if fail:
        print(f"  failed: {len(fail)}")
        for name, _, err in fail:
            print(f"    {name:40s}: {(err or '')[:200]}")
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
