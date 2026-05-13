"""QA bootstrap: seed dummy creds + a fake submission row to satisfy the
front-end gates so we can drive Settings/Editor without real IB."""
from database.db import get_connection
import config

config.save_settings({"username": "qatestuser", "password": "qa-dummy-not-real"})

conn = get_connection()
try:
    conn.execute("""
        INSERT OR IGNORE INTO submissions
            (submission_id, title, username, user_id, create_datetime, type_name,
             rating_id, rating_name, thumb_url, url, description, keywords,
             page_count, views, favorites_count, comments_count, updated_at)
        VALUES
            (999999999, '[QA placeholder]', 'qatestuser', 0, '2026-04-28 00:00:00', 'Picture',
             0, 'General', '', '', '', '',
             1, 0, 0, 0, '2026-04-28 00:00:00')
    """)
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
    print(f"submissions: {n}")
finally:
    conn.close()
