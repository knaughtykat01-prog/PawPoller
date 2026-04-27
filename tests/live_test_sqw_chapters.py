"""Live test: edit work skin metadata + add chapters 2-5 to draft 91374.

1. Update the Work Skin (id 2820) with proper title and description
2. Add Chapters 2-5 of Chosen to the existing draft work
3. Verify the work now has 5 chapters
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from clients.sqw.client import SquidgeWorldClient


WORK_ID = "91374"
SKIN_ID = "2820"
STORY_ROOT = Path("C:/Users/rhysc/claude/m_x/Archives/Complete_Stories/Chosen")

# Skin metadata to apply
NEW_SKIN_TITLE = "Chosen Skin"
NEW_SKIN_DESCRIPTION = (
    "Custom Work Skin for the story 'Chosen' by KnaughtyKat. "
    "Provides themed typography, section breaks, and warning page styling. "
    "Auto-uploaded by PawPoller."
)

# Chapters to add (1 already exists; we add 2 through 5)
CHAPTERS_TO_ADD = [
    {
        "index": 2,
        "title": "Chapter 2: The Market",
        "file": "Chapter_2_The_Market.html",
    },
    {
        "index": 3,
        "title": "Chapter 3: The Clearing",
        "file": "Chapter_3_The_Clearing.html",
    },
    {
        "index": 4,
        "title": "Chapter 4: Chosen",
        "file": "Chapter_4_Chosen.html",
    },
    {
        "index": 5,
        "title": "Chapter 5: After",
        "file": "Chapter_5_After.html",
    },
]


async def main() -> int:
    print("=" * 70)
    print(f"SquidgeWorld Chapters + Skin Edit Test")
    print(f"  Work: {WORK_ID}, Skin: {SKIN_ID}")
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

    # Step 1: Edit the work skin metadata
    print(f"[1/2] Editing Work Skin {SKIN_ID}")
    print(f"      title: {NEW_SKIN_TITLE!r}")
    print(f"      description: {NEW_SKIN_DESCRIPTION[:80]}...")
    skin_result = await client.edit_work_skin(
        SKIN_ID,
        title=NEW_SKIN_TITLE,
        description=NEW_SKIN_DESCRIPTION,
    )
    print(f"      OK: {skin_result['url']}")
    print()

    # Step 2: Add chapters 2-5
    print(f"[2/2] Adding {len(CHAPTERS_TO_ADD)} chapters to work {WORK_ID}")
    added = []
    for ch in CHAPTERS_TO_ADD:
        chapter_path = STORY_ROOT / "SquidgeWorld" / ch["file"]
        if not chapter_path.is_file():
            print(f"  [SKIP] {ch['title']} - file not found: {chapter_path}")
            continue
        content = chapter_path.read_text(encoding="utf-8")
        size = chapter_path.stat().st_size
        print(f"  - {ch['title']} ({size:,} bytes)")
        try:
            result = await client.create_chapter(
                WORK_ID,
                title=ch["title"],
                content=content,
                position=ch["index"],
            )
            print(f"      OK: chapter_id={result.get('chapter_id', '?')} url={result.get('url', '')}")
            added.append((ch["index"], result.get("chapter_id", "?")))
        except Exception as e:
            print(f"      FAIL: {e}")
            return 1
        await asyncio.sleep(2)  # be nice to OTW

    print()
    print(f"Added {len(added)} chapters.")
    print()

    # Step 3: Verify chapter count via the navigation page
    print("Verifying chapter count...")
    nav_resp = await client._http.get(f"https://www.squidgeworld.org/works/{WORK_ID}/navigate")
    if nav_resp.status_code == 200:
        # Each chapter shows up as a list item with /works/{id}/chapters/{ch_id}
        ch_links = set(re.findall(rf'/works/{WORK_ID}/chapters/(\d+)', nav_resp.text))
        print(f"  Found {len(ch_links)} chapter IDs on the navigate page")
        for cid in sorted(ch_links, key=int):
            print(f"    chapter_id={cid}")
    else:
        print(f"  Verify navigate failed (status {nav_resp.status_code}) - check manually")

    print()
    print("Verify visually at:")
    print(f"  https://www.squidgeworld.org/works/{WORK_ID}/preview      (work preview, all chapters)")
    print(f"  https://www.squidgeworld.org/works/{WORK_ID}/navigate     (chapter list)")
    print(f"  https://www.squidgeworld.org/skins/{SKIN_ID}              (the renamed skin)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
