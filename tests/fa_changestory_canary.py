"""Canary: replace the source file on FA submission 64274343 (Hypnotic ch1).

ONE submission, ONE file replacement, then verify by re-fetching the file
metadata from FA. This is the smallest possible test of the changestory
endpoint flow.

Steps:
  1. Read current FA submission state (file size + filename via web page)
  2. Resolve the local PDF that should replace it
  3. Call FurAffinityPoster.replace_file()
  4. Re-fetch and confirm the file changed (filename or size delta)
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from posting.platforms.furaffinity import FurAffinityPoster
from posting.story_reader import build_package, load_story


SUBMISSION_ID = "64274343"  # Hypnotic Claim Part 1
STORY_NAME = "Hypnotic_Claim"
CHAPTER_INDEX = 1


async def fetch_file_info(client, sid: str) -> dict:
    """Get the current source file info for an FA submission.

    Reads the public submission page to find the download URL + filename
    that's currently attached.
    """
    fa = await client._get_fa_http()
    r = await fa.get(f"https://www.furaffinity.net/view/{sid}/", timeout=30)
    info = {"status": r.status_code}
    if r.status_code == 200:
        # Find the download link (usually <a href="//d.furaffinity.net/.../FILE">)
        m = re.search(r'href="(//d\.furaffinity\.net/[^"]+)"', r.text)
        if m:
            info["download_url"] = "https:" + m.group(1)
            info["filename"] = m.group(1).rsplit("/", 1)[-1]
    return info


async def main() -> int:
    print("=" * 70)
    print(f"FA changestory canary — submission {SUBMISSION_ID}")
    print("=" * 70)
    print()

    poster = FurAffinityPoster()
    print("[1/5] Login + validate cookies...")
    client = await poster._ensure_client()
    print("  [OK]")
    print()

    print(f"[2/5] Read current source file on FA submission {SUBMISSION_ID}...")
    before = await fetch_file_info(client, SUBMISSION_ID)
    print(f"  status:       {before.get('status')}")
    print(f"  download URL: {before.get('download_url', '(not found)')}")
    print(f"  filename:     {before.get('filename', '(not found)')}")
    print()

    print(f"[3/5] Resolve local PDF for {STORY_NAME} ch{CHAPTER_INDEX}...")
    story = load_story(STORY_NAME)
    pkg = build_package(story, chapter_index=CHAPTER_INDEX, platform="fa")
    if not pkg.file_path:
        print("  [FAIL] no file_path resolved")
        return 1
    local_path = Path(pkg.file_path)
    print(f"  local PDF: {local_path}")
    print(f"  exists:    {local_path.exists()}")
    print(f"  size:      {local_path.stat().st_size:,} bytes")
    print(f"  filename:  {local_path.name}")
    print()

    if before.get("filename") == local_path.name:
        print("  [INFO] FA already has a file with this exact filename — replacement")
        print("         would still go through but timestamp / content may differ.")
        print()

    print(f"[4/5] Calling FurAffinityPoster.replace_file({SUBMISSION_ID!r}, {str(local_path)!r})...")
    result = await poster.replace_file(SUBMISSION_ID, str(local_path))
    print(f"  success:  {result.success}")
    print(f"  duration: {result.duration_seconds:.1f}s")
    if not result.success:
        print(f"  error:    {result.error}")
        return 1
    print(f"  url:      {result.external_url}")
    print()

    print(f"[5/5] Re-read source file from FA after the replacement...")
    await asyncio.sleep(2)  # let FA finish processing
    after = await fetch_file_info(client, SUBMISSION_ID)
    print(f"  status:       {after.get('status')}")
    print(f"  download URL: {after.get('download_url', '(not found)')}")
    print(f"  filename:     {after.get('filename', '(not found)')}")
    print()

    print("=" * 70)
    print("DIFF")
    print("=" * 70)
    if before.get("download_url") == after.get("download_url"):
        print("  download URL UNCHANGED — file may not have been replaced")
        print(f"    URL: {before.get('download_url')}")
    else:
        print("  download URL CHANGED:")
        print(f"    before: {before.get('download_url')}")
        print(f"    after:  {after.get('download_url')}")
    if before.get("filename") != after.get("filename"):
        print(f"  filename:")
        print(f"    before: {before.get('filename')}")
        print(f"    after:  {after.get('filename')}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
