"""Controlled safety test for create_chapter(publish=False).

Creates a TINY throwaway draft work, attempts to add a chapter via the
publish=False path, and verifies the work stays in drafts at every step.

If the work accidentally goes to published state, the test ABORTS and
deletes the work immediately.

After the test (success or failure), the test work is deleted.

NO REAL STORIES ARE TOUCHED.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from clients.sqw.client import SquidgeWorldClient


TEST_TITLE = "DELETE ME — Draft Chapter Safety Test 2026-04-07"
TEST_CHAPTER_1 = (
    "<p>This is a throwaway test work. If you see this on the live site, "
    "the safety test failed and you should delete it immediately.</p>"
)
TEST_CHAPTER_2 = (
    "<p>This is the second test chapter. If you see this on a published work, "
    "the create_chapter publish=False flow is broken.</p>"
)


async def cleanup(client: SquidgeWorldClient, work_id: str | None) -> None:
    """Always-runs cleanup. Deletes the test work."""
    if not work_id:
        return
    print(f"\n[CLEANUP] Deleting test work {work_id}...")
    try:
        await client.delete_work(work_id)
        print(f"[CLEANUP] Deleted work {work_id}")
    except Exception as e:
        print(f"[CLEANUP] FAILED to delete work {work_id}: {e}")
        print(f"[CLEANUP] MANUALLY DELETE: https://www.squidgeworld.org/works/{work_id}/confirm_delete")


async def main() -> int:
    print("=" * 70)
    print("SquidgeWorld Draft Chapter Add Safety Test")
    print("=" * 70)
    print()
    print("This test:")
    print("  1. Creates a tiny throwaway draft work")
    print("  2. Verifies it is in drafts (NOT published)")
    print("  3. Tries to add chapter 2 via create_chapter(publish=False)")
    print("  4. Verifies the work is STILL in drafts after the chapter add")
    print("  5. Deletes the test work")
    print()
    print("If at any point the work moves to the published listing,")
    print("the test ABORTS and the work is deleted immediately.")
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
    print(f"[OK] Logged in as {client.username}")
    print()

    work_id: str | None = None
    test_passed = False

    try:
        # Step 1: Create the test draft work
        print("[1/5] Creating test draft work...")
        result = await client.create_work(
            title=TEST_TITLE,
            content=TEST_CHAPTER_1,
            fandom="Original Work",
            rating="General Audiences",
            warnings=["No Archive Warnings Apply"],
            categories=["Gen"],
            additional_tags="test, delete me, safety check",
            summary="Throwaway draft for safety testing PawPoller's draft chapter add flow.",
            chapter_title="Chapter 1: Test",
        )
        work_id = result["work_id"]
        print(f"[OK] Created work {work_id} at {result['url']}")
        print()

        # Step 2: Verify it's in drafts
        print("[2/5] Verifying work is in drafts (NOT published)...")
        await asyncio.sleep(2)  # let SQW catch up
        in_drafts = await client.is_work_in_drafts(work_id)
        in_published = await client.is_work_published(work_id)
        print(f"      in drafts:    {in_drafts}")
        print(f"      in published: {in_published}")
        if in_published:
            print("[ABORT] Work is in PUBLISHED — create_work published the work!")
            return 1
        if not in_drafts:
            print("[ABORT] Work is not in drafts. Cannot proceed safely.")
            return 1
        print("[OK] Work is correctly in drafts")
        print()

        # Step 3: Try to add chapter 2 with publish=False
        print("[3/5] Adding chapter 2 via create_chapter(publish=False)...")
        try:
            ch2_result = await client.create_chapter(
                work_id,
                title="Chapter 2: Test",
                content=TEST_CHAPTER_2,
                position=2,
                publish=False,  # SAFETY: must NOT publish
            )
            print(f"[OK] create_chapter returned: {ch2_result}")
        except Exception as e:
            print(f"[FAIL] create_chapter raised: {e}")
            print()
            print("This means create_chapter publish=False does NOT work for drafts.")
            print("Need to find a different approach.")
            return 1
        print()

        # Step 4: Verify work is STILL in drafts
        print("[4/5] Verifying work is STILL in drafts after chapter add...")
        await asyncio.sleep(2)
        still_in_drafts = await client.is_work_in_drafts(work_id)
        now_published = await client.is_work_published(work_id)
        print(f"      in drafts:    {still_in_drafts}")
        print(f"      in published: {now_published}")
        if now_published:
            print("[CRITICAL] Work was PUBLISHED by create_chapter!")
            print("[CRITICAL] publish=False is NOT safe.")
            return 1
        if not still_in_drafts:
            print("[CRITICAL] Work is no longer in drafts. State unknown.")
            return 1
        print("[OK] Work is STILL a draft after chapter add")
        print()

        # Step 5: Verify chapter count
        print("[5/5] Verifying chapter count...")
        chapter_ids = await client.get_chapter_ids(work_id)
        print(f"      chapter count: {len(chapter_ids)} (expected 2)")
        for ch in chapter_ids:
            print(f"        index={ch.get('index', '?')} id={ch.get('chapter_id', '?')}")
        print()

        test_passed = (len(chapter_ids) == 2)
        print("=" * 70)
        if test_passed:
            print("RESULT: PASS — create_chapter(publish=False) works for drafts.")
        else:
            print("RESULT: PARTIAL — chapter count mismatch.")
        print("=" * 70)

    finally:
        await cleanup(client, work_id)

    return 0 if test_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
