"""Cross-platform account registry (multi-account support).

This module is the single source of truth for the *identity* layer that lets
PawPoller run more than one account on the same platform (e.g. two FurAffinity
accounts) simultaneously. Before multi-account, every platform had exactly one
implicit account whose credentials lived under flat keys in settings.json
(``username``/``password`` for Inkbunny, ``fa_username``/``fa_cookie_a`` for FA,
etc.). That implicit account is now modelled as the platform's **default
account** (``is_default=1``) and keeps using those legacy flat keys verbatim, so
existing installs migrate with zero credential movement. Additional accounts are
purely additive and store their credentials under ``acct_<id>_<field>`` keys
(see ``config.get_account_credentials`` / ``config.is_credential_key``).

The ``accounts`` table uses a single global surrogate key (``account_id``) shared
across all platforms — it is what threads through every per-platform analytics
and posting table as the account discriminator.

Design notes:
- ``account_id`` is AUTOINCREMENT and therefore NOT uniformly 1 per platform.
  Any backfill of existing data rows must target *that platform's* default
  ``account_id`` (resolve via :func:`get_default_account_id`), never a literal 1.
- A partial unique index enforces at most one ``is_default`` account per platform.
"""

from __future__ import annotations

import json
import logging
import sqlite3

logger = logging.getLogger(__name__)

# All platform codes PawPoller knows about. Order is the display order.
PLATFORMS = ["ib", "fa", "ws", "sf", "sqw", "ao3", "da", "wp", "ik", "bsky", "tw"]

PLATFORM_NAMES = {
    "ib": "Inkbunny", "fa": "FurAffinity", "ws": "Weasyl", "sf": "SoFurry",
    "sqw": "SquidgeWorld", "ao3": "AO3", "da": "DeviantArt", "wp": "Wattpad",
    "ik": "Itaku", "bsky": "Bluesky", "tw": "X/Twitter",
}

# Predicate per platform: does settings hold credentials for a default account?
# Mirrors the ``checks`` list in server.py ``_poll_all`` — keep the two in sync.
DEFAULT_CRED_CHECKS = {
    "ib": lambda s: bool(s.get("username") and s.get("password")),
    "fa": lambda s: bool(s.get("fa_username") and s.get("fa_cookie_a")),
    "ws": lambda s: bool(s.get("ws_api_key")),
    "sf": lambda s: bool(s.get("sf_username") and s.get("sf_password")),
    "sqw": lambda s: bool(s.get("sqw_username") and s.get("sqw_password")),
    "ao3": lambda s: bool((s.get("ao3_username") and s.get("ao3_password"))
                          or s.get("ao3_session_cookie")),
    "da": lambda s: bool(s.get("da_cookie") and s.get("da_target_user")),
    "wp": lambda s: bool(s.get("wp_target_user")),
    "ik": lambda s: bool(s.get("ik_target_user")),
    "bsky": lambda s: bool(s.get("bsky_identifier") and s.get("bsky_app_password")),
    "tw": lambda s: bool(s.get("tw_auth_token") and s.get("tw_target_user")),
}

# The flat settings key whose value names the default account (for display).
_HANDLE_KEYS = {
    "ib": ["username"],
    "fa": ["fa_username"],
    "ws": ["ws_username"],
    "sf": ["sf_display_name", "sf_username"],
    "sqw": ["sqw_author_username", "sqw_username"],
    "ao3": ["ao3_username"],
    "da": ["da_target_user"],
    "wp": ["wp_target_user"],
    "ik": ["ik_target_user"],
    "bsky": ["bsky_identifier"],
    "tw": ["tw_target_user"],
}


def ensure_accounts_table(conn: sqlite3.Connection) -> None:
    """Create the accounts table + indexes if absent. Idempotent."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            account_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            platform    TEXT NOT NULL,
            label       TEXT NOT NULL DEFAULT '',
            handle      TEXT NOT NULL DEFAULT '',
            enabled     INTEGER NOT NULL DEFAULT 1,
            is_default  INTEGER NOT NULL DEFAULT 0,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_accounts_platform ON accounts(platform, enabled);
        -- At most one default account per platform.
        CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_one_default
            ON accounts(platform) WHERE is_default = 1;
        """
    )


def _default_handle(platform: str, settings: dict) -> str:
    for key in _HANDLE_KEYS.get(platform, []):
        val = settings.get(key)
        if val:
            return str(val)
    return ""


def derive_handle(platform: str, source: dict) -> str:
    """Best-effort display handle from a creds/settings-shaped dict."""
    return _default_handle(platform, source)


def get_default_account_id(conn: sqlite3.Connection, platform: str,
                           create: bool = False, settings: dict | None = None) -> int | None:
    """Return the default account_id for *platform*.

    When *create* is True and no default exists yet, one is created on the spot
    (best-effort label/handle from *settings*). This guarantees a backfill
    target for per-platform schema migrations regardless of whether credentials
    are currently present.
    """
    row = conn.execute(
        "SELECT account_id FROM accounts WHERE platform = ? AND is_default = 1",
        (platform,),
    ).fetchone()
    if row:
        return row["account_id"]
    if not create:
        return None
    if settings is None:
        try:
            import config
            settings = config.get_settings()
        except Exception:
            settings = {}
    label = "%s (default)" % PLATFORM_NAMES.get(platform, platform)
    handle = _default_handle(platform, settings)
    cur = conn.execute(
        "INSERT INTO accounts (platform, label, handle, enabled, is_default, sort_order)"
        " VALUES (?, ?, ?, 1, 1, 0)",
        (platform, label, handle),
    )
    return cur.lastrowid


def seed_default_accounts(conn: sqlite3.Connection, settings: dict) -> int:
    """Create a default account for every platform that currently has creds.

    Returns the number of default accounts created. Idempotent: a platform that
    already has a default account is skipped. Run once during migration so
    existing single-account installs gain their default account rows.
    """
    created = 0
    for platform in PLATFORMS:
        check = DEFAULT_CRED_CHECKS.get(platform)
        if not check or not check(settings):
            continue
        if get_default_account_id(conn, platform) is not None:
            continue
        get_default_account_id(conn, platform, create=True, settings=settings)
        created += 1
    return created


# Per-platform submissions table for account stat rollups. Only platforms whose
# analytics tables carry account_id can be segregated; others return None.
_STATS_TABLE = {
    "ib": "submissions", "fa": "fa_submissions", "ws": "ws_submissions",
    "da": "da_submissions", "wp": "wp_submissions", "ik": "ik_submissions",
    "bsky": "bsky_submissions", "tw": "tw_submissions", "sf": "sf_submissions",
    "sqw": "sqw_submissions", "ao3": "ao3_submissions",
}


def account_stats(conn: sqlite3.Connection, account_id: int, platform: str) -> dict | None:
    """Return {submissions, views, favorites, comments} for one account.

    None if the platform's submissions table isn't account-aware yet (the other
    9 platforms until they're rolled out). Used to show per-account stats on the
    Accounts page so two accounts' numbers appear side by side.
    """
    table = _STATS_TABLE.get(platform)
    if not table:
        return None
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if "account_id" not in cols:
        return None
    # Sum whichever of the standard metric columns this platform's table has
    # (e.g. Wattpad/Bluesky use reads/likes instead of views/favorites_count).
    parts = ["COUNT(*) AS submissions"]
    for col, alias in (("views", "views"), ("favorites_count", "favorites"),
                       ("comments_count", "comments")):
        parts.append(f"COALESCE(SUM({col}), 0) AS {alias}" if col in cols else f"0 AS {alias}")
    row = conn.execute(
        f"SELECT {', '.join(parts)} FROM {table} WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    return dict(row) if row else None


# ── CRUD ───────────────────────────────────────────────────────

def list_accounts(conn: sqlite3.Connection, platform: str | None = None,
                  enabled_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM accounts"
    clauses, params = [], []
    if platform:
        clauses.append("platform = ?")
        params.append(platform)
    if enabled_only:
        clauses.append("enabled = 1")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY platform, is_default DESC, sort_order, account_id"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_account(conn: sqlite3.Connection, account_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
    return dict(row) if row else None


def create_account(conn: sqlite3.Connection, platform: str, label: str,
                   handle: str = "", enabled: bool = True,
                   is_default: bool = False) -> int:
    """Insert an account and return its account_id.

    If *is_default* is requested but the platform already has a default, the new
    account is created as non-default instead (the partial unique index would
    otherwise reject it).
    """
    if is_default and get_default_account_id(conn, platform) is not None:
        is_default = False
    cur = conn.execute(
        "INSERT INTO accounts (platform, label, handle, enabled, is_default, sort_order)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (platform, label or "%s account" % PLATFORM_NAMES.get(platform, platform),
         handle, 1 if enabled else 0, 1 if is_default else 0,
         _next_sort_order(conn, platform)),
    )
    conn.commit()
    return cur.lastrowid


def _next_sort_order(conn: sqlite3.Connection, platform: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM accounts WHERE platform = ?",
        (platform,),
    ).fetchone()
    return row["n"] if row else 0


def update_account(conn: sqlite3.Connection, account_id: int, **fields) -> bool:
    """Update label/handle/enabled/sort_order on an account. Returns True if a row changed."""
    allowed = {"label", "handle", "enabled", "sort_order"}
    sets, params = [], []
    for key, val in fields.items():
        if key not in allowed or val is None:
            continue
        if key == "enabled":
            val = 1 if val else 0
        sets.append(f"{key} = ?")
        params.append(val)
    if not sets:
        return False
    params.append(account_id)
    cur = conn.execute(f"UPDATE accounts SET {', '.join(sets)} WHERE account_id = ?", params)
    conn.commit()
    return cur.rowcount > 0


def delete_account(conn: sqlite3.Connection, account_id: int) -> bool:
    """Delete an account row. Callers must guard against deleting a default
    account (the API layer re-promotes or refuses). Does NOT cascade to the
    per-platform analytics rows — those are left orphaned-by-account_id, which
    is harmless (they simply stop being shown)."""
    cur = conn.execute("DELETE FROM accounts WHERE account_id = ?", (account_id,))
    conn.commit()
    return cur.rowcount > 0


def count_accounts(conn: sqlite3.Connection, platform: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM accounts WHERE platform = ?", (platform,)
    ).fetchone()
    return row["n"] if row else 0


# ── Sync manifest (desktop ↔ server account parity) ────────────
# The accounts table is DB state, not settings, so it does not ride the normal
# settings-sync channel. We serialize it into a settings key (``_accounts_manifest``)
# that the sync layer carries, and re-materialize it on the other side. Apply is
# an ADDITIVE upsert (never deletes) so a stale side can't wipe the other's
# accounts; credential values themselves still travel as flat/prefixed keys.

def get_manifest(conn: sqlite3.Connection) -> list[dict]:
    return [
        {k: r[k] for k in ("account_id", "platform", "label", "handle",
                           "enabled", "is_default", "sort_order", "persona_id")}
        for r in conn.execute("SELECT * FROM accounts ORDER BY account_id").fetchall()
    ]


def apply_manifest(conn: sqlite3.Connection, manifest) -> int:
    """Upsert accounts from a sync manifest. Additive only (no deletes).

    Returns the number of rows inserted or updated. Preserves account_id from
    the manifest so the surrogate key stays stable across desktop↔server.
    """
    if isinstance(manifest, str):
        try:
            manifest = json.loads(manifest)
        except (ValueError, TypeError):
            return 0
    if not isinstance(manifest, list):
        return 0
    n = 0
    for acct in manifest:
        try:
            aid = int(acct["account_id"])
            platform = acct["platform"]
        except (KeyError, TypeError, ValueError):
            continue
        # Don't let an incoming default collide with an existing different default.
        is_default = int(acct.get("is_default", 0))
        if is_default:
            existing_default = conn.execute(
                "SELECT account_id FROM accounts WHERE platform = ? AND is_default = 1",
                (platform,),
            ).fetchone()
            if existing_default and existing_default["account_id"] != aid:
                is_default = 0
        conn.execute(
            "INSERT INTO accounts (account_id, platform, label, handle, enabled, is_default, sort_order)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(account_id) DO UPDATE SET"
            "   label=excluded.label, handle=excluded.handle,"
            "   enabled=excluded.enabled, sort_order=excluded.sort_order",
            (aid, platform, acct.get("label", ""), acct.get("handle", ""),
             int(acct.get("enabled", 1)), is_default, int(acct.get("sort_order", 0))),
        )
        # Persona assignment: only touch persona_id when the manifest actually
        # carries the key (present-but-null = explicit unassign; absent = an old
        # client, so leave the local assignment alone rather than clobber it).
        if "persona_id" in acct:
            conn.execute("UPDATE accounts SET persona_id = ? WHERE account_id = ?",
                         (acct.get("persona_id"), aid))
        n += 1
    conn.commit()
    return n
