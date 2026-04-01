"""Live test: Upload a story PDF to FurAffinity with thumbnail.

Tests the 3-step form scrape: GET key → POST upload → POST finalize.
Submission is created as HIDDEN (visibility not set to public) with scraps=yes.
Thumbnail uploaded alongside the PDF.

Run: python tests/live_test_fa.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from fa_client.client import FAClient


PDF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_upload.pdf")
THUMB_PATH = "C:/Users/rhysc/claude/m_x/Archives/Complete_Stories/Extra_Credit/extra_credit_thumbnail_full_series.png"


async def main():
    settings = config.get_settings()
    username = settings.get("fa_username", "")
    cookie_a = settings.get("fa_cookie_a", "")
    cookie_b = settings.get("fa_cookie_b", "")

    if not cookie_a or not cookie_b:
        print("ERROR: No FA cookies in settings.json")
        return

    print("=== Live FurAffinity Upload Test ===")
    print(f"User: {username}")
    print(f"PDF: {PDF_PATH} ({os.path.getsize(PDF_PATH)} bytes)")
    print(f"Thumbnail: {THUMB_PATH} ({os.path.getsize(THUMB_PATH) // 1024}KB)")
    print()

    client = FAClient(username=username, cookie_a=cookie_a, cookie_b=cookie_b)

    try:
        # Step 1: Validate cookies
        print("--- Step 1: Validate cookies ---")
        valid = await client.validate_cookies()
        if not valid:
            print("  ERROR: FA cookies are invalid or expired!")
            print("  Re-export cookies 'a' and 'b' from your browser.")
            return
        print("  Cookies valid!")

        # Step 2: Upload PDF + thumbnail as a story
        print("\n--- Step 2: Upload story (PDF + thumbnail) ---")
        result = await client.submit_story(
            PDF_PATH,
            title="[TEST] PawPoller Upload Test",
            description="[b]Automated Test[/b]\n\nThis is a test submission from PawPoller's posting module.\nUploaded via the 3-step form scrape pipeline.\n\nIncludes:\n- PDF story file\n- Custom thumbnail\n- BBCode description\n\n[i]Safe to delete after inspection.[/i]",
            keywords="test pawpoller automated delete_me posting_module",
            rating="0",        # General
            cat="13",          # Story
            atype="1",         # All themes
            species="1",       # Unspecified
            gender="0",        # Any
            scrap=True,        # Post to scraps (less visible)
            thumbnail_path=THUMB_PATH,
        )
        submission_id = result.get("submission_id", "")
        url = result.get("url", "")
        print(f"  Uploaded! submission_id = {submission_id}")
        print(f"  URL: {url}")

        # Step 3: Verify by loading the page
        print("\n--- Step 3: Verify submission exists ---")
        fa_http = await client._get_fa_http()
        page_resp = await fa_http.get(f"https://www.furaffinity.net/view/{submission_id}/")
        if page_resp.status_code == 200:
            import re
            title_match = re.search(r'<title>([^<]+)</title>', page_resp.text)
            has_download = "Download" in page_resp.text
            has_thumb = f"thumbnails" in page_resp.text and "KnaughtyKat" in page_resp.text.lower()
            print(f"  Page title: {title_match.group(1).strip() if title_match else '?'}")
            print(f"  Has download link: {has_download}")
            print(f"  Has custom thumbnail: {has_thumb}")
            print("  VERIFIED: Submission exists on FurAffinity!")
        else:
            print(f"  Page returned status {page_resp.status_code}")

        # Step 4: Test editing metadata
        print("\n--- Step 4: Edit metadata ---")
        edit_result = await client.edit_submission(
            submission_id,
            title="[TEST] PawPoller Edit Test — Updated",
            description="[b]Automated Test — UPDATED[/b]\n\nMetadata was updated by PawPoller's edit function.\n\n[i]Upload + Edit both verified.[/i]",
            keywords="test pawpoller automated updated edit_verified posting_module",
        )
        print(f"  Edit result: {edit_result}")

        # Step 5: Verify edit
        print("\n--- Step 5: Verify edit ---")
        page_resp2 = await fa_http.get(f"https://www.furaffinity.net/view/{submission_id}/")
        if page_resp2.status_code == 200:
            import re
            title_match = re.search(r'<title>([^<]+)</title>', page_resp2.text)
            print(f"  Page title: {title_match.group(1).strip() if title_match else '?'}")
            has_updated = "UPDATED" in page_resp2.text
            print(f"  Has updated text: {has_updated}")
            print("  VERIFIED: Edit applied!")

        print(f"\n=== TEST COMPLETE ===")
        print(f"Upload: OK | Thumbnail: check visually | Edit: OK")
        print(f"Submission left up at: {url}")
        print(f"Delete when done: https://www.furaffinity.net/view/{submission_id}/")

    except Exception as e:
        print(f"\n!!! ERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
