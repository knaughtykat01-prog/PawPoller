"""Inspect the SF failed publication."""
from __future__ import annotations
import sys
sys.path.insert(0, "/app")
from database.db import get_connection

conn = get_connection()
rows = conn.execute(
    "SELECT * FROM publications WHERE platform = 'sf' ORDER BY pub_id"
).fetchall()
for r in rows:
    print(f"--- {r['story_name']} ---")
    print(f"  external_id: {r['external_id']}")
    print(f"  status:      {r['status']}")
    print(f"  last_error:  {r['last_error']}")
    print(f"  last_updated:{r['last_updated_at']}")
    print(f"  attempts:    {r['update_count']}")
    print()
print("--- log entries for SF failures ---")
log_rows = conn.execute(
    "SELECT created_at, story_name, action, status, error_message "
    "FROM posting_log WHERE platform = 'sf' AND status != 'success' "
    "ORDER BY log_id DESC LIMIT 10"
).fetchall()
for r in log_rows:
    print(f"  {r['created_at']}  {r['story_name']:25s}  {r['action']:8s}  {r['status']}")
    if r['error_message']:
        print(f"    error: {r['error_message'][:200]}")
