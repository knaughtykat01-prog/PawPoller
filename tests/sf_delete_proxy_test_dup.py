"""Delete the duplicate Tombstone draft created by sf_proxy_post_smoke.py.

We already have nLrR4PBe (the local-direct draft from earlier) — myw0PxW1
is a redundant copy from the proxy smoke test.
"""
from __future__ import annotations
import asyncio
import sys
sys.path.insert(0, "/app")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from posting.platforms.sofurry import SoFurryPoster


SUBMISSION_ID = "myw0PxW1"


async def main() -> int:
    poster = SoFurryPoster()
    client = await poster._ensure_client()
    csrf = await client._get_csrf_meta()
    if not csrf:
        print("[FAIL] no CSRF")
        return 1

    # SoFurry's delete endpoint is DELETE /ui/submission/{id}
    resp = await client._http.request(
        "DELETE",
        f"https://sofurry.com/ui/submission/{SUBMISSION_ID}",
        headers={
            "X-CSRF-TOKEN": csrf,
            "Origin": "https://sofurry.com",
            "Referer": "https://sofurry.com/",
            "Accept": "application/json",
        },
        timeout=30.0,
    )
    print(f"DELETE status: {resp.status_code}")
    if resp.status_code in (200, 204):
        print(f"[OK] deleted {SUBMISSION_ID}")
        return 0
    print(f"[FAIL] {resp.text[:300]}")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
