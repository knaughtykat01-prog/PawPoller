"""Detailed publications listing."""
from __future__ import annotations
import sys
sys.path.insert(0, "/app")
from database.db import get_connection

conn = get_connection()
rows = conn.execute(
    "SELECT platform, story_name, external_id, status, last_updated_at "
    "FROM publications ORDER BY platform, story_name"
).fetchall()
print(f"Total: {len(rows)} publications")
print()
print(f"{'platform':10s} {'story':40s} {'ext_id':>12s}  {'status':10s}")
print("-" * 80)
for r in rows:
    print(f"{r['platform']:10s} {r['story_name'][:38]:40s} {r['external_id']:>12s}  {r['status']:10s}")
