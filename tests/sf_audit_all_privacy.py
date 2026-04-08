"""Audit privacy state of every known SoFurry submission."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from posting.platforms.sofurry import SoFurryPoster


# All known SF submission IDs from publications + bulk drafts this session
SUBMISSIONS = {
    # Pre-existing live works (should be privacy=3 Public)
    "Drumheller_Detour":                    ("mXB3AJz1", "expected: Public"),
    "Extra_Credit":                         ("e3Qxq0En", "expected: Public"),
    "Hypnotic_Claim":                       ("ebQ4Jkd1", "expected: Public (just restored)"),
    "The_Abstinent_Bet/Naughty_Version":    ("mW3Kv5Qm", "expected: Public"),
    "The_Abstinent_Bet/Nice_Version":       ("mywPXpP1", "expected: Public"),
    "The_Silk_Threaded_Bonds":              ("noX5xXp1", "expected: Public"),
    "Velvet_And_Vice":                      ("ejYYA8G1", "expected: Public"),
    # New drafts from this session (should be privacy=1 Private)
    "Tombstone (draft)":                    ("nLrR4PBe", "expected: Private"),
    "Chosen (draft)":                       ("m0KjxlKe", "expected: Private"),
    "NSE Studying (draft)":                 ("ePdyAZ5e", "expected: Private"),
    "Overtime (draft)":                     ("1xJGPWZm", "expected: Private"),
    "Ruins of Breeding (draft)":            ("nd4Pol7n", "expected: Private"),
    "Haunting Desires (draft)":             ("mXB73JG1", "expected: Private"),
}


async def main() -> int:
    poster = SoFurryPoster()
    client = await poster._ensure_client()
    print(f"{'name':40s} {'sub_id':>10s}  {'priv':>4s}  {'note'}")
    print("-" * 80)
    issues = []
    for name, (sub_id, expected) in SUBMISSIONS.items():
        try:
            resp = await client._http.get(
                f"https://sofurry.com/ui/submission/{sub_id}",
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                privacy = data.get("privacy")
                label = {1: "Priv", 2: "Unl", 3: "Pub"}.get(privacy, "?")
                print(f"{name:40s} {sub_id:>10s}  {label:>4s}  {expected}")
                # Check for mismatches
                is_draft = "(draft)" in name
                if is_draft and privacy != 1:
                    issues.append(f"{name}: expected Private, got {label}")
                elif not is_draft and privacy != 3:
                    issues.append(f"{name}: expected Public, got {label}")
            else:
                print(f"{name:40s} {sub_id:>10s}   ???  HTTP {resp.status_code}")
                issues.append(f"{name}: HTTP {resp.status_code}")
        except Exception as e:
            print(f"{name:40s} {sub_id:>10s}   ERR  {e}")
            issues.append(f"{name}: {e}")
        await asyncio.sleep(0.5)
    print()
    if issues:
        print(f"ISSUES ({len(issues)}):")
        for i in issues:
            print(f"  - {i}")
        return 1
    print("ALL EXPECTED STATES MATCH")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
