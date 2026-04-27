"""Verify that the 2026-04-09 SquidgeWorld body edits landed correctly.

For each of 5 draft works, fetches chapter edit pages and runs string
presence/absence checks against the chapter[content] textarea body.

Usage:
  cd C:/Users/rhysc/claude/PawPoller
  python tests/verify_sqw_edits.py
"""
from __future__ import annotations

import asyncio
import io
import re
import sys
from dataclasses import dataclass, field

# Force UTF-8 stdout so Unicode characters in check strings don't crash on cp1252
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from clients.sqw.client import SquidgeWorldClient


# ── Check definitions ───────────────────────────────────────────

@dataclass
class Check:
    chapter_index: int          # 1-based chapter number
    description: str
    must_contain: str | None = None
    must_not_contain: str | None = None


@dataclass
class WorkChecks:
    work_id: str
    title: str
    checks: list[Check] = field(default_factory=list)


WORKS = [
    WorkChecks("91397", "Velvet and Vice", [
        Check(1, 'Ch1 has class="warning-heading"',
              must_contain='class="warning-heading"'),
        Check(1, "Ch1 has 'Prelude: Threads Unraveling'",
              must_contain="Prelude: Threads Unraveling"),
        Check(1, "Ch1 no duplicate <p><strong>Prelude heading",
              must_not_contain='<p><strong>Prelude: Threads Unraveling</strong></p>'),
        Check(2, "Ch2 has 'Chapter 1: Callum'",
              must_contain="Chapter 1: Callum"),
        Check(9, "Ch9 has 'Chapter 8: Communion'",
              must_contain="Chapter 8: Communion"),
    ]),
    WorkChecks("91391", "Drumheller Detour", [
        Check(1, 'Ch1 has class="warning-heading"',
              must_contain='class="warning-heading"'),
        Check(1, "Ch1 no duplicate plain CW block",
              must_not_contain='<p><em>\u2605 CONTENT WARNING \u2605</em></p>'),
        Check(1, 'Ch1 has class="warning-body"',
              must_contain='class="warning-body"'),
    ]),
    WorkChecks("91395", "Ruins of Breeding", [
        Check(1, "Ch1 no <em><strong> bolding bug",
              must_not_contain="<em><strong>"),
        Check(2, "Ch2 no <em><strong> bolding bug",
              must_not_contain="<em><strong>"),
        Check(1, "Ch1 no duplicate title paragraph",
              must_not_contain='<p><strong>Ruins of Breeding</strong></p>'),
    ]),
    WorkChecks("91394", "Overtime", [
        Check(1, "Ch1 no print-container wrapper",
              must_not_contain='<div class="print-container">'),
        Check(1, 'Ch1 has class="chapter-subtitle"',
              must_contain='class="chapter-subtitle"'),
        Check(1, 'Ch1 no old class="chapter-heading"',
              must_not_contain='class="chapter-heading"'),
    ]),
    WorkChecks("91390", "Tombstone", [
        Check(1, "Ch1 no print-container wrapper",
              must_not_contain='<div class="print-container">'),
        Check(1, 'Ch1 has class="chapter-subtitle"',
              must_contain='class="chapter-subtitle"'),
    ]),
]


# ── Fetch chapter body from edit page ───────────────────────────

async def get_chapter_body(client: SquidgeWorldClient, work_id: str, chapter_id: str) -> str | None:
    """Fetch the chapter edit form and extract the chapter[content] textarea."""
    url = f"https://squidgeworld.org/works/{work_id}/chapters/{chapter_id}/edit"
    html = await client._get_page(url)
    if not html:
        return None

    # Scope to the chapter form
    form_match = re.search(
        r'<form[^>]*action="[^"]*chapters/\d+[^"]*"[^>]*>(.*?)</form>',
        html, re.DOTALL,
    )
    form_body = form_match.group(1) if form_match else html

    # Find the chapter[content] textarea
    ta_match = re.search(
        r'<textarea[^>]*name="chapter\[content\]"[^>]*>(.*?)</textarea>',
        form_body, re.DOTALL,
    )
    if not ta_match:
        # Try alternate attribute order
        ta_match = re.search(
            r'<textarea[^>]*>(.*?)</textarea>\s*',
            form_body, re.DOTALL,
        )
        # Last resort: find any textarea with chapter content ID
        if not ta_match:
            return None

    body = ta_match.group(1)
    # Decode HTML entities that the form escapes
    body = (
        body.replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return body


# ── Main ────────────────────────────────────────────────────────

async def main() -> int:
    print("=" * 70)
    print("SquidgeWorld Edit Verification (2026-04-09 fixes)")
    print("=" * 70)
    print()

    settings = config.get_settings()
    client = SquidgeWorldClient(
        settings.get("sqw_author_username") or settings.get("sqw_username"),
        settings.get("sqw_author_password") or settings.get("sqw_password"),
        settings.get("sqw_target_user", ""),
    )

    if not await client.ensure_logged_in():
        print("FATAL: Login failed")
        await client.close()
        return 1
    print(f"Logged in as {client.username}")
    print()

    total_pass = 0
    total_fail = 0
    total_error = 0

    for work in WORKS:
        print("-" * 60)
        print(f"{work.title} (work_id={work.work_id})")
        print("-" * 60)

        # Get chapter list
        chapters = await client.get_chapter_ids(work.work_id)
        if not chapters:
            print(f"  ERROR: Could not fetch chapter list")
            total_error += len(work.checks)
            print()
            continue

        print(f"  Found {len(chapters)} chapters")

        # Build index->chapter_id map (1-based)
        ch_map: dict[int, str] = {}
        for ch in chapters:
            ch_map[ch["index"]] = ch["chapter_id"]

        # Cache fetched chapter bodies to avoid redundant requests
        body_cache: dict[int, str | None] = {}

        for check in work.checks:
            idx = check.chapter_index
            if idx not in ch_map:
                print(f"  ERROR  Chapter {idx} not found in work")
                total_error += 1
                continue

            # Fetch chapter body if not cached
            if idx not in body_cache:
                print(f"  Fetching chapter {idx} (id={ch_map[idx]})...")
                body_cache[idx] = await get_chapter_body(client, work.work_id, ch_map[idx])
                # Rate limit
                await asyncio.sleep(config.SQW_REQUEST_DELAY_SECONDS)

            body = body_cache[idx]
            if body is None:
                print(f"  ERROR  Could not fetch chapter {idx} body")
                total_error += 1
                continue

            # Run the check
            passed = True
            detail = ""

            if check.must_contain is not None:
                if check.must_contain in body:
                    detail = f"found '{check.must_contain[:60]}'"
                else:
                    passed = False
                    detail = f"MISSING '{check.must_contain[:60]}'"

            if check.must_not_contain is not None:
                if check.must_not_contain not in body:
                    neg_detail = f"correctly absent: '{check.must_not_contain[:60]}'"
                    detail = f"{detail}; {neg_detail}" if detail else neg_detail
                else:
                    passed = False
                    neg_detail = f"STILL PRESENT: '{check.must_not_contain[:60]}'"
                    detail = f"{detail}; {neg_detail}" if detail else neg_detail

            status = "PASS" if passed else "FAIL"
            if passed:
                total_pass += 1
            else:
                total_fail += 1
            print(f"  {status:4s}  Ch{idx}: {check.description}")
            print(f"         {detail}")

        print()

    # Summary
    print("=" * 70)
    print(f"RESULTS: {total_pass} passed, {total_fail} failed, {total_error} errors")
    print(f"         out of {total_pass + total_fail + total_error} total checks")
    print("=" * 70)

    await client.close()
    return 0 if (total_fail == 0 and total_error == 0) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
