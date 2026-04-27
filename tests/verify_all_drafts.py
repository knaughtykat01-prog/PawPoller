"""Sequential verification of all SquidgeWorld drafts.

For each work, fetches the edit form and extracts:
  - title
  - fandom
  - rating
  - warnings (checked)
  - categories (checked)
  - characters
  - relationships
  - freeform tags
  - work skin ID
  - chapter count

Compares against the expected values in story.json and reports any
mismatches. Read-only — does not modify anything.
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


ARCHIVE = Path("C:/Users/rhysc/claude/m_x/Archives/Complete_Stories")

# work_id -> story folder name
WORKS = {
    "91374": "Chosen",
    "91390": "Tombstone",
    "91391": "Drumheller_Detour",
    "91393": "Not_So_Efficient_Studying",
    "91394": "Overtime",
    "91395": "Ruins_of_Breeding",
    "91396": "The_Haunting_Desires",
    "91397": "Velvet_And_Vice",
}


def extract_field(html: str, field: str) -> str:
    """Pull the current value of a work[field] text input."""
    m = re.search(
        rf'<input[^>]*name="work\[{re.escape(field)}\]"[^>]*value="([^"]*)"',
        html,
    ) or re.search(
        rf'<input[^>]*value="([^"]*)"[^>]*name="work\[{re.escape(field)}\]"',
        html,
    )
    return m.group(1) if m else ""


def extract_select(html: str, field: str) -> str:
    """Pull the selected option from a work[field] select."""
    sel = re.search(
        rf'<select[^>]*name="work\[{re.escape(field)}\]"[^>]*>(.*?)</select>',
        html, re.DOTALL,
    )
    if not sel:
        return ""
    m = re.search(r'<option[^>]*\bselected[^>]*\bvalue="([^"]*)"', sel.group(1))
    if not m:
        m = re.search(r'<option[^>]*\bvalue="([^"]*)"[^>]*\bselected', sel.group(1))
    return m.group(1) if m else ""


def extract_checked_array(html: str, field: str) -> list[str]:
    """Pull all checked checkboxes for work[field][]."""
    field_pattern = re.escape(field)
    results = []
    for m in re.finditer(
        rf'<input[^>]*name="work\[{field_pattern}\]\[\]"([^>]*?)>',
        html,
    ):
        attrs = m.group(0)
        if "checked" in attrs.lower():
            v_m = re.search(r'\bvalue="([^"]+)"', attrs)
            if v_m:
                results.append(v_m.group(1))
    return results


def extract_textarea(html: str, field: str) -> str:
    """Pull the contents of a work[field] textarea."""
    m = re.search(
        rf'<textarea[^>]*name="work\[{re.escape(field)}\]"[^>]*>(.*?)</textarea>',
        html, re.DOTALL,
    )
    return m.group(1).strip() if m else ""


def unescape(s: str) -> str:
    return (
        s.replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )


async def verify_one(client: SquidgeWorldClient, work_id: str, story_name: str) -> dict:
    story_json_path = ARCHIVE / story_name / "story.json"
    if not story_json_path.is_file():
        return {"error": f"no story.json for {story_name}"}
    expected = json.loads(story_json_path.read_text(encoding="utf-8"))

    edit_url = f"https://www.squidgeworld.org/works/{work_id}/edit"
    r = await client._http.get(edit_url)
    if r.status_code != 200:
        return {"error": f"fetch failed: status {r.status_code}"}
    html = r.text

    actual = {
        "title": unescape(extract_field(html, "title")),
        "fandom": unescape(extract_field(html, "fandom_string")),
        "rating": extract_select(html, "rating_string"),
        "warnings": extract_checked_array(html, "archive_warning_strings"),
        "categories": extract_checked_array(html, "category_strings"),
        "characters": unescape(extract_field(html, "character_string")),
        "relationships": unescape(extract_field(html, "relationship_string")),
        "freeform": unescape(extract_field(html, "freeform_string")),
        "summary": extract_textarea(html, "summary"),
        "work_skin_id": extract_select(html, "work_skin_id"),
    }

    chapters = await client.get_chapter_ids(work_id)
    actual["chapter_count"] = len(chapters)

    is_draft = await client.is_work_in_drafts(work_id)
    is_pub = await client.is_work_published(work_id)

    issues = []
    if not is_draft and is_pub:
        issues.append(f"PUBLISHED (not draft)")
    elif not is_draft and not is_pub:
        issues.append("neither draft nor published")

    exp_title = expected.get("title", "")
    if actual["title"] != exp_title:
        issues.append(f"title mismatch: {actual['title']!r} vs expected {exp_title!r}")
    if actual["fandom"] != expected.get("fandom", "Original Work"):
        issues.append(f"fandom: {actual['fandom']!r} vs {expected.get('fandom')!r}")
    if actual["rating"] not in ("Explicit", "Mature", "Teen And Up Audiences", "General Audiences"):
        issues.append(f"rating not mapped: {actual['rating']!r}")
    exp_warnings = expected.get("warnings") or ["No Archive Warnings Apply"]
    if set(actual["warnings"]) != set(exp_warnings):
        issues.append(f"warnings: {actual['warnings']} vs {exp_warnings}")
    exp_cat = [expected.get("category")] if expected.get("category") else expected.get("categories", [])
    if set(actual["categories"]) != set(exp_cat):
        issues.append(f"categories: {actual['categories']} vs {exp_cat}")
    exp_chars = ", ".join(expected.get("characters", []))
    if actual["characters"] != exp_chars:
        issues.append(f"characters: {actual['characters']!r} vs {exp_chars!r}")
    exp_rels = ", ".join(expected.get("relationships", []))
    if actual["relationships"] != exp_rels:
        issues.append(f"relationships: {actual['relationships']!r} vs {exp_rels!r}")
    exp_chapters = expected.get("chapters", 0)
    if actual["chapter_count"] != exp_chapters:
        issues.append(f"chapter count: {actual['chapter_count']} vs expected {exp_chapters}")
    if not actual["work_skin_id"]:
        issues.append("no work skin selected")

    # Count freeform tags (rough)
    tag_count = len([t for t in actual["freeform"].split(",") if t.strip()])

    return {
        "work_id": work_id,
        "story_name": story_name,
        "is_draft": is_draft,
        "is_published": is_pub,
        "actual": actual,
        "tag_count": tag_count,
        "issues": issues,
    }


async def main() -> int:
    settings = config.get_settings()
    client = SquidgeWorldClient(
        settings.get("sqw_author_username") or settings.get("sqw_username"),
        settings.get("sqw_author_password") or settings.get("sqw_password"),
        settings.get("sqw_target_user", ""),
    )
    await client.ensure_logged_in()

    print("Sequential verification of all SquidgeWorld drafts")
    print("=" * 70)

    all_ok = True
    for work_id, story_name in WORKS.items():
        print()
        print(f"[Work {work_id}] {story_name}")
        print("-" * 70)
        result = await verify_one(client, work_id, story_name)
        if "error" in result:
            print(f"  ERROR: {result['error']}")
            all_ok = False
            continue

        actual = result["actual"]
        state = "PUBLISHED" if result["is_published"] else ("DRAFT" if result["is_draft"] else "UNKNOWN")
        print(f"  state:         {state}")
        print(f"  title:         {actual['title']}")
        print(f"  fandom:        {actual['fandom']}")
        print(f"  rating:        {actual['rating']}")
        print(f"  warnings:      {actual['warnings']}")
        print(f"  categories:    {actual['categories']}")
        print(f"  characters:    {actual['characters']!r}")
        print(f"  relationships: {actual['relationships']!r}")
        print(f"  freeform tags: {result['tag_count']}")
        print(f"  summary words: {len(actual['summary'].split())}")
        print(f"  work_skin_id:  {actual['work_skin_id']}")
        print(f"  chapters:      {actual['chapter_count']}")

        if result["issues"]:
            print(f"  ISSUES:")
            for iss in result["issues"]:
                print(f"    - {iss}")
            all_ok = False
        else:
            print("  [OK]")

        await asyncio.sleep(1)

    print()
    print("=" * 70)
    print(f"Overall: {'ALL OK' if all_ok else 'ISSUES FOUND'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
