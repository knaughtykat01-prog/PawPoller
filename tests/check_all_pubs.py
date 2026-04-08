"""Quick query: list publications grouped by platform."""
from __future__ import annotations
import sys
sys.path.insert(0, "/app")
from database.db import get_connection

conn = get_connection()
rows = conn.execute(
    "SELECT platform, status, COUNT(*) as n FROM publications "
    "GROUP BY platform, status ORDER BY platform, status"
).fetchall()
print(f"{'platform':10s} {'status':10s} count")
print("-" * 30)
for r in rows:
    print(f"{r['platform']:10s} {r['status']:10s} {r['n']}")
