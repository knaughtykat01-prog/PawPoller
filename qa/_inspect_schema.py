from database.db import get_connection
c = get_connection()
cols = c.execute("PRAGMA table_info(submissions)").fetchall()
print("\n".join(f"{r[1]:30s} {r[2]}" for r in cols))
c.close()
