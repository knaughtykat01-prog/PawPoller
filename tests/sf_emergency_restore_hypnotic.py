"""EMERGENCY: restore Hypnotic_Claim from Private to Public on SoFurry.

The buggy edit_submission method just downgraded ebQ4Jkd1 to privacy=1.
This script:
  1. Fetches the RAW JSON for ebQ4Jkd1 (with all fields including privacy)
  2. Submits a complete payload with privacy=3 (Public) explicitly set
  3. Verifies the change took
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from posting.platforms.sofurry import SoFurryPoster


SUBMISSION_ID = "ebQ4Jkd1"


async def main() -> int:
    print(f"[1/3] Login + fetch raw state of {SUBMISSION_ID}...")
    poster = SoFurryPoster()
    client = await poster._ensure_client()

    raw_resp = await client._http.get(
        f"https://sofurry.com/ui/submission/{SUBMISSION_ID}",
        headers={"Accept": "application/json"},
    )
    if raw_resp.status_code != 200:
        print(f"  [FAIL] fetch returned {raw_resp.status_code}")
        return 1
    raw = raw_resp.json()
    print(f"  current privacy: {raw.get('privacy')}")
    print(f"  title:           {raw.get('title')}")

    print(f"[2/3] Posting back with privacy=3 (Public)...")
    csrf = await client._get_csrf_meta()
    if not csrf:
        print("  [FAIL] no CSRF")
        return 1

    # Build complete payload from RAW data + force privacy=3
    payload = {
        "title": raw.get("title", ""),
        "description": raw.get("description", ""),
        "artistTags": raw.get("artistTags", []),
        "category": raw.get("category", 20),
        "type": raw.get("type", 21),
        "rating": raw.get("rating", 20),
        "privacy": 3,  # PUBLIC
        "allowComments": raw.get("allowComments", True),
        "allowDownloads": raw.get("allowDownloads", True),
        "isWip": raw.get("isWip", False),
        "optimize": raw.get("optimize", False),
        "pixelPerfect": raw.get("pixelPerfect", False),
        "isAdvert": raw.get("isAdvert", False),
        "contentOrder": raw.get("contentOrder", []),
    }

    resp = await client._http.post(
        f"https://sofurry.com/ui/submission/{SUBMISSION_ID}",
        headers={
            "X-CSRF-TOKEN": csrf,
            "Origin": "https://sofurry.com",
            "Referer": "https://sofurry.com/",
            "Accept": "application/json",
        },
        json=payload,
        timeout=30.0,
    )
    print(f"  status: {resp.status_code}")
    if resp.status_code not in (200, 201):
        print(f"  [FAIL] {resp.text[:300]}")
        return 1

    print(f"[3/3] Re-fetching to verify...")
    await asyncio.sleep(2)
    verify = await client._http.get(
        f"https://sofurry.com/ui/submission/{SUBMISSION_ID}",
        headers={"Accept": "application/json"},
    )
    if verify.status_code == 200:
        data = verify.json()
        print(f"  privacy now: {data.get('privacy')}")
        if data.get("privacy") == 3:
            print(f"  [OK] Hypnotic Claim restored to Public")
            return 0
        else:
            print(f"  [WARN] privacy is {data.get('privacy')}, expected 3")
            return 1
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
