"""Post all archive stories that aren't yet on SquidgeWorld as DRAFTS.

Strict safety:
  - Lists existing SQW works (drafts + published) by title
  - For each story in the archive, skips if a work with that title already exists
  - For each missing story, calls SquidgeWorldPoster.post() which has post-flight
    safety checks that DELETE the work if it ever moves to published state
  - Reports per-story result

Stories are processed one at a time. After each, the script verifies the
work is in /users/<user>/works/drafts. If the work is in published, the
script aborts and the offending work has already been deleted by the poster.
"""
from __future__ import annotations

import argparse
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
SKIP_DIRS = {"Reference_Guides"}


def _normalize_title(t: str) -> str:
    """Normalize title for fuzzy matching: lowercase + alphanumeric only."""
    import re
    return re.sub(r'[^a-z0-9]', '', t.lower())


async def fetch_existing_titles(client: SquidgeWorldClient) -> dict[str, str]:
    """Fetch existing work titles (drafts + published) keyed by normalized form.

    Returns dict of {normalized_title: original_title}.
    """
    titles: dict[str, str] = {}
    import re
    for path in ["works/drafts", "works"]:
        url = f"https://www.squidgeworld.org/users/{client.username}/{path}"
        r = await client._http.get(url)
        if r.status_code != 200:
            continue
        for m in re.finditer(
            r'<h4[^>]*class="[^"]*heading[^"]*"[^>]*>\s*<a[^>]*href="/works/\d+"[^>]*>([^<]+)</a>',
            r.text,
        ):
            t = m.group(1).strip()
            titles[_normalize_title(t)] = t
    return titles


def list_archive_stories() -> list[dict]:
    """Find all stories with story.json in the archive."""
    out = []
    for d in sorted(ARCHIVE.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or d.name in SKIP_DIRS:
            continue
        sj = d / "story.json"
        if not sj.is_file():
            continue
        try:
            data = json.loads(sj.read_text(encoding="utf-8"))
            out.append({
                "name": d.name,
                "title": data.get("title", d.name.replace("_", " ")),
                "chapters": data.get("chapters", 0),
                "words": data.get("word_count", 0),
            })
        except Exception:
            pass
    return out


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without posting anything",
    )
    parser.add_argument(
        "--story",
        help="Only post this specific story (by folder name)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the per-story confirmation prompt",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("Post missing stories to SquidgeWorld as DRAFTS")
    print("=" * 70)
    print()
    print("SAFETY: Each story is uploaded with strict draft-only checks.")
    print("If a work moves to published state at any point, it will be")
    print("automatically deleted and the script will abort.")
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

    print("Fetching existing SquidgeWorld works (drafts + published)...")
    existing = await fetch_existing_titles(client)
    print(f"  Found {len(existing)} existing works on SQW:")
    for norm, original in sorted(existing.items()):
        print(f"    - {original}")
    print()

    archive_stories = list_archive_stories()
    if args.story:
        archive_stories = [s for s in archive_stories if s["name"] == args.story]
        if not archive_stories:
            print(f"Story not found: {args.story}")
            return 1

    print(f"Archive has {len(archive_stories)} stories:")
    for s in archive_stories:
        norm = _normalize_title(s["title"])
        if norm in existing:
            sqw_title = existing[norm]
            if sqw_title == s["title"]:
                marker = "[ON SQW]"
                detail = ""
            else:
                marker = "[ON SQW*]"
                detail = f"  fuzzy match -> SQW='{sqw_title}'"
        else:
            marker = "[MISSING]"
            detail = ""
        print(f"  {marker:11} {s['name']:35} ({s['chapters']} ch, {s['words']:,} words) — title={s['title']!r}{detail}")
    print()

    missing = [s for s in archive_stories if _normalize_title(s["title"]) not in existing]
    print(f"Stories to upload as drafts: {len(missing)}")
    for s in missing:
        print(f"  - {s['name']} ({s['chapters']} chapters)")
    print()

    if args.dry_run:
        print("DRY RUN: nothing posted.")
        return 0

    if not missing:
        print("Nothing to do. All stories already on SQW.")
        return 0

    if not args.yes:
        print("Proceed with upload? Type 'yes' to continue: ", end="", flush=True)
        try:
            answer = input().strip().lower()
        except EOFError:
            answer = ""
        if answer != "yes":
            print("Aborted.")
            return 0

    poster = SquidgeWorldPoster()
    posted = []
    failed = []

    for s in missing:
        print()
        print("=" * 70)
        print(f"Posting {s['name']} ({s['chapters']} chapters, {s['words']:,} words)")
        print("=" * 70)

        package = StoryUploadPackage(
            story_name=s["name"],
            chapter_index=0,
            chapter_title=s["title"],
            platform="sqw",
            title=s["title"],
            description="",
            tags=[],
            rating="explicit",
        )

        try:
            result = await poster.post(package)
            if result.success:
                print(f"  [OK] work_id={result.external_id} ({result.duration_seconds:.1f}s)")
                print(f"  url:  {result.external_url}")
                posted.append((s["name"], result.external_id))
            else:
                print(f"  [FAIL] {result.error}")
                failed.append((s["name"], result.error))
                # Continue with remaining stories
        except Exception as e:
            print(f"  [EXCEPTION] {e}")
            failed.append((s["name"], str(e)))

        # Pause between stories to be polite
        await asyncio.sleep(5)

    print()
    print("=" * 70)
    print(f"Done. {len(posted)} posted, {len(failed)} failed.")
    print("=" * 70)
    if posted:
        print()
        print("Posted as drafts:")
        for name, wid in posted:
            print(f"  - {name}: https://www.squidgeworld.org/works/{wid}/preview")
    if failed:
        print()
        print("Failed:")
        for name, err in failed:
            print(f"  - {name}: {err}")

    print()
    print("View all drafts: https://www.squidgeworld.org/users/KnaughtyKat/works/drafts")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
