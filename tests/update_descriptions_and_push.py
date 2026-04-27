"""Update story.json descriptions to the new 25-30 word / 2-sentence
versions and push the updates to the live SquidgeWorld works.

Uses SquidgeWorldPoster.edit() which auto-detects draft/published state
and preserves it (safety-checked after the edit).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from posting.platforms.base import StoryUploadPackage
from posting.platforms.squidgeworld import SquidgeWorldPoster
from clients.sqw.client import SquidgeWorldClient


ARCHIVE = Path("C:/Users/rhysc/claude/m_x/Archives/Complete_Stories")

# New descriptions: 25-30 words, 2 sentences max
NEW_DESCRIPTIONS: dict[str, str] = {
    "Chosen": (
        "Tigress's heat hits too hard to suppress. She flees the Jade Palace "
        "and collides with Bo — an ox grain seller whose calm is the only "
        "thing that holds her."
    ),
    "Drumheller_Detour": (
        "Two oil sands workers on a break from Fort McMurray find a roadside "
        "bar in Drumheller. Raptor twins with sharp teeth and sharper "
        "flirting take over the night."
    ),
    "Not_So_Efficient_Studying": (
        "The night before their anatomy exam, a possum and his bull terrier "
        "roommate run out of study methods. Hands-on palpation was supposed "
        "to be clinical — it isn't."
    ),
    "Overtime": (
        "After a home loss, a basketball captain and his rival end up alone "
        "in the locker room. What crawled under his skin all season wasn't hate."
    ),
    "Ruins_of_Breeding": (
        "An archaeologist horse uncovers an intact jungle temple and the "
        "sentient plant entity waiting centuries inside. What follows is not "
        "a rescue story."
    ),
    "The_Haunting_Desires": (
        "Three friends spend the night in a haunted Victorian mansion for a "
        "paranormal investigation. The house has been waiting, and it does "
        "not intend to let them leave unchanged."
    ),
    "The_Silk_Threaded_Bonds": (
        "In the palace of Senchal, the most beautiful servant in Elsweyr "
        "belongs to a noble who cannot admit what he wants. Slow-burn Khajiit "
        "devotion in the Elder Scrolls universe."
    ),
    "Tombstone": (
        "A bull alone in a Siem Reap dive bar, a civet flirting with him, "
        "and a wolf who walks in knowing. The collision plays out in a "
        "graveyard past midnight."
    ),
    "Velvet_And_Vice": (
        "A fox couple's stagnant relationship collides with a panther who "
        "runs Velvet and Vice. What Dain offers isn't fabric — it's the "
        "truth they've been hiding from each other."
    ),
}

# Known work IDs for stories we've posted/confirmed this session
STORY_TO_WORK_ID: dict[str, str] = {
    "Chosen": "91374",
    "Tombstone": "91390",
    "Drumheller_Detour": "91391",
    "Not_So_Efficient_Studying": "91393",
    "Overtime": "91394",
    "Ruins_of_Breeding": "91395",
    "The_Haunting_Desires": "91396",
    "Velvet_And_Vice": "91397",
}


def update_story_json(story_name: str, new_description: str) -> tuple[bool, str]:
    """Update the `description` field in story.json."""
    sj = ARCHIVE / story_name / "story.json"
    if not sj.is_file():
        return False, f"story.json not found: {sj}"
    try:
        data = json.loads(sj.read_text(encoding="utf-8"))
        old = data.get("description", "")
        data["description"] = new_description
        # Pretty-print with 2-space indent
        sj.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return True, f"{len(old.split())}w -> {len(new_description.split())}w"
    except Exception as e:
        return False, str(e)


async def find_silk_work_id(client: SquidgeWorldClient) -> str | None:
    """Look up The Silk-Threaded Bonds work ID on SQW."""
    import re
    r = await client._http.get(
        f"https://www.squidgeworld.org/users/{client.username}/works"
    )
    if r.status_code != 200:
        return None
    # Look for a link to the Silk-Threaded Bonds work
    # Pattern: <h4 class="heading"><a href="/works/{id}">The Silk-Threaded Bonds</a></h4>
    m = re.search(
        r'<a[^>]*href="/works/(\d+)"[^>]*>[^<]*Silk[^<]*Threaded[^<]*Bonds',
        r.text,
    )
    return m.group(1) if m else None


async def main() -> int:
    print("=" * 70)
    print("Update story.json descriptions + push to SquidgeWorld")
    print("=" * 70)
    print()

    # Step 1: Update all 9 story.json files
    print("[1/2] Updating story.json descriptions...")
    for name, new_desc in NEW_DESCRIPTIONS.items():
        ok, msg = update_story_json(name, new_desc)
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {name}: {msg}")
    print()

    # Step 2: Login and find Silk-Threaded Bonds work ID
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
    print("Looking up The Silk-Threaded Bonds work ID...")
    silk_wid = await find_silk_work_id(client)
    if silk_wid:
        print(f"  Found: work {silk_wid}")
        STORY_TO_WORK_ID["The_Silk_Threaded_Bonds"] = silk_wid
    else:
        print("  NOT FOUND — Silk-Threaded Bonds update will be skipped")
    print()

    # Step 3: Push edits to SquidgeWorld
    print("[2/2] Pushing description updates to SquidgeWorld...")
    print()
    poster = SquidgeWorldPoster()
    successes = 0
    failures = []

    for story_name in NEW_DESCRIPTIONS:
        if story_name not in STORY_TO_WORK_ID:
            print(f"  [SKIP] {story_name}: no known work_id")
            continue
        work_id = STORY_TO_WORK_ID[story_name]
        print(f"  {story_name} (work {work_id}):")
        package = StoryUploadPackage(
            story_name=story_name,
            chapter_index=0,
            chapter_title="",
            platform="sqw",
            title="",
            description="",
            tags=[],
            rating="explicit",
        )
        try:
            result = await poster.edit(work_id, package)
            if result.success:
                print(f"    [OK] ({result.duration_seconds:.1f}s)")
                successes += 1
            else:
                print(f"    [FAIL] {result.error}")
                failures.append((story_name, result.error))
        except Exception as e:
            print(f"    [EXCEPTION] {e}")
            failures.append((story_name, str(e)))
        await asyncio.sleep(3)

    print()
    print("=" * 70)
    print(f"Done: {successes} succeeded, {len(failures)} failed")
    if failures:
        print()
        for name, err in failures:
            print(f"  - {name}: {err}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
