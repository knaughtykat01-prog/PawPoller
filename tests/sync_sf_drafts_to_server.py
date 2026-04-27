"""Sync the 6 SF drafts created locally into the server publications table."""
from __future__ import annotations
import sys
sys.path.insert(0, "/app")
from database.db import get_connection
from database.posting_queries import upsert_publication

# Hard-coded so this script is deterministic and side-effect free outside this list.
SF_DRAFTS = [
    ("Tombstone",                  "nLrR4PBe",  8414),
    ("Chosen",                     "m0KjxlKe", 15958),
    ("Not_So_Efficient_Studying",  "ePdyAZ5e", 13602),
    ("Overtime",                   "1xJGPWZm", 11513),
    ("Ruins_of_Breeding",          "nd4Pol7n", 24457),
    ("The_Haunting_Desires",       "mXB73JG1", 30480),
]

conn = get_connection()
for story_name, sub_id, word_count in SF_DRAFTS:
    upsert_publication(
        conn,
        story_name=story_name,
        chapter_index=0,
        platform="sf",
        external_id=sub_id,
        external_url=f"https://sofurry.com/s/{sub_id}",
        title_used=story_name.replace("_", " "),
        description_used="",
        tags_used=[],
        rating_used="adult",
        format_file=f"HTML/{story_name}_Clean.html",
        word_count=word_count,
        status="draft",
    )
    print(f"  upserted {story_name:30s} sf {sub_id}")
print()
rows = conn.execute(
    "SELECT story_name, external_id, status FROM publications "
    "WHERE platform='sf' ORDER BY pub_id"
).fetchall()
print(f"Total SF rows on server now: {len(rows)}")
for r in rows:
    print(f"  {r['story_name']:35s} {r['external_id']:>10s}  {r['status']}")
conn.close()
