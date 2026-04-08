"""Update the SF Hypnotic_Claim publication row from failed -> posted."""
from __future__ import annotations
import sys
sys.path.insert(0, "/app")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from database.db import get_connection

conn = get_connection()
conn.execute(
    "UPDATE publications SET status='posted', last_error=NULL, last_updated_at=datetime('now') "
    "WHERE platform='sf' AND story_name='Hypnotic_Claim' AND external_id='ebQ4Jkd1'"
)
conn.commit()
row = conn.execute(
    "SELECT story_name, external_id, status, last_error FROM publications "
    "WHERE platform='sf' AND external_id='ebQ4Jkd1'"
).fetchone()
print(f"updated: {row['story_name']} {row['external_id']} status={row['status']} err={row['last_error']}")
conn.close()
