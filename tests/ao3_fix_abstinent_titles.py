"""Fix the titles on the two Abstinent Bet AO3 drafts.

The bulk script used story.name.replace('_', ' ') which produced
'The Abstinent Bet/Nice Version' (with a slash). The actual title from
story.json is 'The Abstinent Bet — Nice Version' (em dash).
"""
from __future__ import annotations
import asyncio
import sys
sys.path.insert(0, "/app")

from ao3_client.client import AO3Client
import config


FIXES = [
    ("82713236", "The Abstinent Bet — Nice Version"),
    ("82713271", "The Abstinent Bet — Naughty Version"),
]


async def main() -> int:
    s = config.get_settings()
    c = AO3Client(s["ao3_username"], s["ao3_password"], s.get("ao3_target_user", ""))
    if not await c.ensure_logged_in():
        print("[FAIL] login")
        return 1

    for work_id, new_title in FIXES:
        print(f"Updating work {work_id} title -> {new_title!r}")
        try:
            await c.edit_work(work_id, title=new_title)
            print(f"  [OK]")
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {e}")
        await asyncio.sleep(5)

    await c.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
