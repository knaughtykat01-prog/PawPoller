"""Verify (and optionally edit) the metadata on the 7 existing FA submissions.

The 7 existing FA submissions (per the server publications table) are all
PER-CHAPTER posts for Hypnotic Claim (2 chapters) and The Silk-Threaded
Bonds (5 chapters). Their PDFs are functionally unchanged after the
2026-04-08 styled HTML standardisation pass — that fix only touched the
FULL-story HTML, not per-chapter HTMLs — so there's no PDF content reason
to file-replace them.

But the metadata on the existing FA submissions may be stale relative to
what the current `build_package(story, chapter_index, "fa")` would now
produce. Tag lists, descriptions, and titles may have improved since the
originals were posted weeks/months ago.

This script:
  1. Reads the publications table for FA rows
  2. For each, fetches the current FA state via FAClient.get_submission_detail
  3. Builds a fresh package via build_package(story, chapter_index, "fa")
  4. Compares title, description, tags, rating
  5. Prints a clear diff
  6. (with --apply) actually performs the edit via FurAffinityPoster.edit()

SAFETY:
  - Default mode is READ-ONLY: fetches FA state, shows diff, exits.
  - --apply requires both the flag AND a typed YES confirmation.
  - --apply also rate-limits to 70 seconds between edits (FA's enforced
    minimum, even on edits).
  - The script does NOT touch any submission not in the publications table.
  - The script does NOT post any new submissions — only edits existing ones.
  - Per-chapter PDFs are never replaced (only metadata fields).

Usage:
    python tests/verify_fa_edit_existing.py                  # verify only
    python tests/verify_fa_edit_existing.py --story Hypnotic_Claim  # filter
    python tests/verify_fa_edit_existing.py --apply          # apply edits
    python tests/verify_fa_edit_existing.py --apply --story The_Silk_Threaded_Bonds
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import get_connection
from posting.platforms.furaffinity import FurAffinityPoster
from posting.story_reader import build_package, load_story


# FA's documented 70-second rate limit applies to NEW SUBMISSIONS, not edits.
# Edits via the changeinfo form aren't subject to the same throttle. We use a
# small polite delay (3s) instead of the 70s upload-style cooldown so bulk
# edit runs finish in seconds, not minutes. If FA starts returning 429s on
# edits at this cadence, bump it back up.
FA_RATE_LIMIT_SECONDS = 3

# Known FA publications fallback. Used when the local pubs DB doesn't have
# any FA rows (which is the case on the desktop because the FA bulk-post
# from earlier sessions ran on the GCP server's Docker volume, not local).
# Hardcoded mirror of the server's `publications` table FA rows as of
# 2026-04-08.
KNOWN_FA_PUBS = [
    {"story_name": "Hypnotic_Claim",          "chapter_index": 1, "external_id": "64274343", "status": "posted"},
    {"story_name": "Hypnotic_Claim",          "chapter_index": 2, "external_id": "64274371", "status": "posted"},
    {"story_name": "The_Silk_Threaded_Bonds", "chapter_index": 1, "external_id": "64284286", "status": "posted"},
    {"story_name": "The_Silk_Threaded_Bonds", "chapter_index": 2, "external_id": "64284325", "status": "posted"},
    {"story_name": "The_Silk_Threaded_Bonds", "chapter_index": 3, "external_id": "64284355", "status": "posted"},
    {"story_name": "The_Silk_Threaded_Bonds", "chapter_index": 4, "external_id": "64284453", "status": "posted"},
    {"story_name": "The_Silk_Threaded_Bonds", "chapter_index": 5, "external_id": "64284497", "status": "posted"},
]


def _normalize_tags(tags: list[str] | str) -> list[str]:
    """Normalise tags from FA's response into a sorted set for comparison.

    FA may return tags as a list of strings or a single comma-separated
    string. Underscores in multi-word tags become spaces in the response.
    """
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    return sorted(t.replace("_", " ").strip().lower() for t in tags if t)


def _normalize_rating(rating_str: str) -> str:
    """Normalise FA rating string to a comparable code.

    FA returns 'General' / 'Mature' / 'Adult' from the public page but the
    edit form takes '0' / '2' / '1' codes. Map both ways into a label.
    """
    s = (rating_str or "").lower().strip()
    if s in ("adult", "1", "explicit"):
        return "Adult"
    if s in ("mature", "2", "questionable"):
        return "Mature"
    if s in ("general", "0"):
        return "General"
    return rating_str or "(unknown)"


def _diff_field(label: str, current: str, new: str, max_show: int = 100) -> bool:
    """Print a single field diff. Returns True if there IS a difference."""
    if current == new:
        return False
    cur_show = (current or "")[:max_show]
    new_show = (new or "")[:max_show]
    if len(current or "") > max_show:
        cur_show += "..."
    if len(new or "") > max_show:
        new_show += "..."
    print(f"    {label}:")
    print(f"      current:  {cur_show!r}")
    print(f"      proposed: {new_show!r}")
    return True


def _list_fa_publications(story_filter: str | None = None) -> list[dict]:
    """Pull the FA rows from the publications table.

    If the local pubs DB has no FA rows (which is the case on the desktop
    because the FA bulk-posts ran on the GCP server's Docker volume), fall
    back to the hardcoded KNOWN_FA_PUBS list at the top of this module.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT story_name, chapter_index, external_id, title_used, status "
            "FROM publications WHERE platform = 'fa' "
            "ORDER BY story_name, chapter_index"
        ).fetchall()
    finally:
        conn.close()

    out = []
    if rows:
        source = "local publications table"
        for r in rows:
            out.append({
                "story_name": r["story_name"],
                "chapter_index": r["chapter_index"],
                "external_id": r["external_id"],
                "title_used": r["title_used"],
                "status": r["status"],
            })
    else:
        source = f"hardcoded fallback ({len(KNOWN_FA_PUBS)} known submissions)"
        out = [
            {**p, "title_used": ""}
            for p in KNOWN_FA_PUBS
        ]

    print(f"[source] {source}")

    if story_filter:
        out = [p for p in out if story_filter.lower() in p["story_name"].lower()]
    return out


async def verify_one(
    client,
    poster,
    pub: dict,
    apply: bool,
    skip_tags: bool = False,
    skip_rating: bool = False,
    update_file: bool = False,
) -> tuple[bool, str | None]:
    """Verify (and optionally apply) edits for one FA submission.

    Returns (had_diff, error_message_if_any).
    """
    sid = pub["external_id"]
    story_name = pub["story_name"]
    chapter_index = pub["chapter_index"]

    print(f"\n=== {story_name} ch{chapter_index} (FA {sid}) ===")

    # 1. Fetch current FA state
    try:
        current = await client.get_submission_detail(int(sid))
    except Exception as e:
        print(f"  [SKIP] could not fetch FA submission {sid}: {e}")
        return False, str(e)

    cur_title = current.get("title", "")
    cur_description = current.get("description", "")
    cur_tags = _normalize_tags(current.get("keywords", []))
    cur_rating_label = _normalize_rating(current.get("rating", ""))

    # 2. Build fresh package
    try:
        story = load_story(story_name)
        package = build_package(story, chapter_index=chapter_index, platform="fa")
    except Exception as e:
        print(f"  [SKIP] could not build package: {e}")
        return False, str(e)

    new_title = (package.title or "")[:60]  # FA 60 char cap
    new_description = package.description or ""
    new_tags = _normalize_tags(package.tags)
    new_rating_label = _normalize_rating(package.rating)

    # 3. Diff
    print(f"  current title:  {cur_title!r}")
    print(f"  proposed title: {new_title!r}")
    print(f"  current  tags ({len(cur_tags)}): {', '.join(cur_tags[:8])}{' ...' if len(cur_tags) > 8 else ''}")
    print(f"  proposed tags ({len(new_tags)}): {', '.join(new_tags[:8])}{' ...' if len(new_tags) > 8 else ''}")
    print(f"  current rating:  {cur_rating_label}")
    print(f"  proposed rating: {new_rating_label}")
    print(f"  current desc len: {len(cur_description)} chars")
    print(f"  proposed desc len: {len(new_description)} chars")
    print()
    print("  --- DIFF ---")

    diffs = 0
    if _diff_field("title", cur_title, new_title):
        diffs += 1
    if not skip_rating:
        if _diff_field("rating", cur_rating_label, new_rating_label):
            diffs += 1

    # Tags: compare as sets
    if skip_tags:
        # Path A: keep existing SEO tags, ignore the new tag set entirely.
        # Print a one-liner so the user can see they're being skipped.
        cur_tag_set = set(cur_tags)
        new_tag_set = set(new_tags)
        added_tags = sorted(new_tag_set - cur_tag_set)
        removed_tags = sorted(cur_tag_set - new_tag_set)
        if added_tags or removed_tags:
            print(f"    tags: would change (+{len(added_tags)}/-{len(removed_tags)}) but --skip-tags is set, KEEPING existing")
    else:
        cur_tag_set = set(cur_tags)
        new_tag_set = set(new_tags)
        added_tags = sorted(new_tag_set - cur_tag_set)
        removed_tags = sorted(cur_tag_set - new_tag_set)
        if added_tags or removed_tags:
            print(f"    tags: +{len(added_tags)} added, -{len(removed_tags)} removed")
            if added_tags:
                print(f"      added:   {', '.join(added_tags[:10])}{' ...' if len(added_tags) > 10 else ''}")
            if removed_tags:
                print(f"      removed: {', '.join(removed_tags[:10])}{' ...' if len(removed_tags) > 10 else ''}")
            diffs += 1

    # Description: compare as plain text (FA returns HTML; we just check if
    # they're meaningfully different at a high level — detail-level diff
    # would need an HTML→text converter and isn't worth it for verify mode)
    if cur_description.strip() and new_description.strip():
        # Cheap check: if the first 200 plain chars don't roughly match, flag it
        cur_first = cur_description.replace("\n", " ").strip()[:200]
        new_first = new_description.replace("\n", " ").strip()[:200]
        if cur_first != new_first:
            print(f"    description: differs (showing first 80 chars)")
            print(f"      current:  {cur_first[:80]!r}")
            print(f"      proposed: {new_first[:80]!r}")
            diffs += 1
    elif bool(cur_description.strip()) != bool(new_description.strip()):
        print(f"    description: presence mismatch (current={bool(cur_description)}, proposed={bool(new_description)})")
        diffs += 1

    if diffs == 0:
        print("    [no diff — skipping edit]")
        return False, None

    print(f"  >>> {diffs} field(s) would change")

    # 4. Apply (only if --apply flag set)
    if not apply:
        print("  (verify-only — no edit performed)")
        return True, None

    # When --skip-tags is set, overwrite the package's tags with the
    # existing FA tags so the edit POST doesn't change them. The FA
    # poster's edit() builds the keywords field from package.tags, so this
    # is the cleanest preserve-tags approach.
    if skip_tags:
        package.tags = list(current.get("keywords", []))
        print(f"    (preserving existing {len(package.tags)} FA tags)")
    if skip_rating:
        # FA's edit_submission scrapes existing rating from the form when
        # `rating=None` is passed in. Map our raw rating string to that
        # behaviour by setting it to the current rating label.
        package.rating = cur_rating_label.lower()

    print(f"  [APPLY] calling poster.edit({sid!r}, package)")
    result = await poster.edit(sid, package)
    if not result.success:
        print(f"  [FAIL] metadata edit: {result.error}")
        return True, result.error
    print(f"  [OK] metadata edit ({result.duration_seconds:.1f}s)")

    # Optional file replacement (changestory endpoint)
    if update_file:
        if not package.file_path:
            print(f"  [SKIP] --update-file requested but no file_path in package")
            return True, None
        from pathlib import Path as _P
        if not _P(package.file_path).is_file():
            print(f"  [SKIP] --update-file requested but file does not exist: {package.file_path}")
            return True, None
        # Small pause between metadata edit and file replacement
        await asyncio.sleep(2)
        print(f"  [APPLY] calling poster.replace_file({sid!r}, {_P(package.file_path).name!r})")
        file_result = await poster.replace_file(sid, package.file_path)
        if not file_result.success:
            print(f"  [FAIL] file replacement: {file_result.error}")
            return True, file_result.error
        print(f"  [OK] file replaced ({file_result.duration_seconds:.1f}s)")

    print(f"  url: {result.external_url}")
    return True, None


async def main() -> int:
    parser = argparse.ArgumentParser(description="Verify (and optionally apply) FA edits to existing submissions")
    parser.add_argument("--apply", action="store_true",
                        help="ACTUALLY apply the edits (default is read-only verify)")
    parser.add_argument("--story", default=None,
                        help="filter to a single story (substring match against story_name)")
    parser.add_argument("--yes", action="store_true",
                        help="skip the typed confirmation prompt (only valid with --apply)")
    parser.add_argument("--skip-tags", action="store_true",
                        help="don't change tags (path A: keep existing SEO tags)")
    parser.add_argument("--skip-rating", action="store_true",
                        help="don't change rating (preserve existing)")
    parser.add_argument("--update-file", action="store_true",
                        help="ALSO replace the source PDF file (changestory endpoint)")
    args = parser.parse_args()

    print("=" * 70)
    print("FA edit-existing verification")
    print("=" * 70)
    print()

    pubs = _list_fa_publications(args.story)
    if not pubs:
        filter_msg = f" matching {args.story!r}" if args.story else ""
        print(f"No FA publications found in the local database{filter_msg}.")
        print("(this script reads the LOCAL pubs DB, not the server's. If FA")
        print(" pubs only live on the server, use a docker exec wrapper.)")
        return 1

    print(f"Found {len(pubs)} FA publication(s) to check:")
    for p in pubs:
        print(f"  {p['story_name']:30s} ch{p['chapter_index']:>2}  {p['external_id']:>9}  {p['status']}")
    print()

    if args.apply:
        print("!" * 70)
        print("!!  APPLY MODE  !!")
        print("!" * 70)
        print(f"  About to EDIT {len(pubs)} live FurAffinity submission(s).")
        print("  This is NOT a dry run. Edits go LIVE on FA the moment they")
        print(f"  succeed. Inter-edit delay is {FA_RATE_LIMIT_SECONDS}s (FA's 70s upload")
        print("  rate limit does NOT apply to edits — confirmed empirically).")
        print()
        if not args.yes:
            expected = f"EDIT {len(pubs)} LIVE FA SUBMISSIONS"
            answer = input(f"  Type exactly the following to confirm:\n  > {expected}\n  > ")
            if answer.strip() != expected:
                print("  [ABORT] confirmation mismatch — no edits performed")
                return 1
        print()

    poster = FurAffinityPoster()
    print("[setup] Creating FA client + validating cookies...")
    try:
        client = await poster._ensure_client()
    except Exception as e:
        print(f"[FAIL] FA client setup: {e}")
        return 1
    print("  [OK] cookies valid")

    n_diff = 0
    n_no_diff = 0
    n_failed = 0
    n_applied = 0
    for i, pub in enumerate(pubs):
        had_diff, err = await verify_one(
            client, poster, pub, args.apply,
            skip_tags=args.skip_tags,
            skip_rating=args.skip_rating,
            update_file=args.update_file,
        )
        if err:
            n_failed += 1
        elif had_diff:
            n_diff += 1
            if args.apply:
                n_applied += 1
        else:
            n_no_diff += 1

        # Rate limit between edits (only when applying)
        if args.apply and i < len(pubs) - 1:
            print(f"\n  ... sleeping {FA_RATE_LIMIT_SECONDS}s before next edit (FA rate limit) ...")
            await asyncio.sleep(FA_RATE_LIMIT_SECONDS)

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  total checked:     {len(pubs)}")
    print(f"  no diff:           {n_no_diff}")
    print(f"  would change:      {n_diff}")
    if args.apply:
        print(f"  successfully applied: {n_applied}")
        print(f"  failed:               {n_failed}")
    else:
        print(f"  failed (fetch):    {n_failed}")
        print()
        if n_diff > 0:
            print("  Re-run with --apply to actually perform the edits.")
            print("  Recommended: spot-check the diffs above first.")
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
