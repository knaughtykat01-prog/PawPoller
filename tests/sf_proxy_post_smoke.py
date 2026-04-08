"""SF posting smoke test from inside the GCP container — via CF proxy.

Different from verify_sf_draft.py: that one runs locally with direct httpx.
This one runs in the container, where SoFurryClient auto-picks proxy mode
because cf_worker_url is configured. It exercises:

  1. Login through proxy (already known to work — used by polling)
  2. CSRF fetch (GET, no body — should work pre-fix)
  3. PUT empty submission, JSON body  ← needs Content-Type fix
  4. POST file content, multipart      ← needs Content-Type fix WITH boundary
  5. POST metadata, JSON body          ← needs Content-Type fix
  6. Server-side privacy verification

Posts a single Tombstone draft as Private. If it works, the proxy is fixed
end-to-end for SF posting and we can repeat the pattern for SQW/AO3/DA.
"""
from __future__ import annotations

import asyncio
import sys
sys.path.insert(0, "/app")
from pathlib import Path

from posting.platforms.sofurry import SoFurryPoster
from posting.story_reader import build_package, load_story


STORY_NAME = "Tombstone"


async def main() -> int:
    print("=" * 70)
    print(f"SF posting smoke test via CF proxy — {STORY_NAME}")
    print("=" * 70)
    print()

    print("[1/4] Loading story + building SF package...")
    story = load_story(STORY_NAME)
    package = build_package(story, chapter_index=0, platform="sf")
    package.extra["draft"] = True  # privacy=1 (Private)
    print(f"  story:           {story.name}")
    print(f"  title:           {package.title}")
    print(f"  tag count:       {len(package.tags)}")
    print(f"  resolved file:   {package.file_path}")
    if package.file_path:
        print(f"  file size:       {Path(package.file_path).stat().st_size:,} bytes")
    print()

    poster = SoFurryPoster()

    print("[2/4] Login (will go through CF proxy on this host)...")
    client = await poster._ensure_client()
    print("  [OK] logged in")
    # Sanity check we're really in proxy mode
    transport = client._http._transport
    using_proxy = hasattr(transport, "login_and_fetch")
    print(f"  using CF proxy:  {using_proxy}")
    print()

    print("[3/4] Posting via SoFurryPoster.post() with extra[draft]=True...")
    print("       (this triggers PUT empty + multipart upload + JSON metadata)")
    result = await poster.post(package)
    if not result.success:
        print(f"  [FAIL] {result.error}")
        return 1
    sub_id = result.external_id
    print(f"  [OK] submission_id={sub_id} ({result.duration_seconds:.1f}s)")
    print(f"  url: {result.external_url}")
    print()

    print("[4/4] Verifying privacy via raw /ui/submission/{id}...")
    await asyncio.sleep(2)
    try:
        raw_resp = await client._http.get(
            f"https://sofurry.com/ui/submission/{sub_id}",
            headers={"Accept": "application/json"},
        )
        print(f"  raw API status:  {raw_resp.status_code}")
        if raw_resp.status_code == 200:
            raw = raw_resp.json()
            server_privacy = raw.get("privacy")
            label = {1: "Private", 2: "Unlisted", 3: "Public"}.get(server_privacy, str(server_privacy))
            print(f"  server privacy:  {server_privacy} ({label})")
            print(f"  server title:    {raw.get('title', '')!r}")
            tag_count = len(raw.get("artistTags", []))
            print(f"  server tags:     {tag_count}")
            print()
            if server_privacy == 1:
                print("=" * 70)
                print("PROXY POSTING SMOKE TEST PASSED")
                print(f"  - login through proxy: OK")
                print(f"  - CSRF GET:            OK")
                print(f"  - PUT empty (JSON):    OK  <-- needed Content-Type fix")
                print(f"  - POST file (mpart):   OK  <-- needed Content-Type w/ boundary")
                print(f"  - POST meta (JSON):    OK  <-- needed Content-Type fix")
                print(f"  - server-side verify:  Private (privacy=1) confirmed")
                print(f"  visit: https://sofurry.com/s/{sub_id}")
                return 0
            else:
                print(f"  [WARN] server reports privacy={server_privacy}, expected 1")
                return 1
        else:
            print(f"  [WARN] raw fetch returned {raw_resp.status_code}")
            return 1
    except Exception as e:
        print(f"  [FAIL] verify call failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
