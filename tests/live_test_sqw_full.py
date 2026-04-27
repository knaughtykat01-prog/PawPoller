"""Live test: full SquidgeWorld posting pipeline.

1. Read Chosen's story.json + Work_Skin.css
2. Find or create the Work Skin "Chosen Skin TEST" on SquidgeWorld
3. Edit work 91374 (the existing draft) to:
   - Set proper category (F/M from story.json)
   - Set proper warning (No Archive Warnings Apply)
   - Set proper fandom (Kung Fu Panda)
   - Set characters and relationship from story.json
   - Apply the new Work Skin
   - Add the [WORKSKIN ATTACHED] marker to title for visual confirmation
4. Verify by re-fetching the work page and confirming the changes
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from clients.sqw.client import SquidgeWorldClient


WORK_ID = "91374"
STORY_ROOT = Path("C:/Users/rhysc/claude/m_x/Archives/Complete_Stories/Chosen")
SKIN_TITLE = "Chosen Skin TEST"


async def main() -> int:
    print("=" * 70)
    print(f"SquidgeWorld Full Pipeline Test — Chosen / Work {WORK_ID}")
    print("=" * 70)
    print()

    # 1. Load story metadata + work skin CSS
    story = json.loads((STORY_ROOT / "story.json").read_text(encoding="utf-8"))
    skin_css = (STORY_ROOT / "SquidgeWorld" / "Work_Skin.css").read_text(encoding="utf-8")
    print(f"Story metadata loaded:")
    print(f"  fandom:        {story.get('fandom')}")
    print(f"  category:      {story.get('category')}")
    print(f"  warnings:      {story.get('warnings')}")
    print(f"  characters:    {story.get('characters')}")
    print(f"  relationships: {story.get('relationships')}")
    print(f"  rating:        {story.get('rating')}")
    print()
    print(f"Work Skin CSS: {len(skin_css)} bytes")
    print()

    # 2. Login
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

    # 3. Find or create the Work Skin
    print(f"Looking up existing Work Skin {SKIN_TITLE!r}...")
    skin_id = await client.find_work_skin_by_title(SKIN_TITLE)
    if skin_id:
        print(f"  Found existing skin: id={skin_id}")
    else:
        print("  Not found. Creating new Work Skin...")
        skin_result = await client.create_work_skin(
            title=SKIN_TITLE,
            css=skin_css,
            description="Auto-uploaded by PawPoller live test for Chosen",
        )
        skin_id = skin_result["skin_id"]
        print(f"  Created skin: id={skin_id} url={skin_result['url']}")
    print()

    # 4. Build the edit parameters from story.json
    # OTW Archive expects characters/relationships as comma-separated strings
    characters_str = ", ".join(story.get("characters", []))
    relationships_str = ", ".join(story.get("relationships", []))

    # Map our rating values to OTW canonical
    rating_map = {
        "explicit": "Explicit",
        "mature": "Mature",
        "teen": "Teen And Up Audiences",
        "general": "General Audiences",
    }
    rating = rating_map.get(story.get("rating", "").lower(), "Explicit")

    # Add a marker to the title so we can see the edit landed
    new_title = f"Chosen [DRAFT TEST 2026-04-07] [WORKSKIN ATTACHED]"

    print("Editing work with full metadata + skin...")
    print(f"  new title:     {new_title}")
    print(f"  fandom:        {story.get('fandom')}")
    print(f"  rating:        {rating}")
    print(f"  warnings:      {story.get('warnings')}")
    print(f"  categories:    {[story.get('category')]}")
    print(f"  characters:    {characters_str}")
    print(f"  relationships: {relationships_str}")
    print(f"  work_skin_id:  {skin_id}")
    print()

    result = await client.edit_work(
        WORK_ID,
        title=new_title,
        fandom=story.get("fandom"),
        rating=rating,
        warnings=story.get("warnings", ["No Archive Warnings Apply"]),
        categories=[story.get("category")] if story.get("category") else [],
        characters=characters_str,
        relationship=relationships_str,
        work_skin_id=skin_id,
        save_as_draft=True,
    )

    print(f"Edit result: {result}")
    print()

    # 5. Verify by re-fetching the work
    print("Verifying...")
    verify_resp = await client._http.get(f"https://www.squidgeworld.org/works/{WORK_ID}")
    if verify_resp.status_code != 200:
        print(f"  Verify fetch failed: status {verify_resp.status_code}")
        return 1
    html = verify_resp.text

    import re
    title_m = re.search(r'<h2[^>]*class="title[^"]*"[^>]*>(.*?)</h2>', html, re.DOTALL)
    if title_m:
        actual_title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip()
        print(f"  Live title: {actual_title!r}")
        if "[WORKSKIN ATTACHED]" in actual_title:
            print("  [OK] Title marker present")
        else:
            print("  [FAIL] Title marker NOT found")

    # Look for the work skin reference
    if f'/skins/{skin_id}' in html or f'work_skin_id={skin_id}' in html:
        print(f"  [OK] Work Skin {skin_id} referenced in page")
    else:
        print(f"  (Work Skin reference not found in displayed page; check edit form)")

    print()
    print(f"Verify visually at:")
    print(f"  https://www.squidgeworld.org/works/{WORK_ID}/preview")
    print(f"  https://www.squidgeworld.org/works/{WORK_ID}/edit  (check Work Skin dropdown)")
    print(f"  https://www.squidgeworld.org/skins/{skin_id}       (the new skin)")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
