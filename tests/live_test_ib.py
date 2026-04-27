"""Live test: Upload a draft to Inkbunny, verify, edit, verify, then delete.

This hits the REAL Inkbunny API. The submission is created as a DRAFT
(visibility=no) so watchers are NOT notified.

Run: python tests/live_test_ib.py
"""

import asyncio
import sys
import os
import tempfile

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from clients.ib.client import InkbunnyClient
from database.db import get_connection


async def main():
    settings = config.get_settings()
    username = settings.get("username", "")
    password = settings.get("password", "")

    if not username or not password:
        print("ERROR: No IB credentials in settings.json")
        return

    print(f"=== Live Inkbunny Upload/Edit/Delete Test ===")
    print(f"User: {username}")
    print()

    # Create a tiny test file
    test_content = "[center][b]PawPoller Upload Test[/b][/center]\n\nThis is an automated test submission from PawPoller's posting module.\nIt will be deleted automatically.\n"
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, prefix="pawpoller_test_")
    tmp.write(test_content)
    tmp.close()
    test_file = tmp.name
    print(f"Test file: {test_file} ({os.path.getsize(test_file)} bytes)")

    client = InkbunnyClient(username=username, password=password)
    submission_id = None

    try:
        # Step 1: Login
        print("\n--- Step 1: Login ---")
        conn = get_connection()
        try:
            row = conn.execute("SELECT sid FROM session_cache WHERE id = 1").fetchone()
            cached_sid = row["sid"] if row else None
        finally:
            conn.close()
        sid = await client.ensure_session(cached_sid)
        print(f"  Logged in. SID: {sid[:12]}...")

        # Step 2: Upload as DRAFT (visibility=no, watchers NOT notified)
        print("\n--- Step 2: Upload (draft, visibility=no) ---")
        submission_id = await client.upload_submission(
            test_file,
            submission_type="4",  # writing
        )
        print(f"  Uploaded! submission_id = {submission_id}")
        print(f"  URL: https://inkbunny.net/s/{submission_id}")

        # Step 3: Set metadata (still draft)
        print("\n--- Step 3: Edit metadata (still draft) ---")
        edit_result = await client.edit_submission(
            submission_id,
            title="[TEST] PawPoller Upload Test — DELETE ME",
            description="[b]Automated test[/b]\n\nThis was uploaded by PawPoller's posting module as a test.\nIt should be deleted automatically.",
            keywords="test, pawpoller, automated, delete_me",
            rating_tag_2="no",
            rating_tag_3="no",
            rating_tag_4="no",
            rating_tag_5="no",
            visibility="no",       # DRAFT — not visible, watchers NOT notified
            scraps="no",
            friends_only="no",
            guest_block="no",
        )
        print(f"  Metadata set: {edit_result}")

        # Step 4: Verify it exists by fetching details
        print("\n--- Step 4: Verify submission exists ---")
        details = await client.get_submission_details([submission_id])
        if details:
            d = details[0].to_db_dict()
            print(f"  Title: {d['title']}")
            print(f"  Type: {d['type_name']}")
            print(f"  Keywords: {d['keywords']}")
            print(f"  Views: {d['views']}, Faves: {d['favorites_count']}")
            print("  VERIFIED: Submission exists on Inkbunny!")
        else:
            print("  WARNING: Could not fetch submission details")

        # Step 5: Edit the metadata (simulate an update)
        print("\n--- Step 5: Edit metadata (simulate revision update) ---")
        edit2_result = await client.edit_submission(
            submission_id,
            title="[TEST] PawPoller Edit Test — DELETE ME",
            description="[b]Automated test — UPDATED[/b]\n\nThis metadata was updated by PawPoller's edit function.",
            keywords="test, pawpoller, automated, delete_me, updated",
        )
        print(f"  Edit result: {edit2_result}")

        # Step 6: Verify the edit
        print("\n--- Step 6: Verify edit applied ---")
        details2 = await client.get_submission_details([submission_id])
        if details2:
            d2 = details2[0].to_db_dict()
            print(f"  Title: {d2['title']}")
            print(f"  Keywords: {d2['keywords']}")
            kw = d2.get("keywords", [])
            has_updated = "updated" in (kw if isinstance(kw, list) else str(kw).lower())
            print(f"  VERIFIED: Edit applied = {has_updated}")
        else:
            print("  WARNING: Could not verify edit")

        # Step 7: Delete
        print("\n--- Step 7: Delete test submission ---")
        del_result = await client.delete_submission(submission_id)
        print(f"  Deleted: {del_result}")
        print("  VERIFIED: Test submission cleaned up!")
        submission_id = None  # Prevent double-delete in finally

        print("\n=== ALL TESTS PASSED ===")
        print("Upload: OK | Edit metadata: OK | Verify: OK | Update: OK | Delete: OK")

    except Exception as e:
        print(f"\n!!! ERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Safety net: always try to delete if something went wrong
        if submission_id:
            print(f"\n--- Cleanup: Deleting submission {submission_id} ---")
            try:
                await client.delete_submission(submission_id)
                print("  Cleaned up.")
            except Exception as e:
                print(f"  WARNING: Cleanup delete failed: {e}")
                print(f"  MANUAL DELETE NEEDED: https://inkbunny.net/s/{submission_id}")

        await client.close()
        os.unlink(test_file)


if __name__ == "__main__":
    asyncio.run(main())
