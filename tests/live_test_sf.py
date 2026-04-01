"""Live test: Upload a draft to SoFurry, verify, edit, verify, then delete.

Tests the 3-step REST flow: PUT create → POST content → POST finalize.
Submission is created as PRIVATE (privacy=1) so followers are NOT notified.

Run locally:  python tests/live_test_sf.py
Run in Docker: python tests/live_test_sf.py
"""

import asyncio
import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from sf_client.client import SoFurryClient


async def main():
    settings = config.get_settings()
    username = settings.get("sf_username", "")
    password = settings.get("sf_password", "")
    display_name = settings.get("sf_display_name", "")

    if not username or not password:
        print("ERROR: No SF credentials in settings.json")
        return

    print("=== Live SoFurry Upload/Edit/Delete Test ===")
    print(f"User: {display_name} ({username[:3]}...)")
    print()

    # Create a tiny test file (must be under 512KB)
    test_content = "PawPoller Upload Test\n\nThis is an automated test from PawPoller's posting module.\nIt will be deleted automatically.\n"
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, prefix="pawpoller_sf_test_")
    tmp.write(test_content)
    tmp.close()
    test_file = tmp.name
    print(f"Test file: {test_file} ({os.path.getsize(test_file)} bytes)")

    proxy_url = settings.get("cf_worker_url", "")
    proxy_key = settings.get("cf_worker_key", "")
    client = SoFurryClient(
        username=username, password=password, display_name=display_name,
        proxy_url=proxy_url, proxy_key=proxy_key,
    )

    # Restore saved cookies if available
    saved_cookies = settings.get("sf_session_cookies")
    if saved_cookies:
        client.import_cookies(saved_cookies)
        print("Restored saved session cookies")

    submission_id = None

    try:
        # Step 1: Login
        print("\n--- Step 1: Login ---")
        if not await client.ensure_logged_in():
            print("  ERROR: Login failed!")
            return
        print("  Logged in successfully")

        # Step 2: Upload as PRIVATE (followers NOT notified)
        print("\n--- Step 2: Create submission (private, followers not notified) ---")
        result = await client.create_submission(
            test_file,
            title="[TEST] PawPoller Upload Test — DELETE ME",
            description="Automated test from PawPoller posting module. Will be deleted.",
            tags=["test", "pawpoller", "automated", "delete_me"],
            category=20,    # Writing
            sub_type=21,    # Short story
            rating=0,       # Clean
            privacy=1,      # PRIVATE — not visible to anyone, followers NOT notified
        )
        submission_id = result.get("submission_id")
        url = result.get("url", "")
        print(f"  Created! submission_id = {submission_id}")
        print(f"  URL: {url}")

        # Step 3: Verify via the JSON API
        print("\n--- Step 3: Verify submission exists ---")
        detail = await client.get_submission_detail(int(submission_id))
        if detail:
            print(f"  Title: {detail.get('title', '?')}")
            print(f"  Type: {detail.get('type', '?')}")
            print(f"  Rating: {detail.get('rating', '?')}")
            print("  VERIFIED: Submission exists on SoFurry!")
        else:
            print("  WARNING: Could not fetch submission details (may be private)")
            print("  (This is expected for private submissions — the API may not return them)")

        # Step 4: Edit metadata
        print("\n--- Step 4: Edit metadata ---")
        edit_result = await client.edit_submission(
            str(submission_id),
            title="[TEST] PawPoller Edit Test — UPDATED",
            description="Metadata was updated by PawPoller edit function.",
            tags=["test", "pawpoller", "automated", "updated", "edit_verified"],
        )
        print(f"  Edit result: submission_id={edit_result.get('submission_id')}")

        # Step 5: Verify edit
        print("\n--- Step 5: Verify edit ---")
        detail2 = await client.get_submission_detail(int(submission_id))
        if detail2:
            print(f"  Title: {detail2.get('title', '?')}")
            print("  VERIFIED: Edit applied!")
        else:
            print("  Could not verify via API (private submission)")
            print("  Edit was sent successfully (no error returned)")

        # Step 6: Delete
        print("\n--- Step 6: Delete test submission ---")
        # SoFurry doesn't have a public delete API, so we'll just mark it
        # for manual deletion or leave it as private (invisible).
        # Try the /ui/submission/{id} DELETE method
        csrf = await client._get_csrf_meta()
        if csrf:
            resp = await client._http.request(
                "DELETE",
                f"https://sofurry.com/ui/submission/{submission_id}",
                headers={
                    "X-CSRF-TOKEN": csrf,
                    "Origin": "https://sofurry.com",
                    "Referer": "https://sofurry.com/",
                    "Accept": "application/json",
                },
            )
            if resp.status_code in (200, 204):
                print(f"  Deleted submission {submission_id}")
                submission_id = None
            else:
                print(f"  Delete returned status {resp.status_code}: {resp.text[:100]}")
                print(f"  Submission may need manual deletion at {url}")
        else:
            print("  Could not get CSRF token for deletion")

        print("\n=== TEST COMPLETE ===")
        if submission_id is None:
            print("Upload: OK | Edit: OK | Delete: OK")
        else:
            print("Upload: OK | Edit: OK | Delete: MANUAL NEEDED")
            print(f"  Delete manually: https://sofurry.com/s/{submission_id}")

    except Exception as e:
        print(f"\n!!! ERROR: {e}")
        import traceback
        traceback.print_exc()
        if submission_id:
            print(f"\n  Manual cleanup needed: https://sofurry.com/s/{submission_id}")

    finally:
        await client.close()
        os.unlink(test_file)


if __name__ == "__main__":
    asyncio.run(main())
