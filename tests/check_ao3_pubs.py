"""Quick query: list AO3 publications."""
from __future__ import annotations
import sys
sys.path.insert(0, "/app")
from database.db import get_connection

conn = get_connection()
rows = conn.execute(
    "SELECT story_name, external_id, status, word_count FROM publications "
    "WHERE platform = 'ao3' ORDER BY pub_id"
).fetchall()
print(f"AO3 publications on server: {len(rows)}")
for r in rows:
    print(f"  {r['story_name']:35s} {r['external_id']:>10s}  {r['status']:6s}  {r['word_count']:>6,} words")
