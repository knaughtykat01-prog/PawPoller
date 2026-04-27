"""Live test: clean up the published work 91374 to be the proper live version.

The previous tests left it titled 'Chosen [DRAFT TEST 2026-04-07] [WORKSKIN ATTACHED]'
with a test-marker summary and only chapter-1 tags. Replace with clean metadata
from story.json and keep it published.
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
SKIN_ID = "2820"
STORY_ROOT = Path("C:/Users/rhysc/claude/m_x/Archives/Complete_Stories/Chosen")


async def main() -> int:
    print("=" * 70)
    print(f"SquidgeWorld Finalize Test — Work {WORK_ID}")
    print("=" * 70)
    print()

    story = json.loads((STORY_ROOT / "story.json").read_text(encoding="utf-8"))

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

    # SquidgeWorld (OTW Archive) HARD limit: fandom + relationship + character +
    # additional tags must total <= 75. Fandom (1) + relationships (1) +
    # characters (2) = 4, so additional tags must be <= 71.
    SQW_FREEFORM_LIMIT = 71
    all_tags = story.get("tags", {}).get("default", [])
    if len(all_tags) > SQW_FREEFORM_LIMIT:
        tags = all_tags[:SQW_FREEFORM_LIMIT]
        print(f"  (trimmed {len(all_tags)} -> {SQW_FREEFORM_LIMIT} tags for SQW limit)")
    else:
        tags = all_tags
    additional_tags = ", ".join(tags)
    print(f"Story metadata to apply:")
    print(f"  title:       {story['title']}")
    print(f"  summary:     {story.get('description', '')[:80]}...")
    print(f"  tags:        {len(tags)} tags")
    print(f"  rating:      {story.get('rating')}")
    print(f"  fandom:      {story.get('fandom')}")
    print(f"  category:    {story.get('category')}")
    print(f"  warnings:    {story.get('warnings')}")
    print(f"  characters:  {story.get('characters')}")
    print(f"  relationships: {story.get('relationships')}")
    print(f"  work_skin_id: {SKIN_ID}")
    print()

    print(f"Editing work {WORK_ID} (keeping it published)...")
    result = await client.edit_work(
        WORK_ID,
        title=story["title"],
        summary=story.get("description", ""),
        additional_tags=additional_tags,
        fandom=story.get("fandom"),
        rating="Explicit",
        warnings=story.get("warnings", ["No Archive Warnings Apply"]),
        categories=[story.get("category")] if story.get("category") else [],
        characters=", ".join(story.get("characters", [])),
        relationship=", ".join(story.get("relationships", [])),
        work_skin_id=SKIN_ID,
        save_as_draft=False,  # keep it published
    )
    print(f"Edit result: {result}")
    print()

    # Verify
    print("Verifying live page...")
    import re
    r = await client._http.get(f"https://www.squidgeworld.org/works/{WORK_ID}")
    if r.status_code != 200:
        print(f"  Verify fetch failed: status {r.status_code}")
        return 1
    html = r.text

    title_m = re.search(r'<h2[^>]*class="title[^"]*"[^>]*>(.*?)</h2>', html, re.DOTALL)
    if title_m:
        live_title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip()
        print(f"  Live title: {live_title!r}")
        if live_title == story["title"]:
            print("  [OK] Title is clean")
        else:
            print("  [WARN] Title differs from expected")

    # Tag count check (heuristic)
    tag_links = re.findall(r'<li[^>]*class="freeforms"[^>]*>.*?<a[^>]*>([^<]+)</a>', html, re.DOTALL)
    print(f"  freeform tags on page: {len(tag_links)}")

    print()
    print("Done. Verify visually:")
    print(f"  https://www.squidgeworld.org/works/{WORK_ID}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
