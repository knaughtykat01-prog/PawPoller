"""SoFurry smoke test — login + fetch user submissions. Read-only.

Run from local desktop (residential IP). No CF proxy.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from sf_client.client import SoFurryClient


async def main() -> int:
    s = config.get_settings()
    user = s.get("sf_username", "")
    pw = s.get("sf_password", "")
    display_name = s.get("sf_display_name", "")

    if not user or not pw:
        print("[FAIL] SF creds not in settings")
        return 1

    print(f"[1/3] Login as {user} (display: {display_name})...")
    client = SoFurryClient(
        username=user,
        password=pw,
        display_name=display_name,
        proxy_url="",  # NO CF proxy — direct httpx from residential IP
        proxy_key="",
    )
    ok = await client.ensure_logged_in()
    if not ok:
        print("[FAIL] login failed")
        await client.close()
        return 1
    print("  [OK] logged in")

    print(f"[2/3] Fetching CSRF token...")
    csrf = await client._get_csrf_meta()
    print(f"  csrf token: {'<got>' if csrf else '<none>'}")

    print(f"[3/3] Fetching gallery (read-only)...")
    try:
        gallery = await client.scrape_gallery()
        print(f"  found {len(gallery)} submissions on {display_name or user}")
        for sub in gallery[:10]:
            print(f"    {sub}")
        if len(gallery) > 10:
            print(f"    ... and {len(gallery) - 10} more")
    except Exception as e:
        print(f"  [WARN] gallery scrape failed: {e}")

    await client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
