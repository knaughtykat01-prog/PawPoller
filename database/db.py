"""Database connection manager and schema initialization.

This module handles all SQLite setup: connection creation, schema loading from
external .sql files, and incremental migrations for databases created by older
versions of PawPoller.

Key design decisions:
- WAL journal mode for concurrent read/write access (the UI can read while
  a background poller writes without locking).
- Row factory set to sqlite3.Row so query results behave like dicts
  (row["column_name"]) rather than bare tuples.
- Schema files are loaded via config.resource_path() which resolves paths
  correctly both in development and in PyInstaller frozen builds (_internal/).
- Foreign keys are enabled per-connection (SQLite disables them by default).
- Migrations use a "check table existence, then CREATE IF NOT EXISTS" pattern
  so they are idempotent and safe to re-run on every startup.
"""

import logging
import sqlite3

import config

logger = logging.getLogger(__name__)

# Schema file paths resolved via resource_path(). In development these point to
# the source tree; in a PyInstaller frozen build they resolve into the _internal/
# directory bundled alongside the executable. This ensures the app can always
# find its schema files regardless of deployment method.
_SCHEMA_PATH = config.resource_path("database/schema.sql")       # Inkbunny (primary platform)
_FA_SCHEMA_PATH = config.resource_path("database/fa_schema.sql") # FurAffinity tables
_WS_SCHEMA_PATH = config.resource_path("database/ws_schema.sql") # Weasyl tables
_SF_SCHEMA_PATH = config.resource_path("database/sf_schema.sql") # SoFurry tables
_SQW_SCHEMA_PATH = config.resource_path("database/sqw_schema.sql") # SquidgeWorld tables
_AO3_SCHEMA_PATH = config.resource_path("database/ao3_schema.sql") # AO3 tables
_DA_SCHEMA_PATH = config.resource_path("database/da_schema.sql")   # DeviantArt tables
_WP_SCHEMA_PATH = config.resource_path("database/wp_schema.sql")   # Wattpad tables
_IK_SCHEMA_PATH = config.resource_path("database/ik_schema.sql")   # Itaku tables


def get_connection() -> sqlite3.Connection:
    """Get a new SQLite connection with WAL mode and row factory.

    Every connection is configured with:
    - WAL (Write-Ahead Logging) journal mode: allows concurrent readers and a
      single writer without blocking each other. This is critical because the
      GUI thread reads data for display while the poller thread writes new
      snapshots simultaneously. Without WAL, readers would be blocked during
      writes (or vice versa), causing UI freezes.
    - Row factory set to sqlite3.Row: makes query results accessible by column
      name (row["title"]) in addition to index (row[0]). This improves code
      readability and resilience to column-order changes.
    - Foreign key enforcement: SQLite does not enforce FOREIGN KEY constraints
      by default -- it must be explicitly enabled per-connection via PRAGMA.
      This ensures referential integrity (e.g. snapshots cannot reference a
      non-existent submission_id).
    """
    conn = sqlite3.connect(str(config.DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist.

    Loads and executes all three platform schema files (Inkbunny, FurAffinity,
    Weasyl) then runs incremental migrations for any tables added after the
    initial schema. Each schema file uses CREATE TABLE IF NOT EXISTS, making
    this safe to call on every application startup -- existing tables are
    left untouched.
    """
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    fa_schema_sql = _FA_SCHEMA_PATH.read_text(encoding="utf-8")
    ws_schema_sql = _WS_SCHEMA_PATH.read_text(encoding="utf-8")
    sf_schema_sql = _SF_SCHEMA_PATH.read_text(encoding="utf-8")
    sqw_schema_sql = _SQW_SCHEMA_PATH.read_text(encoding="utf-8")
    ao3_schema_sql = _AO3_SCHEMA_PATH.read_text(encoding="utf-8")
    da_schema_sql = _DA_SCHEMA_PATH.read_text(encoding="utf-8")
    wp_schema_sql = _WP_SCHEMA_PATH.read_text(encoding="utf-8")
    conn = get_connection()
    try:
        # Execute each platform's schema in order.
        conn.executescript(schema_sql)
        conn.executescript(fa_schema_sql)
        conn.executescript(ws_schema_sql)
        conn.executescript(sf_schema_sql)
        conn.executescript(sqw_schema_sql)
        conn.executescript(ao3_schema_sql)
        conn.executescript(da_schema_sql)
        conn.executescript(wp_schema_sql)
        ik_schema_sql = _IK_SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(ik_schema_sql)
        # Apply any migrations for tables added after the original schema release.
        _run_migrations(conn)
        conn.commit()
    finally:
        conn.close()


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply schema migrations for existing databases.

    Migration pattern: query sqlite_master for existing table names, then
    conditionally create any tables that are missing. This approach:
    - Is idempotent (safe to run repeatedly on every startup).
    - Handles upgrades from any previous schema version.
    - Uses CREATE TABLE IF NOT EXISTS as a secondary safety net.

    Each migration block is documented with what it adds and why.
    """
    # Get the set of all table names currently in the database.
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    # Migration 1: Inkbunny comments table.
    # Added to track individual comments on Inkbunny submissions (username,
    # text, timestamp, reply threading). This was not in the original schema
    # which only tracked comment counts in snapshots. Introduced when comment
    # scraping was added to the Inkbunny poller.
    if "comments" not in tables:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS comments (
                comment_id      INTEGER PRIMARY KEY,
                submission_id   INTEGER NOT NULL,
                username        TEXT NOT NULL DEFAULT '',
                comment_text    TEXT NOT NULL DEFAULT '',
                commented_at    TEXT,
                first_seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
                is_reply        INTEGER DEFAULT 0,
                reply_to_comment_id INTEGER,
                FOREIGN KEY (submission_id) REFERENCES submissions(submission_id)
            );
            CREATE INDEX IF NOT EXISTS idx_comments_submission ON comments(submission_id);
            CREATE INDEX IF NOT EXISTS idx_comments_seen ON comments(first_seen_at);
        """)

    # Migration 2: Submission groups (cross-platform tagging/grouping).
    # Allows the user to create named groups (e.g. "Commission batch #3") and
    # assign submissions from any platform to them. The group_members table
    # links a (group_id, platform, submission_id) triple with a uniqueness
    # constraint to prevent duplicates. CASCADE delete ensures removing a group
    # also removes all its member associations.
    if "submission_groups" not in tables:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS submission_groups (
                group_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                description TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS submission_group_members (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id        INTEGER REFERENCES submission_groups(group_id) ON DELETE CASCADE,
                platform        TEXT NOT NULL,
                submission_id   INTEGER NOT NULL,
                UNIQUE(group_id, platform, submission_id)
            );
        """)

    # Migration 3: Cross-platform submission links.
    # Links the "same" submission across platforms (e.g. the same artwork posted
    # to Inkbunny, FurAffinity, and Weasyl). A link_id groups multiple
    # (platform, submission_id) pairs together. This enables cross-platform
    # analytics like comparing view/fave performance of the same piece across
    # sites. CASCADE delete ensures cleaning up a link removes all its members.
    if "submission_links" not in tables:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS submission_links (
                link_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS submission_link_members (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                link_id         INTEGER REFERENCES submission_links(link_id) ON DELETE CASCADE,
                platform        TEXT NOT NULL,
                submission_id   INTEGER NOT NULL,
                UNIQUE(link_id, platform, submission_id)
            );
        """)

    # ── Watcher tables ──────────────────────────────────────────
    if "watchers" not in tables:
        conn.execute("""CREATE TABLE IF NOT EXISTS watchers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL DEFAULT 0,
            username      TEXT NOT NULL,
            first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(username)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_watchers_seen ON watchers(first_seen_at)")

    if "fa_watchers" not in tables:
        conn.execute("""CREATE TABLE IF NOT EXISTS fa_watchers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL,
            first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(username)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fa_watchers_seen ON fa_watchers(first_seen_at)")

    # Add new_watchers_found column to poll logs
    try:
        conn.execute("ALTER TABLE poll_log ADD COLUMN new_watchers_found INTEGER DEFAULT 0")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise
    try:
        conn.execute("ALTER TABLE fa_poll_log ADD COLUMN new_watchers_found INTEGER DEFAULT 0")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise

    # Add new_comments_found column to IB poll_log
    try:
        conn.execute("ALTER TABLE poll_log ADD COLUMN new_comments_found INTEGER DEFAULT 0")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise

    # Migration: Goals table for tracking progress toward user-defined targets
    if "goals" not in tables:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS goals (
                goal_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                platform      TEXT NOT NULL,
                scope         TEXT NOT NULL DEFAULT 'account',
                submission_id INTEGER,
                metric        TEXT NOT NULL,
                target_value  INTEGER NOT NULL,
                created_at    TEXT DEFAULT (datetime('now')),
                completed_at  TEXT
            );
        """)

    # Migration: Tags and submission_tags for user-defined categorisation
    if "tags" not in tables:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tags (
                tag_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT NOT NULL UNIQUE,
                color    TEXT DEFAULT '#6c8cff'
            );
            CREATE TABLE IF NOT EXISTS submission_tags (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_id        INTEGER REFERENCES tags(tag_id) ON DELETE CASCADE,
                platform      TEXT NOT NULL,
                submission_id INTEGER NOT NULL,
                UNIQUE(tag_id, platform, submission_id)
            );
        """)

    # Migration: Rebuild watchers table to use UNIQUE(username) instead of UNIQUE(user_id).
    # The usersviewall page does not expose user_id, so username is the natural key.
    # Check if the old schema is in use by looking for UNIQUE(user_id) constraint.
    watcher_schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='watchers'"
    ).fetchone()
    if watcher_schema and "UNIQUE(user_id)" in (watcher_schema[0] or ""):
        logger.info("Migrating watchers table: UNIQUE(user_id) -> UNIQUE(username)")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS watchers_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL DEFAULT 0,
                username      TEXT NOT NULL,
                first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(username)
            );
            INSERT OR IGNORE INTO watchers_new (user_id, username, first_seen_at)
                SELECT user_id, username, first_seen_at FROM watchers WHERE username != '';
            DROP TABLE watchers;
            ALTER TABLE watchers_new RENAME TO watchers;
            CREATE INDEX IF NOT EXISTS idx_watchers_seen ON watchers(first_seen_at);
        """)

    # Migration: Add confirmation/spam columns to fa_watchers for spam protection.
    # - confirmed: 0 = pending (first seen this cycle), 1 = confirmed (still present next cycle)
    # - last_seen_at: tracks when the watcher was last seen in FAExport's list
    # - is_spam: heuristic or profile-sniff flagged as bot/spam
    # - notified: whether we've already sent a notification for this watcher
    fa_watcher_cols = {r[1] for r in conn.execute("PRAGMA table_info(fa_watchers)").fetchall()}
    if "confirmed" not in fa_watcher_cols:
        logger.info("Migrating fa_watchers: adding confirmed/last_seen_at/is_spam/notified columns")
        try:
            conn.execute("ALTER TABLE fa_watchers ADD COLUMN confirmed INTEGER DEFAULT 1")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE fa_watchers ADD COLUMN last_seen_at TEXT DEFAULT (datetime('now'))")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE fa_watchers ADD COLUMN is_spam INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE fa_watchers ADD COLUMN notified INTEGER DEFAULT 1")
        except sqlite3.OperationalError:
            pass
        # Mark all existing watchers as confirmed+notified (they're from before this feature)
        conn.execute("UPDATE fa_watchers SET confirmed = 1, notified = 1, last_seen_at = first_seen_at WHERE confirmed IS NULL OR confirmed = 1")
    # Ensure the pending-watchers index exists (created here rather than in fa_schema.sql
    # because existing databases need the migration above to add the columns first).
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fa_watchers_pending ON fa_watchers(confirmed, notified)")
    except sqlite3.OperationalError:
        pass  # columns not yet present (shouldn't happen but safe fallback)

    # Migration: Add new_watchers_found column to sf_poll_log
    try:
        conn.execute("ALTER TABLE sf_poll_log ADD COLUMN new_watchers_found INTEGER DEFAULT 0")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise
