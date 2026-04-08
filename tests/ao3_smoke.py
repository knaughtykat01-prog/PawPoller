"""AO3 smoke test — login + list works. Read-only, no posting.

Run from inside the GCP container:
  docker exec pawpoller-pawpoller-1 python /app/tests/ao3_smoke.py
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from ao3_client.client import AO3Client


async def main() -> int:
    s = config.get_settings()
    user = s.get("ao3_username", "")
    pw = s.get("ao3_password", "")
    target = s.get("ao3_target_user", user)

    if not user or not pw:
        print("[FAIL] AO3 creds not in settings")
        return 1

    print(f"[1/3] Login as {user}...")
    c = AO3Client(user, pw, target)
    ok = await c.ensure_logged_in()
    if not ok:
        print("[FAIL] login failed")
        await c.close()
        return 1
    print("  [OK] logged in")

    print(f"[2/3] Listing works for {target}...")
    works = await c.get_all_work_ids()
    print(f"  found {len(works)} works")
    for w in works[:30]:
        print(f"    {w}")

    print("[3/3] Closing session.")
    await c.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
