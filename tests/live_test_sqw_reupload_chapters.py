"""Live test: re-upload all 5 Chosen chapters to work 91374 with the
fixed (non-buggy) content from the regenerated SquidgeWorld files.

Uses the new safe edit_chapter() method.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from clients.sqw.client import SquidgeWorldClient


WORK_ID = "91374"
SQW_DIR = Path("C:/Users/rhysc/claude/m_x/Archives/Complete_Stories/Chosen/SquidgeWorld")

CHAPTERS = [
    "Chapter_1_The_Heat",
    "Chapter_2_The_Market",
    "Chapter_3_The_Clearing",
    "Chapter_4_Chosen",
    "Chapter_5_After",
]


async def main() -> int:
    print("=" * 70)
    print(f"Re-uploading Chosen chapters to work {WORK_ID}")
    print("=" * 70)
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

    # Get the chapter IDs from the work
    print(f"Fetching chapter IDs for work {WORK_ID}...")
    chapter_list = await client.get_chapter_ids(WORK_ID)
    if not chapter_list:
        print("FAILED: no chapters returned")
        return 1
    print(f"  Found {len(chapter_list)} chapters")
    for ch in chapter_list:
        print(f"    index={ch.get('index', '?')} chapter_id={ch.get('chapter_id', '?')}")
    print()

    if len(chapter_list) != len(CHAPTERS):
        print(f"WARNING: expected {len(CHAPTERS)} chapters, found {len(chapter_list)}")

    # Pair source files with chapter IDs by index
    chapter_by_index = {ch.get("index", 0): ch.get("chapter_id", "") for ch in chapter_list}

    print("Updating each chapter with regenerated (fixed) content...")
    print()
    for i, name in enumerate(CHAPTERS, start=1):
        chapter_id = chapter_by_index.get(i)
        if not chapter_id:
            print(f"  [SKIP] Chapter {i} ({name}) — no chapter_id found")
            continue
        sqw_path = SQW_DIR / f"{name}.html"
        if not sqw_path.is_file():
            print(f"  [SKIP] {name} — file not found")
            continue
        content = sqw_path.read_text(encoding="utf-8")
        size = sqw_path.stat().st_size
        print(f"  Ch{i} {name} (id={chapter_id}, {size:,} bytes)")
        try:
            result = await client.edit_chapter(WORK_ID, chapter_id, content=content)
            print(f"      OK: {result}")
        except Exception as e:
            print(f"      FAIL: {e}")
            return 1
        await asyncio.sleep(2)

    print()
    print(f"All chapters updated. Verify at:")
    print(f"  https://www.squidgeworld.org/works/{WORK_ID}/chapters/{chapter_by_index[4]}")
    print(f"  (Ch4 was the worst — should now show clean inner emphasis)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
